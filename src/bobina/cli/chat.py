"""bobina chat (talk to an AI in the terminal, its answers print on the roll) and bobina ai (which AI).

The conversation logic (Session) talks to the person through a small UI object: PlainUI (lines on stdin and stdout:
pipes, tests, agents, or no prompt_toolkit) or the full terminal screen of cli/chat_tui.py (prompt_toolkit, the
extra bobina[ai]). Everything the chat decides is in Session, so it is tested without a terminal."""

from __future__ import annotations

import sys

from .. import ai, config, engine
from .. import profile as profiles
from ..chat import DEFAULT_LIMIT_MM, LAYOUTS, STYLES, Conversation, Ticket
from .common import (
    OK,
    USAGE,
    Fail,
    counts_paper,
    do_send,
    err,
    marks_setting,
    plural,
    print_json,
    printer_overrides,
)

COMMANDS = {  # slash command -> what it does (completion and /help)
    "/tickets": "one ticket per answer, fed to the tear bar to tear off",
    "/strip": "one strip, a dashed line between answers (the default)",
    "/manual": "print only when you type p",
    "/auto": "print every answer right away (the default)",
    "/questions on": "print your messages too, on the right",
    "/questions off": "print only the answers",
    "/help": "this list",
    "/quit": "end the chat (also Ctrl-D)",
}


class Cancelled(Exception):
    """The person stopped the AI's answer (Esc or Ctrl-C while it thinks)."""


def register(sub, cmd) -> None:
    """The parsers of chat and ai (cmd: args._cmd)."""
    p = cmd(
        sub,
        "chat",
        "talk to an AI; its answers print",
        "a conversation in the terminal; each answer of the AI also prints on the roll, short (about 10 cm at"
        " most, the AI is told so on every turn). The AI: bobina ai (asked on the first chat)",
        [
            "bobina chat",
            "bobina chat --manual",
            "bobina chat --questions --limit 6cm",
            "bobina chat --layout tickets --style bubbles",
            "bobina chat --ai ollama --model llama3.2",
            "bobina chat --dry-run",
        ],
        cmd_chat,
    )
    p.add_argument("--ai", metavar="NAME", help="the AI for this chat only (default: bobina ai use NAME)")
    p.add_argument("--model", metavar="MODEL", help="the AI's model for this chat (default: the saved one or its own)")
    p.add_argument(
        "--limit", metavar="LENGTH", help="paper per answer at most (default 10cm; chat_limit in config.toml)"
    )
    p.add_argument(
        "--questions", action="store_true", help="print your messages too, on the right (default: only the answers)"
    )
    p.add_argument(
        "--layout",
        choices=LAYOUTS,
        help="strip: one strip, the AI on top once, a dashed line between answers (default); tickets: one ticket per"
        " answer with the AI and time on top, fed to the tear bar (chat_layout in config.toml)",
    )
    p.add_argument(
        "--style",
        choices=STYLES,
        help="how the two speakers look on paper: plain (default), bubbles, boxes or labels (icons and names;"
        " chat_style in config.toml)",
    )
    p.add_argument("--manual", action="store_true", help="print an answer only when you type p")
    p = cmd(
        sub,
        "ai",
        "choose the AI of bobina chat",
        "the AIs this machine has, best first: programs already logged in (Claude Code, Codex, Gemini CLI), a local"
        " Ollama, API keys (ANTHROPIC_API_KEY, OPENAI_API_KEY); the choice is saved in config.toml",
        ["bobina ai list", "bobina ai use claude", "bobina ai use ollama --model llama3.2", "bobina ai list --json"],
        cmd_ai,
    )
    p.add_argument("action", nargs="?", default="list", choices=["list", "use"])
    p.add_argument("name", nargs="?", choices=list(ai.ORDER), metavar="NAME", help="use: " + ", ".join(ai.ORDER))
    p.add_argument("--model", metavar="MODEL", help="use: the model to save with it (default: the AI's own)")


# ----------------------------------------------------------------------------------------------------- bobina ai


def cmd_ai(args):
    cfg = config.load()
    if args.action == "use":
        if not args.name:
            raise Fail(USAGE, "bobina ai use NAME: " + ", ".join(ai.ORDER), problem="E101")
        found = {f.name: f for f in ai.detect()}[args.name]
        try:
            config.set_value("ai", args.name)
            config.set_value("ai_model", args.model or "")
        except OSError as e:
            raise Fail(USAGE, f"cannot write {config.path()}: {e.strerror or e}", problem="E209") from None
        model = f" (model {args.model})" if args.model else ""
        if args.json:
            print_json({"schema": "bobina.ai/1", "in_use": args.name, "model": args.model or None,
                        "found": [found.as_dict()]}, indent=2, ensure_ascii=False)  # fmt: skip
            return OK
        print(f"bobina chat now talks to {found.label}{model}: saved in {config.path()}")
        if not found.ready:
            err(f"note: {found.label} is not ready on this machine: {found.needs}")
        return OK
    found = ai.detect()
    current, model = cfg.get("ai"), cfg.get("ai_model") or None
    if args.json:
        print_json({"schema": "bobina.ai/1", "in_use": current, "model": model,
                    "found": [f.as_dict() for f in found]}, indent=2, ensure_ascii=False)  # fmt: skip
        return OK
    have = [f for f in found if f.available]
    if have:
        print("AIs on this machine (best first):")
        for f in have:
            mark = "*" if f.name == current else " "
            note = f"  · needs: {f.needs}" if not f.ready else ""
            print(f" {mark} {f.name:9s} {f.label}: {f.detail}{note}")
    else:
        print("no AI found on this machine; " + ai.none_found_hint())
    missing = [f.name for f in found if not f.available]
    if have and missing:
        print("not found: " + ", ".join(missing) + "  (bobina ai list --json says how to get each)")
    if current:
        print(
            f"bobina chat uses: {current}" + (f" (model {model})" if model else "") + "  · change: bobina ai use NAME"
        )
    elif have:
        print("choose one: bobina ai use NAME [--model MODEL] (or the first bobina chat asks)")
    return OK


# ------------------------------------------------------------------------------------------------ choosing the AI


def _choose(args, ui) -> tuple[str, str | None]:
    """The AI of this chat: --ai, else config.toml, else asked now (and saved). Never a dead end: a saved AI that is
    gone falls back to the best one found, and says so."""
    cfg = config.load()
    saved, saved_model = cfg.get("ai"), (cfg.get("ai_model") or None)
    if args.ai:
        if args.ai not in ai.BACKENDS:
            raise Fail(USAGE, f"unknown AI '{args.ai}': " + ", ".join(ai.ORDER), problem="E601")
        return args.ai, args.model or (saved_model if args.ai == saved else None)  # the saved AI keeps its model
    model = args.model or saved_model
    found = ai.detect()
    ready = [f for f in found if f.ready]
    if saved in ai.BACKENDS:
        f = next(x for x in found if x.name == saved)
        if f.ready or not ready:
            return saved, model
        err(f"note: the AI in config.toml ({saved}) is not ready here ({f.needs}); using {ready[0].name} for this chat")
        return ready[0].name, args.model
    if not ready:
        avail = [f for f in found if f.available]
        extra = "".join(f"\n  {f.name}: found, but needs: {f.needs}" for f in avail)
        raise Fail(USAGE, f"no AI found on this machine{extra}\n→ " + ai.none_found_hint().replace("\n", "\n  "),
                   problem="E601")  # fmt: skip
    pick = ui.choose_ai(ready) if len(ready) > 1 else ready[0]
    if len(ready) == 1:
        print(f"using {pick.label}, the AI found on this machine (saved; bobina ai use NAME changes it)")
    try:
        config.set_value("ai", pick.name)
    except OSError as e:
        err(f"note: the choice was not saved ({e.strerror or e})")
    return pick.name, model


def _limit(args, cfg) -> float:
    from .. import paper

    raw = args.limit or cfg.get("chat_limit")
    if raw is None:
        return DEFAULT_LIMIT_MM
    try:
        mm = paper.parse_length(str(raw), "cm")
    except ValueError as e:
        where_ = "--limit" if args.limit else "chat_limit in config.toml"
        raise Fail(USAGE, f"{where_}: {e}", problem="E304") from None
    if mm < 15:
        raise Fail(USAGE, f"{args.limit or raw}: an answer needs at least 1.5cm of paper", problem="E304")
    return mm


def _setting(args, cfg, key: str, option: str, choices: tuple, default: str) -> str:
    value = getattr(args, option) or cfg.get(key) or default
    if value not in choices:
        raise Fail(USAGE, f"{key} = {value!r} in config.toml: use {', '.join(choices)}", problem="E304")
    return value


# ---------------------------------------------------------------------------------------------------- plain lines


class PlainUI:
    """Lines on stdin and stdout: a pipe works too (its lines are echoed, so the transcript reads)."""

    def __init__(self):
        self.interactive = sys.stdin.isatty()

    def welcome(self, lines: list[str]) -> None:
        print("\n".join(lines) + "\n", flush=True)

    def read(self, session) -> str | None:
        if self.interactive:
            try:
                return input("you> ")
            except EOFError:
                return None
        line = sys.stdin.readline()
        if not line:
            return None
        print("you> " + line.rstrip("\n"), flush=True)
        return line.rstrip("\n")

    def answer(self, who: str, text: str) -> None:
        from ..chat import BOLD

        print(f"{who}:\n{BOLD.sub(lambda m: m.group(1), text)}\n", flush=True)

    def note(self, text: str) -> None:
        print(f"  {text}", flush=True)

    dim = note

    def wait(self, label: str, fn):
        """fn() with a line saying the AI is thinking (on a terminal); Ctrl-C stops it (Cancelled)."""
        if sys.stderr.isatty():
            sys.stderr.write(f"  ({label}…)\r")
            sys.stderr.flush()
        try:
            return fn()
        except KeyboardInterrupt:
            ai.cancel()
            raise Cancelled from None
        finally:
            if sys.stderr.isatty():
                sys.stderr.write(" " * (len(label) + 8) + "\r")

    def choose_ai(self, ready: list):
        if not self.interactive:
            others = ", ".join(f.name for f in ready[1:])
            print(f"using {ready[0].label}, the first AI found (also here: {others}); bobina ai use NAME changes it")
            return ready[0]
        print("Which AI should answer? (saved for next time; bobina ai use NAME changes it)")
        for i, f in enumerate(ready, 1):
            print(f"  {i}. {f.name:9s} {f.label}: {f.detail}")
        while True:
            try:
                a = input(f"number or name [1 {ready[0].name}]: ").strip().lower()
            except EOFError:
                a = ""
            if not a:
                return ready[0]
            hit = [f for i, f in enumerate(ready, 1) if a in (str(i), f.name)]
            if hit:
                return hit[0]
            print(f"  1 to {len(ready)}, or a name above")

    def status(self, session) -> None:
        pass


# -------------------------------------------------------------------------------------------------- the session


class Session:
    """The chat: what each line does, what prints, and what the person is told. UI-free."""

    def __init__(self, args, conv: Conversation, printer: str | None, pr: dict | None, ui, question_limit: int):
        self.args, self.conv, self.printer, self.pr, self.ui = args, conv, printer, pr, ui
        self.manual = bool(args.manual)
        self.questions = bool(args.questions)
        self.question_limit = question_limit
        self.last = None  # (answer, question)
        self.model = conv.ai.model

    # what the screen shows

    def who(self) -> str:
        return ai.header(self.conv.ai.vendor, self.model)

    def destination(self) -> str:
        if self.args.dry_run:
            return "nothing prints (--dry-run): the paper each answer would take is shown"
        if not self.pr:
            return "no printer configured: answers show here only (bobina printer add NAME ADDRESS)"
        return f"printer {self.printer}"

    def layout_text(self) -> str:
        return "one strip" if self.conv.layout == "strip" else "one ticket per answer"

    def mode_text(self) -> str:
        return "prints on p" if self.manual else "prints every answer"

    def welcome(self) -> list[str]:
        """The block the chat opens with: the AI, where answers go, the layout and mode, the limits, the commands."""
        a, conv = self.args, self.conv
        model = ai.model_label(self.model) if self.model else "its default model"
        limit = f"at most {conv.limit_mm / 10:g} cm of paper per answer"
        if self.questions:
            limit += f" · your messages print too ({self.question_limit} characters at most)"
        return [
            f"bobina chat · {conv.ai.label} · {model}",
            f"{self.destination()} · layout: {self.layout_text()} · {self.mode_text()}",
            limit,
            " ".join(dict.fromkeys(c.split()[0] for c in COMMANDS)) + " · p prints the last answer"
            + ("" if a.dry_run else " · Ctrl-D ends"),
        ]  # fmt: skip

    def status(self) -> str:
        conv = self.conv
        left = conv.paper_left() if conv.paper_left else None
        parts = [self.who(), self.printer or "no printer", conv.layout, "manual" if self.manual else "auto"]
        if self.questions:
            parts.append("questions printed")
        paper = f"chat {conv.used_mm / 10:.1f} cm" + (f" · roll {left / 1000:.1f} m" if left is not None else "")
        return " │ ".join([*parts, paper])

    def too_long(self, text: str) -> str:
        """Why a message cannot be sent as it is ("" when it can): printed questions have a limit too."""
        t = text.strip()
        if not self.questions or t.startswith("/") or t == "p" or len(t) <= self.question_limit:
            return ""
        return (f"too long to print: {len(t)}/{self.question_limit} characters (about 3 lines); shorten it,"
                " or /questions off")  # fmt: skip

    # the loop

    def run(self) -> int:
        self.ui.welcome(self.welcome())
        while True:
            try:
                line = self.ui.read(self)
            except KeyboardInterrupt:
                line = None
            if line is None or not self.handle(line):
                break
        self.end()
        return OK

    def handle(self, line: str) -> bool:
        """One line from the person; False ends the chat."""
        line = line.strip()
        if not line:
            return True
        if line in ("/quit", "/exit", "/q"):
            return False
        if self.command(line):
            return True
        why = self.too_long(line)
        if why:
            self.ui.note(why)
            return True
        self.turn(line)
        return True

    def command(self, line: str) -> bool:
        ui = self.ui
        if line in ("p", "/p", "/print"):
            if not self.last:
                ui.note("nothing to print yet")
            elif self.last[0].printed:
                ui.note("the last answer is already on paper")
            else:
                self.print_answer(*self.last)
            return True
        if line in ("/manual", "/auto"):
            self.manual = line == "/manual"
            ui.note("manual mode: p prints the last answer" if self.manual else "every answer prints right away")
            return True
        if line in ("/strip", "/tickets"):
            want = line[1:]
            if self.conv.layout == want:
                ui.note(f"already: {self.layout_text()}")
                return True
            if want == "tickets":
                self.close_strip()  # the strip so far goes to the tear bar before the first ticket
            self.conv.layout = want
            ui.note("one ticket per answer from now on" if want == "tickets" else "one strip from now on")
            return True
        if line.split()[0] == "/questions":
            arg = (line.split() + [""])[1]
            if arg not in ("on", "off", ""):
                ui.note("/questions on or /questions off")
                return True
            self.questions = (not self.questions) if not arg else arg == "on"
            ui.note(f"your messages print too, at most {self.question_limit} characters" if self.questions
                    else "only the answers print")  # fmt: skip
            return True
        if line in ("/help", "/?"):
            ui.note("\n  ".join(f"{c:15s} {d}" for c, d in COMMANDS.items()) + "\n  p               print the last"
                    " answer (manual mode, or after a print failed)")  # fmt: skip
            return True
        if line.startswith("/"):
            ui.note(f"unknown command {line}; /help lists them (a message never starts with /)")
            return True
        return False

    def turn(self, question: str) -> None:
        conv, ui = self.conv, self.ui
        try:
            ans = ui.wait(f"{conv.ai.vendor or conv.ai.label} is thinking", lambda: conv.ask(question))
        except Cancelled:
            ui.note("stopped: no answer (ask again, or another question)")
            return
        except ai.AIError as e:
            ui.note(f"no answer: {e}" + (f"\n  → {e.hint}" if e.hint else ""))
            return
        conv.remember(question, ans)
        self.model = ans.model or self.model
        ui.answer(self.who(), ans.text)
        if ans.rewritten and not ans.cut:
            ui.dim(f"rewritten to fit: the first answer took ~{ans.first_mm / 10:.0f} cm")
        if ans.cut:
            ui.dim(f"too long for {conv.limit_mm / 10:g} cm even after a rewrite: on paper it ends with …")
        self.last = (ans, question)
        if self.manual:
            ui.dim("not printed yet: p prints it")
            return
        self.print_answer(ans, question)

    def _problems(self, res) -> None:
        """The job's nudges (fonts, glyphs, paper), as print shows them; they never stop the chat."""
        for n in res.visible_nudges():
            hint = f" → {n.suggestion}" if n.suggestion else ""
            self.ui.note(f"{n.severity} {n.code}: {n.message}{hint}")

    def print_answer(self, ans, question: str) -> None:
        a, conv, ui = self.args, self.conv, self.ui
        res = conv.job(ans, question if self.questions else None)
        cm = res.length_mm / 10
        if a.dry_run:
            self._problems(res)
            passed = conv.count(res)
            ans.printed = True
            ui.dim(f"not printed (--dry-run) · {cm:.1f} cm · chat {conv.used_mm / 10:.1f} cm")
        elif not self.pr:
            ui.dim("not printed: no printer configured (bobina printer add NAME ADDRESS)")
            return
        else:
            if counts_paper(self.pr):
                from .. import paper

                paper.check(self.printer, res.length_mm, res.nudges)  # P101/P102: said, never in the way
            self._problems(res)
            try:
                name = do_send(a, res.data, res.profile, length_mm=res.length_mm)
            except Fail as e:
                head, _, hint = str(e).partition("\n")
                ui.note(f"not printed: {head}" + (f"\n  {hint.strip()}" if hint.strip() else "")
                        + "\n  the chat goes on; p tries this answer again")  # fmt: skip
                self._history(res, "failed", e.code, e.problems())
                return
            passed = conv.count(res)
            ans.printed = True
            self._history(res, "printed", OK, None, name)
            ui.dim(f"printed on {name} · {cm:.1f} cm · chat {conv.used_mm / 10:.1f} cm")
        if passed is not None:
            ui.note(f"this conversation has used ~{passed / 1000:.1f} m of paper")

    def close_strip(self) -> None:
        """A strip ends with the feed to the tear bar (and the tear mark, when marks are on): counted as paper."""
        conv, a = self.conv, self.args
        if not conv.strip_open:
            return
        res = conv.ticket.end_of_strip()
        if a.dry_run or not self.pr:
            conv.count(res, answer=False)
            return
        try:
            do_send(a, res.data, res.profile, check_status=False, length_mm=res.length_mm)
        except Fail as e:
            self.ui.note(f"the strip was not fed to the tear bar: {str(e).splitlines()[0]}")
            return
        passed = conv.count(res, answer=False)
        self.ui.dim(f"fed to the tear bar · {res.length_mm / 10:.1f} cm")
        if passed is not None:
            self.ui.note(f"this conversation has used ~{passed / 1000:.1f} m of paper")

    def _history(self, res, outcome: str, code: int, problems, name: str = "") -> None:
        from .. import history

        rec = history.Recorder(getattr(self.args, "argv", ["chat"]))
        rec.res, rec.printer = res, name or (self.printer or "")
        rec.finish(outcome, code, problems)

    def end(self) -> None:
        conv = self.conv
        try:
            self.close_strip()
        except KeyboardInterrupt:
            pass
        if conv.printed:
            what = "would have taken" if self.args.dry_run else "printed"
            self.ui.note(f"bye: {plural(conv.printed, 'answer')} {what} ~{conv.used_mm / 10:.1f} cm of paper")
        else:
            self.ui.note("bye")


def _ui(args):
    """The full screen when this is a terminal and prompt_toolkit is installed; plain lines otherwise."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            from .chat_tui import TerminalUI
        except ImportError:
            err("note: pip install 'bobina[ai]' for the chat screen (input box, status line, completion)")
            return PlainUI()
        return TerminalUI(color=not args.no_color)
    return PlainUI()


def paper_left_of(printer: str | None, pr: dict | None):
    """mm left on the roll of this printer, or None when unknown; never an error (a damaged or hand-edited
    paper.json, a roll without its length): the chat goes on without the number."""

    def left():
        from .. import paper

        if not (pr and printer and counts_paper(pr)):
            return None
        try:
            r = paper.get(printer)
            roll = float((r or {}).get("roll_mm") or 0)
            used = float((r or {}).get("used_mm") or 0)
        except Exception:  # noqa: BLE001 - only a number for the AI and the status line; see the docstring
            return None
        return max(0.0, roll - used) if roll > 0 else None

    return left


def cmd_chat(args):
    cfg = config.load()
    ui = _ui(args)
    name, model = _choose(args, ui)
    backend = ai.backend(name, model)
    printer, pr = config.printer(cfg, args.printer)
    try:
        prof = profiles.load(args.profile or (pr or {}).get("profile") or cfg.get("profile"))
    except KeyError as e:
        raise Fail(USAGE, str(e).strip("'\""), problem="E207") from None
    # the printer's measured tear bar and the marks setting, as print uses them
    prof = engine.apply_overrides(prof, {**printer_overrides(pr), "marks": marks_setting(args, cfg)})
    layout = _setting(args, cfg, "chat_layout", "layout", LAYOUTS, "strip")
    style = _setting(args, cfg, "chat_style", "style", STYLES, "plain")
    ticket = Ticket(prof, style=style)
    try:
        qlimit = int(cfg.get("chat_question_limit") or ticket.question_chars())
    except (TypeError, ValueError):
        raise Fail(USAGE, "chat_question_limit in config.toml: a number of characters", problem="E304") from None
    conv = Conversation(backend, ticket, limit_mm=_limit(args, cfg), paper_left=paper_left_of(printer, pr),
                        layout=layout)  # fmt: skip
    return Session(args, conv, printer if pr else None, pr, ui, qlimit).run()
