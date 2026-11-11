"""bobina chat: the ticket of a conversation with an AI, and the guardrail that keeps each answer short.

An answer is never parsed as a .bob.md document: it is the AI's text, so it is laid out as plain paragraphs (only
**bold** kept), with no templates, no raw bytes, no images and no files. Paper is measured with the same
estimator check and print use (Result.length_mm)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import engine
from .layout import Layout
from .model import Attrs, Block, Divider, Document, Paragraph, Run
from .nudges import Nudges
from .rows import FeedRow

LAYOUTS = ("strip", "tickets")  # one strip for the whole conversation (default), or one ticket per answer
DEFAULT_LIMIT_MM = 100.0  # about 10 cm of paper per answer (decided 11/11), whatever the paper width
WARN_EVERY_MM = 1000.0  # a terminal note at each metre of paper in one conversation
WRAP_SLACK = 0.8  # words do not fill every line: the budget in characters the AI is given is this share of the grid
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")  # escape codes never reach the printer nor the terminal
BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
ITALIC = re.compile(r"(?<![*\w])[*_](?=\S)([^*_\n]+?)(?<=\S)[*_](?![*\w])")


def clean(text: str) -> str:
    """The AI's answer as plain text: control characters out, tabs as spaces, code fences, heading marks, inline
    code and italics markers dropped, at most one blank line between paragraphs. **bold** stays."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    text = CONTROL.sub("", text)
    lines = []
    for line in text.split("\n"):
        if re.match(r"^\s*(```|~~~)", line):
            continue
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        lines.append(line.rstrip())
    text = "\n".join(lines).replace("`", "")
    text = ITALIC.sub(r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def runs(text: str) -> list[Run]:
    out, pos = [], 0
    for m in BOLD.finditer(text):
        if m.start() > pos:
            out.append(Run(text[pos : m.start()]))
        out.append(Run(m.group(1), bold=True))
        pos = m.end()
    if pos < len(text):
        out.append(Run(text[pos:]))
    return out or [Run("")]


def paragraphs_text(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", clean(text)) if p.strip()]


def paragraphs(text: str) -> list[Block]:
    return [Paragraph(runs=runs(p)) for p in re.split(r"\n\s*\n", text) if p.strip()]


@dataclass
class Ticket:
    """Lays out and measures answers on one printer profile."""

    profile: object
    _base: float | None = None

    def job(self, blocks: list[Block], top: bool = True, feed: bool = True) -> engine.Result:
        """A job of these blocks; top=False: without the top margin, feed=False: without the feed to the tear bar
        (the answers of one strip follow each other with no paper between them)."""
        doc = Document(meta={}, blocks=blocks)
        nudges = Nudges()
        rows = Layout(self.profile, doc, None, nudges).run()
        rows = rows[(0 if top else 1) : (None if feed else -1)]
        if not top and blocks:  # after the answer before it: the gap between two blocks, not a top margin
            rows.insert(0, FeedRow(int(self.profile.get("margins.block_gap_dots", 12))))
        res = engine.Result(doc, rows, nudges, self.profile, None)
        res.source_text = ""
        return res

    def answer_mm(self, text: str) -> float:
        """The paper the answer's text takes, without the margins and the feed every job has."""
        if self._base is None:
            self._base = self.job([]).length_mm
        return self.job(paragraphs(text)).length_mm - self._base

    @property
    def line_mm(self) -> float:
        h = self.profile.cell[1] + int(self.profile.get("native.line_gap_dots", 0))
        return h / (self.profile.dpi / 25.4)

    def chars(self, limit_mm: float) -> int:
        """About how many characters fit in limit_mm: what the AI is told (the check is on the paper itself)."""
        n = int(limit_mm / self.line_mm) * self.profile.columns * WRAP_SLACK
        return max(40, int(n // 10 * 10))

    def cut(self, text: str, limit_mm: float) -> str:
        """The longest start of the text, ending at a word, that fits limit_mm with "…" after it."""
        ends = [m.start() for m in re.finditer(r"\s+", text)]
        lo, hi, best = 0, len(ends) - 1, ""
        while lo <= hi:
            mid = (lo + hi) // 2
            part = _close_bold(text[: ends[mid]].rstrip()) + "…"
            if self.answer_mm(part) <= limit_mm:
                best, lo = part, mid + 1
            else:
                hi = mid - 1
        if not best:  # not even one word: the first characters of it
            n = max(1, self.profile.columns * max(1, int(limit_mm / self.line_mm)) - 1)
            best = text[:n] + "…"
        return best

    def ticket(self, answer: str, *, header: list[str] | None = None, question: str | None = None,
               separator: bool = False, top: bool = True, feed: bool = True) -> engine.Result:  # fmt: skip
        """One answer as it prints: a dashed line between answers, the header, the question, the answer."""
        blocks: list[Block] = []
        if separator:
            blocks.append(Divider(attrs=Attrs({"dashed"})))
        if header:
            blocks.append(Paragraph(attrs=Attrs({"center"}), runs=[Run(header[0], bold=True)]))
            blocks += [Paragraph(attrs=Attrs({"center"}), runs=[Run(line)]) for line in header[1:]]
        if question:  # like a chat app: the person on the right, the AI on the left (wrapped, then each line right)
            blocks += [Paragraph(attrs=Attrs({"right"}), runs=[Run(q)]) for q in paragraphs_text(question)]
        blocks += paragraphs(answer)
        return self.job(blocks, top, feed)

    def end_of_strip(self) -> engine.Result:
        """The feed to the tear bar that ends a strip (with the tear mark when marks are on)."""
        return self.job([], top=False)


def _close_bold(text: str) -> str:
    return text + "**" if text.count("**") % 2 else text


def instruction(*, paper_mm: float, columns: int, limit_chars: int, limit_mm: float, used_mm: float,
                roll_left_mm: float | None) -> str:  # fmt: skip
    """What the AI is told on every turn: the receipt, the limit and the paper, then how to write."""
    left = f"{roll_left_mm / 1000:.1f} m" if roll_left_mm is not None else "unknown"
    return "\n".join([
        "You are chatting with a person through bobina: each of your answers is printed on a thermal receipt printer.",
        f"Receipt: paper {paper_mm:g} mm wide, {columns} characters per line.",
        f"Limit for each answer: {limit_chars} characters (about {limit_mm / 10:.0f} cm of paper). On paper, a"
        " longer answer is cut.",
        f"Paper used in this conversation so far: {used_mm / 10:.0f} cm.",
        f"Paper left on the roll: {left}.",
        "How to write:",
        "- Short sentences, plain text. Get to the point; one short paragraph is often enough.",
        "- No Markdown except **bold** for a word or two: no headings, tables, code blocks, lists or links.",
        "- No emoji.",
        "- Answer in the language the person writes in.",
    ])  # fmt: skip


def rewrite_request(chars: int, mm: float, limit_chars: int, limit_mm: float) -> str:
    return (f"That answer is too long for the receipt: {chars} characters, about {mm / 10:.0f} cm of paper; the"
            f" limit is {limit_chars} characters ({limit_mm / 10:.0f} cm). Write it again within {limit_chars}"
            " characters: the same answer, shorter. Only the new answer.")  # fmt: skip


@dataclass
class Answer:
    text: str  # what the terminal shows (the whole answer)
    paper: str  # what prints: the same, or cut at the limit with "…"
    model: str | None
    rewritten: bool = False
    cut: bool = False
    first_mm: float = 0.0  # the paper the first answer would have taken, when it was too long
    printed: bool = False


@dataclass
class Conversation:
    """The state of one bobina chat: messages, paper used, what printed."""

    ai: object  # an ai.Backend
    ticket: Ticket
    limit_mm: float = DEFAULT_LIMIT_MM
    paper_left: object = None  # () -> mm left on the roll, or None when unknown
    messages: list[dict] = field(default_factory=list)
    used_mm: float = 0.0
    printed: int = 0
    layout: str = "strip"
    strip_open: bool = False  # strip: answers printed since the last feed to the tear bar
    started: str = field(default_factory=lambda: now())

    def system(self) -> str:
        p = self.ticket.profile
        left = self.paper_left() if self.paper_left else None
        return instruction(paper_mm=float(p.get("paper_mm", 58)), columns=p.columns,
                           limit_chars=self.ticket.chars(self.limit_mm), limit_mm=self.limit_mm,
                           used_mm=self.used_mm, roll_left_mm=left)  # fmt: skip

    def ask(self, question: str) -> Answer:
        """The AI's answer within the limit: asked once to rewrite a longer one, then cut. Raises ai.AIError."""
        system = self.system()
        turn = [*self.messages, {"role": "user", "content": question}]
        reply = self.ai.ask(system, turn)
        text = clean(reply.text)
        ans = Answer(text, text, reply.model)
        mm = self.ticket.answer_mm(text)
        if mm > self.limit_mm:
            ans.first_mm = mm
            from .ai import AIError

            limit_chars = self.ticket.chars(self.limit_mm)
            shorten = rewrite_request(len(text), mm, limit_chars, self.limit_mm)
            again = [*turn, {"role": "assistant", "content": reply.text}, {"role": "user", "content": shorten}]
            try:
                shorter = self.ai.ask(system, again)
                text2 = clean(shorter.text)
                if text2:
                    ans = Answer(text2, text2, shorter.model or reply.model, rewritten=True, first_mm=mm)
            except AIError:
                pass  # the first answer, cut below
            if self.ticket.answer_mm(ans.text) > self.limit_mm:
                ans.paper, ans.cut = self.ticket.cut(ans.text, self.limit_mm), True
        self.messages += [{"role": "user", "content": question}, {"role": "assistant", "content": ans.text}]
        return ans

    def header(self, model: str | None, when: str) -> list[str]:
        from .ai import header

        return [header(self.ai.vendor, model or self.ai.model), when]

    def job(self, ans: Answer, question: str | None) -> engine.Result:
        """strip: the header on the first answer, a dashed line before the others, no paper between them.
        tickets: each answer on its own ticket, the header (with the time of the answer) on top, fed to the tear
        bar to be torn off."""
        if self.layout == "tickets":
            return self.ticket.ticket(ans.paper, header=self.header(ans.model, now()), question=question)
        first = not self.strip_open
        head = self.header(ans.model, self.started) if first else None
        return self.ticket.ticket(ans.paper, header=head, question=question, separator=not first, top=first,
                                  feed=False)  # fmt: skip

    def count(self, res: engine.Result, answer: bool = True) -> float | None:
        """After a job printed: the paper of this conversation; the metre just passed, if one was."""
        before = self.used_mm
        self.used_mm += res.length_mm
        if answer:
            self.printed += 1
            self.strip_open = self.layout == "strip"
        else:  # the end of a strip
            self.strip_open = False
        if int(self.used_mm // WARN_EVERY_MM) > int(before // WARN_EVERY_MM):
            return self.used_mm
        return None


def now() -> str:
    from .templating import current_time, resolve_tz

    return current_time(resolve_tz({})).strftime("%Y-%m-%d %H:%M")
