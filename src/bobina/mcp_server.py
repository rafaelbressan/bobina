"""bobina mcp: a Model Context Protocol server (stdio) whose tools are the commands of the CLI.

Each tool runs the CLI in a child process (`python -m bobina … --json`) and returns what it wrote: the same JSON
(docs/schemas/), the same problem codes and the same exit code, with the command line it ran. A child process:
- keeps stdout clean (here it is the protocol channel) and holds no state between calls (the CLI is not
  thread-safe, docs/CLI.md "Two commands at the same time");
- never reaches the user's terminal: no stdin, BOBINA_NONINTERACTIVE=1 and a session of its own;
- has the CLI's safety as it is: sandboxed templates, no network images without allow_net, the size limits.
print without confirm: true is a dry run (--dry-run): nothing is sent to the printer.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Annotated

from .cli.common import LEFT_OUT, OK, USAGE, Fail

INSTALL = "uv tool install 'bobina[mcp]'  (or: pip install 'bobina[mcp]')"
TIMEOUT = 300  # seconds for a command; a print waits longer (a long strip over Bluetooth)
PRINT_TIMEOUT = 1800
IMAGE_MAX_DOTS = 8000  # taller images are refused by most agent clients: the path is given instead
IMAGE_MAX_BYTES = 4_000_000
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp"}  # fmt: skip
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")  # a template, topic, scheme or printer: never an option

INSTRUCTIONS = """\
bobina prints Markdown (.bob.md: receipts, lists, labels, QR and payment codes) on thermal roll printers.
Look before printing: check (paper length and problems) and preview (the exact image). print sends to the
printer only with confirm: true, after the user agreed; without it, it is a dry run. Every result starts with
the bobina command line it ran and its exit code: 0 ok, 9 printed without a payment code (Q111), others are
errors. A problem code (E401, Q111…) is explained by help with that code. Document format: help topic format."""


@dataclass
class Run:
    argv: list[str]
    code: int
    stdout: str
    stderr: str


def run(argv: list[str], stdin: str | None = None, timeout: int = TIMEOUT) -> Run:
    """bobina ARGV in a child process; problems on stderr as JSON (--problems json)."""
    env = {**os.environ, "BOBINA_NONINTERACTIVE": "1", "BOBINA_PROBLEMS": "json", "NO_COLOR": "1"}
    feed = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    try:
        p = subprocess.run(
            [sys.executable, "-m", "bobina", *argv], capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=timeout, start_new_session=os.name == "posix", **feed,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return Run(argv, USAGE, "", f"stopped after {timeout} s: bobina {' '.join(argv)} did not finish")
    return Run(argv, p.returncode, p.stdout, p.stderr)


def _meaning(code: int) -> str:
    from .cli.args import EXIT_CODES

    return EXIT_CODES.get(code, "")


def result(r: Run, *extra):
    """The run as a tool result: the command line and exit code, stdout (the CLI's JSON), stderr (problems as
    JSON, notes). An error unless the exit is 0 or 9 (the job went out without a payment code: docs/CLI.md)."""
    from mcp.types import CallToolResult, TextContent

    meaning = _meaning(r.code)
    head = f"bobina {' '.join(r.argv)}\nexit {r.code}" + (f" ({meaning})" if meaning else "")
    texts = [head, r.stdout.strip(), "stderr:\n" + r.stderr.strip() if r.stderr.strip() else ""]
    content = [TextContent(type="text", text=t) for t in texts if t]
    return CallToolResult(content=content + [x for x in extra if x], is_error=r.code not in (OK, LEFT_OUT))


def _error(message: str):
    from mcp.server.mcpserver.exceptions import ToolError

    return ToolError(message)


def _name(value: str, what: str) -> str:
    if not NAME.fullmatch(value):
        raise _error(f"not a {what}: {value!r} (letters, digits, '.', '_' and '-')")
    return value


def _target(text: str | None, path: str | None) -> tuple[str, str | None]:
    """(the CLI target, stdin): text goes in on stdin (-), never on the command line."""
    if (text is None) == (path is None):
        raise _error("give the document as text or as path (one of them)")
    if text is not None:
        return "-", text
    if path.startswith("@"):  # a saved label: bobina library
        _name(path[1:], "saved label")
        return path, None
    p = Path(path).expanduser()
    if not p.is_file():  # the CLI would print a name that is not a file as text
        raise _error(f"file not found: {path} (E201; relative paths start at {os.getcwd()})")
    return str(p if p.is_absolute() else Path.cwd() / p), None


class Server:
    """The tools, with the defaults given to bobina mcp (--printer, --profile, --allow, --strict)."""

    def __init__(self, printer=None, profile=None, allow: list[str] | None = None, strict: bool = False):
        self.printer, self.profile, self.allow, self.strict = printer, profile, list(allow or []), strict
        self.previews: Path | None = None  # a temporary folder, made by the first preview without output
        self.n = count(1)

    def options(self, set_=None, data=None, profile=None, allow=None, allow_net=False, strict=False, printer=None):
        """Tool arguments as CLI options, each one token (--set=K=V): a value never reads as another option."""
        a = [f"--set={k}={v}" for k, v in (set_ or {}).items()]
        if data:
            a.append(f"--data={data}")
        for flag, value in (("--printer", printer or self.printer), ("--profile", profile or self.profile)):
            if value:
                a.append(f"{flag}={value}")
        if allow or self.allow:
            a.append("--allow=" + ",".join([*self.allow, *(allow or [])]))
        return a + (["--allow-net"] if allow_net else []) + (["--strict"] if strict or self.strict else [])

    def check(self, text=None, path=None, **opts):
        target, stdin = _target(text, path)
        return result(run(["check", target, "--json", *self.options(**opts)], stdin))

    def preview(self, text=None, path=None, output=None, **opts):
        target, stdin = _target(text, path)
        if not output and self.previews is None:
            self.previews = Path(tempfile.mkdtemp(prefix="bobina-mcp-"))
        out = output or str(self.previews / f"preview-{next(self.n)}.png")
        r = run(["preview", target, f"--output={out}", "--json", *self.options(**opts)], stdin)
        try:
            files = json.loads(r.stdout).get("files") or []
        except (ValueError, AttributeError):
            files = []
        return result(r, *_image(files[0] if files else None))

    def print(self, text=None, path=None, confirm=False, copies=1, **opts):
        target, stdin = _target(text, path)
        mode = ["--yes"] if confirm is True else ["--dry-run"]  # only a real true prints
        copies_ = [f"--copies={copies}"] if copies != 1 else []
        argv = ["print", target, *mode, "--json", *copies_, *self.options(**opts)]
        r = run(argv, stdin, PRINT_TIMEOUT if confirm is True else TIMEOUT)
        if confirm is not True and r.code in (OK, LEFT_OUT):
            from mcp.types import TextContent

            note = "dry run: nothing was printed. Show the user what will print (preview), then call print with" \
                   " confirm: true once they agree."  # fmt: skip
            return result(r, TextContent(type="text", text=note))
        return result(r)

    def template_list(self):
        return result(run(["template", "list", "--json"]))

    def template_show(self, name):
        from mcp.types import TextContent

        name = _name(name, "template name")
        fields, starter = run(["template", "show", name, "--json"]), run(["template", "new", name])
        if fields.code != OK or starter.code != OK:
            return result(fields if fields.code != OK else starter)
        doc = f"the template as a document to fill (bobina template new {name}):\n\n{starter.stdout}"
        return result(fields, TextContent(type="text", text=doc))

    def help(self, topic=None, name=None):
        words = [_name(w, "help topic") for w in (topic, name) if w]
        return result(run(["help", *words, "--json"]))

    def status(self, printer=None):
        return result(run(["status", "--json", *self.options(printer=printer)]))

    def paper(self, printer=None):
        return result(run(["paper", "--json", *self.options(printer=printer)]))


def _image(path: str | None) -> list:
    """The preview as image content, when a client can take it; otherwise a note with the reason."""
    from mcp.types import ImageContent, TextContent

    if not path:
        return []
    p = Path(path)
    kind = IMAGE_TYPES.get(p.suffix.lower())
    why = "" if kind else f"{p.suffix} is not an image format agents read (PNG is)"
    if kind:
        from PIL import Image

        try:
            with Image.open(p) as im:
                height = im.height
            size = p.stat().st_size
        except OSError as e:
            return [TextContent(type="text", text=f"the preview {p} could not be read back: {e}")]
        if height > IMAGE_MAX_DOTS or size > IMAGE_MAX_BYTES:
            why = f"it is {height} dots tall and {size // 1024} KB, too large to attach"
    if why:
        return [TextContent(type="text", text=f"the image is not attached: {why}. It is saved at {p}")]
    import base64

    return [ImageContent(type="image", data=base64.b64encode(p.read_bytes()).decode(), mime_type=kind)]


def build(printer=None, profile=None, allow: list[str] | None = None, strict: bool = False):
    """The MCP server with bobina's tools (tests call it without stdio). The argument types are built here, not
    at import: pydantic comes with the MCP SDK, an extra, and bobina mcp says how to install it when missing."""
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations
    from pydantic import Field

    from . import __version__

    s = Server(printer, profile, allow, strict)
    mcp = MCPServer("bobina", version=__version__, instructions=INSTRUCTIONS)
    reads = ToolAnnotations(read_only_hint=True, open_world_hint=False)
    TextArg = Annotated[str | None, Field(description="the document as text (.bob.md Markdown); or give path")]
    PathArg = Annotated[
        str | None, Field(description="a .bob.md, image or PDF file (absolute path), or @NAME for a saved label")
    ]
    SetArg = Annotated[dict[str, str] | None, Field(description="template fields, printed literally (--set KEY=VALUE)")]
    DataArg = Annotated[str | None, Field(description="a CSV, TSV, JSON or .xlsx file: one label per row (--data)")]
    ProfileArg = Annotated[str | None, Field(description="printer profile, e.g. mtp-ii-58 (--profile)")]
    AllowArg = Annotated[list[str] | None, Field(description="problem codes to silence, e.g. ['F301'] (--allow)")]
    NetArg = Annotated[bool, Field(description="fetch https images from public hosts (--allow-net)")]
    StrictArg = Annotated[bool, Field(description="warnings stop the job, exit 3 (--strict)")]
    PrinterArg = Annotated[str | None, Field(description="a printer name from bobina printer list (--printer)")]

    @mcp.tool(annotations=reads)
    def check(
        text: TextArg = None, path: PathArg = None, set: SetArg = None, data: DataArg = None,
        profile: ProfileArg = None, allow: AllowArg = None, allow_net: NetArg = False,
        strict: StrictArg = False,
    ):  # fmt: skip
        """Lint a document without printing (bobina check --json): paper length, labels, line breaks, glyphs,
        codes, and every problem with its code and a suggestion. Nothing is printed or saved."""
        return s.check(text, path, set_=set, data=data, profile=profile, allow=allow, allow_net=allow_net,
                       strict=strict)  # fmt: skip

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False))
    def preview(
        text: TextArg = None, path: PathArg = None, set: SetArg = None, data: DataArg = None,
        profile: ProfileArg = None, allow: AllowArg = None, allow_net: NetArg = False,
        output: Annotated[
            str | None, Field(description="where to save it (.png default, .pdf, .jpg…); default: a temporary file")
        ] = None,
    ):  # fmt: skip
        """The exact dots that will be printed (bobina preview --json), returned as an image with the path of the
        file and the problems. Nothing is printed."""
        return s.preview(text, path, output, set_=set, data=data, profile=profile, allow=allow, allow_net=allow_net)

    @mcp.tool(name="print", annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                                        idempotent_hint=False, open_world_hint=True))  # fmt: skip
    def print_(
        text: TextArg = None, path: PathArg = None,
        confirm: Annotated[
            bool, Field(description="true sends the job to the printer (--yes); only after the user agreed."
                                    " false or missing: a dry run, nothing printed")
        ] = False,
        set: SetArg = None, data: DataArg = None,
        copies: Annotated[int, Field(description="identical copies (--copies)")] = 1,
        printer: PrinterArg = None, profile: ProfileArg = None, allow: AllowArg = None,
        allow_net: NetArg = False, strict: StrictArg = False,
    ):  # fmt: skip
        """Print a document on the thermal printer (bobina print --json). Without confirm: true it is a dry run
        (--dry-run): the same figures and problems, nothing sent. Exit 9: printed without a payment code (Q111)."""
        return s.print(text, path, confirm, copies, set_=set, data=data, printer=printer, profile=profile,
                       allow=allow, allow_net=allow_net, strict=strict)  # fmt: skip

    @mcp.tool(annotations=reads)
    def template_list():
        """The ready-made documents (bobina template list --json): receipt, label, todo, shop tags…"""
        return s.template_list()

    @mcp.tool(annotations=reads)
    def template_show(name: Annotated[str, Field(description="a name from template_list, e.g. receipt")]):
        """A template's fields (bobina template show --json) and the template as a document to fill in."""
        return s.template_show(name)

    @mcp.tool(name="help", annotations=reads)
    def help_(
        topic: Annotated[
            str | None,
            Field(description="commands, format, data, pay, nudges, aliases, a command, or a problem code (Q111);"
                              " none: the whole CLI for programs"),
        ] = None,
        name: Annotated[str | None, Field(description="with topic pay: one scheme, e.g. pix")] = None,
    ):  # fmt: skip
        """bobina help --json: the document format, a problem code and what to do, a payment scheme, a command."""
        return s.help(topic, name)

    @mcp.tool(annotations=reads)
    def status(printer: PrinterArg = None):
        """The printer's state (bobina status --json): online, paper, cover, error. Bluetooth printers only."""
        return s.status(printer)

    @mcp.tool(annotations=reads)
    def paper(printer: PrinterArg = None):
        """Paper left on the roll (bobina paper --json): the roll length minus what bobina printed."""
        return s.paper(printer)

    return mcp


def serve(args) -> int:
    """bobina mcp: the server on stdin/stdout until the client closes it."""
    allow = [c.strip() for v in (getattr(args, "allow", None) or []) for c in v.split(",") if c.strip()]
    try:
        server = build(getattr(args, "printer", None), getattr(args, "profile", None), allow, bool(args.strict))
    except ImportError as e:
        if not (e.name or "").startswith(("mcp", "pydantic")):
            raise
        raise Fail(USAGE, f"bobina mcp needs the MCP SDK, an optional part of bobina\n→ {INSTALL}",
                   problem="E101") from None  # fmt: skip
    idle = [f for f, on in (("--quiet", args.quiet), ("--verbose", args.verbose), ("--debug", args.debug),
                            ("--problems", args.problems)) if on]  # fmt: skip
    if idle:  # the tools always return the problems, as JSON
        print(f"note: {', '.join(idle)} does nothing in bobina mcp: its tools return every problem as JSON",
              file=sys.stderr)  # fmt: skip
    if sys.stdin is not None and sys.stdin.isatty():
        print("bobina mcp: an MCP server on stdin/stdout, started by an agent (claude mcp add bobina -- bobina mcp);"
              " Ctrl-C stops it", file=sys.stderr)  # fmt: skip
    try:
        server.run("stdio")
    except KeyboardInterrupt:
        pass
    return OK
