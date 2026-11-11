"""Commands that talk to the printer or describe it: send, status, mode, printer, paper, calibrate."""

from __future__ import annotations

import sys
from pathlib import Path  # noqa: F401
from types import SimpleNamespace

from .. import config, engine, transport
from .. import profile as profiles
from . import common
from .common import (
    CONFIRM,
    OK,
    PRINTER_ERR,
    STATUS_LIST,
    UNREACHABLE,
    USAGE,
    Fail,
    ask,
    build,
    do_send,
    err,
    print_json,
    printer_name,
    printer_status,
    read_input,
)

SEND_MAX = 64_000_000  # a 1000-label job is ~0.2 MB; photos a few MB


def cmd_send(args):
    data = sys.stdin.buffer.read(SEND_MAX + 1) if args.file == "-" else Path(args.file).read_bytes()
    if len(data) > SEND_MAX:
        raise Fail(USAGE, f"more than {SEND_MAX // 1_000_000} MB of raw bytes: not a print job", problem="E201")
    prof = profiles.load(args.profile)
    if not args.yes:
        tty = common.open_tty()
        if tty is None:
            raise Fail(
                CONFIRM, f"{len(data)} raw bytes: confirmation required (no terminal). Use --yes.", problem="E107"
            )
        with tty:
            if ask(
                tty, f" send {len(data)} raw bytes untouched (no checks, no preview)? [p] print [q] quit\n> "
            ) not in ("p", "print"):
                return CONFIRM
    if args.dry_run:
        err(f"dry run: {len(data)} bytes not sent")
        return OK
    do_send(args, data, prof, check_status=False)
    return OK


def cmd_status(args):
    if args.list:
        for k, v in STATUS_LIST:
            print(f"{k:16s} {v}")
        return OK
    name, pr = config.printer(config.load(), args.printer)
    if pr is None:
        raise Fail(UNREACHABLE, "no printer configured: bobina printer add NAME ADDRESS", problem="E401")
    if pr.get("transport", "bluetooth") != "bluetooth":
        path = str(pr.get("path", ""))
        if pr.get("transport") != "file":
            where = "it only runs a command"
        elif path.startswith("/dev/"):
            where = f"it writes to the device {path}, which gives no status here"
        else:
            where = f"its bytes are appended to {path}"
        raise Fail(
            USAGE,
            f"status needs a bluetooth printer ('{name}' uses {pr.get('transport')}: {where})"
            "\n→ printing works the same; bobina printer list shows each printer and where it goes",
            problem="E404",
        )
    st = printer_status(pr)
    if args.json:
        print_json({"printer": name, **st}, indent=2)
    else:
        print(
            f"{name}: "
            + (
                "ready"
                if st.get("online") and not st.get("cover_open") and not st.get("paper_out") and not st.get("error")
                else "NOT ready"
            )
        )
        for k, v in st.items():
            print(f"  {k:16s} {v}")
        if st.get("paper_out") and profiles.load(args.profile).get("status.cover_sensor", True) is False:
            print(f"  → {common.PAPER_OUT_HINT}")
    if st.get("cover_open") or st.get("paper_out") or st.get("error"):
        return PRINTER_ERR
    return OK


MODES = {"esc": 0x55, "tspl": 0x33, "cpcl": 0x44}


def cmd_mode(args):
    name, pr = config.printer(config.load(), args.printer)
    if not args.language:
        print(
            "The printer cannot report its command language. bobina needs ESC/POS (esc).\n"
            "  bobina mode esc    switch back to ESC/POS (receipts, this tool)\n"
            "  bobina mode tspl   labels (TSC)        bobina mode cpcl   (Zebra-like)\n"
            "Proprietary command 1F 1B 1F FC 01 02 03 xx; the MTP-II-6114 ignores it (docs/printers/mtp-ii-58.md)."
        )
        if pr and pr.get("transport", "bluetooth") == "bluetooth":
            st = printer_status(pr, quiet=True)
            print(f"\n{name}: " + ("answers DLE EOT → ESC/POS" if st and st.get("answered") else "no DLE EOT answer"))
        return OK
    data = bytes([0x1F, 0x1B, 0x1F, 0xFC, 0x01, 0x02, 0x03, MODES[args.language]])
    prof = profiles.load(args.profile)
    if prof.get("language_switch", True) is False:
        err(
            f"note: profile {prof.id} ignores this command (ESC/POS only, tested); "
            "sending anyway — it is harmless here."
        )
    elif args.language != "esc":
        err("warning: after this, bobina print will not work until: bobina mode esc")
    if not args.yes:
        tty = common.open_tty()
        if tty is None:
            raise Fail(CONFIRM, "confirmation required (no terminal). Use --yes.", problem="E107")
        with tty:
            if ask(tty, f" switch {name} to {args.language.upper()}? [y/N] ") not in ("y", "yes"):
                return CONFIRM
    if args.dry_run:
        print(data.hex(" "))
        return OK
    do_send(args, data, prof, check_status=False)
    print(f"{name}: switched to {args.language}")
    return OK


def cmd_printer(args):
    cfg = config.load()
    printers = cfg.setdefault("printers", {})
    if args.action == "list":
        if args.json:
            print_json({"default": cfg.get("default_printer"), "printers": printers}, indent=2)
            return OK
        if not printers:
            print("no printers. Add one: bobina printer add NAME ADDRESS   (find it: bobina printer scan)")
        for n, p in printers.items():
            star = "*" if n == cfg.get("default_printer") else " "
            where = p.get("address") or p.get("command") or p.get("path")
            print(
                f"{star} {n:12s} {p.get('transport', 'bluetooth'):10s} {where}  [{p.get('profile', profiles.BUILTIN)}]"
            )
        return OK
    if args.action == "scan":
        try:
            for mac, nm in transport.scan(args.seconds):
                print(f"{mac}  {nm}")
        except transport.PrinterUnreachable as e:
            raise Fail(UNREACHABLE, str(e), problem="E402") from e
        return OK
    if args.action == "add":
        if not args.name or not (args.address or args.command or args.path):
            raise Fail(USAGE, "usage: bobina printer add NAME ADDRESS | --command CMD | --path FILE", problem="E101")
        p = {"transport": "command" if args.command else "file" if args.path else "bluetooth"}
        if args.address:
            p["address"] = args.address
            p["channel"] = args.channel
        if args.command:
            p["command"] = args.command
        if args.path:
            p["path"] = args.path
        p["profile"] = args.profile or profiles.BUILTIN

        def add(cfg):
            cfg.setdefault("printers", {})[args.name] = p
            if args.default or not cfg.get("default_printer"):
                cfg["default_printer"] = args.name

        config.update(add)
        print(f"added {args.name} → {config.path()}")
        from .. import locales

        _, notes = locales.Machine().get()  # a new machine: its locale is chosen (and said) here too
        if notes and not args.quiet:
            from ..nudges import Nudge

            for line in common.render_problems([Nudge(c, m, None, h) for c, m, h in notes], ""):
                err(line)
        return OK
    if args.action in ("use", "remove"):

        def change(cfg):
            printers = cfg.setdefault("printers", {})
            if args.name not in printers:
                raise Fail(USAGE, f"unknown printer '{args.name}' (see: bobina printer list)", problem="E401")
            if args.action == "use":
                cfg["default_printer"] = args.name
            else:
                del printers[args.name]
                if cfg.get("default_printer") == args.name:
                    cfg.pop("default_printer")

        config.update(change)
        print(f"{args.action}: {args.name}")
        return OK
    return USAGE


def cmd_paper(args):
    from .. import paper

    name = printer_name(args)
    if not name:
        raise Fail(UNREACHABLE, "no printer configured: bobina printer add NAME ADDRESS", problem="E401")
    code, shown = OK, []  # P103, when the roll is not the printer's width
    try:
        if args.action == "new":
            for given in (args.length, args.diameter):  # a package code: the question it raises, never a guess
                if given and (advice := paper.code_advice(given, cli=True)):
                    raise Fail(USAGE, advice, problem="E304")
            width = paper.parse_width(args.width) if args.width else None  # a wrong width records nothing
            if args.diameter:
                mm = paper.from_diameter(
                    paper.parse_length(args.diameter, "mm"), paper.parse_length(args.core, "mm"), float(args.thickness)
                )
                note = f"from diameter {args.diameter}, core {args.core}, thickness {args.thickness} mm"
            elif args.length or config.load().get("paper_roll"):
                spec = args.length or config.load()["paper_roll"]
                mm, note = paper.parse_length(spec), "" if args.length else f"default roll {spec}"
            else:
                raise Fail(
                    USAGE,
                    "usage: bobina paper new LENGTH (10m) | --diameter 30mm [--core 12mm]  "
                    "(--remember saves LENGTH as the default roll)",
                    problem="E101",
                )
            shown = _roll_width(args, name, width).filtered(common.allow_set(args)) if width else []
            if not common.strict_hits(shown, args):  # --strict: P103 stops it; otherwise recorded anyway
                if args.remember and args.length:
                    config.update(lambda cfg: cfg.__setitem__("paper_roll", args.length))
                paper.new_roll(name, mm, note, width)
                if not args.json:  # --json: the roll as it is now, below
                    wide = f", {width:.0f} mm wide" if width else ""
                    print(f"{name}: new roll of {mm / 1000:.1f} m{wide}" + (f" ({note})" if note else ""))
            if shown:
                code = common.report_nudges(SimpleNamespace(visible_nudges=lambda: shown), args)
            if not args.json:
                return code
        if args.action == "used":
            if not args.length:
                raise Fail(
                    USAGE, "usage: bobina paper used LENGTH|+LENGTH  (3m = total so far, +30cm = add)", problem="E101"
                )
            if args.length.startswith("+"):
                paper.add(name, paper.parse_length(args.length[1:]), count=False)
            else:
                paper.add(name, paper.parse_length(args.length, zero=True), set_to=True)
    except ValueError as e:
        raise Fail(USAGE, str(e), problem="E304") from None
    r = paper.get(name)
    problems = {"problems": [n.as_dict() for n in shown]} if shown else {}
    if not r or not r.get("roll_mm"):  # 0: a damaged or hand-edited roll
        if args.json:
            print_json({"printer": name, "roll_mm": None, "left_mm": None, **problems}, indent=2)
        else:
            print(f"{name}: roll length unknown. When you load a roll: bobina paper new 15m  (or --diameter 40mm)")
        return code
    left = r["roll_mm"] - r.get("used_mm", 0.0)
    avg = r["printed_mm"] / r["prints"] if r.get("prints") and r.get("printed_mm") else None
    if args.json:
        print_json({"printer": name, **r, "left_mm": round(left, 1), **problems}, indent=2)
        return code
    print(
        f"{name}: ~{max(left, 0) / 1000:.2f} m left of {r['roll_mm'] / 1000:.1f} m "
        f"({max(left, 0) / r['roll_mm'] * 100:.0f}%) · {r.get('prints', 0)} prints since {r['loaded']}"
    )
    if avg:
        print(f"  average print {avg / 10:.1f} cm → about {int(max(left, 0) // avg)} more like it")
    print(
        "  estimate: prints from other apps, raw send jobs and the self-test are not counted\n"
        "  correct with: bobina paper used +30cm (add) or bobina paper used 3m (total)"
    )
    return OK


def _roll_width(args, name: str, width: float):
    """Nudges: P103 when the roll is not as wide as the printer's paper (an 80 mm roll on a 58 mm printer). Recorded
    anyway: the user may be about to move it, or the profile may be the wrong one."""
    from .. import paper
    from ..nudges import Nudges

    cfg = config.load()
    _, prof = _strip_profile(args, cfg, config.printer(cfg, name)[1] or {})
    paper_mm = float(prof.get("paper_mm", 58))
    n = Nudges()
    if paper.fits(width, paper_mm):
        return n
    n.add(
        "P103",
        f"this {width:.0f} mm roll does not fit {name}: its profile ({prof.id}) takes {paper_mm:g} mm paper",
        None,
        f"load a {paper_mm:g} mm roll, or record this one for the printer it fits (--printer)",
    )
    return n


def tear_ruler(profile):
    """Ruler printed at the very end of the paper: the mark at the torn edge is the head→tear-bar distance."""
    from PIL import Image, ImageDraw

    from ..emulator import Emulator
    from ..rows import Cell

    em = Emulator(profile)
    W, dpmm, top = profile.width_dots, profile.dpi / 25.4, 30
    h = int(top * dpmm) + 2
    im = Image.new("L", (W, h), 255)
    d = ImageDraw.Draw(im)
    for k in range(0, top + 1):
        y = int(round((top - k) * dpmm))
        long = k % 5 == 0
        L = 90 if long else 40
        d.rectangle((0, y, L, y + 1), fill=0)
        d.rectangle((W - 1 - L, y, W - 1, y + 1), fill=0)
        if long and k:
            lab = em.line_image([Cell(c) for c in f"{k} mm"])
            im.paste(lab, ((W - lab.width) // 2, max(0, y - lab.height // 2)))
    return im.convert("1", dither=Image.NONE)


def _tear_mm(value: str) -> float:
    """calibrate tear MM: 16, 16mm or 1,6cm read at the torn edge; the ruler goes up to 30 mm."""
    import math

    from .. import paper

    try:
        mm = paper.parse_length(value, "mm")
    except ValueError:
        mm = float("nan")
    if not math.isfinite(mm) or not 0 < mm <= 100:
        raise Fail(USAGE, f"calibrate tear {value}: give the number read at the torn edge, in mm (like 16 or 16mm)",
                   problem="E101")  # fmt: skip
    return round(mm, 1)


def _say(args, text: str, **data) -> None:
    """calibrate tear|feed: the sentence for people, or the same facts as JSON with --json."""
    if args.json:
        common.print_json(data, indent=2, ensure_ascii=False)
    else:
        print(text)


FEED_ANSWERS = {"touching": True, "apart": False}  # B and C touch -> feeds after images need white rows


def _calibrated_printer(args, what: str):
    """(cfg, name, printer dict) of a printer saved in config.toml: a calibration is stored per printer, and a bare
    --printer MAC has nowhere to keep it (it was reported as saved and lost)."""
    cfg = config.load()
    name, pr = config.printer(cfg, args.printer)
    if pr is None:
        raise Fail(UNREACHABLE, "no printer configured: bobina printer add NAME ADDRESS", problem="E401")
    if (cfg.get("printers") or {}).get(name) is not pr:
        raise Fail(USAGE, f"calibrate {what} is kept per printer: add it first (bobina printer add NAME {name})",
                   problem="E101")  # fmt: skip
    return cfg, name, pr


def _keep(name: str, key: str, value) -> None:
    """Saves one measured value of printer NAME on the config as it is now (config.update)."""

    def change(cfg):
        if name not in (cfg.get("printers") or {}):  # removed by another command meanwhile
            raise Fail(USAGE, f"printer '{name}' is no longer in config.toml", problem="E401")
        cfg["printers"][name][key] = value

    config.update(change)


def _strip_printer(args):
    """(cfg, printer dict) for a strip: the configured printer, a bare --printer MAC, or {} (none, a dry run)."""
    cfg = config.load()
    return cfg, config.printer(cfg, args.printer)[1] or {}


def _strip_profile(args, cfg, pr):
    """The profile a print to this printer uses: --profile, the printer's, the config's (as _build)."""
    name = args.profile or pr.get("profile") or cfg.get("profile")
    return name, engine.apply_overrides(profiles.load(name), common.printer_overrides(pr))


def _confirm_strip(args, what: str) -> bool:
    """The confirmation of a calibration strip: --yes, or [p] on the terminal; no terminal and no --yes is E107."""
    if args.yes:
        return True
    tty = common.open_tty()
    if tty is None:
        raise Fail(CONFIRM, "confirmation required (no terminal). Use --yes.", problem="E107")
    with tty:
        if ask(tty, f" print {what}? [p] print [q] quit\n> ") in ("p", "print"):
            return True
    err("not printed (p prints)")  # never a silent exit: 'y' is a natural answer and it quit without a word
    return False


FEED_INTRO = (
    "Three lines below. A to B: 10 mm drawn as an image. B to C: a 10 mm paper feed. "
    "If B and C touch (or are closer than A and B): bobina calibrate feed touching. "
    "If they are 10 mm apart: bobina calibrate feed apart"
)


def feed_strip(prof_name, prof, pr, intro: str = FEED_INTRO, tail: bool = True) -> tuple[bytes, float]:
    """(bytes, length in mm) of the feed test: lines A, B, C. tail=False: nothing after C (bobina init prints the
    tear ruler right after it)."""
    from PIL import Image

    from .. import escpos

    head = engine.build(
        "# FEED TEST {.center}\n\n" + intro,
        profile_name=prof_name,
        overrides={**common.printer_overrides(pr), "margins.feed_after_dots": 0},
    )
    W, mm = prof.width_dots, prof.dpi / 25.4
    gap, top = round(10 * mm), round(3 * mm)
    end = int(prof.get("margins.feed_after_dots", 88)) if tail else 0
    line = escpos.raster(Image.new("1", (W, 3), 0), 3)  # one GS v 0 block each: the test needs B whole, then ESC J
    data = (
        head.data + escpos.blank_rows(W, top) + line + escpos.blank_rows(W, gap, band=gap) + line  # A, 10 mm, B
        + escpos.feed(gap) + line  # ESC J of 10 mm right after B, then C
        + (escpos.blank_rows(W, end) if end else b"")  # out past the tear bar whatever the answer
    )  # fmt: skip
    return data, head.length_mm + (top + 3 + gap + 3 + gap + 3 + end) / mm


TEAR_INTRO = (
    "Tear at the serrated edge. The number at the torn edge is the distance (mm) from the head to the tear bar. "
    "Then: bobina calibrate tear MM"
)


def tear_strip(prof_name, prof, pr, intro: str = TEAR_INTRO):
    """(bytes, length in mm, ruler image) of the tear test: a ruler at the very end of the paper, no feed after it."""
    from .. import escpos

    head = engine.build(
        "# TEAR TEST {.center}\n\n" + intro,
        profile_name=prof_name,
        overrides={**common.printer_overrides(pr), "margins.feed_after_dots": 0},  # build loads by name
    )
    ruler = tear_ruler(prof)
    data = head.data + escpos.raster(ruler, int(prof.get("transport.band_rows", 64)))
    return data, head.length_mm + ruler.height / (prof.dpi / 25.4), ruler


def _calibrate_feed(args):
    """Does this printer obey a paper feed right after an image? Prints lines A, B, C: A–B is 10 mm of white raster
    rows (exact on any printer), B–C is an ESC J of 10 mm sent right after B. On the MTP-II B and C touch (08/11). If
    they touch, the feed was ignored (or dropped while the printer was busy with the image): white rows fix both, so
    'touching' keeps the safe mode for this printer and 'apart' turns it off (ESC J again: ~4 KB less per label)."""
    if args.photo:
        answer = args.photo.lower()
        if answer not in FEED_ANSWERS:
            raise Fail(
                USAGE,
                f"calibrate feed {args.photo}: answer touching (lines B and C touch) or apart (10 mm, like A and B)",
                problem="E101",
            )
        cfg, name, pr = _calibrated_printer(args, "feed")
        value = FEED_ANSWERS[answer]
        facts = {"printer": name, "blank_rows_after_raster": value, "dry_run": bool(args.dry_run)}
        if args.dry_run:
            _say(args, f"dry run: {name} would be set to blank_rows_after_raster = {str(value).lower()}", **facts)
            return OK
        pr["blank_rows_after_raster"] = value
        _keep(name, "blank_rows_after_raster", value)
        if value:
            _say(args, f"{name}: feeds after images are not obeyed; they keep going as white rows (safe mode)", **facts)
        else:
            _say(args, f"{name}: ESC J works after images; feeds go as ESC J again, not white rows (faster, fewer "
                 "bytes)", **facts)  # fmt: skip
        return OK
    if args.dry_run:  # nothing is printed or saved: no printer needed, a bare --printer MAC is fine too
        cfg, pr = _strip_printer(args)
    else:
        cfg, name, pr = _calibrated_printer(args, "feed")
    prof_name, prof = _strip_profile(args, cfg, pr)
    data, length = feed_strip(prof_name, prof, pr)
    nxt = ["bobina calibrate feed touching", "bobina calibrate feed apart"]
    if args.dry_run:
        _say(args, f"dry run: {length / 10:.1f} cm (lines A, B, C; nothing printed)", printed=False,
             length_mm=round(length, 1), next=nxt)  # fmt: skip
        return OK
    if not _confirm_strip(args, f"the feed test (~{length / 10:.0f} cm)"):
        return CONFIRM
    do_send(args, data, prof, length_mm=length)
    _say(args, "look at lines B and C, then: bobina calibrate feed touching   (or: bobina calibrate feed apart)",
         printed=True, length_mm=round(length, 1), next=nxt)  # fmt: skip
    return OK


def cmd_calibrate(args):
    from PIL import Image

    from .. import fidelity

    if args.action == "feed":
        return _calibrate_feed(args)
    if args.action == "tear":
        if args.photo:  # bobina calibrate tear 16  → store it
            mm = _tear_mm(args.photo)
            cfg, name, pr = _calibrated_printer(args, "tear")
            facts = {"printer": name, "tear_mm": mm, "dry_run": bool(args.dry_run)}
            if args.dry_run:
                _say(args, f"dry run: {name} would be set to tear_mm = {mm:g}", **facts)
                return OK
            pr["tear_mm"] = mm
            _keep(name, "tear_mm", mm)
            over = common.printer_overrides(pr)
            feed_mm = over["margins.tear_mm"] + over["margins.tear_margin_mm"]
            _say(
                args,
                f"{name}: tear bar at {mm:g} mm from the head; jobs now end with "
                f"{feed_mm:.0f} mm of feed so the last line clears it",
                **facts,
                final_feed_mm=round(feed_mm, 1),
            )
            return OK
        cfg, pr = _strip_printer(args)
        prof_name, prof = _strip_profile(args, cfg, pr)  # the printer's profile, as the feed strip
        data, length, ruler = tear_strip(prof_name, prof, pr)
        nxt = ["bobina calibrate tear MM"]
        if args.dry_run:
            ruler.convert("L").save("tear-ruler.png")
            _say(args, f"dry run: {length / 10:.1f} cm; ruler saved as tear-ruler.png", printed=False,
                 length_mm=round(length, 1), files=["tear-ruler.png"], next=nxt)  # fmt: skip
            return OK
        if not _confirm_strip(args, f"the tear ruler (~{length / 10:.0f} cm, no final feed)"):
            return CONFIRM
        do_send(args, data, prof, length_mm=length)
        _say(args, "now tear at the serrated edge and read the number at the edge: bobina calibrate tear MM",
             printed=True, length_mm=round(length, 1), next=nxt)  # fmt: skip
        return OK
    if args.action != "compare" or not args.photo or not args.target:
        raise Fail(
            USAGE, "usage: bobina calibrate compare PHOTO DOCUMENT | tear [MM] | feed [touching|apart]", problem="E101"
        )
    source, base, origin = read_input(args)
    res = build(args, source, base)
    rep, sheet = fidelity.compare(Image.open(args.photo), res.image, res.profile)
    out = args.output or "fidelity.png"
    sheet.save(out)
    if args.json:
        print_json(rep.__dict__, indent=2)
    else:
        for line in rep.lines():
            print(line)
        print(f"side by side (exact | realistic | photo): {out}")
    return OK
