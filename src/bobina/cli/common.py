"""Shared CLI plumbing: exit codes, input, building, the confirmation screen, sending."""

from __future__ import annotations

import argparse
import errno
import json  # noqa: F401
import os
import re
import select
import subprocess
import sys
from pathlib import Path

from .. import config, datasource, editor, engine, state, transport, view  # noqa: F401
from ..nudges import Nudge, SecurityError, problems_header
from ..templating import Tainted

OK, USAGE, DOC, STRICT, UNREACHABLE, PRINTER_ERR, MODE, CONFIRM, SECURITY, LEFT_OUT = range(10)
# LEFT_OUT: the job went out (printed, saved, shown) without a part it exists for. A warning, so the rest still
# prints (nudges, not blocks), but a script or an agent with --yes must not read it as a clean print. --allow
# CODE silences it and the exit is 0 again.
LEFT_OUT_CODES = {"Q111"}  # a payment code that was not built: a receipt without its QR


_JSON_WRITTEN = [False]  # did this run answer --json? (main says so when a command or subcommand did not)


def print_json(obj, **kw) -> None:
    """Writes one JSON answer on stdout and remembers that --json was answered."""
    import json as _json

    _JSON_WRITTEN[0] = True
    print(_json.dumps(obj, **kw))


def json_written(reset: bool = False) -> bool:
    was = _JSON_WRITTEN[0]
    if reset:
        _JSON_WRITTEN[0] = False
    return was


def refuse_json_on_stdout_output(args) -> None:
    """--json writes one object on stdout: -o must not send the job's bytes or image there too."""
    out = getattr(args, "output", None)
    if not (getattr(args, "json", False) and out):
        return
    same = str(out) in ("/dev/stdout", "/dev/fd/1", "/proc/self/fd/1")  # "-" is a file named "-" for -o
    try:
        a, b = os.stat(os.path.expanduser(str(out))), os.fstat(sys.stdout.fileno())
        same = same or (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
    except (OSError, ValueError, AttributeError):  # no such file yet, or stdout without a descriptor (tests)
        pass
    if same:
        raise Fail(USAGE, f"--json and -o {out} would both write to stdout: drop --json, or save to a file",
                   problem="E101")  # fmt: skip


def strict_hits(job, args) -> bool:
    """--strict and a warning or error left: the job must not go out. job: a result, or its visible problems."""
    problems = job.visible_nudges() if hasattr(job, "visible_nudges") else job
    return bool(args.strict) and any(n.severity in ("warning", "error") for n in problems)


def job_json(res) -> dict:
    """The figures and the problems of a job, as check, print and preview --json write them."""
    return {"stats": res.stats(), "problems": [n.as_dict() for n in res.visible_nudges()]}


def job_code(job) -> int:
    """OK, or LEFT_OUT when a visible problem says part of the job was left out. job: a result or its problems."""
    problems = job.visible_nudges() if hasattr(job, "visible_nudges") else job
    return LEFT_OUT if any(n.code in LEFT_OUT_CODES for n in problems) else OK


ALIASES = {"p": "print", "c": "check", "pv": "preview", "v": "view", "e": "edit", "s": "status", "m": "mode"}


GLOBAL_WITH_VALUE = {"--profile", "--printer", "--allow", "--editor", "--problems"}


GLOBAL_FLAGS = {
    "--quiet",
    "-q",
    "--strict",
    "--json",
    "--dry-run",
    "-n",
    "--yes",
    "-y",
    "--verbose",
    "--debug",
    "--no-color",
}


class Fail(Exception):
    """A stop: exit code + message + problem code from the catalog (nudges.CATALOG, E-codes).
    problem="MULTI": several problems of a multi-part job, in .items."""

    def __init__(self, code: int, message: str, problem: str = "", items: list | None = None):
        super().__init__(message)
        self.code = code
        self.problem = problem
        self.items = items or []

    def problems(self) -> list:
        if self.problem == "MULTI":
            return self.items
        from ..nudges import Nudge

        head, _, hint = (self.args[0] if self.args else "").partition("\n")
        return [Nudge(self.problem or "E101", head, None, hint.strip().lstrip("→ ").strip(), severity="error")]

    def format(self) -> str:
        return "\n".join(render_problems(self.problems(), stopped()))


PROBLEM_FORMATS = ("pretty", "plain", "json", "jsonl")
_FMT = ["pretty"]


def set_problem_format(argv: list[str]) -> None:
    """--problems FORMAT (any command) or BOBINA_PROBLEMS; read from argv so parse errors follow it too."""
    fmt = os.environ.get("BOBINA_PROBLEMS", "pretty")
    for k, tok in enumerate(argv):
        if tok == "--problems" and k + 1 < len(argv):
            fmt = argv[k + 1]
        elif tok.startswith("--problems="):
            fmt = tok.split("=", 1)[1]
    _FMT[0] = fmt if fmt in PROBLEM_FORMATS else "pretty"


_STOPPED = ["nothing printed"]
STOPPED_BY_COMMAND = {  # what an error means for each command: the last words of the problems header
    "print": "nothing printed", "send": "nothing printed", "edit": "nothing printed",
    "calibrate": "nothing printed", "mode": "nothing sent to the printer",
    "preview": "nothing saved", "check": "", "view": "", "status": "", "history": "", "help": "", "fonts": "",
}  # fmt: skip


def command_word(argv: list[str]) -> str:
    """The command of a command line: the first word that is not an option nor the value of a global option,
    aliases resolved ("" when there is none). Used for the outcome of errors and for option hints."""
    skip = False
    for t in argv:
        if skip:
            skip = False
        elif t in GLOBAL_WITH_VALUE:
            skip = True  # its value is not the command
        elif not t.startswith("-"):
            return ALIASES.get(t, t)
    return ""


def set_command(argv: list[str]) -> None:
    """The command of this run, so errors end with the right outcome."""
    _STOPPED[0] = STOPPED_BY_COMMAND.get(command_word(argv) or "print", "nothing changed")


def stopped() -> str:
    return _STOPPED[0]


def render_problems(items: list, outcome: str) -> list[str]:
    """The problems in the chosen format: pretty (people), plain (one line each, grep), json (one object),
    jsonl (one object per line, for logs). Same fields everywhere: docs/CLI.md 'Problems'."""
    import json as _json

    fmt = _FMT[0]
    if fmt == "plain":
        return [_plain(n) for n in items]
    if fmt == "json":
        return [_json.dumps({"outcome": outcome, "problems": [n.as_dict() for n in items]}, ensure_ascii=False)]
    if fmt == "jsonl":
        return [_json.dumps({**n.as_dict(), "outcome": outcome}, ensure_ascii=False) for n in items]
    return nudge_block(items, outcome)


def _plain(n) -> str:
    where = " ".join(x for x in (n.source, f"line {n.line}" if n.line else "") if x)
    return (
        f"{n.severity} {n.code}"
        + (f" {where}" if where else "")
        + f": {n.message}"
        + (f" -- {n.suggestion}" if n.suggestion else "")
    )


def plural(n: int, word: str) -> str:
    """1 label, 2 labels (regular English nouns; the CLI text is English)."""
    return f"{n} {word}{'' if n == 1 else 's'}"


def err(msg: str):
    print(msg, file=sys.stderr)


STDIN_MAX = 10_000_000  # characters; a document is a few KB


def stdin_has_data(wait: float = 1.0) -> bool:
    if sys.stdin is None or sys.stdin.isatty():
        return False
    try:
        return bool(select.select([sys.stdin], [], [], wait)[0])
    except (OSError, ValueError):
        return False


def read_input(args) -> tuple[str, str, str]:
    """-> (source, base_dir, origin). Inline text is an implicit .bob.md document. With --ask, the missing
    fields are asked on the terminal here (answers are literal data, like --set)."""
    source, base, origin = _read_target(args)
    if getattr(args, "ask", False):
        args.asked = ask_fields(args, source, base)
    return source, base, origin


def _read_target(args) -> tuple[str, str, str]:
    target = getattr(args, "target", None)
    if isinstance(target, list):  # several targets are split into parts by load_job
        if len(target) > 1:
            raise Fail(USAGE, "this command takes one document", problem="E102")
        args = argparse.Namespace(**{**vars(args), "target": target[0] if target else None})
    return _read_one(args)


def _read_one(args) -> tuple[str, str, str]:
    target = getattr(args, "target", None)
    if target == "-" or (target is None and stdin_has_data()):
        text = sys.stdin.read(STDIN_MAX + 1)
        if len(text) > STDIN_MAX:
            raise Fail(USAGE, f"stdin is larger than {STDIN_MAX // 1_000_000} MB: not a document", problem="E201")
        return text, os.getcwd(), "stdin"
    if target is None:
        raise Fail(
            USAGE, 'nothing to print: give a FILE, "TEXT" or pipe something (see: bobina print --help)', problem="E205"
        )
    if re.fullmatch(r"@[A-Za-z0-9][A-Za-z0-9._-]{0,63}", target):
        from .. import library

        try:
            source, base = library.get(target[1:])
        except library.LibraryError as e:
            raise Fail(USAGE, str(e), problem="E206") from None
        return source, base, target
    p = Path(target).expanduser()
    try:
        is_file = "\n" not in target and len(target) < 1024 and p.is_file()
    except OSError as e:
        if e.errno == errno.ENAMETOOLONG or not looks_like_path(target):
            is_file = False  # too long or not shaped like a file name: it is text
        else:
            raise Fail(USAGE, f"{target}: {e.strerror}", problem="E201") from None
    if is_file:
        return file_input(p, args)
    if re.fullmatch(r"https?://\S+", target):
        if not getattr(args, "allow_net", False):
            from ..sources import NET_HINT, NET_WHY

            raise Fail(USAGE, f"not fetched: {NET_WHY}.\n  {NET_HINT}", problem="E204")
        return image_document(target, args), os.getcwd(), "inline"
    if looks_like_path(target):
        hint = did_you_mean(target)
        raise Fail(USAGE, f"file not found: {target}" + (f"\n→ did you mean {hint}?" if hint else ""), problem="E201")
    return target.replace("\\n", "\n"), os.getcwd(), "inline"


PATH_SUFFIXES = (".md", ".bob", ".txt", ".csv", ".tsv", ".xlsx", ".json", ".pdf", ".svg", ".png", ".jpg", ".jpeg",
                 ".gif", ".bmp", ".webp", ".tif", ".tiff", ".bin")  # fmt: skip


def looks_like_path(target: str) -> bool:
    """A single token that names a file (an extension bobina reads, or a folder in it): a typo, not text."""
    if "\n" in target or " " in target or len(target) > 1024:
        return False
    return target.lower().endswith(PATH_SUFFIXES)  # 12/3.5, R$10/2.5kg, 07/11/2026. are text


def did_you_mean(target: str) -> str:
    import difflib

    p = Path(target).expanduser()
    try:
        names = [x.name for x in (p.parent if str(p.parent) else Path(".")).iterdir() if x.is_file()]
    except OSError:
        return ""
    best = difflib.get_close_matches(p.name, names, n=1, cutoff=0.75)
    return str(p.parent / best[0]) if best and str(p.parent) != "." else (best[0] if best else "")


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".pdf", ".svg"}


def page_range(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(1, total + 1))
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", spec.strip())
    if not m:
        raise Fail(USAGE, f"--page expects N or N-M, got '{spec}'", problem="E203")
    a, b = int(m.group(1)), int(m.group(2) or m.group(1))
    if not 1 <= a <= b <= total:
        raise Fail(USAGE, f"--page {spec}: the PDF has {total} page(s)", problem="E203")
    return list(range(a, b + 1))


SUPPORTED = "documents (.bob.md, .md, .txt), images (PNG, JPEG, GIF, BMP, WebP, TIFF, SVG) and PDF"


def file_input(p: Path, args) -> tuple[str, str, str]:
    """A file given as the target. Decided by content, not only by name: a document, an image/SVG/PDF, or a
    clear refusal - never a crash and never binary bytes printed as text."""
    from .. import imaging, sources

    base, origin = str(p.resolve().parent), str(p)
    try:
        with p.open("rb") as f:  # never more than 64 MB in memory, even to refuse a 1 GB file
            data = f.read(64 * 1024 * 1024)
    except OSError as e:
        raise Fail(USAGE, f"{p.name}: {e.strerror}", problem="E201") from None
    kind = sources.sniff(data)
    suffix = p.suffix.lower()
    if kind == "pdf" or (kind == "svg" and suffix == ".svg") or (kind == "raster" and suffix in IMAGE_SUFFIXES):
        try:  # open it now: a broken image is an error here, not an empty print
            imaging.open_image(str(p.resolve()), base, width=64)
        except sources.ImageError as e:
            raise Fail(USAGE, f"{p.name}: {e}" + (f"\n  {e.hint}" if e.hint else ""), problem="E203") from None
        return image_document(str(p.resolve()), args), base, origin
    refuse = f"{p.name}: bobina prints {SUPPORTED}.\n  export it as PDF or PNG and print that file"
    if data.lstrip()[:4] == b"%!PS":
        raise Fail(
            USAGE,
            f"{p.name}: PostScript/EPS is not supported (it would print as code).\n  export it as PDF",
            problem="E202",
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Fail(USAGE, refuse, problem="E202") from None
    if "\x00" in text:
        raise Fail(USAGE, refuse, problem="E202")
    return text, base, origin


def image_document(src: str, args) -> str:
    """A photo, SVG, PDF or https image given as the target becomes a one-image .bob.md document."""
    from .. import sources

    dest = f"<{src}>" if not src.startswith("https://") else src
    pages = [1]
    if src.lower().endswith(".pdf") and not src.startswith("https://"):
        try:
            pages = page_range(getattr(args, "page", None), sources.pdf_pages(Path(src).read_bytes()))
        except sources.ImageError as e:
            raise Fail(USAGE, f"{e}" + (f" ({e.hint})" if e.hint else ""), problem="E203") from None
    return "\n\n".join(f"![]({dest}){{page={n}}}" if n > 1 or len(pages) > 1 else f"![]({dest})" for n in pages) + "\n"


def _readline(tty, prompt: str) -> str | None:
    tty.write(prompt)
    tty.flush()
    line = tty.readline()
    return None if line == "" else line.rstrip("\r\n")


def _describe(name: str, spec: dict) -> str:
    bits = [name]
    if spec.get("required"):
        bits.append("(required)")
    if spec.get("help"):
        bits.append(f"- {spec['help']}")
    if spec.get("example"):
        bits.append(f"e.g. {spec['example']}")
    d = spec.get("default")
    if d not in (None, ""):
        bits.append("[automatic]" if "{{" in str(d) or "{%" in str(d) else f"[{d}]")
    return " ".join(bits)


def _ask_one(tty, name: str, spec: dict):
    """-> Tainted, list of rows, or None (empty: the default or nothing)."""
    if spec.get("type") == "table":
        cols = [str(c) for c in spec.get("columns") or []] or ["value"]
        tty.write(f"{_describe(name, spec)}\n  one row per line: {'; '.join(cols)}  (empty line to finish)\n")
        rows = []
        while True:
            line = _readline(tty, f"  {len(rows) + 1}> ")
            if not line or not line.strip():
                break
            cells = [c.strip() for c in line.split(";")]
            cells = (cells + [""] * len(cols))[: len(cols)]
            rows.append([Tainted(c) for c in cells])
        if rows or not spec.get("required"):
            return rows or None
        line = _readline(tty, "  required: add a row, or Enter to leave it empty\n  1> ")
        if line and line.strip():
            cells = ([c.strip() for c in line.split(";")] + [""] * len(cols))[: len(cols)]
            return [[Tainted(c) for c in cells]]
        return None
    value = _readline(tty, f"{_describe(name, spec)}: ")
    if value is None:
        return None
    if not value.strip() and spec.get("required") and spec.get("default") in (None, ""):
        value = _readline(tty, "  required: type a value, or Enter to leave it empty: ") or ""
    return Tainted(value) if value.strip() else None


def ask_fields(args, source: str, base: str) -> dict:
    from .. import engine
    from ..nudges import SecurityError

    try:
        todo = engine.fields_to_ask(source, base)
    except (ValueError, KeyError, SecurityError):
        return {}  # the build that follows reports the problem
    have = set(parse_sets(getattr(args, "set", None)))
    if getattr(args, "data", None):
        have |= set((read_data(args)[0] or [{}])[0])
    todo = [(k, s) for k, s in todo if k not in have]
    if not todo:
        err("--ask: every field already has a value")
        return {}
    tty = open_tty()
    if tty is None:
        raise Fail(USAGE, "--ask needs a terminal; pass the values with --set KEY=VALUE instead", problem="E107")
    out = {}
    with tty:
        tty.write("Fill in the fields (Enter = default / leave empty):\n")
        for name, spec in todo:
            v = _ask_one(tty, name, spec)
            if v is not None:
                out[name] = v
    return out


def parse_sets(pairs) -> dict:
    out = {}
    for s in pairs or []:
        if "=" not in s:
            raise Fail(USAGE, f"--set expects key=value, got '{s}'", problem="E304")
        k, v = s.split("=", 1)
        out[k.strip()] = Tainted(v)
    return out


def allow_set(args) -> set[str]:
    """--allow and --allow-all of this run (--last and --again have no parts: both mean the whole job)."""
    given = list(getattr(args, "allow", None) or []) + list(getattr(args, "allow_all", None) or [])
    return {c.strip() for a in given for c in a.split(",") if c.strip()}


def read_data(args) -> tuple[list[dict] | None, list[int] | None, list[tuple[str, str, str]]]:
    """--data [NAME=]FILE (CSV, TSV/TXT, XLSX, JSON) with --join NAME=FILE --on KEY (left joins), then --sheet,
    --rows, --where and --copies-from. -> (rows as literal values, copies per row, join notes)."""
    specs = getattr(args, "data", None) or []
    specs = [specs] if isinstance(specs, str) else specs
    joins, ons = getattr(args, "join", None) or [], getattr(args, "on", None) or []
    if len(specs) > 1:
        raise Fail(USAGE, "--data was given twice in one part: to print both lists use --then, to combine them "
                          "--join OTHER --on KEY", problem="E101")  # fmt: skip
    spec = specs[0] if specs else None
    if not spec:
        needs = [f for f, v in (("--join", joins), ("--where", getattr(args, "where", None)),
                                ("--rows", getattr(args, "rows", None)),
                                ("--copies-from", getattr(args, "copies_from", None)),
                                ("--sheet", getattr(args, "sheet", None))) if v]  # fmt: skip
        if needs:
            raise Fail(USAGE, f"{needs[0]} needs --data FILE (it works on the rows of a data file)", problem="E101")
        return None, None, []
    if len(joins) != len(ons):
        raise Fail(USAGE, "each --join needs its own --on KEY (written after it)", problem="E101")
    from .. import datasource

    notes: list[tuple[str, str, str]] = []
    try:
        main_name, path = datasource.named(spec)
        rows = datasource.read_rows(path, sheet=getattr(args, "sheet", None), notes=notes)
        others = []
        for jspec in joins:
            name, jpath = datasource.named(jspec)
            others.append([name, jpath, "=" in jspec and jspec.split("=", 1)[0] == name])
        others_rows = [datasource.read_rows(jpath, notes=notes) for _, jpath, _ in others]
        bare = set(datasource.columns(rows)).union(*(datasource.columns(o) for o in others_rows))
        bare |= {datasource.ident(c) for c in bare}  # the aliases too: Stock is usable as {{ stock }}
        sources = [[main_name, path, "=" in spec and spec.split("=", 1)[0] == main_name], *others]
        named = bool(joins) or "=" in spec  # without names there are no source groups, so nothing can clash
        used: set[str] = set()
        for src in sources if named else []:  # a source name must not hide a column: {{ product }} would be a group
            name, spath, explicit = src
            if name in bare or name in used:
                clash = "a column" if name in bare else "another source"
                if explicit:
                    raise datasource.DataError(
                        f"the source name '{name}' is also {clash}: choose another, e.g. --data x={spath}", "E304"
                    )
                new = name + "_src"
                while new in bare or new in used:
                    new += "_"
                notes.append(("M155", f"{spath} is called '{new}' ('{name}' is also {clash})",
                              f"write {{{{ {new}.column }}}}, or name it: {new}={spath}"))  # fmt: skip
                src[0] = name = new
            used.add(name)
        main_name = sources[0][0]
        if named:
            rows = [{**r, **{f"{main_name}.{c}": v for c, v in r.items()}} for r in rows]
        for (name, _p, _e), orows, on in zip(others, others_rows, ons, strict=True):
            rows, n = datasource.join(rows, main_name, orows, name, on)
            notes += n
        if getattr(args, "sheet", None) and not path.lower().endswith((".xlsx", ".xlsm")):
            notes.append(("M156", f"--sheet does nothing for {Path(path).name}: only .xlsx files have sheets", ""))
        if (getattr(args, "repeat", 1) or 1) > 1:
            notes.append(("M156", "--repeat does nothing with --data: there is one label per row",
                          "use --copies N for identical copies"))  # fmt: skip
        rows, originals = datasource.normalize_columns(rows, notes, {x[0] for x in sources} if named else set())
        # the file's row number, set after the joins (no source.prefixed copy of it) and before the filters
        rows = [{**r, datasource.LINE: n} for n, r in enumerate(rows, 1)]
        rows = datasource.select(rows, rows_spec=getattr(args, "rows", None), where=getattr(args, "where", None))
        if not rows:
            hint = ""
            ambiguous = {}  # used name (raw header or its alias) -> (raw header, a source that also has it)
            for n in notes:
                if n[0] == "M152" and len(n) > 4:
                    ambiguous[n[3]] = ambiguous[datasource.ident(n[3])] = (n[3], n[4])
            for w in getattr(args, "where", None) or []:
                m = datasource.WHERE_RE.fullmatch(w)
                if m and m.group(1) in ambiguous:
                    raw, other = ambiguous[m.group(1)]
                    hint = (f"\n→ '{m.group(1)}' is in more than one source and --where used {main_name}'s; for "
                            f"{other}'s write --where {other}.{raw}{m.group(2)}{m.group(3)}")  # fmt: skip
                    break
            raise datasource.DataError(f"{Path(path).name}: no row matches --rows/--where{hint}", "E302")
        col = getattr(args, "copies_from", None)
        per_row = datasource.copies_per_row(rows, col) if col else None
    except datasource.DataError as e:
        raise Fail(USAGE, str(e), problem=e.code) from None
    names = {src[0] for src in sources} if named else set()
    out = []
    for r in rows:
        d = datasource.nest({k: v if datasource.internal(k) else Tainted(v) for k, v in r.items() if k}, names)
        if "row" not in d:  # {{ row['Product Name'] }}: the columns exactly as the file names them
            d["row"] = {k: Tainted(v) for k, v in r.items() if k in originals}
        out.append(d)
    return out, per_row, notes


def names_used(args, source: str, base_dir: str) -> set[str] | None:
    """Bare column names the job reads: {{ name }} in the document, --where, --copies-from and -o {name}."""
    from .. import export

    names = engine.template_names(source, base_dir)
    if names is None:
        return None
    for w in getattr(args, "where", None) or []:
        names.add(datasource.where_column(w))
    if getattr(args, "copies_from", None):
        names.add(args.copies_from)
    names |= {m.group(1) for m in export.PLACEHOLDER.finditer(getattr(args, "output", None) or "")}
    return names


TEAR_MARGIN_MM = 6.0  # paper past the tear bar after the last line: rather a little extra paper than a label torn
# through its text or one the user must pull out (08/11: with 2 mm the last line stopped at the tear bar)


def printer_overrides(pr: dict | None) -> dict:
    """Measured per-printer values stored in config.toml (e.g. tear_mm from bobina calibrate tear, and
    tear_margin_mm for whoever wants less paper after each label)."""
    out = {}
    if pr and pr.get("tear_mm"):
        out["margins.tear_mm"] = float(pr["tear_mm"])  # dots with the profile's dpi (engine.apply_overrides)
        out["margins.tear_margin_mm"] = float(pr.get("tear_margin_mm", TEAR_MARGIN_MM))
    for key, dotted in (("blank_rows_after_raster", "escpos.blank_rows_after_raster"),
                        ("idle_before_tail", "transport.idle_before_tail")):  # fmt: skip
        if key in (pr or {}):  # measured by bobina calibrate: off when the printer does not need it (faster)
            out[dotted] = bool(pr[key])
    return out


MARKS = ("none", "cut", "tear", "both")


def marks_setting(args, cfg: dict) -> str:
    """--marks, else marks in config.toml, else none (decided 08/11: no mark on paper unless asked)."""
    value = getattr(args, "marks", None) or cfg.get("marks") or "none"
    if value not in MARKS:
        raise Fail(USAGE, f"marks = {value!r} in config.toml: use {', '.join(MARKS)}", problem="E101")
    return value


def build(args, source, base_dir, counters=None, machine=None):
    """machine: the job's locales.Machine (one for all the parts of a job); None: a new one, so each rebuild of
    bobina edit reads config.toml again."""
    if counters is not None or not getattr(args, "reserve_counters", False):
        return _build(args, source, base_dir, counters, machine)
    store = counter_store(args)  # a print: numbers reserved now, given back if the build fails
    try:
        return _build(args, source, base_dir, store, machine)
    except BaseException:
        store.release()
        raise


def sandbox_dirs(cfg: dict, base_dir: str, doc_folder: bool = True) -> tuple[str, ...]:
    """The folders a sandboxed document's images may come from: its own folder (not for stdin or inline text: they
    have none) and image_dirs in config.toml."""
    extra = cfg.get("image_dirs") or []
    if isinstance(extra, str):
        extra = [extra]
    return tuple(([base_dir] if doc_folder else []) + [str(d) for d in extra if str(d).strip()])


def _build(args, source, base_dir, counters=None, machine=None):
    from .. import locales

    cfg = config.load()
    _, pr = config.printer(cfg, args.printer)
    copies, repeat = getattr(args, "copies", 1), getattr(args, "repeat", 1)
    if (copies is not None and copies < 1) or (repeat is not None and repeat < 1):
        raise Fail(USAGE, "--copies and --repeat must be 1 or more", problem="E304")
    data_rows, per_row, notes = read_data(args)
    try:
        b = engine.build_batch(
            source,
            rows_data=data_rows,
            repeat=getattr(args, "repeat", 1) or 1,
            overrides={**printer_overrides(pr), "marks": marks_setting(args, cfg)},
            copies=getattr(args, "copies", 1) or 1,
            row_copies=per_row,
            base_dir=base_dir,
            profile_name=args.profile,
            config_profile=(pr or {}).get("profile") or cfg.get("profile"),
            fields={**parse_sets(getattr(args, "set", None)), **getattr(args, "asked", {})},
            plain=getattr(args, "plain", False),
            allow=allow_set(args),
            net=getattr(args, "allow_net", False),
            image_dirs=sandbox_dirs(cfg, base_dir, getattr(args, "doc_folder", True))
            if getattr(args, "sandbox", False)
            else None,
            locale=machine or locales.Machine(),  # the locale of a document without locale:
            **({"counters": counters} if counters is not None else {}),
        )
    except KeyError as e:
        raise Fail(USAGE, str(e).strip("'\""), problem="E207") from None
    except ValueError as e:  # typed errors carry their code (engine.JobError, templating.CounterConflict)
        code = getattr(e, "code", "E501")
        raise Fail(DOC if code == "E501" else USAGE, str(e), problem=code) from None
    sets = parse_sets(getattr(args, "set", None))
    if data_rows and sets:
        clash = sorted(set(sets) & set(data_rows[0]))
        if clash:
            notes.append(("M157", f"--set {', '.join(clash)} replaces the data column of the same name in every row",
                          ""))  # fmt: skip
    used = None
    for code, msg, hint, *extra in notes:  # join notes (unmatched keys, duplicates, ambiguous columns)
        if code == "M152" and extra:  # ambiguous column: only worth a warning when the bare name is used
            used = used if used is not None else names_used(args, source, base_dir)
            if used is not None and extra[0] not in used and datasource.ident(extra[0]) not in used:
                continue  # (the job may use the header itself or its alias: Categoria -> categoria)
        b.first.nudges.add(code, msg, None, hint)
    b.source_text = source
    return b


JOB_FLAGS = (
    "yes", "dry_run", "compact_all", "quiet", "strict", "json", "no_color", "verbose", "debug", "force", "pages",
)  # fmt: skip
JOB_VALUES = ("printer", "profile", "output", "editor", "marks")
PLAIN_WORD = re.compile(r"[^\s/\\.@:]+")


def load_job(args):
    """See _load_job. A print reserves its seq numbers while it is built (args.reserve_counters); if building
    fails, they are given back."""
    store = counter_store(args)
    try:
        return _load_job(args, store)
    except BaseException:
        store.release()
        raise


def counter_store(args):
    from ..nudges import Nudges
    from ..templating import CounterStore

    return CounterStore(None, Nudges(), reserve=getattr(args, "reserve_counters", False))


def _load_job(args, store):
    """The targets of every part (bobina print A B --then C …) built as one job ->
    (result, source, base_dir, origin). Part options apply to the files of that part; job options
    (--compact-all, --yes, --dry-run, --printer, --profile, -o …) may be written in any part.
    Joins: inside a part its --compact decides; between parts a ✂ line only if both are compact."""
    parts_args = [args, *getattr(args, "chain", [])]
    for k in JOB_VALUES:  # job options take one value for the whole job
        vals = list(dict.fromkeys(getattr(a, k, None) for a in parts_args if getattr(a, k, None)))
        if len(vals) > 1:
            flag = "-o" if k == "output" else f"--{k}"
            raise Fail(
                USAGE,
                f"{flag} applies to the whole job and was given twice: {' and '.join(map(str, vals))}",
                problem="E103",
            )
    for a in parts_args[1:]:
        for k in JOB_FLAGS:
            if getattr(a, k, False):
                setattr(args, k, True)
        for k in JOB_VALUES:
            if getattr(a, k, None) and not getattr(args, k, None):
                setattr(args, k, getattr(a, k))
    for a in parts_args[1:]:
        for k in JOB_FLAGS + JOB_VALUES:
            setattr(a, k, getattr(args, k, None))
    set_all = [v for a in parts_args for v in (getattr(a, "set_all", None) or [])]
    allow_all = [v for a in parts_args for v in (getattr(a, "allow_all", None) or [])]
    for a in parts_args:  # job-wide defaults; the part's own --set comes later and wins
        a.set = set_all + list(getattr(a, "set", None) or [])
        a.allow = allow_all + list(getattr(a, "allow", None) or [])
    if len(parts_args) > 1 and getattr(args, "profile", None):
        from .. import profile as profiles

        try:
            profiles.load(args.profile)
        except KeyError as e:
            raise Fail(USAGE, str(e).strip("'\""), problem="E207") from None
    compact_all = bool(getattr(args, "compact_all", False))
    if compact_all and all(getattr(a, "compact", None) is False for a in parts_args):
        err("note: --compact-all has no effect: every part says --no-compact")
    items = []  # (part number, namespace with one target)
    for g, a in enumerate(parts_args):
        t0 = getattr(a, "target", None)
        targets = [t for t in (t0 if isinstance(t0, list) else [t0]) if t is not None]
        if not targets and len(parts_args) > 1 and (g > 0 or not stdin_has_data()):
            where = "after a --then" if g else "before the first --then"
            raise Fail(USAGE, f"part {g + 1} has no document ({where}): every part needs a file, @name or text",
                       problem="E104")  # fmt: skip
        targets = targets or [None]
        if len(targets) > 1:
            words = [t for t in targets if PLAIN_WORD.fullmatch(t) and not Path(t).exists()]
            if words:
                raise Fail(
                    USAGE,
                    f"'{words[0]}' is not a file. Several targets print several documents; "
                    f"to print text with spaces, use quotes: bobina print {quote_loose(targets)}",
                    problem="E101",
                )
        for t in targets:
            items.append((g, argparse.Namespace(**{**vars(a), "target": t})))
    if len(items) > 1 and sum(1 for _, a in items if a.target in (None, "-")) > 1:
        raise Fail(USAGE, "only one part can read stdin (-): give the others as files or text", problem="E106")
    if len(items) > 1 and items[0][1].target is None and not stdin_has_data():
        raise Fail(USAGE, "--then needs a document before it too: bobina print FIRST --then SECOND", problem="E104")
    built, first_src = [], None
    many = len(items) > 1
    from .. import locales

    machine = locales.Machine()  # one per job: its parts and their rows say its locale note once
    failed: list[tuple[Nudge, int]] = []  # every part is built; all problems are reported together
    for g, a in items:
        label = f"part {g + 1} ({_short(a.target)})" if many else ""
        try:
            s, b, origin = _read_one(a)
            a.doc_folder = origin not in ("stdin", "inline")  # --sandbox: stdin and inline text have no folder
            if getattr(a, "ask", False):
                cache = args.__dict__.setdefault("_asked", {})  # an edit-and-rebuild keeps the answers
                if (g, a.target) not in cache:
                    if label:
                        err(f"— {label}")
                    cache[(g, a.target)] = ask_fields(a, s, b)
                a.asked = cache[(g, a.target)]
            res = build(a, s, b, counters=store, machine=machine)
        except Fail as e:
            if not many:
                raise
            n = e.problems()[0]  # message and hint split, the same shape as a single-part error
            n.source, n.part, n.file = label, g + 1, _short(a.target)
            failed.append((n, e.code))
            continue
        except SecurityError as e:
            if not many:
                raise
            e.nudge.source, e.nudge.part, e.nudge.file = label, g + 1, _short(a.target)
            failed.append((e.nudge, SECURITY))
            continue
        for r in res.results:
            for n in r.nudges:
                if label and not n.source:
                    n.source, n.part, n.file = label, g + 1, _short(a.target)
        store = res.first.rendered.counters if res.first.rendered else store  # counters continue
        compact = getattr(a, "compact", None)
        compact = compact if compact is not None else compact_all
        built.append((res, g, compact, s, b, origin))
        first_src = first_src or (s, b, origin)
    if failed:
        warnings = [n for r, *_ in built for n in r.visible_nudges()]
        shown = [n for n, _ in failed] + warnings
        codes = {c for _, c in failed}
        code = SECURITY if SECURITY in codes else DOC if DOC in codes else USAGE
        raise Fail(code, "\n".join(nudge_block(shown, stopped())), problem="MULTI", items=shown)
    metas, n = [], 0
    for res, g, _c, _s, _b, origin in built:  # per label: where it came from (export names, reports)
        stem = file_stem(origin)
        for i, r in enumerate(res.results * res.copies, 1):
            n += 1
            metas.append({"n": n, "i": i, "part": g + 1, "file": stem, "fields": getattr(r, "fields", {})})
    if len(built) == 1:
        res, _, compact, s, b, origin = built[0]
        res.compact = compact
        res.label_meta = metas
        return res, s, b, origin
    try:
        job = engine.join([(r, g, c) for r, g, c, *_ in built])
    except ValueError as e:
        raise Fail(DOC, f"error: {e}", problem=getattr(e, "code", "E305")) from None
    job.source_text = first_src[0]
    job.label_meta = metas
    return job, first_src[0], first_src[1], "(chain)"


def file_stem(origin: str) -> str:
    """{file} in export names: jar.v1.bob.md -> jar.v1 (only the document suffix goes), foto.jpg -> foto."""
    if origin == "stdin":
        return "stdin"
    if origin == "inline":
        return "text"
    name = Path(origin.lstrip("@")).name
    for ext in (".bob.md", ".md"):
        if name.endswith(ext) and len(name) > len(ext):
            return name[: -len(ext)]
    return Path(name).stem or name


def quote_loose(targets: list[str]) -> str:
    """The targets with each run of loose words in quotes: a.bob.md hello world. -> a.bob.md "hello world.".
    A word is loose unless it is an existing file, @name, a URL or looks like a file name; punctuation (10:30,
    R$5.00, world.) stays inside the text."""
    out, run = [], []
    for t in targets:
        if not _is_named_target(t):
            run.append(t)
            continue
        if run:
            out.append('"' + " ".join(run) + '"')
            run = []
        out.append(t)
    if run:
        out.append('"' + " ".join(run) + '"')
    return " ".join(out)


def _is_named_target(t: str) -> bool:
    return (
        t == "-"
        or t.startswith("@")
        or t.startswith(("https://", "http://"))
        or Path(t).exists()
        or (looks_like_path(t) and not t.endswith("."))
    )


def _short(target) -> str:
    t = "stdin" if target in (None, "-") else str(target).replace("\n", " ")
    return t if len(t) <= 28 else t[:25] + "…"


def nudge_block(shown, printed: str) -> list[str]:
    """Header + one problem per entry, in the single format (nudges.problem_line)."""
    if not shown:
        return []
    count = {s: sum(1 for n in shown if n.severity == s) for s in ("error", "warning", "note")}
    return [problems_header(count["error"], count["warning"], count["note"], printed)] + [n.format() for n in shown]


def input_paths(args) -> set[Path]:
    """Every file this job reads (documents, images, PDFs, data): an output must never replace one of them."""
    out: set[Path] = set()
    for a in [args, *getattr(args, "chain", [])]:
        targets = a.target if isinstance(getattr(a, "target", None), list) else [getattr(a, "target", None)]
        data = getattr(a, "data", None) or []
        sources = [*([data] if isinstance(data, str) else data), *(getattr(a, "join", None) or [])]
        specs = [*targets, *(datasource_path(x) for x in sources)]
        for t in specs:
            if not t or t == "-" or "\n" in t or len(t) > 1024:
                continue
            path = t
            try:
                p = Path(path).expanduser()
                if p.is_file():
                    out.add(p.resolve())
            except OSError:
                continue
    return out


def datasource_path(spec: str) -> str:
    from .. import datasource

    return datasource.named(spec)[1]


def guard_outputs(paths, args, explicit: bool = False, extra_inputs=()) -> None:
    """Outputs never replace an input of the job; an explicit -o FILE that exists needs --force (decided
    07/11: the same rule as -o with {placeholders}). extra_inputs: files the args do not name (--again's document)."""
    inputs = input_paths(args) | {Path(p).expanduser().resolve() for p in extra_inputs}
    if explicit and not getattr(args, "force", False):
        exists = [p for p in paths if Path(p).expanduser().exists()]
        if exists:
            raise Fail(USAGE, f"{exists[0]} exists: use --force to replace it", problem="E208")
    for p in paths:
        if Path(p).expanduser().resolve() in inputs:
            raise Fail(
                USAGE, f"{p} is an input of this job: saving would destroy it; choose another -o", problem="E208"
            )


def export_labels(res, pattern: str, kind: str, args) -> list[Path]:
    """-o with {placeholders}: one file per label. kind: 'bytes' (what the printer gets) or 'image'."""
    import io

    from .. import export, fileio, preview

    try:
        paths = export.names(pattern, res.label_meta)
    except export.ExportError as e:
        raise Fail(USAGE, str(e), problem="E208") from None
    if kind == "image":
        bad = sorted({p.suffix.lower() or p.name for p in paths} - set(IMAGE_FORMATS))
        if bad:
            raise Fail(USAGE, f"cannot save images as {', '.join(bad)}: use {', '.join(IMAGE_FORMATS)}", problem="E208")
    guard_outputs(paths, args)
    exists = [p for p in paths if p.exists()]
    if exists and not getattr(args, "force", False):
        raise Fail(
            USAGE, f"{exists[0]} exists ({plural(len(exists), 'file')} would be replaced): use --force", problem="E208"
        )
    for d in sorted({p.parent for p in paths}):  # check every folder before writing anything
        blocker = next((x for x in [d, *d.parents] if x.exists() and not x.is_dir()), None)
        if blocker is not None:
            raise Fail(USAGE, f"cannot create the folder {d}: {blocker} is a file (nothing written)", problem="E208")
    done, encoded = 0, {}
    try:
        for p, label in zip(paths, res.labels, strict=True):
            p.parent.mkdir(parents=True, exist_ok=True)
            if kind == "bytes":
                fileio.write_output(p, label.data)  # a file is either the whole label or absent
            else:  # drawn here and dropped: no image kept per label; copies of a label reuse its encoded file
                key = (id(label), _image_format(p))
                if key not in encoded or res.copies == 1:
                    buf = io.BytesIO()
                    save_image(preview.render(label.rows, label.profile, label.emulator), buf, _image_format(p))
                    if res.copies == 1:  # no copies: nothing to reuse, keep nothing
                        encoded.clear()
                    encoded[key] = buf.getvalue()
                fileio.write_output(p, encoded[key])
            done += 1
    except OSError as e:
        raise Fail(USAGE, f"{e.filename or p}: {e.strerror} ({done} of {len(paths)} files written)",
                   problem="E208") from None  # fmt: skip
    return paths


ONE_BIT = {"PNG", "TIFF", "BMP", "GIF"}  # formats that keep a 1-bit image as is (8x smaller in memory than L)


def save_image(im, dest, fmt: str | None = None) -> None:
    """Saves a preview image. Thermal dots are black or white: 1-bit when the format allows it."""
    fmt = fmt or _image_format(Path(dest))
    (im if fmt in ONE_BIT else im.convert("L")).save(dest, format=fmt)


def _image_format(p: Path) -> str:
    return {".jpg": "JPEG", ".jpeg": "JPEG", ".tif": "TIFF", ".tiff": "TIFF"}.get(
        p.suffix.lower(), p.suffix[1:].upper()
    )


IMAGE_FORMATS = (".png", ".jpg", ".jpeg", ".pdf", ".webp", ".bmp", ".gif", ".tif", ".tiff")


def report_nudges(res, args) -> int:
    shown = res.visible_nudges()
    strict = strict_hits(shown, args)  # one pass over a 1000-label batch, not two
    left_out = [n for n in shown if n.code in LEFT_OUT_CODES]
    if strict and args.quiet:  # -q hides nudges, but never the reason of a stop
        shown = [n for n in shown if n.severity in ("warning", "error")]
    elif args.quiet:  # … nor the reason of exit 9
        shown = left_out
    if (not args.quiet or strict or left_out) and not args.json:
        cmd = getattr(args, "command", "print")
        if strict:
            outcome = f"{stopped() or 'stopped'} (--strict)"
        elif cmd not in ("print", "edit"):
            outcome = ""  # check, view, preview: the warnings are the answer, nothing was meant to print
        elif getattr(args, "dry_run", False):
            outcome = "nothing printed (dry run)"
        elif getattr(args, "output", None):
            outcome = "saved to the file anyway"
        else:
            outcome = "printing anyway (--yes)" if getattr(args, "yes", False) else ""
        for line in render_problems(shown, outcome):
            err(line)
    if strict:
        return STRICT
    return LEFT_OUT if left_out else OK  # job_code, from the list already in hand


def summary(res) -> list[str]:
    st = res.stats()
    cm = st["length_mm"] / 10
    size = f"{st['bytes'] / 1024:.1f} KB" if st["bytes"] >= 1024 else f"{st['bytes']} bytes"
    lines = [f" ~{cm:.1f} cm of paper · {plural(st['native_rows'], 'native row')}, {st['raster_rows']} raster · {size}"]
    n = len(getattr(res, "labels", [])) or 1
    if n > 1:
        cuts = getattr(res, "joins", []).count("cut")
        tears = n - 1 - cuts + 1  # every tear join, and the end of the job always goes to the tear bar
        shown = "" if n <= res.SHOW else f"; the preview above shows the first {res.SHOW} (the PNG preview has all)"
        lines.append(
            f" {n} labels in one job: {plural(cuts, 'cut line')} ✂, {plural(tears, 'feed')} to the tear bar ⟶"
            f" (the last at the end){shown}"
        )
    first = getattr(res, "first", res)
    reserving = bool(first.rendered and first.rendered.counters.reserve)
    note = "reserved for this print; given back if it is not printed" if reserving else "nothing is taken by this view"
    for name, vals in st["counters"].items():
        rng = vals[0] if len(vals) == 1 else f"{vals[0]} to {vals[-1]} ({len(vals)})"
        lines.append(f" seq.{name}: will use {rng} ({note})")
    marks = res.profile.get("marks", "none")
    where = []
    if marks in ("cut", "both") and "cut" in getattr(res, "joins", []):
        where.append("the cut lines ✂")
    if marks in ("tear", "both"):
        where.append("the tear bar ⟶")
    if where:
        lines.append(f" marks on paper: a fine dashed line at {' and '.join(where)} (--marks {marks})")
    elif marks == "cut":
        lines.append(" marks on paper: none (--marks cut, and this job has no cut: --compact glues labels)")
    if not res.profile.get("preview.calibrated", False):
        lines.append(" preview: exact dots; ink spread not calibrated yet")
    return lines


def printer_name(args) -> str | None:
    name, pr = config.printer(config.load(), getattr(args, "printer", None))
    return name if pr else None


def counts_paper(pr: dict) -> bool:
    """A roll is counted for every printer but a plain file (--path out.bin); a device path (/dev/usb/lp0,
    /dev/rfcomm0) is a real printer with a real roll."""
    return pr.get("transport") != "file" or str(pr.get("path", "")).startswith("/dev/")


def where(name: str) -> str:
    """The printer as a print message names it: a file printer also says which file got the bytes."""
    _, pr = config.printer(config.load(), name)
    if pr and not counts_paper(pr):  # a plain file: say where it is, whatever folder the path was added from
        return f"{name} (file {Path(str(pr.get('path'))).expanduser().resolve()})"
    return name


def paper_printer(args) -> str | None:
    """The printer whose roll is counted (see counts_paper)."""
    name, pr = config.printer(config.load(), getattr(args, "printer", None))
    return name if pr and counts_paper(pr) else None


def screen(res, title: str, color: bool, args=None) -> str:
    from .. import paper

    body = view.render(res.rows, res.profile, title, color)
    out = [body] + summary(res)
    name = paper_printer(args) if args is not None else None
    if name:
        out.append(paper.check(name, res.length_mm, res.nudges if hasattr(res, "nudges") else res.first.nudges))
    shown = res.visible_nudges()
    if shown and _FMT[0] == "pretty":
        out += [""] + nudge_block(shown, "check them before printing")
    elif shown:  # json/jsonl/plain: machine output goes to stderr, the screen stays for people
        for line in render_problems(shown, "not printed yet"):
            err(line)
    return "\n".join(out)


def noninteractive() -> bool:
    """BOBINA_NONINTERACTIVE=1 (servers, bots, cron): never ask on the terminal. A process started by a server can
    still have a controlling terminal, and a question there would wait forever; with it, --ask and the
    confirmation screen stop with E107 at once."""
    return os.environ.get("BOBINA_NONINTERACTIVE", "").strip().lower() not in ("", "0", "false", "no")


def open_tty():
    """The user's terminal, even when stdin/stdout are pipes. A tty is not seekable, so it cannot be opened
    with the buffered "r+" mode (that always failed on real terminals): raw read/write + a text wrapper."""
    if os.name == "nt" or noninteractive():
        return None
    try:
        raw = open("/dev/tty", "rb+", buffering=0)  # noqa: SIM115 - returned to the caller, closed by its with
    except OSError:
        return None
    import io

    return io.TextIOWrapper(raw, encoding="utf-8", errors="replace", write_through=True)


def ask(tty, prompt: str) -> str:
    tty.write(prompt)
    tty.flush()
    line = tty.readline()
    return line.strip().lower() if line else "q"


def confirm_loop(args, res, title, rebuild=None, source_path=None, draft=False) -> tuple[bool, object]:
    """Shows the confirmation screen. Returns (print?, result) — result may be rebuilt after edits."""
    color = view.use_color(sys.stderr) and not args.no_color
    if args.yes:
        return True, res
    tty = open_tty()
    if tty is None:
        err(screen(res, title, False, args))
        raise Fail(
            CONFIRM,
            "confirmation required: no terminal attached. Re-run with --yes to print without it.",
            problem="E107",
        )
    with tty:
        while True:
            tty.write(screen(res, title, color, args) + "\n\n")
            opts = " [p] print   " + ("[e] edit again   " if rebuild else "") + "[s] save as…   [q] quit\n> "
            a = ask(tty, opts)
            if a in ("p", "print"):
                if strict_hits(res, args):  # a job rebuilt after [e] can bring new warnings
                    tty.write(" --strict: these warnings stop the print; [e] edit again or [q] quit\n")
                    continue
                return True, res
            if a == "":
                tty.write(" (Enter alone never prints)\n")
                continue
            if a in ("q", "quit", "n", "no"):
                return False, res
            if a in ("e", "edit") and rebuild:
                res.release()  # its seq numbers go back; the rebuilt job reserves its own
                res = rebuild()
                continue
            if a in ("s", "save"):
                dest = ask(tty, " save as (path): ")
                if dest and dest != "q":
                    Path(dest).expanduser().write_text(res.source_text)
                    tty.write(f" saved {dest}\n")
                continue


STATUS_LIST = [
    ("online", "printer answered and is online"),
    ("offline", "DLE EOT 1 bit 3: printer offline (cover open, paper out or error)"),
    ("cover_open", "DLE EOT 2 bit 2: the lid is open"),
    ("feed_button", "DLE EOT 2 bit 3: paper being fed with the button"),
    ("paper_out", "DLE EOT 2 bit 5 / DLE EOT 4 bits 5-6: no paper"),
    ("paper_near_end", "DLE EOT 4 bits 2-3: paper running out"),
    ("error", "DLE EOT 2 bit 6 / DLE EOT 3: printer error (head too hot, etc.)"),
    ("language", "command language cannot be read back: ESC/POS assumed when DLE EOT answers"),
]


def decode_status(r) -> dict:
    if all(x is None for x in r):
        return {"online": False, "answered": False, "language": "unknown (no DLE EOT answer: TSPL/CPCL mode?)"}
    b = [x[0] if x else 0 for x in r]
    return {
        "answered": True,
        "online": not b[0] & 0x08,
        "cover_open": bool(b[1] & 0x04),
        "feed_button": bool(b[1] & 0x08),
        "paper_out": bool(b[1] & 0x20) or bool(b[3] & 0x60),
        "paper_near_end": bool(b[3] & 0x0C),
        "error": bool(b[1] & 0x40) or bool(b[2] & 0x6C),
        "language": "ESC/POS",
        "raw": " ".join(f"{x:02x}" for x in b),
    }


def printer_status(pr, quiet=False, connect_timeout: float = 15) -> dict | None:
    try:
        with transport.printer_lock(pr, log=lambda *a, **k: None, timeout=5):  # never while a job prints
            r = transport.query(pr["address"], int(pr.get("channel", 1)), transport.STATUS_QUERIES,
                                connect_timeout=connect_timeout)  # fmt: skip
    except transport.PrinterBusy as e:
        if quiet:
            return None
        raise Fail(UNREACHABLE, f"{e}: ask again when it finishes", problem="E405") from e
    except (OSError, transport.PrinterUnreachable) as e:
        if quiet:
            return None
        raise Fail(UNREACHABLE, f"printer unreachable: {e}", problem="E402") from e
    return decode_status(r)


PAPER_OUT_HINT = (
    "this printer has no cover sensor: an open cover reads as 'paper out'. Close the cover with the end of the "
    "paper sticking out over the tear bar (otherwise it keeps beeping). New roll? bobina paper new LENGTH"
)


def status_problem(st: dict, prof) -> tuple[list[str], str]:
    """(what is wrong, what to do) for a decoded status; ([], "") when it is ready. One wording for the check before
    a print, the reason after a failed one, and bobina status."""
    bad = [k for k in ("cover_open", "paper_out", "error") if st.get(k)]
    hint = "new roll? bobina paper new LENGTH" if st.get("paper_out") else ""
    if st.get("paper_out") and prof.get("status.cover_sensor", True) is False:
        bad = ["no paper or cover open"] + [b for b in bad if b != "paper_out"]
        hint = PAPER_OUT_HINT
    if st.get("cover_open") and not hint:
        hint = "close the cover"
    return bad, hint


def _why_it_stopped(pr: dict, prof) -> str:
    """After a send that failed half way, ask the printer why (08/11: the roll ran out in the middle of a job and
    all bobina said was a timeout). Quick (one 5 s connect, a busy link recovered) and never in the way: empty when
    it cannot tell, whatever goes wrong while asking."""
    if pr.get("transport", "bluetooth") != "bluetooth":
        return ""
    try:
        err("asking the printer why…")
        st = printer_status(pr, quiet=True, connect_timeout=5) or {}
        bad, hint = status_problem(st, prof)
    except Exception:  # noqa: BLE001 - the send error must reach the user as it is
        return ""
    return f"\n→ the printer reports {', '.join(bad).replace('_', ' ')}: {hint}" if bad else ""


def do_send(args, res_data: bytes, prof, check_status=True, length_mm: float = 0.0, progress=None):
    cfg = config.load()
    name, pr = config.printer(cfg, args.printer)
    if pr is None:
        raise Fail(
            UNREACHABLE,
            "no printer configured: bobina printer add NAME ADDRESS  (see: bobina printer --help)",
            problem="E401",
        )

    def precheck(replies):
        bad, hint = status_problem(decode_status(replies), prof)
        hint = f"  → {hint}" if hint else ""
        if bad:
            raise Fail(
                PRINTER_ERR,
                "printer not ready: " + ", ".join(bad) + "  (see: bobina status --list)" + hint,
                problem="E403",
            )

    try:
        transport.send(
            res_data, pr, prof, log=print, precheck=precheck if check_status else None, length_mm=length_mm,
            progress=progress,
        )  # fmt: skip
    except transport.PrinterBusy as e:
        hint = "nothing was sent; to wait longer, add busy_timeout = SECONDS to the printer in config.toml"
        raise Fail(UNREACHABLE, f"{e}\n→ {hint}", problem="E405") from e
    except transport.PrinterUnreachable as e:
        raise Fail(UNREACHABLE, str(e), problem="E402") from e
    except transport.SendFailed as e:  # part of the job may be on paper
        if length_mm and e.sent and counts_paper(pr):
            _count_paper(name, length_mm * min(1.0, e.sent / max(1, len(res_data))))
        f = Fail(UNREACHABLE, f"{e}{_why_it_stopped(pr, prof)}\n→ part of the job may have printed: check the paper"
                 " before printing again", problem="E402")  # fmt: skip
        f.partial = e.sent > 0
        raise f from e
    except (OSError, subprocess.SubprocessError) as e:
        raise Fail(UNREACHABLE, f"sending failed: {e}", problem="E402") from e
    if length_mm and counts_paper(pr):
        _count_paper(name, length_mm)
    return name


def _count_paper(name: str, mm: float) -> None:
    """After the paper moved: a broken paper file must not turn a finished print into an error (the user would
    print again, and the seq numbers of a printed job would be given back)."""
    from .. import fileio, paper

    try:
        paper.add(name, mm)
    except (fileio.StateError, fileio.LockTimeout, OSError) as e:
        err(f"note: paper not counted ({e}); correct it later with: bobina paper used LENGTH")
