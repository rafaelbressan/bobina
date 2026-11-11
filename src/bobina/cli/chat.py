"""bobina chat (talk to an AI in the terminal, its answers print on the roll) and bobina ai (which AI)."""

from __future__ import annotations

import sys

from .. import ai, config, engine, view
from .. import profile as profiles
from ..chat import DEFAULT_LIMIT_MM, LAYOUTS, Conversation, Ticket
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
    where,
)

HELP = """\
  type a message and Enter: the AI answers here and on paper
  p          print the last answer (manual mode, or after a print failed)
  /manual    print only when you type p      /auto     print every answer (the default)
  /strip     one strip, a dashed line between answers, no paper between them (the default)
  /tickets   one ticket per answer: the AI and the time on top, fed to the tear bar to tear off
  /help      this list                       /quit     end (also Ctrl-D)"""


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
            "bobina chat --layout tickets",
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


# --------------------------------------------------------------------------------------------------- bobina chat


def _readline(prompt: str) -> str | None:
    """A line from the person (None at the end). A pipe works too: its lines are echoed, the transcript reads."""
    if sys.stdin.isatty():
        try:
            return input(prompt)
        except EOFError:
            return None
    line = sys.stdin.readline()
    if not line:
        return None
    print(prompt + line.rstrip("\n"))
    return line.rstrip("\n")


def _choose(args) -> tuple[str, str | None]:
    """The AI of this chat: --ai, else config.toml, else asked now (and saved). Never a dead end: a saved AI that is
    gone falls back to the best one found, and says so."""
    cfg = config.load()
    model = args.model or (cfg.get("ai_model") or None)
    if args.ai:
        if args.ai not in ai.BACKENDS:
            raise Fail(USAGE, f"unknown AI '{args.ai}': " + ", ".join(ai.ORDER), problem="E601")
        return args.ai, args.model
    saved = cfg.get("ai")
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
    pick = ready[0]
    if len(ready) > 1 and sys.stdin.isatty():
        print("Which AI should answer? (saved for next time; bobina ai use NAME changes it)")
        for i, f in enumerate(ready, 1):
            print(f"  {i}. {f.name:9s} {f.label}: {f.detail}")
        while True:
            a = (_readline(f"number or name [1 {ready[0].name}]: ") or "").strip().lower()
            if not a:
                break
            hit = [f for i, f in enumerate(ready, 1) if a in (str(i), f.name)]
            if hit:
                pick = hit[0]
                break
            print(f"  1 to {len(ready)}, or a name above")
    else:
        others = f" (also here: {', '.join(f.name for f in ready[1:])})" if len(ready) > 1 else ""
        print(f"using {pick.label}, the first AI found{others}; bobina ai use NAME changes it")
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


def _terminal(text: str, color: bool) -> str:
    """The answer as the terminal shows it: **bold** in bold (or without the stars when there are no colors)."""
    from ..chat import BOLD

    return BOLD.sub(lambda m: f"\x1b[1m{m.group(1)}\x1b[0m" if color else m.group(1), text)


class Chat:
    """The terminal loop: ask, show, print (or not), and say what happened to the paper."""

    def __init__(self, args, conv: Conversation, printer: str | None, pr: dict | None):
        self.args, self.conv, self.printer, self.pr = args, conv, printer, pr
        self.manual = args.manual
        self.color = view.use_color() and not args.no_color
        self.last = None  # (answer, question)

    def say(self, text: str) -> None:
        print(text, flush=True)

    def start(self) -> None:
        a, conv = self.args, self.conv
        model = f" ({conv.ai.model})" if conv.ai.model else ""
        cm = f"{conv.limit_mm / 10:g} cm"
        if a.dry_run:
            dest = "nothing prints (--dry-run): the answers show here, with the paper they would take"
        elif not self.pr:
            dest = "no printer configured: the answers show here only (bobina printer add NAME ADDRESS)"
        elif self.manual:
            dest = f"manual mode: p prints the last answer on {self.printer} (at most {cm} each)"
        else:
            dest = f"each answer prints on {self.printer} right away (at most {cm} each); /manual: only when you type p"
        if conv.layout == "tickets":
            layout = "layout: one ticket per answer, fed to the tear bar to tear off (/strip: one strip instead)"
        else:
            layout = "layout: one strip, a dashed line between answers (/tickets: one ticket per answer instead)"
        self.say(f"bobina chat · {conv.ai.label}{model}\n{dest}\n{layout}\n/help for commands · /quit or Ctrl-D"
                 " to end\n")  # fmt: skip

    def run(self) -> int:
        self.start()
        try:
            while True:
                line = _readline("you> ")
                if line is None:
                    break
                line = line.strip()
                if not line:
                    continue
                if line in ("/quit", "/exit", "/q"):
                    break
                if self.command(line):
                    continue
                self.turn(line)
        except KeyboardInterrupt:
            print()
        self.end()
        return OK

    def command(self, line: str) -> bool:
        if line in ("p", "/p", "/print"):
            if not self.last:
                self.say("  nothing to print yet")
            elif self.last[0].printed:
                self.say("  the last answer is already on paper")
            else:
                self.print_answer(*self.last)
            return True
        if line == "/manual":
            self.manual = True
            self.say("  manual mode: p prints the last answer")
            return True
        if line == "/auto":
            self.manual = False
            self.say("  every answer prints right away")
            return True
        if line in ("/strip", "/tickets"):
            want = line[1:]
            if self.conv.layout == want:
                self.say(f"  already: {'one strip' if want == 'strip' else 'one ticket per answer'}")
                return True
            if want == "tickets":
                self.close_strip()  # the strip so far goes to the tear bar before the first ticket
            self.conv.layout = want
            self.say("  one ticket per answer from now on" if want == "tickets" else "  one strip from now on")
            return True
        if line in ("/help", "/?"):
            self.say(HELP)
            return True
        if line.startswith("/"):
            self.say(f"  unknown command {line}; /help lists them (a message never starts with /)")
            return True
        return False

    def turn(self, question: str) -> None:
        conv = self.conv
        if sys.stderr.isatty():
            sys.stderr.write(f"  ({conv.ai.label} is thinking…)\r")
            sys.stderr.flush()
        try:
            ans = conv.ask(question)
        except ai.AIError as e:
            if sys.stderr.isatty():
                sys.stderr.write(" " * 60 + "\r")
            hint = f"\n  → {e.hint}" if e.hint else ""
            self.say(f"  [no answer: {e}]{hint}")
            return
        if sys.stderr.isatty():
            sys.stderr.write(" " * 60 + "\r")
        who = ai.header(conv.ai.vendor, ans.model)
        self.say(f"{who}:\n{_terminal(ans.text, self.color)}\n")
        if ans.rewritten and not ans.cut:
            self.say(f"  (the first answer took ~{ans.first_mm / 10:.0f} cm; the AI rewrote it within the limit)")
        if ans.cut:
            self.say(f"  (too long for {conv.limit_mm / 10:g} cm even after a rewrite: on paper it is cut with …;"
                     " the whole answer is above)")  # fmt: skip
        self.last = (ans, question)
        if self.manual:
            self.say("  p prints it")
            return
        self.print_answer(ans, question)

    def print_answer(self, ans, question: str) -> None:
        a, conv = self.args, self.conv
        res = conv.job(ans, question if a.questions else None)
        cm = res.length_mm / 10
        if a.dry_run:
            passed = conv.count(res)
            ans.printed = True
            self.say(f"  [not printed (--dry-run): ~{cm:.1f} cm · this chat ~{conv.used_mm / 10:.1f} cm]")
        elif not self.pr:
            self.say("  [not printed: no printer configured (bobina printer add NAME ADDRESS)]")
            return
        else:
            try:
                name = do_send(a, res.data, res.profile, length_mm=res.length_mm)
            except Fail as e:
                head, _, hint = str(e).partition("\n")
                self.say(f"  [not printed: {head}]" + (f"\n  {hint.strip()}" if hint.strip() else "")
                         + "\n  the chat goes on; p tries this answer again")  # fmt: skip
                self._history(res, "failed", e.code, e.problems())
                return
            passed = conv.count(res)
            ans.printed = True
            self._history(res, "printed", OK, None, name)
            self.say(f"  [printed on {where(name)}: ~{cm:.1f} cm · this chat ~{conv.used_mm / 10:.1f} cm]")
        if passed is not None:
            self.say(f"  note: this conversation has used ~{passed / 1000:.1f} m of paper")

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
            self.say(f"  [the strip was not fed to the tear bar: {str(e).splitlines()[0]}]")
            return
        passed = conv.count(res, answer=False)
        self.say(f"  [fed to the tear bar: ~{res.length_mm / 10:.1f} cm]")
        if passed is not None:
            self.say(f"  note: this conversation has used ~{passed / 1000:.1f} m of paper")

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
            self.say(f"bye: {plural(conv.printed, 'answer')} {what} ~{conv.used_mm / 10:.1f} cm of paper")
        else:
            self.say("bye")


def cmd_chat(args):
    cfg = config.load()
    name, model = _choose(args)
    backend = ai.backend(name, model)
    printer, pr = config.printer(cfg, args.printer)
    try:
        prof = profiles.load(args.profile or (pr or {}).get("profile") or cfg.get("profile"))
    except KeyError as e:
        raise Fail(USAGE, str(e).strip("'\""), problem="E207") from None
    # the printer's measured tear bar and the marks setting, as print uses them
    prof = engine.apply_overrides(prof, {**printer_overrides(pr), "marks": marks_setting(args, cfg)})
    layout = args.layout or cfg.get("chat_layout") or "strip"
    if layout not in LAYOUTS:
        raise Fail(USAGE, f"chat_layout = {layout!r} in config.toml: use {' or '.join(LAYOUTS)}", problem="E304")

    def paper_left():
        from .. import fileio, paper

        if not (pr and counts_paper(pr)):
            return None
        try:
            return paper.remaining(printer)
        except (fileio.StateError, OSError):
            return None

    conv = Conversation(backend, Ticket(prof), limit_mm=_limit(args, cfg), paper_left=paper_left, layout=layout)
    return Chat(args, conv, printer if pr else None, pr).run()
