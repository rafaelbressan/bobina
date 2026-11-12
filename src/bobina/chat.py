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


@dataclass(frozen=True)
class Look:
    """How the two speakers look on paper (a --style)."""

    person: str = "label"  # label: name line, then the text on the right · text: the text only · bubble: a black
    # bubble with the icon by it · box: a framed bubble with the icon · named-bubble / named-box: the name line,
    # then the bubble or box (fitted to the text, on the right)
    full: bool = False  # the bubble across the paper (the text still on its right)
    ai_label: bool = True  # "✦ Claude" over the answer
    ai_icon: str = "sparkles"
    under_person: str = ""  # a short mark under the person's name: solid, dashed, dotted, hook
    under_ai: str = ""  # the same under the AI's name
    between: str = ""  # between exchanges: dashed-full, double, dotted-full (rules across), dots, ornament (short)
    inside: str = ""  # between the person's message and the answer: a dashed rule across
    above_names: bool = False  # a rule across over each name line
    under_messages: bool = False  # a rule across under each message


LOOKS = {
    # the D set (11/11): one continuous conversation; short marks only, by the speaker they belong to
    "labels-underline": Look(under_person="solid", under_ai="solid"),  # D1
    "labels-dashes": Look(under_person="dashed", under_ai="dashed"),  # D2
    "labels-dots": Look(between="dots"),  # D3
    "labels-outline": Look(person="named-box"),  # D4
    "labels-filled": Look(person="named-bubble", under_ai="dotted"),  # D5
    "labels-hook": Look(under_person="hook", under_ai="hook", between="ornament"),  # D6
    # earlier ones, kept behind --style
    "labels": Look(between="dashed-full"),
    "labels-ruled": Look(above_names=True),
    "labels-underlined": Look(under_messages=True),
    "labels-exchange": Look(between="double", inside="dashed"),
    "labels-bubble": Look(person="bubble", full=True, between="dotted-full"),
    "bubbles": Look(person="bubble", full=True),
    "boxes": Look(person="box", ai_icon="bot", between="dashed-full"),
    "plain": Look(person="text", ai_label=False, between="dashed-full"),
}
STYLES = tuple(LOOKS)
SPEAKER_ICON = {"ai": "sparkles", "person": "user-round", "ai-boxes": "bot"}
ICON_PX = 24  # one line of native text
PAD = 6  # dots inside a bubble or box
MARK_GAP = 3  # dots between a name and the short mark under it


def _narrow(profile, width: int):
    """The same printer, as if its paper were `width` dots wide (to lay out text inside a bubble)."""
    import dataclasses

    return dataclasses.replace(profile, width_dots=width)


def text_image(profile, text: str, width: int, *, bold: bool = False, align: str = "left"):
    """Text laid out as the printer's own font would print it, as a 1-bit image at most `width` dots wide,
    cropped to its ink (wrapped like native text: by words)."""
    from . import preview
    from .emulator import Emulator

    prof = _narrow(profile, width)
    blocks = [Paragraph(attrs=Attrs({align}), runs=[Run(p, bold=bold)] if bold else runs(p))
              for p in re.split(r"\n\s*\n", text) if p.strip()]  # fmt: skip
    rows = Layout(prof, Document(meta={}, blocks=blocks), None, Nudges()).run()[1:-1]
    im = preview.render(rows, prof, Emulator(prof))
    from PIL import ImageOps

    box = ImageOps.invert(im.convert("L")).getbbox()
    if not box:
        return im.crop((0, 0, 1, 1))
    return im.crop((0 if align == "left" else box[0], 0, box[2] if align == "left" else width, box[3]))


def _short_mark(d, x0: int, x1: int, y: int, kind: str, side: str) -> None:
    """A short mark from x0 to x1 (2 dots thick): solid, dashed (- - -), dotted (· · ·) or a hook bending down
    on the side of the text that follows (left speaker: at its end; right speaker: at its start)."""
    if kind == "dashed":
        for x in range(x0, x1, 10):
            d.rectangle((x, y, min(x + 5, x1), y + 1), fill=0)
    elif kind == "dotted":
        for x in range(x0, x1, 6):
            d.rectangle((x, y, x + 1, y + 1), fill=0)
    else:
        d.rectangle((x0, y, x1, y + 1), fill=0)
        if kind == "hook":
            hx = x1 - 1 if side == "left" else x0
            d.rectangle((hx, y, hx + 1, y + 6), fill=0)


def speaker_row(profile, icon: str, label: str, side: str = "left", under: str = ""):
    """One line: a small icon and a name ("✦ Claude" on the left, "Ana 👤" on the right), as an image row;
    under: a short mark under them (only as wide as icon and name)."""
    from PIL import Image, ImageDraw

    from . import icons
    from .rows import BitmapRow

    w = profile.width_dots
    mark = icons.load(icon, ICON_PX)
    name = text_image(profile, label, w - ICON_PX - 8, bold=True, align="left")
    h = max(ICON_PX, name.height)
    extra = (MARK_GAP + 2 + (6 if under == "hook" else 0)) if under else 0
    out = Image.new("1", (w, h + extra), 1)
    span = ICON_PX + 8 + name.width
    if side == "left":
        out.paste(mark, (0, (h - ICON_PX) // 2))
        out.paste(name, (ICON_PX + 8, (h - name.height) // 2))
        x0, x1 = 0, span
    else:
        out.paste(mark, (w - ICON_PX, (h - ICON_PX) // 2))
        out.paste(name, (w - ICON_PX - 8 - name.width, (h - name.height) // 2))
        x0, x1 = w - span, w - 1
    if under:
        _short_mark(ImageDraw.Draw(out), x0, x1, h + MARK_GAP, under, side)
    return BitmapRow(out, 0, "chat")


def rule_row(profile, style: str = "solid"):
    """A thin rule across the paper (2 dots: thinner prints broken, B101) with little space around it."""
    from . import imaging
    from .rows import BitmapRow

    return BitmapRow(imaging.divider(profile.width_dots, style, 2, pad=2), 0, "divider")


def ornament_row(profile, kind: str):
    """A small mark in the middle between two exchanges: "·  ·  ·" (dots) or "— ✦ —" (ornament); short, so the
    conversation still reads as one."""
    from PIL import Image, ImageDraw

    from . import icons
    from .rows import BitmapRow

    w = profile.width_dots
    if kind == "dots":
        out = Image.new("1", (w, 8), 1)
        d = ImageDraw.Draw(out)
        for i in (-1, 0, 1):
            x = w // 2 + i * 16
            d.rectangle((x - 1, 3, x + 1, 5), fill=0)
        return BitmapRow(out, 0, "divider")
    star = icons.load("sparkles", ICON_PX)
    out = Image.new("1", (w, ICON_PX), 1)
    d = ImageDraw.Draw(out)
    mid, y = w // 2, ICON_PX // 2 - 1
    d.rectangle((mid - ICON_PX // 2 - 8 - 36, y, mid - ICON_PX // 2 - 8, y + 1), fill=0)
    d.rectangle((mid + ICON_PX // 2 + 8, y, mid + ICON_PX // 2 + 8 + 36, y + 1), fill=0)
    out.paste(star, (mid - ICON_PX // 2, 0))
    return BitmapRow(out, 0, "divider")


def bubble_row(profile, text: str, *, inverted: bool, full: bool = False, icon: str | None = "user-round"):
    """The person's message on the right, like a chat app: wrapped inside a rounded bubble (white on black when
    inverted, else a 2-dot frame), the person icon next to its top (icon=None: no icon, the bubble to the edge).
    full: the bubble spans the paper, the text still on its right."""
    from PIL import Image, ImageDraw, ImageOps

    from . import icons
    from .rows import BitmapRow

    w = profile.width_dots
    side = ICON_PX + 6 if icon else 0
    inner = w - side - 2 * PAD - 4
    words = text_image(profile, text, inner, align="right" if full else "left")
    bw = (w - side) if full else words.width + 2 * PAD
    bh = words.height + 2 * PAD
    out = Image.new("1", (w, bh), 1)
    x0 = w - side - bw
    tx = x0 + bw - PAD - words.width  # the text against the bubble's right side
    d = ImageDraw.Draw(out)
    if inverted:
        d.rounded_rectangle((x0, 0, x0 + bw - 1, bh - 1), radius=8, fill=0)
        white = ImageOps.invert(words.convert("L")).convert("1")
        out.paste(white, (tx, PAD))
    else:
        d.rounded_rectangle((x0, 0, x0 + bw - 1, bh - 1), radius=8, outline=0, width=2)
        out.paste(words, (tx, PAD))
    if icon:
        out.paste(icons.load(icon, ICON_PX), (w - ICON_PX, 0))
    return BitmapRow(out, 0, "chat")


@dataclass
class Ticket:
    """Lays out and measures answers on one printer profile, in one of the STYLES; name: the person ("you")."""

    profile: object
    style: str = "plain"
    name: str = "you"
    _base: float | None = None

    @property
    def look(self) -> Look:
        return LOOKS[self.style]

    def job(self, parts: list, top: bool = True, feed: bool = True) -> engine.Result:
        """A job of these parts (lists of blocks laid out by bobina, or image rows), a block gap between them;
        top=False: without the top margin, feed=False: without the feed to the tear bar (the answers of one strip
        follow each other with no paper between them)."""
        gap = int(self.profile.get("margins.block_gap_dots", 12))
        nudges, rows, blocks = Nudges(), [], []
        for part in parts:
            if isinstance(part, list):
                if not part:
                    continue
                got = Layout(self.profile, Document(meta={}, blocks=part), None, nudges).run()[1:-1]
                blocks += part
            else:
                got = [part]
            if rows:
                rows.append(FeedRow(gap))
            rows += got
        frame = Layout(self.profile, Document(meta={}, blocks=[]), None, Nudges()).run()  # [top margin, feed]
        head = [frame[0]] if top else ([FeedRow(gap)] if rows else [])
        rows = head + rows + ([frame[-1]] if feed else [])
        doc = Document(meta={}, blocks=blocks)
        res = engine.Result(doc, rows, nudges, self.profile, None)
        res.source_text = ""
        return res

    def answer_mm(self, text: str) -> float:
        """The paper the answer's text takes, without the margins and the feed every job has."""
        if self._base is None:
            self._base = self.job([]).length_mm
        return self.job([paragraphs(text)]).length_mm - self._base

    @property
    def line_mm(self) -> float:
        h = self.profile.cell[1] + int(self.profile.get("native.line_gap_dots", 0))
        return h / (self.profile.dpi / 25.4)

    def chars(self, limit_mm: float) -> int:
        """About how many characters fit in limit_mm: what the AI is told (the check is on the paper itself)."""
        n = int(limit_mm / self.line_mm) * self.profile.columns * WRAP_SLACK
        return max(40, int(n // 10 * 10))

    def question_chars(self, lines: int = 3) -> int:
        """The longest message of the person that prints in about `lines` lines (inside a bubble when there is one)."""
        in_bubble = self.look.person in ("bubble", "box", "named-bubble", "named-box")
        cols = self.profile.columns - (3 if in_bubble else 0)
        return max(20, int(cols * lines * 0.9))

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
               separator: bool = False, top: bool = True, feed: bool = True,
               who: str = "AI") -> engine.Result:  # fmt: skip
        """One answer as it prints: a mark between exchanges (by style), the header, the person's message on the
        right, the AI's answer on the left (under its icon and name, but in plain)."""
        look, p = self.look, self.profile
        parts: list = []
        if separator and look.between:
            if look.between == "dashed-full":
                parts.append([Divider(attrs=Attrs({"dashed"}))])
            elif look.between in ("dots", "ornament"):
                parts.append(ornament_row(p, look.between))
            else:
                parts.append(rule_row(p, look.between.removesuffix("-full")))
        if header:
            head = [Paragraph(attrs=Attrs({"center"}), runs=[Run(header[0], bold=True)])]
            parts.append(head + [Paragraph(attrs=Attrs({"center"}), runs=[Run(line)]) for line in header[1:]])
        if question:
            text = "\n\n".join(paragraphs_text(question))
            if look.person in ("bubble", "box"):
                parts.append(bubble_row(p, text, inverted=look.person == "bubble", full=look.full))
            else:
                if look.above_names:
                    parts.append(rule_row(p))
                if look.person != "text":
                    parts.append(speaker_row(p, SPEAKER_ICON["person"], self.name, "right", look.under_person))
                if look.person in ("named-bubble", "named-box"):
                    parts.append(bubble_row(p, text, inverted=look.person == "named-bubble", icon=None))
                else:  # wrapped first, then each line aligned right (never stretched)
                    parts.append([Paragraph(attrs=Attrs({"right"}), runs=[Run(q)])
                                  for q in paragraphs_text(question)])  # fmt: skip
                if look.under_messages:
                    parts.append(rule_row(p))
                if look.inside:
                    parts.append(rule_row(p, look.inside))
        if look.ai_label:
            if look.above_names:
                parts.append(rule_row(p))
            parts.append(speaker_row(p, look.ai_icon, who, "left", look.under_ai))
        parts.append(paragraphs(answer))
        if look.under_messages:
            parts.append(rule_row(p))
        return self.job(parts, top, feed)

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
    printed_cm: float = 0.0  # the paper its last print took


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
        """The AI's answer within the limit: asked once to rewrite a longer one, then cut. Raises ai.AIError.
        Nothing changes here: remember() adds the turn to the conversation."""
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
        return ans

    def remember(self, question: str, ans: Answer) -> None:
        """The turn joins the conversation (not before: a turn stopped half way leaves no trace)."""
        self.messages += [{"role": "user", "content": question}, {"role": "assistant", "content": ans.text}]

    def header(self, model: str | None, when: str) -> list[str]:
        from .ai import header

        return [header(self.ai.vendor, model or self.ai.model), when]

    def job(self, ans: Answer, question: str | None) -> engine.Result:
        """strip: the header on the first answer, a dashed line before the others, no paper between them.
        tickets: each answer on its own ticket, the header (with the time of the answer) on top, fed to the tear
        bar to be torn off."""
        if self.layout == "tickets":
            return self.ticket.ticket(ans.paper, header=self.header(ans.model, now()), question=question,
                                      who=self.ai.vendor)  # fmt: skip
        first = not self.strip_open
        head = self.header(ans.model, self.started) if first else None
        return self.ticket.ticket(ans.paper, header=head, question=question, separator=not first, top=first,
                                  feed=False, who=self.ai.vendor)  # fmt: skip

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
