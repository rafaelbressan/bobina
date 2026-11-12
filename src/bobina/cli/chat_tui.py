"""The chat screen of bobina chat on a terminal (prompt_toolkit).

Inline, like Claude Code: the terminal keeps its scrollback; messages scroll above a framed input box pinned under
the last message (at the bottom once the screen fills), with a status line under it. Only how things look and how
keys work live here; what the chat does is cli/chat.py (Session), tested without a terminal."""

from __future__ import annotations

import os
import shutil
import sys
import textwrap
import threading
import time

from prompt_toolkit import print_formatted_text
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.defaults import load_key_bindings
from prompt_toolkit.layout import Float, FloatContainer, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.output.color_depth import ColorDepth
from prompt_toolkit.styles import Style
from prompt_toolkit.validation import ValidationError, Validator

from .. import ai
from ..chat import BOLD
from .chat import COMMANDS, Cancelled, PlainUI

STYLE = Style.from_dict({
    "frame": "#5f87af",
    "title": "bold",
    "you": "bold #00afaf",
    "you-text": "#87d7d7",
    "ai": "bold #d787ff",
    "dim": "#808080",
    "note": "#d7af5f",
    "counter": "#808080",
    "over": "bold #ff5f5f",
    "bottom-toolbar": "noreverse",
    "bottom-toolbar.text": "#808080",
    "validation-toolbar": "bg:#5f0000 #ffffff",
})  # fmt: skip
SPINNER = "◐◓◑◒"


def width() -> int:
    return max(24, min(shutil.get_terminal_size((80, 24)).columns, 120))


def rich_text(text: str, style: str = "") -> list[tuple[str, str]]:
    """**bold** as bold, the rest in `style`."""
    out, pos = [], 0
    for m in BOLD.finditer(text):
        out.append((style, text[pos : m.start()]))
        out.append((f"{style} bold".strip(), m.group(1)))
        pos = m.end()
    out.append((style, text[pos:]))
    return out


def right_aligned(text: str, cols: int) -> list[str]:
    """The person's message on the right, like on paper: wrapped first, then each line pushed right."""
    wrap = max(16, min(cols - 6, int(cols * 0.7)))
    lines = []
    for para in text.splitlines() or [""]:
        lines += textwrap.wrap(para, wrap) or [""]
    return [line.rjust(cols - 1) for line in lines]


class Commands(Completer):
    def get_completions(self, document, complete_event):
        t = document.text_before_cursor
        if not t.startswith("/"):
            return
        for cmd, what in COMMANDS.items():
            if cmd.startswith(t):
                yield Completion(cmd, start_position=-len(t), display_meta=what)


class Limit(Validator):
    def __init__(self, session):
        self.session = session

    def validate(self, document):
        why = self.session.too_long(document.text)
        if why:
            raise ValidationError(message=why, cursor_position=len(document.text))


class TerminalUI(PlainUI):
    def __init__(self, color: bool = True):
        super().__init__()
        self.color = color and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"
        self.depth = None if self.color else ColorDepth.DEPTH_1_BIT
        self.app: Application | None = None
        self.buffer: Buffer | None = None
        self.error = ""

    def out(self, parts: list[tuple[str, str]]) -> None:
        print_formatted_text(FormattedText(parts), style=STYLE, color_depth=self.depth)

    def welcome(self, lines: list[str]) -> None:
        w = min(width(), 100)
        inner = w - 4
        rows = [("class:frame", "╭─ "), ("class:title", "bobina chat"), ("class:frame", " " + "─" * (w - 16) + "╮\n")]
        for line in lines[1:]:
            for part in textwrap.wrap(line, inner) or [""]:
                rows += [("class:frame", "│ "), ("", part.ljust(inner)), ("class:frame", " │\n")]
        rows += [("class:frame", "╰" + "─" * (w - 2) + "╯")]
        self.out([("class:ai", "✦ "), ("class:title", lines[0].removeprefix("bobina chat · ")), ("", "\n")] + rows)

    def _box(self, session) -> Application:
        """The input box: a frame of 3 lines and the status line under it, drawn under the last message (pinned to
        the bottom of the terminal once messages fill it). Enter sends; a message too long to print stays, with
        the reason in red under the box."""
        if self.app is not None:
            return self.app
        buf = Buffer(completer=Commands(), complete_while_typing=True, multiline=False)
        self.buffer = buf
        keys = KeyBindings()

        @keys.add("enter", eager=True)
        def _(event):
            state = buf.complete_state
            if state and state.current_completion:  # Enter on a highlighted command takes it
                buf.apply_completion(state.current_completion)
                return
            why = session.too_long(buf.text)
            if why:
                self.error = why
                return
            self.error = ""
            event.app.exit(result=buf.text)

        @keys.add("c-c")
        def _(event):  # with text: clears it; on an empty line: ends the chat (as Ctrl-D)
            if buf.text:
                buf.reset()
                self.error = ""
            else:
                event.app.exit(exception=EOFError())

        @keys.add("c-d")
        def _(event):
            if not buf.text:
                event.app.exit(exception=EOFError())

        def top():
            return [("class:frame", "╭" + "─" * (width() - 2) + "╮")]

        def counter():
            text = buf.text.strip()
            if not session.questions or text.startswith("/"):
                return [("class:frame", " │")]
            limit = session.question_limit
            return [("class:over" if len(text) > limit else "class:counter", f" {len(text)}/{limit}"),
                    ("class:frame", " │")]  # fmt: skip

        def bottom():
            return [("class:frame", "╰" + "─" * (width() - 2) + "╯")]

        def status():
            if self.error:
                return [("class:over", " " + self.error)]
            s = session.status()
            w = width()
            return [("class:dim", " " + (s if len(s) <= w - 2 else s[: w - 3] + "…"))]

        def counter_width():
            return D.exact(sum(len(t) for _, t in counter()))

        line = VSplit([
            Window(FormattedTextControl([("class:frame", "│ "), ("class:you", "› ")]), width=4, dont_extend_width=True),
            Window(BufferControl(buffer=buf), wrap_lines=True, height=D(min=1, max=4), dont_extend_height=True),
            Window(FormattedTextControl(counter), width=counter_width, dont_extend_width=True),
        ])  # fmt: skip
        body = HSplit([
            Window(FormattedTextControl(top), height=1),
            line,
            Window(FormattedTextControl(bottom), height=1),
            Window(FormattedTextControl(status), height=1),
        ])  # fmt: skip
        root = FloatContainer(body, floats=[Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=3))])
        self.app = Application(
            layout=Layout(root, focused_element=buf), key_bindings=merge_key_bindings([load_key_bindings(), keys]),
            style=STYLE, color_depth=self.depth, full_screen=False, erase_when_done=True, mouse_support=False,
        )  # fmt: skip
        return self.app

    def read(self, session) -> str | None:
        app = self._box(session)
        self.buffer.reset()
        try:
            line = app.run()
        except EOFError:
            return None
        text = line.strip()
        if text.startswith("/say "):
            text = text[5:].strip()
        elif text.startswith("/") or text == "p":
            text = ""
        if text:
            self.user(text)
        return line

    def user(self, text: str) -> None:
        cols = width()
        rows = [("class:you", "you ‹".rjust(cols - 1) + "\n")]
        rows += [("class:you-text", line + "\n") for line in right_aligned(text, cols)]
        self.out(rows)

    def answer(self, who: str, text: str) -> None:
        cols = width() - 1
        wrapped = "\n".join(textwrap.fill(p, cols) if p.strip() else "" for p in text.split("\n"))
        self.out([("class:ai", f"✦ {who}\n"), *rich_text(wrapped), ("", "\n")])

    def note(self, text: str) -> None:
        self.out([("class:note", f"  › {text}")])

    def dim(self, text: str) -> None:
        self.out([("class:dim", f"  · {text}")])

    def wait(self, label: str, fn):
        """fn() in a thread, a spinner meanwhile; Esc or Ctrl-C stop it (Cancelled) and the chat goes on."""
        box: dict = {}

        def work():
            try:
                box["value"] = fn()
            except BaseException as e:  # noqa: BLE001 - handed to the main thread as it is
                box["error"] = e

        t = threading.Thread(target=work, daemon=True)
        t.start()
        keys = _Keys()
        i = 0
        try:
            with keys:
                while t.is_alive():
                    sys.stdout.write(f"\r{SPINNER[i % len(SPINNER)]} {label}… (Esc stops it)")
                    sys.stdout.flush()
                    i += 1
                    if keys.escape(0.1):
                        raise KeyboardInterrupt
        except KeyboardInterrupt:
            ai.cancel()
            raise Cancelled from None
        finally:
            sys.stdout.write("\r" + " " * (len(label) + 20) + "\r")
            sys.stdout.flush()
        if "error" in box:
            raise box["error"]
        return box["value"]


class _Keys:
    """Esc while the AI answers: the terminal in cbreak mode (Ctrl-C still interrupts), keys read without Enter."""

    def __enter__(self):
        self.old = None
        if os.name == "nt":
            return self
        try:
            import termios
            import tty

            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        except (ImportError, OSError, ValueError):
            self.old = None
        return self

    def __exit__(self, *exc):
        if self.old is not None:
            import termios

            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    def escape(self, timeout: float) -> bool:
        if os.name == "nt":
            import msvcrt

            time.sleep(timeout)
            while msvcrt.kbhit():
                if msvcrt.getwch() == "\x1b":
                    return True
            return False
        if self.old is None:
            time.sleep(timeout)
            return False
        import select

        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        return bool(ready) and os.read(self.fd, 1) == b"\x1b"
