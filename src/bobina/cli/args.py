"""Argument parsing, help topics and the entry point."""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys

from .. import __version__
from ..fileio import LockTimeout, StateError
from ..nudges import CATALOG, SecurityError
from . import common
from .common import ALIASES, GLOBAL_WITH_VALUE, LEFT_OUT, MARKS, OK, SECURITY, USAGE, Fail, err, print_json
from .device import MODES, cmd_calibrate, cmd_mode, cmd_paper, cmd_printer, cmd_send, cmd_status
from .documents import cmd_check, cmd_edit, cmd_preview, cmd_print, cmd_view
from .history import cmd_history
from .library import cmd_fonts, cmd_library, cmd_profile, cmd_seq, cmd_template
from .settings import cmd_config


def cmd_mcp(args):
    from ..mcp_server import serve  # the MCP SDK is an extra: imported only by this command

    return serve(args)


HELP_FORMAT = """\
.bob.md — Markdown for thermal roll printers (full spec: docs/FORMAT.md)

TEXT
  # Title / ## / ###        native 2x2 / 1x2 / bold (fonts.title sets a raster font)
  **bold** *italic* ~~strike~~ `mono`   [span]{.bold .invert .underline font=hand size=32px}
  {.center .right .justify .invert .bold .flip rotate=90 size=small|normal|large|title|huge|2x|1x2|20px|3mm}
  a line with only {.compact} applies to the block above (e.g. a table)
  - item · 1. item · - [ ] todo · - [x] done (struck; tasks: {done: check|plain})
  | table |  (stretches to the paper; {.compact} keeps it narrow)    > quote
  ---  or  --- {.dashed|.dotted|.double|.wavy|.cut thickness=2}
  ![alt](photo.jpg){width=50% dither=atkinson gamma=1.5 .left}     <!-- comments are ignored -->

OBJECTS (fenced blocks)
  ```qr {module=4 ecc=M size=full|half|30mm caption="Menu"}
  ```barcode {type=code128|ean13|… width=full orientation=auto|vertical}
  ```datamatrix {module=4}      ```pdf417 {module=2 columns=4}
  ```pay {scheme=pix|upi|epc|… to=… amount=10.00}  (bobina help pay)      ```text {rotate=90}
  ```raw   (hex bytes, bypasses every check)

FRONT MATTER
  locale: pt-BR · timezone: America/Sao_Paulo · profile: mtp-ii-58 · align · size
  fonts: {body: native|Atkinson Hyperlegible, title: …, code: IBM Plex Mono, ALIAS: FAMILY}
  image: {dither: floyd-steinberg|atkinson|bayer|threshold, gamma: 1.8}
  counters: {ticket: {start: 1, step: 1, stop: 99, wrap: true, format: "A-{:03}", style: letters}}
  template: receipt (+ its fields) · allow: [F301] · labels: {pt: {total: Total}}

VARIABLES (Jinja, sandboxed; comments are <# … #>)
  {{ now | date("full") }}  {{ now | date("dd/MM HH:mm") }}  {{ now | add(days=7) | date("short") }}
  {{ 1234.5 | currency("BRL") }}  {{ 0.25 | percent }}  {{ seq.ticket }}  {% for n in seq.ticket.take(10) %}
  Values from --set/--data are printed literally; {{ value | markdown }} opts in (raw blocks removed).
"""


HELP_DATA = """\
bobina help data — one label per row (guide: docs/guides/batch-printing.md)

  bobina print label.bob.md --data rows.csv              one label per row; {{ column }} in the document
  bobina print label.bob.md --data stock.xlsx --sheet Estoque   a sheet other than the first
  … --where shelf=A                                      only the rows that match (repeat: all must match)
  … --copies-from jars                                   that many copies of each row (0 skips the row)
  … --rows 2-5                                           data rows 2 to 5 (1 = first after the header)
  … --data a=prices.xlsx --join b=catalog.json --on name   two sources: {{ a.price }} {{ b.id }}
  … --set unit=kg                                        one value for every label
  bobina check label.bob.md --data rows.csv              paper length and problems, nothing printed
  bobina preview label.bob.md --data rows.csv -o 'labels/{column}.png'   one PNG per label ({n} {i} too)

Files: CSV, TSV, JSON (a list of objects), Excel .xlsx. Column names are the header row; a {{ name }}
that is not a column is printed empty and reported (M130, with the columns the data has).
Without a terminal add --yes: a print waits for confirmation otherwise (E107, exit 7).
"""


def _command_json(name: str) -> dict:
    p = COMMANDS[name]

    def option(a):
        return {"flags": a.option_strings, "help": a.help, "choices": list(a.choices) if a.choices else None,
                "takes_value": a.nargs != 0}  # fmt: skip

    return {
        "kind": COMMAND_KIND[name],
        "description": p.description,
        "options": [option(a) for a in p._actions if a.option_strings and a.help != argparse.SUPPRESS],
        "positionals": [
            {"name": a.dest, "choices": list(a.choices) if a.choices else None}
            for a in p._actions
            if not a.option_strings
        ],  # fmt: skip
    }


def _problems_json() -> list:
    from ..problem_help import explain

    return [explain(code) for code in CATALOG]


def _help_json() -> dict:
    """The CLI for programs: commands, their options, help topics, and every problem code with what to do."""
    return {
        "schema": "bobina.help/1",
        "commands": {name: _command_json(name) for name in COMMANDS},
        "topics": [*TOPICS, "CODE (a problem code, e.g. E302)", "COMMAND (a command name)"],
        "problems": _problems_json(),
        "exit_codes": EXIT_CODES,
    }


EXIT_CODES = {  # bobina help --json and the tools of bobina mcp say what each exit code means
    common.OK: "ok",
    common.USAGE: "usage",
    common.DOC: "document",
    common.STRICT: "strict nudges",
    common.UNREACHABLE: "unreachable",
    common.PRINTER_ERR: "printer not ready",
    common.MODE: "command language",
    common.CONFIRM: "confirmation needed or declined",
    common.SECURITY: "security",
    common.LEFT_OUT: "part of the job left out (a payment code, Q111)",
}  # fmt: skip


def _help_code(code: str, as_json: bool) -> int:
    from ..problem_help import explain

    e = explain(code)
    if as_json:
        print_json(e, indent=2, ensure_ascii=False)
        return OK
    stops = "stops the job: nothing prints" if e["severity"] == "error" else "never stops the job (except --strict)"
    print(f"{e['code']}  {e['severity']} · {e['category']} · {stops}\n  {e['title']}\n\n  what to do: {e['fix']}")
    if e["evidence"]:
        print(f"  evidence: printed test {e['evidence']}")
    print(f"  docs: {e['doc']} in the bobina repository")
    return OK


TOPICS = ("commands", "format", "data", "pay", "nudges", "problems", "aliases")


def _help_text(topic: str, name: str | None = None) -> str:
    from ..problem_help import CATEGORY

    if topic == "commands":
        return PARSER.format_help()
    if topic == "format":
        return HELP_FORMAT
    if topic == "data":
        return HELP_DATA
    if topic == "pay":
        from ..pay import help_text

        return help_text(name)
    if topic in ("nudges", "problems"):  # problems: the name the docs use for the catalog
        return "\n".join(
            f"{code}  {sev:8s} {CATEGORY.get(code[0], ''):17s} {title}" + (f"  (evidence: {ev})" if ev else "")
            for code, (sev, title, ev) in CATALOG.items()
        )
    if topic != "aliases":
        raise KeyError(topic)
    lines = ["Typing shortcuts (docs and output always use full names):"]
    lines += [f"  bobina {a:3s} = bobina {c}" for a, c in ALIASES.items()]
    return "\n".join([*lines, "  bob = bobina"])


def cmd_help(args):
    topic, as_json, name = args.topic, getattr(args, "json", False), getattr(args, "name", None)
    topic = topic.lower() if topic and topic.lower() in (*TOPICS, "pay") else topic
    if name and topic != "pay":
        raise Fail(USAGE, f"only 'bobina help pay SCHEME' takes a second word (got '{name}')", problem="E101")
    if name:
        from ..pay import SCHEMES, closest

        name = name.lower()
        if name not in SCHEMES:
            near = closest(name)
            raise Fail(USAGE, f"unknown pay scheme '{name}'" + (f" (did you mean {near}?)" if near else "")
                       + ": " + ", ".join(SCHEMES), problem="E207")  # fmt: skip
    if topic and topic.upper() in CATALOG:
        return _help_code(topic, as_json)
    if as_json:  # every topic has a structured form, each marked with the schema (an agent may parse any of them)
        if topic in (None, "commands"):
            out = _help_json()
        elif topic in COMMANDS:
            out = {"schema": "bobina.help/1", "kind": "command", "command": topic, **_command_json(topic)}
        elif topic in ("nudges", "problems"):
            out = {"schema": "bobina.help/1", "kind": "problems", "problems": _problems_json()}
        elif topic == "pay":
            from ..pay import SCHEMES, scheme_json, schemes_json

            out = {"schema": "bobina.help/1", "kind": "pay", "schemes": schemes_json()}
            if name in SCHEMES:
                out = {"schema": "bobina.help/1", "kind": "pay-scheme", **scheme_json(SCHEMES[name])}
        elif topic in TOPICS:
            out = {"schema": "bobina.help/1", "kind": "topic", "topic": topic, "text": _help_text(topic)}
        else:
            out = None
        if out is not None:
            print_json(out, indent=2, ensure_ascii=False, default=str)
            return OK
    elif topic in (None, "commands"):
        PARSER.print_help()
        return OK
    elif topic in TOPICS:
        print(_help_text(topic, name))
        return OK
    elif topic in COMMANDS:
        COMMANDS[topic].print_help()
        return OK
    raise Fail(
        USAGE,
        f"unknown help topic '{topic}': commands, format, data, pay, nudges (or problems), aliases, a problem code"
        " (e.g. E302), or a command name",
        problem="E207",
    )


COMMANDS: dict[str, argparse.ArgumentParser] = {}


PARSER: argparse.ArgumentParser


def _common(printing: bool = True):
    """Options every command takes. printing=False (check, preview, view): without --yes, --dry-run and --editor,
    which mean nothing there (they never print and never edit)."""
    c = argparse.ArgumentParser(add_help=False)
    g = c.add_argument_group("global options")
    g.add_argument("--profile", help="printer profile (default: from the printer or mtp-ii-58)")
    g.add_argument("--printer", help="printer name from config, or a Bluetooth address")
    g.add_argument("-q", "--quiet", action="store_true", help="no nudges")
    g.add_argument("--strict", action="store_true", help="nudges become errors (exit 3)")
    g.add_argument("--json", action="store_true", help="structured output")
    if printing:
        g.add_argument("-n", "--dry-run", action="store_true", help="never touch the printer")
        g.add_argument("-y", "--yes", action="store_true", help="print without the confirmation screen")
    else:  # accepted (old scripts, aliases) but not listed: they do nothing here, and a note says so
        g.add_argument("-n", "--dry-run", action="store_true", help=argparse.SUPPRESS)
        g.add_argument("-y", "--yes", action="store_true", help=argparse.SUPPRESS)
        g.add_argument("--editor", help=argparse.SUPPRESS)
    g.add_argument("--allow", action="append", metavar="CODES", help="silence nudges, e.g. --allow F301,L101")
    if printing:
        g.add_argument("--editor", help="editor command (default: config, $VISUAL, $EDITOR, nano)")
    g.add_argument("--verbose", action="store_true")
    g.add_argument("--debug", action="store_true")
    g.add_argument("--no-color", action="store_true", help="no colors (also NO_COLOR)")
    g.add_argument(
        "--problems",
        choices=["pretty", "plain", "json", "jsonl"],
        help="how errors and warnings are written (default pretty; also BOBINA_PROBLEMS)",
    )
    return c


# Commands with nothing to write as JSON: --json is accepted (it is a global option) and a note says it does nothing.
NO_JSON = {"view", "edit", "send", "mode", "mcp"}

# Every command declares its kind; a new command must be added here (and to tests/test_option_hints.py CASES):
# "prints" commands take --yes, --dry-run and --editor; "reads" commands never print, so those options are not
# offered and the hint explains why.
COMMAND_KIND = {
    "print": "prints", "edit": "prints", "send": "prints", "mode": "prints", "calibrate": "prints",
    "history": "prints",  # history clear --yes
    "check": "reads", "preview": "reads", "view": "reads", "status": "reads", "printer": "reads",
    "profile": "reads", "template": "reads", "seq": "reads", "fonts": "reads", "library": "reads",
    "paper": "reads", "help": "reads", "config": "reads",
    "mcp": "reads",  # the server: its print tool prints only with confirm: true in that call
}  # fmt: skip
_PARENTS: dict = {}


def _cmd(sub, name, help_, desc, examples, func):
    if name not in COMMAND_KIND:
        raise RuntimeError(
            f"new command '{name}': add it to COMMAND_KIND in cli/args.py (prints or reads) and give it hint cases "
            "in tests/test_option_hints.py"
        )
    p = sub.add_parser(
        name,
        help=help_,
        parents=[_PARENTS[COMMAND_KIND[name]]],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=f"bobina {name} — {desc}",
        epilog="EXAMPLES\n" + "\n".join("  " + e for e in examples),
    )
    p.set_defaults(func=func)
    COMMANDS[name] = p
    return p


LAST_ARGV: list[str] = []


def _command_word(argv: list[str]) -> str:
    from .common import command_word

    return command_word(argv)


def _options(parser) -> list[str]:
    """Long options offered by the parser (not the hidden ones of "reads" commands)."""
    return [
        o for a in parser._actions for o in a.option_strings
        if o.startswith("--") and o != "--help" and a.help != argparse.SUPPRESS
    ]  # fmt: skip


ALSO_KNOWN = {  # words people type for an option, by meaning (English and Portuguese)
    "--copies": ["--copy", "--copias", "--copia", "--vezes", "--times"],
    "--dry-run": ["--dryrun", "--simulate", "--test", "--teste", "--simular", "--no-print"],
    "--yes": ["--force-print", "--confirm", "--sim", "--noconfirm", "--no-confirm"],
    "--output": ["--out", "--save", "--salvar", "--saida", "--file", "--arquivo"],
    "--data": ["--csv", "--xlsx", "--excel", "--planilha", "--dados", "--sheet-file", "--json-data"],
    "--printer": ["--impressora", "--device", "--dev"],
    "--set": ["--var", "--field", "--campo", "--define", "--param"],
    "--where": ["--filter", "--filtro", "--onde", "--if"],
    "--rows": ["--linhas", "--range", "--lines"],
    "--compact": ["--compacto", "--glue", "--join-labels", "--strip", "--tira"],
    "--marks": ["--marcas", "--cut-marks", "--tear-marks", "--marcar", "--guides"],
    "--quiet": ["--silent", "--silencioso"],
    "--profile": ["--perfil", "--model", "--modelo"],
    "--on": ["--key", "--chave", "--match", "--by", "--por", "--join-on", "--join-key"],
    "--sheet": ["--aba", "--tab", "--planilha-aba", "--worksheet"],
    "--ask": ["--pergunta", "--perguntar", "--prompt", "--interactive", "--interativo"],
    "--limit": ["--count", "--tail", "--last-n", "--max", "--limite", "--number"],
    "--since": ["--desde", "--from", "--after", "--de"],
    "--repeat": ["--repetir", "--repeticoes"],
    "--force": ["--overwrite", "--sobrescrever", "--replace", "--forca"],
    "--then": ["--and", "--next", "--depois", "--e", "--append", "--plus"],
    "--join": ["--merge", "--juntar", "--combine", "--lookup"],
    "--page": ["--pagina", "--pg"],
    "--pages": ["--paginas", "--per-page", "--one-per-page"],
    "--plain": ["--raw-text", "--texto", "--no-markdown", "--literal"],
    "--strict": ["--estrito", "--fail-on-warning", "--werror"],
    "--verbose": ["--detalhado", "--detail"],
    "--allow-net": ["--internet", "--net", "--network", "--online", "--web"],
    "--sandbox": ["--untrusted", "--safe-mode", "--seguro", "--isolado", "--confined"],
    "--copies-from": ["--qty-column", "--quantidade", "--qtd", "--copies-column"],
    "--set-all": ["--set-every", "--global-set"],
    "--json": ["--machine"],
    "--last": ["--ultimo", "--reprint", "--repeat-last"],
    "--again": ["--de-novo", "--novamente", "--rerender"],
    "--realistic": ["--realista", "--ink"],
    "--default": ["--padrao", "--main", "--principal"],
    "--command": ["--cmd", "--comando", "--exec"],
    "--width": ["--largura", "--paper-width", "--roll-width"],
}
# Options reviewed for synonyms and left without them (their names are what people type, or too specific to
# guess). A new option goes in ALSO_KNOWN or here: tests/test_option_hints.py fails until it is in one of them.
NO_SYNONYMS = {
    "--allow", "--allow-all", "--channel", "--compact-all", "--core", "--debug",
    "--diameter", "--editor", "--list", "--long", "--no-color", "--no-compact", "--note", "--outcome", "--path",
    "--problems", "--remember", "--seconds", "--template", "--thickness",
}  # fmt: skip


def _edits(a: str, b: str) -> int:
    """Typing distance: insertions, deletions, substitutions and swapped neighbours (--joni -> --join) count 1."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def _closest(norm: str, opts: list[str]) -> list[str]:
    """The nearest options by typing distance (at most 2 edits, 1 for short names); both when they tie.
    Then a long option with a mistyped ending (--copies-form -> --copies-from) by its beginning."""
    word = norm[2:]
    limit = 1 if len(word) <= 4 else 2
    scored = sorted((_edits(word, o[2:]), -difflib.SequenceMatcher(None, word, o[2:]).ratio(), o) for o in opts)
    best = [x for x in scored if x[0] <= limit and x[0] == scored[0][0]] if scored else []
    if best:
        return [o for *_, o in best[:3]]
    if len(word) >= 5:
        same_start = [o for o in opts if o[2:].startswith(word[: max(4, len(word) - 4)])]
        near = difflib.get_close_matches(norm, same_start, n=1, cutoff=0.6)
        if near:
            return near
    return []


def _either(opts: list[str]) -> str:
    return opts[0] if len(opts) == 1 else ", ".join(opts[:-1]) + " or " + opts[-1]


def option_hint(token: str, cmd: str = "") -> str:
    """The hint for an unknown option: the option meant (typo, wrong case, _ for -, one dash, a synonym), or
    the command that has it, or why it does not apply here. "" when nothing is close enough."""
    raw = token.split("=", 1)[0]
    target = COMMANDS.get(cmd)
    prog = target.prog if target else "bobina"
    opts = _options(target) if target else sorted({o for p in COMMANDS.values() for o in _options(p)})
    norm = "--" + raw.lstrip("-").lower().replace("_", "-")
    if norm in opts and norm != raw:
        return f"did you mean {norm}? (see: {prog} --help)"
    for opt, words in ALSO_KNOWN.items():
        if norm in words and opt in opts:
            return f"did you mean {opt}? (see: {prog} --help)"
    owners = [n for n, p in COMMANDS.items() if n != cmd and norm in _options(p)]
    close = _closest(norm, opts)
    if close:
        elsewhere = f"; {norm} is an option of {_either(['bobina ' + o for o in owners[:2]])}" if owners else ""
        return f"did you mean {_either(close)}? (see: {prog} --help{elsewhere})"
    if owners:
        return f"{norm} belongs to {_either(['bobina ' + o for o in owners[:2]])}, not {prog}"
    return ""


class JoinAction(argparse.Action):
    """--join FILE: the --join before it must already have its --on (each --join takes exactly one --on, written
    right after it), so the pairing the user wrote is the pairing bobina uses."""

    def __call__(self, parser, ns, value, option_string=None):
        joins, ons = list(getattr(ns, "join", None) or []), getattr(ns, "on", None) or []
        if len(ons) < len(joins):
            raise argparse.ArgumentError(self, f"the --join before {value} has no --on: --join OTHER --on KEY")
        ns.join = [*joins, value]


class OnAction(argparse.Action):
    def __call__(self, parser, ns, value, option_string=None):
        joins, ons = getattr(ns, "join", None) or [], list(getattr(ns, "on", None) or [])
        if not joins:
            raise argparse.ArgumentError(self, f"--on {value} needs a --join before it: --join OTHER --on KEY")
        if len(ons) >= len(joins):
            raise argparse.ArgumentError(self, f"--on {value}: the --join before it already has --on {ons[-1]}")
        ns.on = [*ons, value]


class Parser(argparse.ArgumentParser):
    """argparse exits with 2 on usage errors; bobina's code for a usage error is 1 (2 = document error).
    Abbreviations are off: full names are canonical, and `--the` or `--set-a=` must not be guessed."""

    def __init__(self, *a, **k):
        k.setdefault("allow_abbrev", False)
        super().__init__(*a, **k)

    def error(self, message):
        from ..nudges import Nudge
        from .common import _FMT, render_problems, stopped

        target = self
        cmd = _command_word(LAST_ARGV)
        if self.prog == "bobina" and cmd in COMMANDS:  # unknown options are found by the top parser
            target = COMMANDS[cmd]
        hint = f"see: {target.prog} --help"
        m = re.match(r"unrecognized arguments: (.*)", message)
        unknown = [t for t in (m.group(1).split() if m else []) if t.startswith("-")]
        if unknown:
            hint = option_hint(unknown[0], cmd if cmd in COMMANDS else "") or hint
        if _FMT[0] == "pretty":
            target.print_usage(sys.stderr)
        lines = render_problems([Nudge("E101", message, None, hint)], stopped())
        self.exit(USAGE, "\n".join(lines) + "\n")


def make_parser():
    global PARSER
    common = _common()
    viewing = _common(printing=False)
    _PARENTS.update(prints=common, reads=viewing)
    ap = Parser(
        prog="bobina",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="bobina — print Markdown on thermal roll printers",
        epilog="Every command that prints shows a confirmation first (--yes skips it).\n"
        "Help: bobina help format | nudges | aliases | COMMAND",
    )
    ap.add_argument("--version", action="version", version=f"bobina {__version__}")
    sub = ap.add_subparsers(dest="command", metavar="COMMAND")

    def target(p, h='a .bob.md file, "TEXT" (\\n = new line), or - for stdin'):
        p.add_argument("target", nargs="*", help=h + "; several = one strip")
        p.add_argument("--plain", action="store_true", help="do not interpret Markdown")
        p.add_argument("--set", action="append", metavar="KEY=VALUE", help="template field (printed literally)")
        p.add_argument(
            "--data",
            action="append",
            metavar="[NAME=]FILE",
            help="one label per row: CSV, TSV/TXT, XLSX or JSON; columns are fields (literal)",
        )
        p.add_argument("--sheet", metavar="NAME", help="--data .xlsx: the sheet (default: the first)")
        p.add_argument(
            "--join",
            action=JoinAction,
            metavar="[NAME=]FILE",
            help="add the columns of another source to each --data row (matched by --on)",
        )
        p.add_argument(
            "--on",
            action=OnAction,
            metavar="KEY",
            help="the column that matches the rows of the --join before it;"
            " NAME=OTHER when the names differ (--on name=product)",
        )
        p.add_argument("--rows", metavar="N-M", help="--data: only these data rows (1 = first after the header)")
        p.add_argument(
            "--where", action="append", metavar="COL=VAL", help="--data: keep rows where COL=VAL, COL!=VAL or COL~=TEXT"
        )
        p.add_argument("--copies-from", metavar="COL", help="--data: copies of each row from this column (0 skips)")
        p.add_argument("--repeat", type=int, default=1, metavar="N", help="N renders, each with new counter values")
        p.add_argument("--copies", type=int, default=1, metavar="N", help="N identical copies")
        p.add_argument("--ask", action="store_true", help="ask the missing template fields on the terminal")
        p.add_argument(
            "--compact",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="this part's labels glued, to be cut apart (no line on paper unless --marks cut; --no-compact:"
            " tear feed after each)",
        )
        p.add_argument("--compact-all", action="store_true", help="every part compact unless it says --no-compact")
        p.add_argument(
            "--marks",
            choices=MARKS,
            help="print a fine dashed line where a label ends: cut (between --compact labels), tear (on the tear"
            " bar), both; default none, or marks in config.toml",
        )
        p.add_argument(
            "--set-all", action="append", metavar="KEY=VALUE", help="a field for every part (a part's --set wins)"
        )
        p.add_argument("--allow-all", action="append", metavar="CODES", help="silence nudges in every part")
        p.add_argument("--then", metavar="TARGET", help="add another document/batch to the same job (repeatable)")
        p.add_argument("--force", action="store_true", help="-o: replace files that already exist")
        p.add_argument("--page", metavar="N|N-M", help="PDF target: pages to print (default: all)")
        p.add_argument("--allow-net", action="store_true", help="allow https images (public hosts only)")
        p.add_argument(
            "--sandbox",
            action="store_true",
            help="a document from someone else: its images only from its own folder and image_dirs (config.toml)",
        )

    p = _cmd(
        sub,
        "print",
        "render, confirm and print",
        "print a document, inline text or stdin",
        [
            'bobina print "buy bread"',
            "bobina print list.bob.md",
            "bobina print list.bob.md --dry-run",
            'echo "hello" | bobina print --yes',
            "bobina print --last",
        ],
        cmd_print,
    )
    target(p)
    p.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="save to FILE instead of printing (the bytes the printer would get);"
        " with {n} {i} {file} {part} {column}: one file per label",
    )
    p.add_argument(
        "--last", action="store_true", help="reprint the last job, identical bytes (-o FILE: save them instead)"
    )
    p.add_argument(
        "--again", action="store_true", help="re-render and print the last document (new now/seq; -o FILE: save it)"
    )

    p = _cmd(
        sub,
        "check",
        "lint without printing",
        "line breaks, glyphs, codes, paper length, nudges",
        ["bobina check list.bob.md", "bobina check list.bob.md --json --strict"],
        cmd_check,
    )
    target(p)
    p = _cmd(
        sub,
        "preview",
        "write the exact bitmap as PNG",
        "the dots that will be printed",
        ["bobina preview list.bob.md -o list.png"],
        cmd_preview,
    )
    target(p)
    p.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="save the preview image to FILE: .png (default: DOCUMENT.preview.png), .jpg, .pdf, .webp, .bmp,"
        " .gif, .tif; with {n} {i} {file} {part} {column}: one image per label",
    )
    p.add_argument("--pages", action="store_true", help="-o FILE.pdf: one page per label")
    p.add_argument("--realistic", action="store_true", help="simulate ink spread (needs calibration)")
    p = _cmd(
        sub,
        "view",
        "preview in the terminal",
        "text on the 32-column grid, images as braille",
        ["bobina view list.bob.md"],
        cmd_view,
    )
    target(p)
    p = _cmd(
        sub,
        "edit",
        "write in your editor, confirm, print",
        "open a draft or file in the editor",
        ["bobina edit", "bobina edit list.bob.md", "bobina edit --editor 'code --wait'"],
        cmd_edit,
    )
    p.add_argument("target", nargs="?", help="file to edit (created if missing); none = a new draft")
    p.add_argument("--template", help="start from a template (fields prefilled)")
    p.add_argument("--set", action="append", metavar="KEY=VALUE")
    p.add_argument("--sandbox", action="store_true", help="images only from the document folder and image_dirs")
    p = _cmd(
        sub,
        "status",
        "printer state",
        "paper, cover, errors (DLE EOT)",
        ["bobina status", "bobina status --list"],
        cmd_status,
    )
    p.add_argument("--list", action="store_true", help="explain every state")
    p = _cmd(
        sub,
        "mode",
        "show or switch the command language",
        "esc (needed by bobina), tspl, cpcl",
        ["bobina mode", "bobina mode esc"],
        cmd_mode,
    )
    p.add_argument("language", nargs="?", choices=sorted(MODES))
    p = _cmd(
        sub,
        "send",
        "send raw bytes untouched",
        "escape hatch: no checks, no preview",
        ["bobina send job.bin", "cat job.bin | bobina send --yes -"],
        cmd_send,
    )
    p.add_argument("file", help="file with bytes, or -")
    p = _cmd(
        sub,
        "printer",
        "find and store printers",
        "printers live in ~/.config/bobina/config.toml",
        [
            "bobina printer scan",
            "bobina printer add mtp AA:BB:CC:DD:EE:FF",
            "bobina printer add tower --command 'ssh tower bobina send --yes -'",
            "bobina printer list",
        ],
        cmd_printer,
    )
    p.add_argument("action", choices=["list", "scan", "add", "use", "remove"])
    p.add_argument("name", nargs="?")
    p.add_argument("address", nargs="?", help="Bluetooth MAC")
    p.add_argument("--channel", type=int, default=1)
    p.add_argument("--command", dest="command", help="pipe bytes to this command (e.g. ssh to the printer host)")
    p.add_argument("--path", help="append bytes to this file/device")
    p.add_argument("--default", action="store_true")
    p.add_argument("--seconds", type=int, default=8, help="scan duration")
    p = _cmd(
        sub,
        "config",
        "see and change settings",
        "settings in ~/.config/bobina/config.toml. locale: the locale of documents without locale: (dates, numbers"
        " and money); without one, the first print, check or preview infers it from the time zone and saves it",
        ["bobina config locale", "bobina config locale pt-BR", "bobina config locale --json"],
        cmd_config,
    )
    p.add_argument("key", choices=["locale"])
    p.add_argument("value", nargs="?", metavar="TAG", help="a BCP 47 tag (pt-BR, en-US, fr-CA): saved; none: shown")
    p = _cmd(
        sub,
        "profile",
        "printer profiles",
        "measured capabilities per printer model",
        ["bobina profile list", "bobina profile show mtp-ii-58"],
        cmd_profile,
    )
    p.add_argument("action", choices=["list", "show"])
    p.add_argument("name", nargs="?")
    p = _cmd(
        sub,
        "template",
        "ready-made documents",
        "receipt, label, todo, card, note, and price tags and labels for shops (template list)",
        [
            "bobina template list",
            "bobina template show receipt",
            "bobina template new receipt sale.bob.md",
            "bobina edit --template todo",
        ],
        cmd_template,
    )
    p.add_argument("action", choices=["list", "show", "new"])
    p.add_argument("name", nargs="?")
    p.add_argument("file", nargs="?")
    p = _cmd(
        sub,
        "history",
        "what was printed",
        "every print job: printed, cancelled, saved, failed (like git log)",
        [
            "bobina history",
            "bobina history --long --limit 5",
            "bobina history --outcome failed --since 2026-11-01",
            "bobina history show last",
            "bobina history stats",
            "bobina history --json",
        ],
        cmd_history,
    )
    p.add_argument("action", nargs="?", default="list", choices=["list", "show", "stats", "clear"])
    p.add_argument("id", nargs="?", help="show: a job id (or its start), or last")
    p.add_argument("--limit", type=int, default=20, metavar="N", help="list: the last N jobs (0 = all)")
    p.add_argument("--long", action="store_true", help="list: every detail of each job")
    p.add_argument("--since", metavar="DATE", help="only jobs from this date/time on (2026-11-01, 2026-11-07T18:00)")
    p.add_argument("--outcome", metavar="WORD", help="only jobs with this outcome: printed, cancelled, failed, saved …")
    p = _cmd(
        sub,
        "library",
        "saved labels",
        "ready labels printed by name: bobina print @NAME",
        [
            "bobina library add shelf shelf-label.bob.md --note 'pantry shelf'",
            'bobina library add bread "# BREAD\\nbest before {{ today | add(days=3) | date }}"',
            "bobina library list",
            "bobina print @shelf --set item=Rice",
            "bobina library rm shelf",
        ],
        cmd_library,
    )
    p.add_argument("action", choices=["list", "add", "show", "rm"])
    p.add_argument("name", nargs="?")
    p.add_argument("source", nargs="?", help='add: a .bob.md file, an image/PDF, or "TEXT"')
    p.add_argument("--note", help="add: a short description shown in the list")
    p.add_argument("--force", action="store_true", help="add: replace an existing entry")
    p = _cmd(
        sub,
        "seq",
        "persistent counters",
        "values used by {{ seq.NAME }}",
        ["bobina seq list", "bobina seq set ticket 100", "bobina seq reset ticket"],
        cmd_seq,
    )
    p.add_argument("action", choices=["list", "set", "reset"])
    p.add_argument("name", nargs="?")
    p.add_argument("value", nargs="?")
    p = _cmd(
        sub,
        "calibrate",
        "measure the printer",
        "measure the printer with short test strips: compare (a photo of a ticket against its preview), tear"
        " (where the tear bar is) and feed (whether it obeys paper feeds after images). tear and feed print"
        " their strip, then take your answer: bobina calibrate tear 16, bobina calibrate feed touching",
        [
            "bobina calibrate compare ticket.jpg ticket.bob.md",
            "bobina calibrate tear",
            "bobina calibrate tear 16",
            "bobina calibrate feed",
            "bobina calibrate feed apart",
        ],
        cmd_calibrate,
    )
    p.add_argument("action", choices=["compare", "tear", "feed"])
    p.add_argument(
        "photo",
        nargs="?",
        metavar="PHOTO|MM|ANSWER",
        help="compare: photo of the ticket · tear: the mm read at the torn edge · feed: touching or apart"
        " (lines B and C)",
    )
    p.add_argument("target", nargs="?", metavar="DOCUMENT", help="compare: the .bob.md of the photographed ticket")
    p.add_argument("-o", "--output", help="side-by-side PNG (default: fidelity.png)")
    p = _cmd(
        sub,
        "paper",
        "paper left on the roll",
        "an odometer: roll length minus what bobina printed",
        [
            "bobina paper",
            "bobina paper new 15m",
            "bobina paper new --diameter 40mm --core 12mm",
            "bobina paper new 50ft --width 57mm",
            "bobina paper new 10m --remember",
            "bobina paper new",
            "bobina paper used 3m",
            "bobina paper used +30cm",
        ],
        cmd_paper,
    )
    p.add_argument("action", nargs="?", default="status", choices=["status", "new", "used"])
    p.add_argument("length", nargs="?", help="15m, 1500cm, 50ft … (a bare number is metres)")
    p.add_argument("--diameter", help="outer diameter of the roll (e.g. 40mm)")
    p.add_argument("--core", default="12mm", help="core diameter (default 12mm)")
    p.add_argument("--thickness", default="0.06", help="paper thickness in mm (default 0.06)")
    p.add_argument("--width", help="the roll's paper width (57mm, 80mm, 2 1/4in): a warning if it is not the printer's")
    p.add_argument(
        "--remember", action="store_true", help="save LENGTH as the default roll (paper new without arguments)"
    )
    p = _cmd(
        sub,
        "fonts",
        "recommended fonts",
        "tested fonts, minimum sizes, test tickets; fonts for other scripts (Thai, Hindi, Chinese…)",
        [
            "bobina fonts list",
            'bobina fonts test "DejaVu Serif"',
            'bobina fonts mark "DejaVu Serif" 20',
            "bobina fonts scripts",
            "bobina fonts get thai devanagari",
            "bobina fonts get menu.bob.md",
        ],
        cmd_fonts,
    )
    p.add_argument("action", nargs="?", default="list", choices=["list", "test", "mark", "scripts", "get"])
    p.add_argument(
        "names", nargs="*", metavar="NAME", help="test/mark: FAMILY [MIN_PX]; get: scripts, languages or documents"
    )
    p.add_argument("--note")
    p.add_argument("--plain", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--set", action="append", help=argparse.SUPPRESS)
    p = _cmd(
        sub,
        "help",
        "help topics",
        "commands, format, data, nudges, aliases, a problem code (E302) or a command; --json for programs",
        ["bobina help format", "bobina help print"],
        cmd_help,
    )
    p.add_argument("topic", nargs="?")
    p.add_argument("name", nargs="?", help="with pay: one scheme (bobina help pay pix)")
    _cmd(
        sub,
        "mcp",
        "a server for AI agents (MCP)",
        "a Model Context Protocol server on stdin/stdout: check, preview, print (only with confirm), templates,"
        " help, status and paper as tools. Needs the extra: uv tool install 'bobina[mcp]'. --printer, --profile,"
        " --allow and --strict are the defaults of check, preview and print; --printer also of status and paper",
        ["claude mcp add bobina -- bobina mcp", "bobina mcp --printer test"],
        cmd_mcp,
    )
    PARSER = ap
    return ap


CHAINABLE = ("print", "preview", "check", "view")


def normalize(argv: list[str]) -> list[str]:
    """Resolves aliases and moves global options written before the command to after it."""
    pre, i = [], 0
    while i < len(argv) and argv[i].startswith("-") and argv[i] not in ("-h", "--help", "--version"):
        pre.append(argv[i])
        if argv[i] in GLOBAL_WITH_VALUE and i + 1 < len(argv):
            pre.append(argv[i + 1])
            i += 1
        i += 1
    if i < len(argv):
        cmd = ALIASES.get(argv[i], argv[i])
        return [cmd] + pre + argv[i + 1 :]
    return argv


def parse_args(ap, argv: list[str]):
    """argv -> args; with --then, args.chain holds the later parts (each parsed as the same command)."""
    argv = normalize(argv)
    LAST_ARGV[:] = argv
    chain = []
    if argv and argv[0] in CHAINABLE and any(t == "--then" or t.startswith("--then=") for t in argv):
        segs, cur = [], []
        for tok in argv[1:]:
            if tok == "--then":
                segs.append(cur)
                cur = []
            elif tok.startswith("--then="):  # --then=FILE: same as --then FILE
                segs.append(cur)
                cur = [tok.split("=", 1)[1]]
            else:
                cur.append(tok)
        segs.append(cur)
        if any(not s for s in segs[1:]):
            ap.error("--then needs a document after it")
        for s in segs:
            if "--compact" in s and "--no-compact" in s:
                ap.error("--compact and --no-compact in the same part: choose one")
        chain = [ap.parse_args([argv[0], *s]) for s in segs[1:]]
        argv = [argv[0], *segs[0]]
    elif argv and argv[0] in CHAINABLE and "--compact" in argv and "--no-compact" in argv:
        ap.error("--compact and --no-compact in the same part: choose one")
    args = ap.parse_args(argv)
    args.chain = chain
    return args


def _font_notice(args) -> None:
    """Before a font for another script is downloaded, one line on the terminal says which, its license, size and
    source. Not with -q, BOBINA_NONINTERACTIVE or problems as JSON: there, the F304 note in the problems says it."""
    from .. import scriptfonts
    from .common import _FMT, err, noninteractive

    quiet = getattr(args, "quiet", False) or noninteractive() or _FMT[0] in ("json", "jsonl")
    scriptfonts.NOTICE = None if quiet else (lambda m: err(f"bobina: {m}"))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from .common import set_command, set_problem_format

    set_problem_format(argv)
    set_command(argv)
    ap = make_parser()
    if not argv:
        ap.print_help()
        return USAGE
    args = parse_args(ap, argv)
    args.argv = list(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return USAGE
    if os.environ.get("NO_COLOR"):
        args.no_color = True
    cmd = _command_word(argv)
    if COMMAND_KIND.get(cmd) == "reads":
        given = [f for f, on in (("--yes", args.yes), ("--dry-run", args.dry_run), ("--editor", args.editor)) if on]
        if given:
            err(f"note: {', '.join(given)} does nothing in bobina {cmd}: it never prints")
            args.yes, args.dry_run, args.editor = False, False, None
    from .common import json_written

    json_written(reset=True)
    _font_notice(args)
    if cmd in NO_JSON and getattr(args, "json", False):  # said, never ignored in silence (it also muted warnings)
        err(f"note: --json does nothing in bobina {cmd}: it writes no data (bobina check --json for the problems)")
        args.json = False
    if any(getattr(a, "sandbox", False) for a in (args, *(getattr(args, "chain", None) or []))):
        from ..fileio import limit_memory

        limit_memory()  # untrusted input: a hard ceiling under bobina's own size checks
    try:
        code = args.func(args) or OK
        if getattr(args, "json", False) and not json_written() and code in (OK, LEFT_OUT):
            what = " ".join(x for x in (cmd, getattr(args, "action", None)) if isinstance(x, str))
            err(f"note: --json does nothing in bobina {what}: it writes no data")  # stdout above is prose
        return code
    except Fail as e:
        err(e.format())
        return e.code
    except SecurityError as e:
        from .common import render_problems, stopped

        err("\n".join(render_problems([e.nudge], stopped())))
        return SECURITY
    except StateError as e:  # counters, paper, library index, config, last job: damaged, never reset silently
        f = Fail(USAGE, f"{e}\n→ fix the file by hand, or move it away to start that part over", problem="E209")
        err(f.format())
        return f.code
    except LockTimeout as e:
        f = Fail(USAGE, f"{e}\n→ wait for the other command to finish, then try again", problem="E209")
        err(f.format())
        return f.code
    except KeyboardInterrupt:
        err("interrupted")
        return 130
    except MemoryError:
        from ..fileio import memory_limit
        from ..nudges import Nudge
        from .common import render_problems, stopped

        ceiling = memory_limit()
        why = f"the {ceiling // 1024**3} GB allowed for --sandbox" if ceiling else "the memory of this machine"
        msg = f"the document needs more than {why}: nothing was printed"
        err("\n".join(render_problems([Nudge("M313", msg)], stopped())))
        return SECURITY
