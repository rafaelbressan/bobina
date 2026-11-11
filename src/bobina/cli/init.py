"""bobina init: from nothing to the first label — printer, profile, locale, roll, and a test strip that carries the
calibration (tear ruler, and the feed test where the profile was not measured). --yes (and BOBINA_NONINTERACTIVE)
asks nothing and prints nothing. Answers are read from stdin, so a file of answers works too."""

from __future__ import annotations

import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .. import config, discover, engine, locales, paper
from .. import profile as profiles
from ..nudges import Nudge
from . import common
from .common import CONFIRM, OK, UNREACHABLE, USAGE, Fail, err, print_json, render_problems

STEPS = ("printer", "profile", "locale", "roll", "test strip")
YES, NO = ("y", "yes", "s", "sim"), ("n", "no", "nao", "não")
NO_ANSWER = ("bobina init asks questions and got no answer (no terminal, or stdin ended)"
             "\n→ run it in a terminal; scripts and agents: bobina init --yes")  # fmt: skip
FIRST = 'bobina print "# Hello from bobina"'


class Dialog:
    """Questions on OUT, answers from stdin (a terminal, or a file of answers). No answer: E107."""

    def __init__(self, out):
        self.out = out

    def say(self, text: str = "") -> None:
        print(text, file=self.out, flush=True)

    def ask(self, prompt: str) -> str:
        self.out.write(prompt)
        self.out.flush()
        line = sys.stdin.readline()
        if not line:
            self.say()
            raise Fail(CONFIRM, NO_ANSWER, problem="E107")
        if not sys.stdin.isatty():  # answers from a file or a pipe: shown, so the dialog reads as it went
            self.out.write(line if line.endswith("\n") else line + "\n")
        return line.strip()

    def yes(self, prompt: str, default: bool) -> bool:
        while True:
            a = self.ask(prompt + (" [Y/n] " if default else " [y/N] ")).lower()
            if not a:
                return default
            if a in YES or a in NO:
                return a in YES
            self.say("  answer y or n")


@dataclass
class Setup:
    name: str | None = None  # the printer's name in config.toml
    pr: dict | None = None
    device: str = ""  # the name the printer gives itself (for the profile)
    found_by: str = ""  # bluetooth | usb | file | command | option | config
    profile: str | None = None
    profile_by: str = ""  # name | chosen | option | default | config
    found: list = field(default_factory=list)
    notes: list = field(default_factory=list)  # Nudges
    changed: list = field(default_factory=list)
    strip: dict | None = None
    said: int = 0  # the first notes, already said in the dialog
    picked: str = ""  # --yes with several printers: which one it took, and the others


def _note(st: Setup, code: str, message: str, hint: str = "") -> None:
    st.notes.append(Nudge(code, message, None, hint))


def _slug(text: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24].strip("-")
    return s or fallback


def _target(pr: dict) -> tuple:
    return pr.get("transport", "bluetooth"), str(pr.get("address") or pr.get("path") or pr.get("command") or "")


def _name_for(cfg: dict, pr: dict, hint: str) -> str:
    """The printer's name: the one it already has in config.toml (same address, path or command), else HINT, made
    unique (mtp-ii-2)."""
    printers = cfg.get("printers") or {}
    same = next((n for n, p in printers.items() if _target(p) == _target(pr)), None)
    if same:
        return same
    name, k = hint, 2
    while name in printers:
        name, k = f"{hint}-{k}", k + 1
    return name


def _where(pr: dict) -> str:
    t, where = _target(pr)
    if t == "file":
        return f"file {where}" if not where.startswith("/dev/") else f"usb {where}"
    return f"{t} {where}"


# ---------------------------------------------------------------- printer


def _from_device(d: discover.Device) -> tuple[dict, str]:
    if d.kind == "bluetooth":
        return {"transport": "bluetooth", "address": d.where, "channel": 1}, _slug(d.name, "printer")
    return {"transport": "file", "path": d.where}, _slug(d.name if d.name != d.where else "usb", "usb")


def _command(cmd: str) -> tuple[dict, str]:
    words = shlex.split(cmd) if cmd.strip() else []
    host = next((w for w in words[1:] if not w.startswith("-")), "") if words[:1] == ["ssh"] else ""
    return {"transport": "command", "command": cmd}, _slug(host.split("@")[-1], "remote")


def _file(path: str) -> tuple[dict, str]:
    p = Path(path).expanduser()
    if str(p).startswith("/dev/"):
        return {"transport": "file", "path": str(p)}, _slug(discover._usb_model(str(p)) or "usb", "usb")
    return {"transport": "file", "path": str(p.resolve())}, "test"


def _look(args, st: Setup, d: Dialog | None) -> list:
    if d:
        bt = "" if discover.bluetooth_missing() else f"Bluetooth for {args.seconds} s, "
        d.say(f"Looking for printers ({bt}USB)…")
    found, notes = [], []
    for got, said in (discover.usb(), discover.bluetooth(args.seconds)):
        found += got
        notes += said
    for c, m, h in notes:
        _note(st, c, m, h)
        if d:
            d.say(f"  note[{c}]: {m} → {h}")
            st.said += 1
    st.found = discover.ranked(found)
    return st.found


def _use(st: Setup, pr: dict, hint: str, device: str, by: str) -> None:
    st.pr, st.device, st.found_by = pr, device, by
    st.name = _name_for(config.load(), pr, hint)


def _printer_option(args, st: Setup, value: str) -> None:
    cfg = config.load()
    if value in (cfg.get("printers") or {}):
        st.name, st.pr, st.found_by = value, dict(cfg["printers"][value]), "config"
        return
    if discover.MAC.match(value):
        name = discover.known_name(value)
        _use(st, {"transport": "bluetooth", "address": value.upper(), "channel": 1}, _slug(name, "printer"), name,
             "option")  # fmt: skip
        return
    if "/" in value or "\\" in value or value.endswith(".bin"):
        pr, hint = _file(value)
        _use(st, pr, hint, discover._usb_model(pr["path"]) if pr["path"].startswith("/dev/") else "", "option")
        return
    devices = _look(args, st, None)
    low = value.lower()
    hit = [x for x in devices if x.name.lower() == low] or [x for x in devices if low in x.name.lower()]
    if not hit:
        names = ", ".join(f"{x.name} ({x.where})" for x in devices) or "none"
        raise Fail(UNREACHABLE, f"no printer called '{value}' was found (found: {names})"
                   "\n→ bobina init --printer ADDRESS, or DEVICE, or a name from bobina printer list",
                   problem="E406")  # fmt: skip
    pr, hint = _from_device(hit[0])
    _use(st, pr, hint, hit[0].name, hit[0].kind)


def _auto_printer(args, st: Setup) -> None:
    devices = [x for x in _look(args, st, None) if x.printer_like]
    if not devices:
        others = [x for x in st.found if not x.printer_like]
        seen = f" (found, not printers: {', '.join(f'{x.name} {x.where}' for x in others)})" if others else ""
        raise Fail(UNREACHABLE, "", problem="MULTI", items=[Nudge(
            "E406", f"bobina init --yes found no printer to set up{seen}", None,
            "turn it on, or name it: bobina init --yes --printer ADDRESS (or DEVICE, or --command 'ssh HOST bobina"
            " send --yes -')", severity="error"), *st.notes])  # fmt: skip
    pick = devices[0]
    pr, hint = _from_device(pick)
    _use(st, pr, hint, pick.name, pick.kind)
    if len(devices) > 1:
        rest = ", ".join(f"{x.name} ({x.where})" for x in devices[1:])
        st.picked = f"took {pick.name} ({pick.where}), the first of {len(devices)} printers; also found: {rest}"


def _ask_printer(args, st: Setup, d: Dialog) -> None:
    devices = _look(args, st, d)
    rows = []
    for x in devices:
        what = profiles.load(x.profile).name if x.profile else ("" if x.printer_like else "not a printer?")
        rows.append((x.name, f"{x.kind} {x.where}", what))
    default = "1" if devices and devices[0].printer_like else ""
    if not devices:
        d.say("  no printer found.")
    for i, (name, where, what) in enumerate(rows, 1):
        d.say(f"  {i}  {name[:22]:22s} {where:28s} {what}")
    d.say("  t  a test file printer: the bytes go to a file, nothing prints")
    d.say("  s  a printer on another machine (ssh)")
    d.say("  a  type a Bluetooth address or a device path")
    while True:
        a = d.ask(f"Printer{f' [{default}]' if default else ''}: ").lower() or default
        if a.isdigit() and 1 <= int(a) <= len(devices):
            pr, hint = _from_device(devices[int(a) - 1])
            _use(st, pr, hint, devices[int(a) - 1].name, devices[int(a) - 1].kind)
            return
        if a == "t":
            path = d.ask("  file for the bytes [bobina-test.bin]: ") or "bobina-test.bin"
            pr, hint = _file(path)
            _use(st, pr, hint, "", "file")
            return
        if a == "s":
            host = d.ask("  the other machine: its ssh name (tower), or the whole command: ")
            if host:
                cmd = host if " " in host else f"ssh {host} bobina send --yes -"
                pr, hint = _command(cmd)
                _use(st, pr, hint, "", "command")
                return
        elif a == "a":
            value = d.ask("  Bluetooth address (AA:BB:CC:DD:EE:FF) or device path (/dev/usb/lp0): ")
            if discover.MAC.match(value) or value.startswith("/"):
                _printer_option(args, st, value)
                return
            d.say("  that is neither an address nor a path")
        else:
            d.say(f"  answer a number{' (1 to ' + str(len(devices)) + ')' if devices else ''}, t, s or a")


# ---------------------------------------------------------------- profile


def _profile_line(pid: str) -> str:
    p = profiles.load(pid)
    measured = "measured on paper" if p.get("measured", True) is not False else "not measured on paper"
    name = re.sub(r"\s*\(\d+ ?mm\)", "", p.name)  # Goldensky MTP-II (58 mm): the width is said next
    return f"{name}, {p.get('paper_mm', 58):g} mm paper, {measured}"


def _all_profiles() -> list:
    out = []
    for pid in profiles.available():
        try:
            p = profiles.load(pid)
        except (OSError, ValueError, KeyError):
            continue
        out.append((pid, p))
    return out


def _pick_profile(d: Dialog) -> str:
    every = _all_profiles()
    widths = sorted({float(p.get("paper_mm", 58)) for _, p in every})
    shown = "/".join(f"{w:g}" for w in widths)
    while True:
        a = d.ask(f"  paper width ({shown} mm) [58]: ") or "58"
        try:
            mm = paper.parse_width(a)
        except ValueError as e:
            d.say(f"  {e}")
            continue
        near = [w for w in widths if paper.fits(mm, w)]
        if near:
            break
        d.say(f"  no profile for {mm:g} mm paper: {shown} mm")
    rows = sorted((p for p in every if float(p[1].get("paper_mm", 58)) == near[0]),
                  key=lambda r: (r[0] != profiles.BUILTIN, r[1].get("measured", True) is False, r[1].name))  # fmt: skip
    for i, (pid, p) in enumerate(rows, 1):
        kind = "measured" if p.get("measured", True) is not False else "not measured"
        d.say(f"  {i:2d}  {pid:24s} {p.name} · {kind}")
    while True:
        a = d.ask("  profile [1]: ") or "1"
        if a.isdigit() and 1 <= int(a) <= len(rows):
            return rows[int(a) - 1][0]
        if a in dict(every):
            return a
        d.say(f"  a number from 1 to {len(rows)}, or a profile id (bobina profile list)")


def _choose_profile(args, st: Setup, d: Dialog | None) -> None:
    if args.profile:
        try:
            profiles.load(args.profile)
        except KeyError as e:
            raise Fail(USAGE, str(e).strip("'\""), problem="E207") from None
        st.profile, st.profile_by = args.profile, "option"
        return
    match = discover.match_profile(st.device) if st.device else None
    if d is None:
        if match:
            st.profile, st.profile_by = match, "name"
        elif st.pr and st.pr.get("profile") and st.found_by == "config":
            st.profile, st.profile_by = st.pr["profile"], "config"
        else:
            st.profile, st.profile_by = profiles.BUILTIN, "default"
            what = f"no profile matches '{st.device}'" if st.device else "no printer name to go by"
            _note(st, "P402", f"{what}: {profiles.BUILTIN} was taken ({_profile_line(profiles.BUILTIN)})",
                  "another: bobina init --profile ID (bobina profile list)")  # fmt: skip
        return
    if match:
        if d.yes(f"Profile: looks like a {_profile_line(match)}: right?", True):
            st.profile, st.profile_by = match, "name"
            return
    elif st.device:
        d.say(f"Profile: no profile matches '{st.device}'.")
    else:
        d.say("Profile: which printer is it?")
    st.profile, st.profile_by = _pick_profile(d), "chosen"


# ---------------------------------------------------------------- locale


def _locale(args, st: Setup, d: Dialog | None) -> dict:
    from .settings import _examples

    found = locales.Machine().peek()
    value = found.value or locales.FALLBACK

    def facts(tag: str, source: str) -> dict:
        shown = locales.printable(locales.parse(tag))
        return {"value": tag, "source": source, "example": _examples(shown)}

    if d is None:
        if found.source == "config" or args.dry_run:
            return facts(value, found.source)
        tag, notes = locales.Machine().get()  # saves an inferred one and says it (M203, M204)
        st.notes += [Nudge(c, m, None, h) for c, m, h in notes]
        if tag:
            st.changed.append("locale")
        return facts(tag or locales.FALLBACK, "config" if tag else "default")
    where = {"config": "config.toml", "default": "nothing else to go by"}.get(found.source, f"from {found.detail}")
    ex = " · ".join(facts(value, found.source)["example"].values())
    d.say(f"Locale (dates and money): {value} ({where}): {ex}")
    while True:
        a = d.ask("  Enter keeps it, or type another (en-US, pt-BR, fr-CA): ")
        if not a:
            tag = value
            break
        loc = locales.parse(a)
        if loc is not None:
            tag = locales.tag(loc)
            ex = " · ".join(facts(tag, "config")["example"].values())
            d.say(f"  {tag}: {ex}")
            break
        near = locales.closest(a)
        d.say(f"  '{a}' is not a locale bobina knows" + (f": did you mean {near}?" if near else ""))
    if found.source != "config" or tag != value:
        if not args.dry_run:
            config.set_value("locale", tag)
        st.changed.append("locale")
    return facts(tag, "config")


# ---------------------------------------------------------------- roll


def _roll_answer(d: Dialog, a: str) -> tuple[float, str, float | None] | None:
    """(length mm, note, width mm) from an answer as paper new takes it: 15m or 50ft is the length, 40mm or 1.5in
    the outer diameter (core 12 mm); a package code (57x30) asks what its number is. None: ask again."""
    m = paper.CODE.match(a)
    width = None
    if m:
        w, n, core = (x.strip() if x else "" for x in m.groups()[0::2])
        wu, nu, cu = (paper.CANON.get(u.lower(), u.lower()) if u else "" for u in m.groups()[1::2])
        inch = wu == "in" or (not wu and ("/" in w or paper._number(w) < 10))
        width = paper.parse_width(w + (wu or ("in" if inch else "mm")))
        if not nu:
            if inch:
                nu = "ft" if d.yes(f"  is {n} the roll's length in feet?", True) else "in"
            else:
                q = d.ask(f"  is {n} the length in metres (m) or the outer diameter in mm (mm)? ").lower()
                if q not in ("m", "mm"):
                    d.say("  answer m or mm")
                    return None
                nu = q
        a = n + nu + (f" core {core}{cu or 'mm'}" if core else "")
    core_mm = 12.0
    if " core " in a:
        a, _, c = a.partition(" core ")
        core_mm = paper.parse_length(c, "mm")
    mm = paper.parse_length(a, None)  # a unit is required: 15 is metres or mm?
    unit = paper.UNIT.match(a).group(2).lower()
    if paper.CANON.get(unit, unit) in ("mm", "in"):
        if mm <= core_mm:
            raise ValueError(f"a diameter of {a} is not more than the core ({core_mm:g} mm)")
        length = paper.from_diameter(mm, core_mm)
        return length, f"from diameter {a}, core {core_mm:g}mm, thickness 0.06 mm", width
    return mm, "", width


def _roll_now(name: str | None) -> dict:
    """The roll as paper.json has it: its length and what is left (None: not recorded)."""
    cur = (paper.get(name) if name else None) or {}
    roll = cur.get("roll_mm") or None
    left = round(roll - cur.get("used_mm", 0.0), 1) if roll else None
    return {"roll_mm": roll, "left_mm": left, "width_mm": cur.get("width_mm")}


def _roll(args, st: Setup, d: Dialog | None, prof) -> dict:
    out = _roll_now(st.name)
    cur = out["roll_mm"]
    if not common.counts_paper(st.pr or {}):
        if d:
            d.say("Roll: a file printer has no roll to count.")
        return out
    if d is None:
        if not cur:
            _note(st, "P104", f"the roll length of {st.name} is missing: without it bobina cannot estimate the"
                  " paper left", "when you know it: bobina paper new 30m (its length) or bobina paper new"
                  " --diameter 40mm (its outer diameter)")  # fmt: skip
        return out
    d.say("Roll: the roll in the printer: its length (15m, 50ft), outer diameter (40mm) or package code (57x30)")
    while True:
        a = d.ask("  roll (Enter skips): ")
        if not a:
            if not cur:
                _note(
                    st,
                    "P104",
                    f"the roll length of {st.name} is missing: without it bobina cannot estimate the paper left",
                    "when you know it: bobina paper new 30m or bobina paper new --diameter 40mm",
                )
            return out
        try:
            got = _roll_answer(d, a)
        except ValueError as e:
            msg = str(e)
            if "use 15m" in msg:
                msg = f"'{a}': give the unit: 15m (length) or 40mm (outer diameter)"
            d.say(f"  {msg}")
            continue
        if got:
            break
    mm, note, width = got
    paper_mm = float(prof.get("paper_mm", 58))
    if width and not paper.fits(width, paper_mm):
        _note(st, "P103", f"this {width:.0f} mm roll does not fit {st.name}: its profile ({prof.id}) takes"
              f" {paper_mm:g} mm paper", f"load a {paper_mm:g} mm roll")  # fmt: skip
    if not args.dry_run:
        paper.new_roll(st.name, mm, note, width)
    st.changed.append("roll")
    d.say(f"  new roll of {mm / 1000:.1f} m" + (f" ({note})" if note else ""))
    return (
        _roll_now(st.name)
        if not args.dry_run
        else {"roll_mm": round(mm, 1), "left_mm": round(mm, 1), "width_mm": round(width, 1) if width else None}
    )


# ---------------------------------------------------------------- test strip


def _strip_bytes(st: Setup, prof, loc: dict) -> tuple[bytes, float, list[str]]:
    """The test strip: a sample, then the feed test where the profile was not measured (and the printer was not
    calibrated), then the tear ruler at the very end: one print, the calibration read from the same paper."""
    from . import device

    pr = st.pr or {}
    over = {**common.printer_overrides(pr), "margins.feed_after_dots": 0}
    ex = loc["example"]
    sample = engine.build(
        f"# bobina {{.center}}\n\nPrinter {st.name} · {prof.id}\n\n{prof.get('paper_mm', 58):g} mm paper, "
        f"{prof.columns} columns\n\n**bold** *italic* ~~struck~~ `mono`\n\n{ex['date']} · {ex['money']}\n\n"
        "--- {.dashed}",
        profile_name=st.profile,
        overrides=over,
    )
    data, length, modules = sample.data, sample.length_mm, ["sample"]
    if prof.get("measured", True) is False and "blank_rows_after_raster" not in pr:
        fd, fl = device.feed_strip(st.profile, prof, pr, "A to B: 10 mm drawn as an image. B to C: a 10 mm paper"
                                   " feed. Do B and C touch, or are they apart like A and B?", tail=False)  # fmt: skip
        data, length = data + fd, length + fl
        modules.append("feed")
    td, tl, _ = device.tear_strip(st.profile, prof, pr, "Tear at the serrated edge and read the number (mm) at"
                                  " the torn edge: the distance from the head to the tear bar.")  # fmt: skip
    return data + td, length + tl, [*modules, "tear"]


def _test_strip(args, st: Setup, d: Dialog, prof, loc: dict) -> None:
    from . import device

    data, length, modules = _strip_bytes(st, prof, loc)
    calib = " and ".join({"feed": "the feed test", "tear": "the tear ruler"}[m] for m in modules[1:])
    st.strip = {"printed": False, "length_mm": round(length, 1), "modules": modules, "tear_mm": None,
                "blank_rows_after_raster": None}  # fmt: skip
    if not d.yes(f"Print a test strip? (~{length / 10:.0f} cm: a sample, then {calib})", False):
        return
    if args.dry_run:
        d.say("  dry run: not printed")
        return
    args.printer = st.name
    common.do_send(args, data, prof, length_mm=length)
    st.strip["printed"] = True
    st.changed.append("test strip")
    if not common.counts_paper(st.pr or {}):
        d.say(f"  written to {st.pr.get('path')}: no paper to read, so no calibration questions (on a real printer:"
              " bobina calibrate tear)")  # fmt: skip
        return
    if "feed" in modules:
        while True:
            a = d.ask("  feed test: lines B and C touching, or apart (like A and B)? Enter skips: ").lower()
            ans = {"t": "touching", "a": "apart"}.get(a, a)
            if not a or ans in device.FEED_ANSWERS:
                break
            d.say("  answer touching or apart")
        if a:
            st.strip["blank_rows_after_raster"] = device.FEED_ANSWERS[ans]
            device._keep(st.name, "blank_rows_after_raster", device.FEED_ANSWERS[ans])
    while True:
        a = d.ask("  tear at the serrated edge: the number (mm) at the torn edge? Enter skips: ")
        if not a:
            return
        try:
            mm = device._tear_mm(a)
            break
        except Fail as e:
            d.say("  " + str(e).split("\n")[0])
    st.strip["tear_mm"] = mm
    device._keep(st.name, "tear_mm", mm)
    d.say(f"  tear bar at {mm:g} mm from the head: every job now ends past it")


# ---------------------------------------------------------------- the command


def _current(d: Dialog, name: str, pr: dict) -> set:
    from .settings import _examples

    found = locales.Machine().peek()
    loc = locales.printable(locales.parse(found.value or locales.FALLBACK))
    r = paper.get(name) if common.counts_paper(pr) else None
    roll = (f"~{(r['roll_mm'] - r.get('used_mm', 0)) / 1000:.1f} m left of {r['roll_mm'] / 1000:.1f} m" if r and
            r.get("roll_mm") else "not set" if common.counts_paper(pr) else "a file: none")  # fmt: skip
    d.say("bobina is set up here:")
    d.say(f"  1 printer   {name} ({_where(pr)})")
    d.say(f"  2 profile   {_profile_line(pr.get('profile') or profiles.BUILTIN)}")
    d.say(f"  3 locale    {found.value or locales.FALLBACK}: {' · '.join(_examples(loc).values())}")
    d.say(f"  4 roll      {roll}")
    d.say("  5 test strip")
    while True:
        a = d.ask("What to change? (numbers or names, 1,3; Enter: nothing): ").lower()
        if not a:
            return set()
        picked = set()
        for w in re.split(r"[,\s]+", a):
            hit = [s for i, s in enumerate(STEPS, 1) if w == str(i) or (w and s.startswith(w))]
            if not hit and w not in ("test", "strip"):
                break
            picked |= set(hit or ["test strip"])
        else:
            return picked | ({"profile"} if "printer" in picked else set())
        d.say(f"  1 to 5, or {', '.join(STEPS)}")


def _save_printer(st: Setup) -> None:
    pr, profile = dict(st.pr or {}), st.profile

    def change(cfg):
        printers = cfg.setdefault("printers", {})
        name = _name_for(cfg, pr, st.name)
        entry = printers.get(name, {})
        entry.update(pr)
        entry["profile"] = profile
        printers[name] = entry
        cfg["default_printer"] = name
        return name

    st.name = config.update(change)
    st.pr = config.load()["printers"][st.name]


def cmd_init(args):
    if args.seconds < 1:
        raise Fail(USAGE, "--seconds: 1 or more (the Bluetooth scan)", problem="E304")
    auto = args.yes or common.noninteractive()
    d = None if auto else Dialog(sys.stderr if args.json else sys.stdout)
    st = Setup()
    cfg = config.load()
    cur_name, cur_pr = config.printer(cfg, None)
    configured = bool(cur_pr) and cur_name in (cfg.get("printers") or {})
    todo = set(STEPS)
    if configured and not (args.printer or args.command):
        st.name, st.pr, st.found_by = cur_name, dict(cur_pr), "config"
        keep = {"locale", "roll"} | ({"profile"} if args.profile else set())  # --yes: the printer stays
        todo = _current(d, cur_name, cur_pr) if d else keep
    elif d:
        d.say("bobina init: a printer, its profile, the locale, the roll, and a test strip. Ctrl-C stops.\n")
    if "printer" in todo:
        if args.command:
            pr, hint = _command(args.command)
            _use(st, pr, hint, "", "command")
        elif args.printer:
            _printer_option(args, st, args.printer)
        elif d:
            _ask_printer(args, st, d)
        else:
            _auto_printer(args, st)
        if d:
            d.say(f"  → {st.name}: {_where(st.pr)}")
    if "profile" in todo:
        _choose_profile(args, st, d)
    else:
        st.profile, st.profile_by = (st.pr or {}).get("profile") or profiles.BUILTIN, "config"
    if {"printer", "profile"} & todo:
        if (st.pr or {}).get("profile") != st.profile or st.found_by != "config":
            st.changed += [s for s in ("printer", "profile") if s in todo]
        if not args.dry_run:
            _save_printer(st)
        elif st.name is None:
            st.name = _name_for(config.load(), st.pr, "printer")
    prof = engine.apply_overrides(profiles.load(st.profile), common.printer_overrides(st.pr))
    from .settings import _examples

    if "locale" in todo:
        loc = _locale(args, st, d)
    else:
        found = locales.Machine().peek()
        tag = found.value or locales.FALLBACK
        loc = {"value": tag, "source": found.source, "example": _examples(locales.printable(locales.parse(tag)))}
    roll = _roll(args, st, d, prof) if "roll" in todo else _roll_now(st.name)
    if "test strip" in todo and d:
        _test_strip(args, st, d, prof, loc)
    return _report(args, st, d, prof, loc, roll)


def _report(args, st: Setup, d: Dialog | None, prof, loc: dict, roll: dict) -> int:
    nxt = [FIRST]
    if any(n.code == "P104" for n in st.notes):
        nxt.append("bobina paper new 30m")
    if args.json:
        print_json({
            "schema": "bobina.init/1", "dry_run": bool(args.dry_run), "changed": st.changed,
            "printer": {"name": st.name, "transport": (st.pr or {}).get("transport", "bluetooth"),
                        "where": _target(st.pr or {})[1], "found_by": st.found_by},
            "found": [x.as_dict() for x in st.found],
            "picked": st.picked or None,
            "profile": {"id": prof.id, "name": prof.name, "paper_mm": float(prof.get("paper_mm", 58)),
                        "measured": prof.get("measured", True) is not False, "by": st.profile_by},
            "locale": loc, "roll": roll, "test_strip": st.strip,
            "problems": [n.as_dict() for n in st.notes], "next": nxt,
        }, indent=2, ensure_ascii=False)  # fmt: skip
        return OK
    say = d.say if d else print
    head = "dry run: nothing saved. bobina would be set up so:" if args.dry_run else "bobina is set up:"
    say(("\n" if d else "") + head)
    say(f"  printer   {st.name} ({_where(st.pr or {})}), the default")
    if st.picked:
        say(f"            {st.picked}; another: bobina init --yes --printer ADDRESS")
    say(f"  profile   {prof.id}: {_profile_line(prof.id)}")
    say(f"  locale    {loc['value']}: {' · '.join(loc['example'].values())}")
    if common.counts_paper(st.pr or {}):
        r = roll
        say(
            f"  roll      ~{r['left_mm'] / 1000:.1f} m left of {r['roll_mm'] / 1000:.1f} m"
            if r.get("roll_mm")
            else "  roll      not set: bobina paper new 30m when you know it"
        )
    pr = config.load().get("printers", {}).get(st.name, st.pr or {})
    cal = [f"tear bar at {pr['tear_mm']:g} mm"] if pr.get("tear_mm") else []
    if "blank_rows_after_raster" in pr:
        cal.append("feeds after images: " + ("white rows (safe)" if pr["blank_rows_after_raster"] else "ESC J"))
    if cal:
        say(f"  measured  {' · '.join(cal)}")
    say(f"first print: {FIRST}" + ("  (without a terminal, add --yes)" if not d else ""))
    left = st.notes[st.said :] if d else st.notes
    if left and not args.quiet:
        sys.stdout.flush()  # the summary first, then its notes
        for line in render_problems(left, ""):
            err(line)
    return OK
