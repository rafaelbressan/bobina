"""bobina mcp: a Model Context Protocol server (stdio) whose tools are the commands of the CLI.

Each tool runs the CLI in a child process (`python -m bobina … --json`) and returns what it wrote: the same JSON
(docs/schemas/), the same problem codes and the same exit code, with the command line it ran. A child process:
- keeps stdout clean (here it is the protocol channel) and holds no state between calls (the CLI is not
  thread-safe, docs/CLI.md "Two commands at the same time");
- never reaches the user's terminal: no stdin, BOBINA_NONINTERACTIVE=1 and a session of its own;
- has the CLI's safety as it is: sandboxed templates, no network images without allow_net, the size limits;
- can be stopped with everything it started (its process group): on a timeout, and when the client cancels the
  call. A stopped print may be partly on paper, and the result says so.
print without confirm: true is a dry run (--dry-run): nothing is sent to the printer.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Annotated

from .cli.common import LEFT_OUT, OK, USAGE, Fail
from .datasource import NAME_OK
from .library import NAME_RE, LibraryError, check_name

INSTALL = "uv tool install 'bobina[mcp]'  (or: pip install 'bobina[mcp]')"
TIMEOUT = 300  # seconds for any command, a print too: a stuck printer is reported, not waited on
GRACE = 5  # seconds between Ctrl-C (bobina records an interrupted job in its history) and a kill
IMAGE_MAX_DOTS = 8000  # taller images are refused by most agent clients: the path is given instead
IMAGE_MAX_BYTES = 4_000_000  # one image
IMAGES_MAX = 10  # images attached to one preview result (every path is listed)
IMAGES_MAX_BYTES = 8_000_000  # all of them
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp"}  # fmt: skip
ROLL_LENGTH = re.compile(r"\d+(?:[.,]\d+)?\s*(?:mm|cm|m)")  # the unit is required
PAPER_WARNING = "part of the job may already be on paper: check the paper and bobina history before printing again"

INSTRUCTIONS = """\
bobina prints Markdown (.bob.md: receipts, lists, labels, QR and payment codes) on thermal roll printers.
Look before printing: check (paper length and problems) and preview (the exact image), with the printer the job
will go to. print sends to the printer only with confirm: true, after the user agreed; without it, it is a dry
run. Every result starts with the bobina command line it ran and its exit code: 0 ok, 9 printed without a
payment code (Q111), others are errors. A print stopped before it finished may be partly on paper: never print
again before checking. A problem code (E401, Q111…) is explained by help with that code. Document format: help
topic format."""


@dataclass
class Run:
    argv: list[str]
    code: int | None  # None: stopped before it finished
    stdout: str
    stderr: str
    stopped: str = ""  # why it was stopped


def _signal(proc, sig) -> None:
    """sig to the child and everything it started (its own session = its own process group)."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, sig)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


async def _stop(proc) -> None:
    """Ctrl-C first (a print records 'interrupted' and spends its seq numbers if bytes went out), then a kill."""
    import anyio

    _signal(proc, signal.SIGINT if os.name == "posix" else signal.SIGTERM)
    with anyio.move_on_after(GRACE):
        await proc.wait()
    if os.name == "posix":
        _signal(proc, signal.SIGKILL)  # a command printer's ssh, even when bobina itself already ended
    else:
        proc.kill()
    await proc.wait()


async def run(argv: list[str], stdin: str | None = None, timeout: float = TIMEOUT) -> Run:
    """bobina ARGV in a child process; problems on stderr as JSON (--problems json). Stopped with its process
    group after `timeout` seconds or when the tool call is cancelled."""
    import anyio

    env = {**os.environ, "BOBINA_NONINTERACTIVE": "1", "BOBINA_PROBLEMS": "json", "NO_COLOR": "1",
           "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}  # fmt: skip
    proc = await anyio.open_process(
        [sys.executable, "-m", "bobina", *argv], stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=os.name == "posix",
    )  # fmt: skip
    out, err = bytearray(), bytearray()

    async def drain(stream, buf):
        async for chunk in stream:
            buf.extend(chunk)

    async def feed():
        try:
            await proc.stdin.send(stdin.encode("utf-8"))
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            pass  # the child stopped reading (an error before the document): its answer says why
        finally:
            await proc.stdin.aclose()

    stopped = ""
    try:
        with anyio.fail_after(timeout):
            async with anyio.create_task_group() as tg:
                tg.start_soon(drain, proc.stdout, out)
                tg.start_soon(drain, proc.stderr, err)
                if stdin is not None:
                    tg.start_soon(feed)
            await proc.wait()
    except TimeoutError:
        stopped = f"stopped after {timeout:g} s: bobina {argv[0]} did not finish"
        with anyio.CancelScope(shield=True):
            await _stop(proc)
    except anyio.get_cancelled_exc_class():  # the client cancelled the call: nothing may keep printing
        with anyio.CancelScope(shield=True):
            await _stop(proc)
        print(f"bobina mcp: the call was cancelled; bobina {' '.join(argv)} was stopped"
              + (f"; {PAPER_WARNING}" if argv[0] == "print" else ""), file=sys.stderr)  # fmt: skip
        raise
    finally:
        with anyio.CancelScope(shield=True):
            await proc.aclose()  # its pipes, whatever happened
    decode = lambda b: bytes(b).decode("utf-8", "replace")  # noqa: E731
    return Run(argv, None if stopped else proc.returncode, decode(out), decode(err), stopped)


def _meaning(code: int) -> str:
    from .cli.args import EXIT_CODES

    return EXIT_CODES.get(code, "")


def result(r: Run, *extra):
    """The run as a tool result: the command line and exit code, stdout (the CLI's JSON), stderr (problems as
    JSON, notes). An error unless the exit is 0 or 9 (the job went out without a payment code: docs/CLI.md)."""
    from mcp.types import CallToolResult, TextContent

    if r.code is None:  # never read as a usage error: the agent must not simply call again
        status = f"no exit code, {r.stopped}" + (f"; {PAPER_WARNING}" if r.argv[0] == "print" else "")
    else:
        meaning = _meaning(r.code)
        status = f"exit {r.code}" + (f" ({meaning})" if meaning else "")
    texts = [f"bobina {' '.join(r.argv)}\n{status}", r.stdout.strip(),
             "stderr:\n" + r.stderr.strip() if r.stderr.strip() else ""]  # fmt: skip
    content = [TextContent(type="text", text=t) for t in texts if t]
    return CallToolResult(content=content + [x for x in extra if x], is_error=r.code not in (OK, LEFT_OUT))


def _error(message: str):
    from mcp.server.mcpserver.exceptions import ToolError

    return ToolError(message)


def _name(value: str, what: str) -> str:
    if not NAME_RE.fullmatch(value):
        raise _error(f"not a {what}: {value!r} (letters, digits, '.', '_' and '-')")
    return value


def _target(text: str | None, path: str | None) -> tuple[str, str | None]:
    """(the CLI target, stdin): text goes in on stdin (-), never on the command line."""
    if (text is None) == (path is None):
        raise _error("give the document as text or as path (one of them)")
    if text is not None:
        return "-", text
    p = Path(path).expanduser()
    if path.startswith("@") and not p.is_file():  # a saved label (bobina library); a file named @x is that file
        try:
            check_name(path[1:])
        except LibraryError as e:
            raise _error(f"{e} (E206)") from None
        return path, None
    if not p.is_file():  # the CLI would print a name that is not a file as text
        raise _error(f"file not found: {path} (E201; relative paths start at {os.getcwd()})")
    return str(p if p.is_absolute() else Path.cwd() / p), None  # absolute: never read as an option or @label


def _sets(fields: dict | None) -> list[str]:
    """--set=KEY=VALUE, as the CLI reads it (KEY is everything before the first '=')."""
    out = []
    for k, v in (fields or {}).items():
        if not k.strip() or "=" in k:
            raise _error(f"a field name must not be empty or contain '=': {k!r} (E304)")
        out.append(f"--set={k}={v}")
    return out


def _data(spec: str) -> str:
    """--data=[NAME=]FILE. The CLI reads 'NAME=FILE' as a named source, so a path with '=' is ambiguous unless it
    starts with an explicit NAME= (letters, digits, _)."""
    name, sep, path = spec.partition("=")
    if sep and not (NAME_OK.fullmatch(name) and path):
        raise _error(f"data {spec!r}: a path with '=' reads as NAME=FILE; rename the file, or write NAME=FILE"
                     " (NAME: letters, digits, _) (E301)")  # fmt: skip
    return f"--data={spec}"


class Server:
    """The tools. The defaults given to bobina mcp (--printer, --profile, --allow, --strict) apply to the document
    tools (check, preview, print) and --printer also to status and paper."""

    def __init__(self, printer=None, profile=None, allow: list[str] | None = None, strict: bool = False):
        self.printer, self.profile, self.allow, self.strict = printer, profile, list(allow or []), strict
        self.previews: Path | None = None  # a temporary folder, made by the first preview without output
        self._lock = threading.Lock()
        self.n = count(1)

    def preview_dir(self) -> Path:
        with self._lock:  # made once, whatever thread or task asks first
            if self.previews is None:
                self.previews = Path(tempfile.mkdtemp(prefix="bobina-mcp-"))
            return self.previews

    def cleanup(self) -> None:
        """The temporary previews go with the server (an output the caller named stays)."""
        with self._lock:
            if self.previews is not None:
                shutil.rmtree(self.previews, ignore_errors=True)
                self.previews = None

    def options(self, set_=None, data=None, profile=None, allow=None, allow_net=False, strict=False, printer=None):
        """Tool arguments as CLI options, each one token (--set=K=V): a value never reads as another option."""
        a = _sets(set_) + ([_data(data)] if data else [])
        for flag, value in (("--printer", printer or self.printer), ("--profile", profile or self.profile)):
            if value:  # a name or a Bluetooth address; one token, so it never reads as an option
                a.append(f"{flag}={value}")
        if allow or self.allow:
            a.append("--allow=" + ",".join([*self.allow, *(allow or [])]))
        return a + (["--allow-net"] if allow_net else []) + (["--strict"] if strict or self.strict else [])

    async def check(self, text=None, path=None, **opts):
        target, stdin = _target(text, path)
        return result(await run(["check", target, "--json", *self.options(**opts)], stdin))

    async def preview(self, text=None, path=None, output=None, **opts):
        target, stdin = _target(text, path)
        out = output or str(self.preview_dir() / f"preview-{next(self.n)}.png")
        r = await run(["preview", target, f"--output={out}", "--json", *self.options(**opts)], stdin)
        try:
            files = json.loads(r.stdout).get("files") or []
        except (ValueError, AttributeError):
            files = []
        return result(r, *_images(files))

    async def print(self, text=None, path=None, confirm=False, copies=1, **opts):
        target, stdin = _target(text, path)
        mode = ["--yes"] if confirm is True else ["--dry-run"]  # only a real true prints
        copies_ = [f"--copies={copies}"] if copies != 1 else []
        argv = ["print", target, *mode, "--json", *copies_, *self.options(**opts)]
        r = await run(argv, stdin, TIMEOUT)
        if confirm is not True and r.code in (OK, LEFT_OUT):
            from mcp.types import TextContent

            note = "dry run: nothing was printed. Show the user what will print (preview), then call print with" \
                   " confirm: true once they agree."  # fmt: skip
            return result(r, TextContent(type="text", text=note))
        return result(r)

    async def template_list(self):
        return result(await run(["template", "list", "--json"]))

    async def template_show(self, name):
        from mcp.types import TextContent

        from .cli.library import starter_from_fields

        name = _name(name, "template name")
        r = await run(["template", "show", name, "--json"])
        try:
            fields = json.loads(r.stdout) if r.code == OK else None
        except ValueError:
            fields = None
        if not isinstance(fields, dict):
            return result(r)
        doc = f"the template as a document to fill (bobina template new {name}):\n\n{starter_from_fields(name, fields)}"
        return result(r, TextContent(type="text", text=doc))

    async def help(self, topic=None, name=None):
        words = [_name(w, "help topic") for w in (topic, name) if w]
        return result(await run(["help", *words, "--json"]))

    async def status(self, printer=None):
        p = printer or self.printer
        return result(await run(["status", "--json", *([f"--printer={p}"] if p else [])]))

    async def paper(self, printer=None):
        p = printer or self.printer
        return result(await run(["paper", "--json", *([f"--printer={p}"] if p else [])]))

    async def paper_new(self, length, printer=None):
        """A roll the user loaded, with the length they said: never a default (bobina paper new without LENGTH
        would take the remembered roll), never a bare number (30: metres or centimetres?)."""
        if not isinstance(length, str) or not ROLL_LENGTH.fullmatch(length.strip()):
            raise _error(f"length {length!r}: the length the user gave, with its unit: 30m, 1500cm or 400mm (E101)")
        p = printer or self.printer
        argv = ["paper", "new", length.strip(), "--json", *([f"--printer={p}"] if p else [])]
        return result(await run(argv))


def _images(paths: list[str]) -> list:
    """The preview files as image content, as many as a client takes (IMAGES_MAX, IMAGES_MAX_BYTES); every path
    is listed, so an agent never approves twenty labels after seeing one."""
    import base64

    from mcp.types import ImageContent, TextContent

    if not paths:
        return []
    attached, skipped, total = [], [], 0
    for path in paths:
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
                why = f"it could not be read back ({e})"
            else:
                if height > IMAGE_MAX_DOTS or size > IMAGE_MAX_BYTES:
                    why = f"{height} dots tall and {size // 1024} KB, too large to attach"
                elif len(attached) >= IMAGES_MAX or total + size > IMAGES_MAX_BYTES:
                    why = f"over {IMAGES_MAX} images or {IMAGES_MAX_BYTES // 1_000_000} MB in one result"
        if why:
            skipped.append(f"{p} ({why})")
            continue
        total += size
        attached.append(ImageContent(type="image", data=base64.b64encode(p.read_bytes()).decode(), mime_type=kind))
    lines = [f"{len(paths)} file(s) written, {len(attached)} attached as images in this order:", *paths]
    if skipped:
        lines += ["", "not attached (open them before approving a print):", *skipped]
    return [TextContent(type="text", text="\n".join(lines)), *attached]


def build(printer=None, profile=None, allow: list[str] | None = None, strict: bool = False, tools=None):
    """The MCP server with bobina's tools (tests call it without stdio). The argument types are built here, not
    at import: pydantic comes with the MCP SDK, an extra, and bobina mcp says how to install it when missing.
    tools: a Server to use (serve keeps it to remove its temporary previews at the end)."""
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations
    from pydantic import Field

    from . import __version__

    s = tools or Server(printer, profile, allow, strict)
    mcp = MCPServer("bobina", version=__version__, instructions=INSTRUCTIONS)
    reads = ToolAnnotations(read_only_hint=True, open_world_hint=False)
    TextArg = Annotated[str | None, Field(description="the document as text (.bob.md Markdown); or give path")]
    PathArg = Annotated[
        str | None, Field(description="a .bob.md, image or PDF file (absolute path), or @NAME for a saved label")
    ]
    SetArg = Annotated[dict[str, str] | None, Field(description="template fields, printed literally (--set KEY=VALUE)")]
    DataArg = Annotated[
        str | None, Field(description="a CSV, TSV, JSON or .xlsx file: one label per row (--data [NAME=]FILE)")
    ]
    ProfileArg = Annotated[str | None, Field(description="printer profile, e.g. mtp-ii-58 (--profile)")]
    AllowArg = Annotated[list[str] | None, Field(description="problem codes to silence, e.g. ['F301'] (--allow)")]
    NetArg = Annotated[bool, Field(description="fetch https images from public hosts (--allow-net)")]
    StrictArg = Annotated[bool, Field(description="warnings stop the job, exit 3 (--strict)")]
    PrinterArg = Annotated[
        str | None,
        Field(description="a printer name from bobina printer list (--printer); check and preview with the printer"
                          " print will use: its profile sets the paper width"),
    ]  # fmt: skip

    @mcp.tool(annotations=reads)
    async def check(
        text: TextArg = None, path: PathArg = None, set: SetArg = None, data: DataArg = None,
        printer: PrinterArg = None, profile: ProfileArg = None, allow: AllowArg = None, allow_net: NetArg = False,
        strict: StrictArg = False,
    ):  # fmt: skip
        """Lint a document without printing (bobina check --json): paper length, labels, line breaks, glyphs,
        codes, and every problem with its code and a suggestion. Nothing is printed or saved."""
        return await s.check(text, path, set_=set, data=data, printer=printer, profile=profile, allow=allow,
                             allow_net=allow_net, strict=strict)  # fmt: skip

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False))
    async def preview(
        text: TextArg = None, path: PathArg = None, set: SetArg = None, data: DataArg = None,
        printer: PrinterArg = None, profile: ProfileArg = None, allow: AllowArg = None, allow_net: NetArg = False,
        output: Annotated[
            str | None,
            Field(description="where to save it (.png default, .pdf, .jpg…; {n} {column}: one file per label);"
                              " default: a temporary file"),
        ] = None,
    ):  # fmt: skip
        """The exact dots that will be printed (bobina preview --json), returned as images (every label or page,
        up to a limit) with the path of every file written and the problems. Nothing is printed."""
        return await s.preview(text, path, output, set_=set, data=data, printer=printer, profile=profile,
                               allow=allow, allow_net=allow_net)  # fmt: skip

    @mcp.tool(name="print", annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                                        idempotent_hint=False, open_world_hint=True))  # fmt: skip
    async def print_(
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
        (--dry-run): the same figures and problems, nothing sent. Exit 9: printed without a payment code (Q111).
        A print stopped before it finished (no exit code) may be partly on paper: do not print it again before
        the user checked the paper and bobina history."""
        return await s.print(text, path, confirm, copies, set_=set, data=data, printer=printer, profile=profile,
                             allow=allow, allow_net=allow_net, strict=strict)  # fmt: skip

    @mcp.tool(annotations=reads)
    async def template_list():
        """The ready-made documents (bobina template list --json): receipt, label, todo, shop tags…"""
        return await s.template_list()

    @mcp.tool(annotations=reads)
    async def template_show(name: Annotated[str, Field(description="a name from template_list, e.g. receipt")]):
        """A template's fields (bobina template show --json) and the template as a document to fill in."""
        return await s.template_show(name)

    @mcp.tool(name="help", annotations=reads)
    async def help_(
        topic: Annotated[
            str | None,
            Field(description="commands, format, data, pay, nudges, aliases, a command, or a problem code (Q111);"
                              " none: the whole CLI for programs"),
        ] = None,
        name: Annotated[str | None, Field(description="with topic pay: one scheme, e.g. pix")] = None,
    ):  # fmt: skip
        """bobina help --json: the document format, a problem code and what to do, a payment scheme, a command."""
        return await s.help(topic, name)

    @mcp.tool(annotations=reads)
    async def status(printer: PrinterArg = None):
        """The printer's state (bobina status --json): online, paper, cover, error. Bluetooth printers only."""
        return await s.status(printer)

    @mcp.tool(annotations=reads)
    async def paper(printer: PrinterArg = None):
        """Paper left on the roll (bobina paper --json): the roll length minus what bobina printed."""
        return await s.paper(printer)

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True,
                                          open_world_hint=False))  # fmt: skip
    async def paper_new(
        length: Annotated[str, Field(description="the roll length the user gave, with its unit: 30m, 1500cm")],
        printer: PrinterArg = None,
    ):
        """Record a new roll (bobina paper new LENGTH --json): the paper count starts again from it. Only when the
        user says they loaded a roll and says its length: never guess it or use a usual size; ask instead."""
        return await s.paper_new(length, printer)

    return mcp


def serve(args) -> int:
    """bobina mcp: the server on stdin/stdout until the client closes it."""
    import atexit

    allow = [c.strip() for v in (getattr(args, "allow", None) or []) for c in v.split(",") if c.strip()]
    tools = Server(getattr(args, "printer", None), getattr(args, "profile", None), allow, bool(args.strict))
    try:
        server = build(tools=tools)
    except ImportError as e:
        if not (e.name or "").startswith(("mcp", "pydantic", "anyio")):
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
    atexit.register(tools.cleanup)  # also when the process ends some other way
    try:
        server.run("stdio")
    except KeyboardInterrupt:
        pass
    finally:
        tools.cleanup()
    return OK
