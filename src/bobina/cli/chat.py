"""bobina chat (talk to an AI; its answers print on the roll) and bobina ai (which AI).

Two ways: `bobina chat` on a terminal opens the chat screen (cli/chat_tui.py) until the person leaves, and each
answer prints right away (entering the chat is the consent); `bobina chat "QUESTION"` (or the question on stdin)
asks once, writes the answer and exits, and prints only with --yes, as print does. The conversation logic (Session)
talks to the screen through a small UI object, so it is tested without a terminal (a test double stands in)."""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys

from .. import ai, config, engine
from .. import profile as profiles
from ..chat import BOLD, DEFAULT_LIMIT_MM, LAYOUTS, STYLES, Conversation, Ticket
from . import chat_theme
from .chat_theme import THEMES
from .chat_theme import WORDS as THEME_WORDS
from .common import (
    CONFIRM,
    OK,
    STDIN_MAX,
    STRICT,
    UNREACHABLE,
    USAGE,
    Fail,
    counts_paper,
    do_send,
    err,
    marks_setting,
    noninteractive,
    plural,
    print_json,
    printer_overrides,
    render_problems,
    report_nudges,
    stdin_has_data,
    strict_hits,
)

DEFAULT_STYLE = "labels-underline"  # D1: a short mark under each name (chosen 11/11)
COMMANDS = {  # slash command -> what it does (completion and /help)
    "/print": "print the last answer, if it is not on paper yet (p for short)",
    "/again": "print another copy of the last answer",
    "/manual": "print only on /print (p)",
    "/auto": "print every answer right away (the default)",
    "/tickets": "one ticket per answer, fed to the tear bar to tear off",
    "/strip": "one strip, the answers one after the other (the default)",
    "/questions on": "print your messages too, on the right",
    "/questions off": "print only the answers",
    "/say": "/say TEXT sends TEXT as it is (the letter p, or a line that starts with /)",
    "/theme": "the colours of this screen: /theme lists them, /theme NAME switches",
    "/theme dark": "light text on a dark terminal",
    "/theme light": "dark text on a light terminal",
    "/theme mono": "no colours (bold and dim stay)",
    "/theme contrast": "high contrast",
    "/help": "this list",
    "/quit": "end the chat (also Ctrl-D)",
}
LAYOUT_WORDS = {"continuous": "strip", "roll": "strip", "tira": "strip", "one": "strip", "single": "strip",
                "ticket": "tickets", "receipt": "tickets", "receipts": "tickets", "each": "tickets",
                "separate": "tickets", "cupom": "tickets", "tiquetes": "tickets"}  # fmt: skip
STYLE_WORDS = {"label": "labels", "c": "labels", "c1": "labels-ruled", "c2": "labels-underlined",
               "c3": "labels-exchange", "c4": "labels-bubble", "a": "bubbles", "bubble": "bubbles", "b": "boxes",
               "box": "boxes", "simple": "plain", "none": "plain", "ruled": "labels-ruled",
               "underlined": "labels-underlined", "exchange": "labels-exchange", "d1": "labels-underline",
               "d2": "labels-dashes", "d3": "labels-dots", "d4": "labels-outline", "d5": "labels-filled",
               "d6": "labels-hook", "outline": "labels-outline", "outlined": "labels-outline",
               "filled": "labels-filled", "hook": "labels-hook", "dots": "labels-dots"}  # fmt: skip


def _value(kind: str, valid: tuple, words: dict):
    """An option value with its synonyms and typos: the valid name, or an error that suggests one and lists all."""

    def convert(text: str) -> str:
        k = text.strip().lower().replace("_", "-")
        if k in valid:
            return k
        if k in words:
            return words[k]
        near = difflib.get_close_matches(k, [*valid, *words], n=1, cutoff=0.6)
        hint = f" (did you mean {words.get(near[0], near[0])}?)" if near else ""
        raise argparse.ArgumentTypeError(f"unknown {kind} '{text}'{hint}: {', '.join(valid)}")

    convert.__name__ = kind
    return convert


class Cancelled(Exception):
    """The person stopped the AI's answer (Esc or Ctrl-C while it thinks)."""


def register(sub, cmd) -> None:
    """The parsers of chat and ai (cmd: args._cmd)."""
    p = cmd(
        sub,
        "chat",
        "talk to an AI; its answers print",
        "on a terminal, a chat that stays open: each answer of the AI shows and prints right away (/manual: only on"
        " /print). With a QUESTION (or one on stdin): asks once, writes the answer and exits; it prints only with"
        " --yes. Answers stay short on paper (about 10 cm, the AI is told so every turn). The AI: bobina ai",
        [
            "bobina chat",
            'bobina chat "why is the sky blue?"',
            'bobina chat "why is the sky blue?" --yes',
            'echo "a haiku about paper" | bobina chat --yes --json',
            "bobina chat --manual --questions --limit 6cm",
            "bobina chat --layout tickets --style labels-ruled",
            "bobina chat --ai ollama --model llama3.2 --dry-run",
        ],
        cmd_chat,
    )
    p.add_argument("question", nargs="*", metavar="QUESTION", help="ask once and exit (prints only with --yes)")
    p.add_argument("--ai", metavar="NAME", help="the AI for this run only (default: bobina ai use NAME)")
    p.add_argument("--model", metavar="MODEL", help="the AI's model for this run (default: the saved one or its own)")
    p.add_argument(
        "--limit", metavar="LENGTH", help="paper per answer at most, with its unit: 10cm (default), 100mm, 4in"
        " (chat_limit in config.toml)"
    )  # fmt: skip
    p.add_argument(
        "--questions", action="store_true", help="print your messages too, on the right (default: only the answers;"
        " chat_questions in config.toml)"
    )  # fmt: skip
    p.add_argument(
        "--layout",
        type=_value("layout", LAYOUTS, LAYOUT_WORDS),
        choices=LAYOUTS,
        help="strip: one strip, the AI on top once, the answers one after the other (default); tickets: one ticket"
        " per answer with the AI and time on top, fed to the tear bar (chat_layout in config.toml)",
    )
    p.add_argument(
        "--style",
        type=_value("style", STYLES, STYLE_WORDS),
        choices=STYLES,
        help=f"how the two speakers look on paper (default {DEFAULT_STYLE}; chat_style in config.toml)",
    )
    p.add_argument("--name", metavar="NAME", help='your name over your messages, on paper and on screen (default'
                   ' "you"; chat_name in config.toml)')  # fmt: skip
    p.add_argument(
        "--theme",
        type=_value("theme", THEMES, THEME_WORDS),
        choices=THEMES,
        help="the chat screen's colours: dark, light, mono, contrast (default: the terminal's, else dark;"
        " chat_theme and [chat.colors] in config.toml)",
    )
    p.add_argument("--manual", action="store_true", help="the chat screen: print an answer only on /print (p)")
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
    """The AI of this chat: --ai, else config.toml, else the best one found now (asked on a terminal, and saved).
    Never a dead end: a saved AI that is gone falls back to the best one found, and says so."""
    cfg = config.load()
    saved, saved_model = cfg.get("ai"), (cfg.get("ai_model") or None)
    if args.ai:
        if args.ai not in ai.BACKENDS:
            near = difflib.get_close_matches(args.ai.lower(), ai.ORDER, n=1)
            hint = f" (did you mean {near[0]}?)" if near else ""
            raise Fail(USAGE, f"unknown AI '{args.ai}'{hint}: " + ", ".join(ai.ORDER), problem="E601")
        return args.ai, args.model or (saved_model if args.ai == saved else None)  # the saved AI keeps its model
    model = args.model or saved_model
    found = ai.detect()
    ready = [f for f in found if f.ready]
    if saved in ai.BACKENDS:
        f = next(x for x in found if x.name == saved)
        if f.ready or not ready:
            return saved, model
        err(f"note: the AI in config.toml ({saved}) is not here any more ({f.needs}); using {ready[0].name} for"
            f" this chat (bobina ai use {ready[0].name} saves it)")  # fmt: skip
        return ready[0].name, args.model
    if not ready:
        avail = [f for f in found if f.available]
        extra = "".join(f"\n  {f.name}: found, but needs: {f.needs}" for f in avail)
        raise Fail(USAGE, f"no AI found on this machine{extra}\n→ " + ai.none_found_hint().replace("\n", "\n  "),
                   problem="E601")  # fmt: skip
    pick = ui.choose_ai(ready) if (ui is not None and len(ready) > 1) else ready[0]  # one question: the best
    if ui is None or len(ready) == 1:
        others = f" (also here: {', '.join(f.name for f in ready[1:])})" if len(ready) > 1 else ""
        err(f"using {pick.label}, the first AI found{others}; saved: bobina ai use NAME changes it")
    try:
        config.set_value("ai", pick.name)
    except OSError as e:
        err(f"note: the choice was not saved ({e.strerror or e})")
    return pick.name, model


# ------------------------------------------------------------------------------------------------------ settings

MAX_LIMIT_MM = 1000.0  # more paper than this for one answer is not a chat any more


def _limit(args, cfg, roll_left: float | None) -> float:
    """--limit (or chat_limit): a length with its unit, from 1.5 cm to 1 m. Too much is capped, with a note."""
    from .. import paper

    raw = args.limit if args.limit is not None else cfg.get("chat_limit")
    if raw is None:
        mm = DEFAULT_LIMIT_MM
    else:
        where_ = f"--limit {raw}" if args.limit is not None else f"chat_limit = {raw!r} in config.toml"
        text = str(raw).strip()
        if text.startswith("-") or re.fullmatch(r"[0.,\s]+", text):
            raise Fail(USAGE, f"{where_}: a length is more than 0 (10cm)", problem="E304")
        if re.fullmatch(r"[\d.,\s/-]+", text):  # nudges, not blocks: centimetres, said
            err(f"note: {where_}: read as {text}cm; give a unit to be sure (10cm, 100mm, 4in)")
            text += "cm"
        try:
            mm = paper.parse_length(text, None)
        except ValueError as e:
            raise Fail(USAGE, f"{where_}: {e}", problem="E304") from None
        if mm < 15:
            raise Fail(USAGE, f"{where_}: an answer needs at least 1.5cm of paper", problem="E304")
        if mm > MAX_LIMIT_MM:
            err(f"note: {where_} is more than 1 m of paper per answer: capped at 1m")
            mm = MAX_LIMIT_MM
    if roll_left is not None and mm > roll_left:
        err(f"note: the roll has ~{roll_left / 10:.0f} cm left, less than one answer may take: answers print until"
            " it runs out (bobina paper new LENGTH after loading a new roll)")  # fmt: skip
    return mm


def _setting(args, cfg, key: str, option: str, choices: tuple, default: str) -> str:
    value = getattr(args, option) or cfg.get(key) or default
    if value not in choices:
        raise Fail(USAGE, f"{key} = {value!r} in config.toml: use {', '.join(choices)}", problem="E304")
    return value


# -------------------------------------------------------------------------------------------------- the session


class Session:
    """The chat: what each line does, what prints, and what the person is told. UI-free."""

    def __init__(self, args, conv: Conversation, printer: str | None, pr: dict | None, ui, question_limit: int,
                 questions: bool = False):  # fmt: skip
        self.args, self.conv, self.printer, self.pr, self.ui = args, conv, printer, pr, ui
        self.manual = bool(args.manual)
        self.questions = bool(questions or args.questions)
        self.question_limit = question_limit
        self.last = None  # (answer, question)
        self.model = conv.ai.model
        self.counts = bool(pr and counts_paper(pr)) and not args.dry_run  # a roll to count

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
        if self.args.dry_run or not self.pr:
            return "nothing prints"
        return "prints on /print (p)" if self.manual else "each answer prints right away (/manual: only on p)"

    def welcome(self) -> list[str]:
        """The block the chat opens with: the AI, where answers go, the layout and mode, the limits, the commands."""
        a, conv = self.args, self.conv
        model = ai.model_label(self.model) if self.model else "its default model"
        limit = f"at most {conv.limit_mm / 10:g} cm of paper per answer"
        if self.questions:
            limit += f" · your messages print too ({self.question_limit} characters at most)"
        roll = []
        if self.counts:
            left = self.roll_left()
            unknown = "roll: its length is unknown; set it with bobina paper new 30m (or --diameter 40mm)"
            roll = [f"roll: {left / 1000:.1f} m left" if left is not None else unknown]
        return [
            f"bobina chat · {conv.ai.label} · {model}",
            f"{self.destination()} · layout: {self.layout_text()} · {self.mode_text()}",
            limit,
            *roll,
            " ".join(dict.fromkeys(c.split()[0] for c in COMMANDS)) + " · p = /print"
            + ("" if a.dry_run else " · Ctrl-D ends"),
        ]  # fmt: skip

    def roll_left(self) -> float | None:
        return self.conv.paper_left() if self.conv.paper_left else None

    def status(self) -> str:
        conv = self.conv
        parts = [self.who(), self.printer or "no printer", conv.layout, "manual" if self.manual else "auto"]
        if self.args.dry_run:
            parts[1] = f"{self.printer or 'no printer'} (dry run)"
        if self.questions:
            parts.append("questions printed")
        parts.append(f"chat {conv.used_mm / 10:.1f} cm")
        if self.counts:  # a file printer has no roll to count
            left = self.roll_left()
            parts.append(f"roll {left / 1000:.1f} m left" if left is not None else "roll ?")
        return " │ ".join(parts)

    def too_long(self, text: str) -> str:
        """Why a message cannot be sent as it is ("" when it can): printed questions have a limit too."""
        t = text.strip()
        if t.startswith("/say "):
            t = t[5:].strip()
        elif t.startswith("/") or t == "p":
            return ""
        if not self.questions or len(t) <= self.question_limit:
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
        if line == "/say" or line.startswith("/say "):  # the text as it is: "p", or a line that starts with /
            line = line[4:].strip()
            if not line:
                self.ui.note("/say TEXT sends TEXT to the AI as it is (the letter p, or a line that starts with /)")
                return True
        elif self.command(line):
            return True
        why = self.too_long(line)
        if why:
            self.ui.note(why)
            return True
        self.turn(line)
        return True

    def command(self, line: str) -> bool:
        ui = self.ui
        words = line.split()
        if line in ("p", "/print", "/p"):
            if not self.last:
                ui.note("nothing to print yet")
            elif self.last[0].printed:
                ui.note(f"already printed (~{self.last[0].printed_cm:.1f} cm); /again prints another copy")
            else:
                self.print_answer(*self.last)
            return True
        if line == "/again":
            if not self.last:
                ui.note("nothing to print yet")
            else:
                self.print_answer(*self.last)
            return True
        if line in ("/manual", "/auto"):
            self.manual = line == "/manual"
            ui.note("manual mode: p (or /print) prints the last answer" if self.manual
                    else "every answer prints right away")  # fmt: skip
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
        if words[0] == "/questions":
            arg = (words + [""])[1]
            if arg not in ("on", "off", ""):
                ui.note("/questions on or /questions off")
                return True
            self.questions = (not self.questions) if not arg else arg == "on"
            ui.note(f"your messages print too, at most {self.question_limit} characters" if self.questions
                    else "only the answers print")  # fmt: skip
            return True
        if words[0] == "/theme":
            self.theme(words[1] if len(words) > 1 else "")
            return True
        if line in ("/help", "/?"):
            ui.note("\n  ".join(f"{c:15s} {d}" for c, d in COMMANDS.items()))
            return True
        if line.startswith("/"):
            ui.note(f"unknown command {words[0]}; /help lists them (/say TEXT sends a line that starts with /)")
            return True
        return False

    def theme(self, wanted: str) -> None:
        """/theme: the themes, the one in use marked; /theme NAME: switch (one's own [chat.colors] stay on top)."""
        current = getattr(getattr(self.ui, "theme", None), "name", "")
        if not wanted:
            self.ui.note("themes: " + ", ".join(f"{t} (in use)" if t == current else t for t in THEMES)
                         + " · /theme NAME switches; chat_theme in config.toml keeps one")  # fmt: skip
            return
        name = chat_theme.name_of(wanted)
        if not name:
            self.ui.note(f"no theme '{wanted}': {', '.join(THEMES)}")
            return
        theme = chat_theme.pick(name, config.load())
        self.ui.set_theme(theme)
        for n in theme.notes:
            self.ui.note(n)
        no_color = "" if theme.color or name == "mono" else " (NO_COLOR is set: no colours)"
        self.ui.note(f"theme {name}{no_color}")

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

    def _problems(self, res, outcome: str) -> bool:
        """The job's nudges (fonts, glyphs, the roll), in the format of every command (render_problems); -q keeps
        only warnings. True when --strict stops this print."""
        shown = list(res.visible_nudges())
        strict = strict_hits(shown, self.args)
        if self.args.quiet and not strict:
            shown = [n for n in shown if n.severity in ("warning", "error")]
        for line in render_problems(shown, "not printed (--strict)" if strict else outcome):
            self.ui.note(line)
        return strict

    def print_answer(self, ans, question: str) -> None:
        a, conv, ui = self.args, self.conv, self.ui
        res = conv.job(ans, question if self.questions else None)
        cm = res.length_mm / 10
        if a.dry_run:
            self._problems(res, "nothing printed (dry run)")
            passed = conv.count(res)
            ans.printed, ans.printed_cm = True, cm
            ui.dim(f"not printed (--dry-run) · {cm:.1f} cm · chat {conv.used_mm / 10:.1f} cm")
        elif not self.pr:
            ui.dim("not printed: no printer configured (bobina printer add NAME ADDRESS)")
            return
        else:
            check_roll(res, self.printer, self.pr)
            if self._problems(res, "printing anyway"):
                return
            name, problems = send(a, res, self.printer, self.pr, ui.note)
            if problems is not None:
                ui.note("the chat goes on; p tries this answer again")
                return
            passed = conv.count(res)
            ans.printed, ans.printed_cm = True, cm
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


def check_roll(res, printer: str | None, pr: dict | None) -> None:
    """P101/P102 on the job, as print adds them (said with the job's other problems, never in the way)."""
    from .. import paper

    if pr and printer and counts_paper(pr):
        paper.check(printer, res.length_mm, res.nudges)


def send(args, res, printer: str | None, pr: dict, note) -> tuple[str, list | None]:
    """Prints a chat job and records it in the history, as print does. (printer name, None) when it printed;
    (name, problems) when it did not."""
    from .. import history

    rec = history.Recorder(getattr(args, "argv", ["chat"]))
    rec.res, rec.printer = res, printer or ""
    try:
        name = do_send(args, res.data, res.profile, length_mm=res.length_mm)
    except Fail as e:
        head, _, hint = str(e).partition("\n")
        note(f"not printed: {head}" + (f"\n  {hint.strip()}" if hint.strip() else ""))
        rec.finish("failed", e.code, e.problems())
        return printer or "", [e]
    rec.printer = name
    rec.finish("printed", OK, None)
    return name, None


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


# ------------------------------------------------------------------------------------------------ bobina chat


def terminal() -> bool:
    """The chat screen needs a terminal on both sides (and BOBINA_NONINTERACTIVE unset)."""
    return sys.stdin.isatty() and sys.stdout.isatty() and not noninteractive()


def _ui(args, cfg):
    """The chat screen, with its theme (--no-color as NO_COLOR); notes about the theme first."""
    from .chat_tui import TerminalUI

    env = {**os.environ, **({"NO_COLOR": "1"} if args.no_color else {})}
    theme = chat_theme.pick(args.theme, cfg, env)
    for n in theme.notes:
        err(f"note: {n}")
    return TerminalUI(theme)


def _stdin_waiting() -> bool:
    """Bytes waiting in a stdin pipe, looked at without reading them nor waiting (FIONREAD); False when it cannot
    tell (no note then)."""
    try:
        import fcntl
        import struct
        import termios

        got = fcntl.ioctl(sys.stdin.fileno(), termios.FIONREAD, b"\0\0\0\0")
        return struct.unpack("i", got)[0] > 0
    except (ImportError, OSError, ValueError, AttributeError):
        return False


STDIN_WAIT_S = 2.0  # no question and no terminal: how long stdin may take to bring one


def _question(args) -> str | None:
    """The question of one-question use: the words on the command line, else (no terminal) stdin. None: the chat
    screen."""
    if args.question:
        words = " ".join(args.question).strip()
        if not sys.stdin.isatty() and _stdin_waiting():
            err("note: the text on stdin was not read: the question is the one on the command line")
        if not words:
            raise Fail(USAGE, 'an empty question: ask something, e.g. bobina chat "why is the sky blue?"',
                       problem="E101")  # fmt: skip
        return words
    if terminal():
        return None
    if sys.stdin.isatty() or not stdin_has_data(STDIN_WAIT_S):  # a terminal on one side only, or a silent pipe
        raise Fail(CONFIRM, 'the chat screen needs a terminal; for one question: bobina chat "QUESTION" (add --yes'
                   " to print the answer), or the question on stdin", problem="E107")  # fmt: skip
    text = sys.stdin.read(STDIN_MAX + 1)
    if len(text) > STDIN_MAX:
        raise Fail(USAGE, "the question on stdin is too long", problem="E304")
    if not text.strip():
        raise Fail(USAGE, 'no question on stdin: echo "why is the sky blue?" | bobina chat', problem="E101")
    return text.strip()


NAME_MAX = 20  # characters: a name is one line over the message


def _name(args, cfg) -> str:
    """--name, else chat_name in config.toml, else "you"; one line (longer names are cut, with a note)."""
    raw = args.name if args.name is not None else cfg.get("chat_name")
    name = " ".join(str(raw).split()) if raw is not None else ""
    if not name:
        return "you"
    if len(name) > NAME_MAX:
        err(f"note: the name '{name}' is long for one line: '{name[:NAME_MAX]}' is used")
        name = name[:NAME_MAX]
    return name


def cmd_chat(args):
    cfg = config.load()
    question = _question(args)
    one = question is not None
    if not one and args.json:
        err('note: --json does nothing in the chat screen; for JSON ask one question: bobina chat "QUESTION" --json')
        args.json = False
    ui = None if one else _ui(args, cfg)
    name, model = _choose(args, ui)
    backend = ai.backend(name, model)
    printer, pr = config.printer(cfg, args.printer)
    if args.printer and not pr:
        raise Fail(UNREACHABLE, f"unknown printer '{args.printer}': bobina printer list", problem="E401")
    try:
        prof = profiles.load(args.profile or (pr or {}).get("profile") or cfg.get("profile"))
    except KeyError as e:
        raise Fail(USAGE, str(e).strip("'\""), problem="E207") from None
    # the printer's measured tear bar and the marks setting, as print uses them
    prof = engine.apply_overrides(prof, {**printer_overrides(pr), "marks": marks_setting(args, cfg)})
    layout = _setting(args, cfg, "chat_layout", "layout", LAYOUTS, "strip")
    style = _setting(args, cfg, "chat_style", "style", STYLES, DEFAULT_STYLE)
    ticket = Ticket(prof, style=style, name=_name(args, cfg))
    try:
        qlimit = int(cfg.get("chat_question_limit") or ticket.question_chars())
    except (TypeError, ValueError):
        raise Fail(USAGE, "chat_question_limit in config.toml: a number of characters", problem="E304") from None
    left = paper_left_of(printer, pr)
    conv = Conversation(backend, ticket, limit_mm=_limit(args, cfg, left()), paper_left=left, layout=layout)
    questions = bool(args.questions or cfg.get("chat_questions") is True)
    if one:
        return one_question(args, conv, printer if pr else None, pr, question, qlimit, questions)
    return Session(args, conv, printer if pr else None, pr, ui, qlimit, questions).run()


def one_question(args, conv, printer, pr, question: str, qlimit: int, questions: bool) -> int:
    """bobina chat "QUESTION": asks once, writes the answer, exits. It prints only with --yes (as print)."""
    if args.manual:
        err("note: --manual does nothing with one question: it prints only with --yes")
    if args.theme:
        err("note: --theme does nothing with one question: it is the chat screen's")
    if args.dry_run and args.yes:
        err("note: --dry-run wins over --yes: nothing prints")
    if args.layout == "strip":
        err("note: --layout strip does nothing with one question: a single answer is always one ticket")
    printing = args.yes and not args.dry_run
    if questions and (args.yes or args.dry_run) and len(question) > qlimit:
        raise Fail(USAGE, f"the question is too long to print: {len(question)}/{qlimit} characters (about 3 lines)"
                   "\n→ shorten it, or leave out --questions", problem="E304")  # fmt: skip
    out = {"schema": "bobina.chat/1", "question": question, "answer": None, "ai": conv.ai.name, "model": None,
           "paper_mm": None, "printed": False, "printer": printer, "rewritten": False, "cut": False,
           "problems": []}  # fmt: skip
    try:
        ans = conv.ask(question)
    except ai.AIError as e:
        f = Fail(UNREACHABLE, f"no answer: {e}" + (f"\n→ {e.hint}" if e.hint else ""), problem="E602")
        if args.json:
            print_json({**out, "problems": [n.as_dict() for n in f.problems()]}, indent=2, ensure_ascii=False)
        raise f from None
    except KeyboardInterrupt:
        ai.cancel()
        raise
    conv.layout = "tickets"  # one answer: a whole ticket, the header on top, fed to the tear bar
    res = conv.job(ans, question if questions else None)
    out |= {"answer": ans.text, "model": ans.model, "paper_mm": round(res.length_mm, 1), "rewritten": ans.rewritten,
            "cut": ans.cut, "paper_answer": ans.paper}  # fmt: skip
    if not args.json:
        print(BOLD.sub(lambda m: m.group(1), ans.text), flush=True)
    cm = res.length_mm / 10
    failed = None
    if ans.cut:
        err(f"note: too long for {conv.limit_mm / 10:g} cm even after a rewrite: on paper it would end with …")
    if printing:
        check_roll(res, printer, pr)
    code = report_nudges(res, args)  # as print: the format of --problems, -q, and --strict (exit 3)
    problems = list(res.visible_nudges())
    if code == STRICT:
        printing = False
    if not printing:
        if code != STRICT and not args.quiet:
            err(f"not printed (--dry-run): ~{cm:.1f} cm" if args.dry_run else f"not printed: ~{cm:.1f} cm; add"
                " --yes to print")  # fmt: skip
    elif not pr:
        failed = Fail(UNREACHABLE, "not printed: no printer configured: bobina printer add NAME ADDRESS",
                      problem="E401")  # fmt: skip
        problems += failed.problems()
    else:
        name, errors = send(args, res, printer, pr, err)
        if errors:
            failed = errors[0]
            problems += failed.problems()
        else:
            out |= {"printed": True, "printer": name}
            if not args.quiet:
                err(f"printed on {name}: ~{cm:.1f} cm")
    out["problems"] = [n.as_dict() for n in problems]
    if args.json:
        print_json(out, indent=2, ensure_ascii=False, default=str)
    if failed is not None:
        raise failed
    return code
