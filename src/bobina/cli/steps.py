"""A print of several labels stops after each one, so it can be torn off on the tear bar (decided 12/11).

On for a person at a terminal printing on a real printer; never without a terminal (agents, MCP, scripts, pipes,
BOBINA_NONINTERACTIVE), with --yes (unless --step is written), -o, --dry-run or a file printer. --no-step prints
one job at once, bobina config set step off every job; --step N stops every N labels. --compact glues the labels
on purpose, so it prints at once (P105). Each stop is its own send: the Bluetooth link is closed while the
person tears, and the next label connects again."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from .. import config, config_keys
from ..nudges import CATALOG
from ..problem_help import FIX
from .common import Fail, ask, err, open_tty, paper_printer, plural

NEXT = ("", "c", "n", "next", "continue", "p", "print")  # p: what the confirmation taught
ALL = ("a", "all")
AGAIN = ("r", "again")
SKIP = ("s", "skip")
STOP = ("q", "quit", "stop")


def setting(args) -> tuple[int, bool]:
    """(labels per stop, 0 = no stops; True when the command line chose it). The first part that says --step or
    --no-step decides (it is a job option); else step in config.toml (default on). A value bobina cannot read
    there is said once and taken as on: a typo in the config never stops a print."""
    for a in [args, *getattr(args, "chain", [])]:
        v = getattr(a, "step", None)
        if v is not None:
            return int(v), True
    return (1 if config_keys.read(config.load(), "step", say=err) else 0), False


def labels_of(res) -> list:
    return list(getattr(res, "labels", None) or [res])


def _terminal() -> bool:
    tty = open_tty()
    if tty is None:
        return False
    tty.close()
    return True


def plan(args, n: int, stripped: bool = False, note=None) -> int:
    """How many labels between stops for a print of n labels, 0 = none. note(code) is called when the stops
    would have happened but cannot (P105 glued labels, P106 no terminal for --step)."""
    every, explicit = setting(args)
    if not every or every >= n or args.dry_run or args.output or paper_printer(args) is None:
        return 0  # --step 5 with 3 labels: nothing to stop between, they print at once
    if args.yes and not explicit:  # --yes asks nothing: a script or an agent never waits for a key
        return 0
    if stripped:  # glued on purpose, to be cut apart later
        if note:
            note("P105")
        return 0
    if not _terminal():
        if explicit and note:
            note("P106")
        return 0
    return every


def message(code: str) -> tuple[str, str]:
    """The message and the hint of a step note, as the catalog and docs/problems say them."""
    return CATALOG[code][1], FIX[code]


def plan_job(args, res) -> int:
    """plan() for a built job, worked out once per job (a rebuilt job after [e] gets its own): its notes go to the
    job's problems, so the confirmation screen shows them."""
    if getattr(res, "_step_every", None) is not None:
        return res._step_every
    nudges = res.first.nudges if hasattr(res, "first") else res.nudges

    def note(code):
        if not any(x.code == code for x in nudges):
            msg, hint = message(code)
            nudges.add(code, msg, None, hint)

    res._step_every = plan(args, len(labels_of(res)), bool(getattr(res, "stripped", False)), note)
    return res._step_every


def screen_line(n: int, every: int) -> str:
    """Said on the confirmation screen, above [p] print."""
    each = "each label" if every == 1 else f"every {every} labels"
    return f" {n} labels: bobina stops after {each} so you can tear it off (--no-step: all at once)"


def title(label) -> str:
    """The first line of text of a label, for the pause line ("4/10 · Honey jar")."""
    from ..rows import TextRow

    if getattr(label, "title", None) is not None:  # a stored label of --last: its title was kept
        return label.title
    for row in getattr(label, "rows", None) or []:
        if isinstance(row, TextRow):
            text = " ".join("".join(c.ch for c in row.cells).split())
            if text:
                return text if len(text) <= 32 else text[:31] + "…"
    return ""


@dataclass
class Run:
    """What happened to each label: printed (again with [r]: still once here), skipped, or never reached."""

    total: int
    printed: set[int] = field(default_factory=set)
    skipped: set[int] = field(default_factory=set)
    next: int = 0  # the first label not reached yet
    stopped: bool = False
    length_mm: float = 0.0  # paper sent, reprints included

    @property
    def complete(self) -> bool:
        return not self.skipped and self.next >= self.total


def run(labels: list, every: int, send, st: Run) -> Run:
    """Prints `labels` (each with .data and .length_mm) `every` at a time, asking on the terminal between pieces.
    send(data, length_mm) prints one piece and raises Fail when the printer fails. `st` says what printed, also
    when send raises (the caller keeps those labels' seq numbers): a piece that failed part way, or was
    interrupted, counts as printed (rather skip a number than print it twice)."""
    last = range(0)

    def out(r: range) -> None:
        nonlocal last
        try:
            send(b"".join(labels[i].data for i in r), sum(labels[i].length_mm for i in r))
        except Fail as e:
            if getattr(e, "partial", False):  # part of it may be on paper: its numbers are spent
                st.printed.update(r)
                st.next = max(st.next, r.stop)
            raise
        except BaseException:  # Ctrl-C while sending: the piece may be on paper
            st.printed.update(r)
            st.next = max(st.next, r.stop)
            raise
        st.printed.update(r)
        last = r

    first = range(0, min(every, st.total))
    out(first)
    st.next = first.stop
    tty = open_tty()
    if tty is None:  # the terminal went away after the confirmation: the rest at once
        out(range(st.next, st.total))
        st.next = st.total
        return st
    with tty:
        said = f" ✓ {first.stop}/{st.total} printed: tear it off"
        while st.next < st.total:
            nxt = range(st.next, min(st.next + every, st.total))
            what = f"{nxt.start + 1}/{st.total}" if len(nxt) == 1 else f"{nxt.start + 1}-{nxt.stop}/{st.total}"
            name = title(labels[nxt.start])
            tty.write(said + "\n")
            try:
                a = ask(tty, f" [Enter] next ({what}{' · ' + name if name else ''})   [a] all {st.total - st.next} "
                             "left   [r] again   [s] skip   [q] stop\n> ")  # fmt: skip
            except KeyboardInterrupt:
                a = "q"
            if a in NEXT:
                out(nxt)
                st.next = nxt.stop
                said = f" ✓ {st.next}/{st.total} printed: tear it off"
            elif a in ALL:
                out(range(st.next, st.total))
                st.next = st.total
            elif a in AGAIN:
                out(last)  # the same bytes, so the same numbers: printed again on purpose
                said = " ✓ printed again: tear it off"
            elif a in SKIP:
                st.skipped.update(nxt)
                st.next = nxt.stop
                said = f" skipped {what}"
            elif a in STOP:
                st.stopped = True
                break
            else:
                said = " type Enter, a, r, s or q"
    return st


def send_labels(args, labels: list, every: int, profile, do_send) -> tuple[list[str], Run]:
    """run() on the configured printer: each piece is one do_send (its paper counted). -> (printer names, Run).
    On a failure the Run is attached to the exception (e.step_run) for the caller's summary."""
    st = Run(len(labels))
    names: list[str] = []

    def send(data: bytes, length_mm: float) -> None:
        names.append(do_send(args, data, profile, length_mm=length_mm))
        st.length_mm += length_mm

    try:
        run(labels, every, send, st)
    except BaseException as e:
        e.step_run = st
        raise
    return names, st


def add_summary(e: Fail, st: Run, argv=None, res=None) -> None:
    """A failure after some labels printed says how many, and how to print the rest."""
    if st.printed:
        e.args = (e.args[0] + "\n  " + summary(st, argv, res),)
        e.outcome = f"{len(st.printed)} of {plural(st.total, 'label')} printed"


def summary(st: Run, argv: list[str] | None = None, res=None, where: str = "") -> str:
    """After the job: how many printed (on where, ~cm) and, stopped before the end, the command for the rest."""
    of = f"{len(st.printed)} of {plural(st.total, 'label')} printed"
    skipped = f", {len(st.skipped)} skipped" if st.skipped else ""
    on = f" on {where} (~{st.length_mm / 10:.1f} cm)" if where else ""
    if st.next >= st.total:
        return of + on + skipped
    line = f"stopped: {of}{on}{skipped}, {st.total - st.next} not printed"
    rest = resume_command(argv, res, st.next) if res is not None else ""
    if rest:
        return line + f"\n  to print the rest: {rest}"
    left = f"{st.next + 1}" if st.next + 1 == st.total else f"{st.next + 1}-{st.total}"
    return line + f"\n  not printed: labels {left} of this job; no option starts a job there (print those parts or" \
                  " rows on their own)"  # fmt: skip


def resume_command(argv: list[str] | None, res, start: int) -> str:
    """The command that prints labels[start:]: the same command with --rows (data), --copies or --repeat for
    what is left. "" when no option says it (--then, --last, copies of several labels, among a row's copies)."""
    if not argv or getattr(res, "groups", None):
        return ""
    if any(t == "--then" or t.startswith("--then=") or t == "--last" for t in argv):
        return ""
    from ..datasource import LINE

    labels = labels_of(res)
    results = getattr(res, "results", [res])
    if getattr(res, "copies", 1) != 1:
        return _command(argv, {"--copies": str(len(labels) - start)}) if len(results) == 1 else ""
    lines = [(getattr(r, "fields", None) or {}).get(LINE) for r in results]
    if all(x is not None for x in lines):  # --data: one or more labels per row (--copies-from), in file order
        r = labels[start]
        if start and labels[start - 1] is r:  # among the copies of one row: --rows cannot say "2 of 3"
            return ""
        a, b = lines[results.index(r)], lines[-1]
        return _command(argv, {"--rows": str(a) if a == b else f"{a}-{b}"})
    return _command(argv, {"--repeat": str(len(labels) - start)})  # new seq numbers for the rest


def _command(argv: list[str], replace: dict[str, str]) -> str:
    out, i = [], 0
    while i < len(argv):
        tok = argv[i]
        if tok.split("=", 1)[0] in replace:
            i += 1 if "=" in tok else 2
            continue
        out.append(tok)
        i += 1
    for k, v in replace.items():
        out += [k, v]
    return "bobina " + shlex.join(out)
