"""`.bob.md` text -> Document. Markdown via markdown-it (CommonMark + tables + strikethrough),
Pandoc-style attributes `{.class key=value}`, fenced objects. Jinja runs before this (templating)."""

from __future__ import annotations

import contextvars
import re
from dataclasses import replace
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.attrs import attrs_plugin

from .model import (
    Attrs,
    Block,
    Div,
    Divider,
    Document,
    Fence,
    Heading,
    Image,
    Item,
    ListBlock,
    Paragraph,
    Quote,
    Run,
    Table,
)
from .nudges import Nudges
from .templating import PH_CLOSE, PH_OPEN, PH_RE

PH_SPLIT = re.compile(f"({PH_OPEN}\\d+{PH_CLOSE})")  # a value's placeholder, kept by re.split

KNOWN_CLASSES = {
    "center",
    "right",
    "left",
    "justify",
    "invert",
    "bold",
    "italic",
    "underline",
    "strike",
    "flip",
    "mono",
    "compact",
    "solid",
    "dashed",
    "dotted",
    "double",
    "wavy",
    "cut",
    "mirror",  # images: left-right (the short form of mirror=x)
    "threshold",  # images: sharp black and white, the cut between ink and paper
    "dither",  # images: dithered like a photo, even if bobina sees a logo
}
KNOWN_KEYS = {
    "size",
    "font",
    "align",
    "rotate",
    "leading",
    "tracking",
    "indent",
    "thickness",
    "render",
    "module",
    "ecc",
    "width",
    "dither",
    "gamma",
    "threshold",
    "type",
    "text",
    "height",
    "columns",
    "header",
    "id",
    "ratio",
    "orientation",
}

ATTR_TAIL = re.compile(r"\s*\{([^{}]*)\}\s*$")
ATTRS_ONLY = re.compile(r"\s*\{([^{}]*)\}\s*")  # a line, or a cell, that is only {…}
DIVIDER_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*\{([^{}]*)\}\s*$")
TASK_RE = re.compile(r"^\[([ xX])\]\s+")
TOKEN_RE = re.compile(r"""\.[\w-]+|\#[\w-]+|[\w-]+=(?:"[^"]*"|'[^']*'|[^\s"']+)""")


TABLE_ONLY = frozenset({"style"})  # keys only a table's {…} line takes (style=receipt); elsewhere: unknown
CAPTION_KEYS = frozenset({"caption", "caption-align"})  # images and codes: a line under them, placed on its own
IMAGE_KEYS = CAPTION_KEYS | {"mirror"}  # mirror=x|y|xy: images only
CODES = ("qr", "barcode", "datamatrix", "pdf417")
WORD_BLOCKS = {"contact"}  # blocks that take a word after their kind: ```contact whatsapp


def parse_attrs(s: str) -> Attrs | None:
    """Pandoc attribute list -> Attrs, or None if `s` is not a well-formed attribute list."""
    s = s.strip()
    if not s:
        return Attrs()
    rest = TOKEN_RE.sub("", s)
    if rest.strip():
        return None
    a = Attrs()
    for tok in TOKEN_RE.findall(s):
        if tok.startswith("."):
            a.classes.add(tok[1:])
        elif tok.startswith("#"):
            a.kv["id"] = tok[1:]
        else:
            k, v = tok.split("=", 1)
            if v[:1] in "\"'":
                v = v[1:-1]
            a.kv[k] = v
    return a


def check_attrs(
    a: Attrs, line: int, nudges: Nudges, keys: bool = True, extra: frozenset = frozenset(), classes=frozenset()
):
    """keys=False: the block checks its own keys (pay: each scheme names the ones it takes); extra: keys only this
    block takes (caption= on a QR); classes: classes only it takes (.shade in a table cell)."""
    for c in a.classes - KNOWN_CLASSES - classes:
        nudges.add("M101", f"unknown class '.{c}'", line, "see: bobina help format")
    for k in set(a.kv) - KNOWN_KEYS - extra if keys else ():
        nudges.add("M101", f"unknown key '{k}='", line, "see: bobina help format")


def _neighbour(kids: list, i: int, side: int) -> str:
    """The character a text token touches on one side (side -1: before, 1: after), across emphasis markers: in
    "**Ana**:ok:" it is the "a" of Ana, in "**:heart: x**" the start of the line. A line break or nothing is a space;
    code, images and placeholders count as a word ("`x`:ok:" stays text, like "Ana:ok:")."""
    j = i + side
    while 0 <= j < len(kids) and (
        kids[j].type.endswith(("_open", "_close")) or (kids[j].type == "text" and not kids[j].content)
    ):
        j += side
    if not 0 <= j < len(kids) or kids[j].type in ("softbreak", "hardbreak"):
        return " "
    tok = kids[j]
    if tok.type == "text":
        ch = tok.content[-1] if side < 0 else tok.content[0]
        return "a" if ch == ":" else ch
    return "a"


def _icons_rule(state) -> None:
    """Known :name: in plain text become icon characters (icons.char_for); :a::b: is two. Runs before text_join, so
    an escaped colon (\\:fragile:) and code stay text; data is still a placeholder here (a word to its neighbours),
    so a value is never an icon. Unknown names stay as written and are listed in env["icons_unknown"] (line, name)
    for M161."""
    from . import icons

    for tok in state.tokens:
        if tok.type != "inline" or not tok.children:
            continue
        line = tok.map[0] if tok.map else 0
        kids = tok.children
        for i, child in enumerate(kids):
            if child.type in ("softbreak", "hardbreak"):
                line += 1  # the next line of the paragraph
            if child.type != "text" or ":" not in child.content:
                continue

            def one(m, line=line):
                name = icons.canonical(m.group(1))
                if name:
                    return icons.char_for(name)
                state.env.setdefault("icons_unknown", []).append((line, m.group(1)))
                return m.group(0)

            def run(m):
                return icons.ONE.sub(one, m.group(0))

            before, after = _neighbour(kids, i, -1), _neighbour(kids, i, 1)
            # a placeholder is a word to its neighbours: its outer edges become letters while the rule runs
            text = child.content.replace(PH_OPEN, "a\x01").replace(PH_CLOSE, "\x02a")
            out = icons.RUN.sub(run, before + text + after)[1:-1]
            if out != text:
                child.content = out.replace("a\x01", PH_OPEN).replace("\x02a", PH_CLOSE)


DIV_LINE = re.compile(r"(:{3,})(?:(?=\{)|\s+|$)(.*)")  # ::: {…}, ::: word, or a line of colons only (a closer)


def _div_rule(state, start: int, end: int, silent: bool) -> bool:
    """A line of 3 or more colons (Pandoc fenced divs, as in Quarto): with {…} or a word after them it opens a
    block, alone it closes one. Only the line is read here, as a marker token: _divs pairs them in each container
    (a closer closes the innermost open block). A code fence's lines never reach this rule, and a value from
    --set/--data is still a placeholder: it never starts with colons (FORMAT §7.4)."""
    if state.is_code_block(start):
        return False
    pos, stop = state.bMarks[start] + state.tShift[start], state.eMarks[start]
    m = DIV_LINE.fullmatch(state.src[pos:stop].rstrip())
    if not m:
        return False
    if silent:
        return True
    tok = state.push("fenced_div", "div", 0)
    tok.map, tok.markup, tok.info = [start, start + 1], m.group(1), m.group(2).strip()
    state.line = start + 1
    return True


def _md(icons: bool = True) -> MarkdownIt:
    """The document's Markdown; icons=False for data (data never brings an icon)."""
    md = MarkdownIt("commonmark", {"breaks": True, "html": False})
    md.enable(["table", "strikethrough"])
    md.use(attrs_plugin, spans=True)
    md.block.ruler.before("fence", "fenced_div", _div_rule, {"alt": ["paragraph", "reference", "blockquote", "list"]})
    if icons:
        md.core.ruler.before("text_join", "icons", _icons_rule)
    return md


def _span_attrs(node) -> Attrs:
    a = Attrs()
    for k, v in (node.attrs or {}).items():
        if k == "class":
            a.classes |= set(str(v).split())
        else:
            a.kv[k] = str(v)
    return a


def inline_runs(node, base: Run | None = None) -> list[Run]:
    """Inline SyntaxTreeNode -> list of styled runs ('\n' runs for line breaks)."""
    out: list[Run] = []
    base = base or Run("")

    def style(r: Run, **kw) -> Run:
        d = dict(r.__dict__)
        d.update(kw)
        d["text"] = ""
        return Run(**d)

    def walk(n, st: Run):
        for c in n.children:
            t = c.type
            if t == "text" and PH_OPEN in c.content and (sp := _splice()).inline(c.content):  # Markdown values
                text = ""
                for k, part in enumerate(PH_SPLIT.split(c.content)):
                    if k % 2 and int(part[1:-1]) in sp.direct:
                        if text:
                            out.append(Run(**{**st.__dict__, "text": text}))
                        text = ""
                        out.extend(sp.runs(int(part[1:-1]), st))
                    else:
                        text += part
                if text:
                    out.append(Run(**{**st.__dict__, "text": text}))
            elif t == "text":
                out.append(Run(**{**st.__dict__, "text": c.content}))
            elif t in ("softbreak", "hardbreak"):
                out.append(Run("\n"))
            elif t == "code_inline":
                out.append(Run(**{**st.__dict__, "text": c.content, "mono": True}))
            elif t == "strong":
                walk(c, style(st, bold=True))
            elif t == "em":
                walk(c, style(st, italic=True))
            elif t == "s":
                walk(c, style(st, strike=True))
            elif t == "span":
                a = _span_attrs(c)
                walk(
                    c,
                    style(
                        st,
                        bold=st.bold or a.has("bold"),
                        italic=st.italic or a.has("italic"),
                        strike=st.strike or a.has("strike"),
                        underline=st.underline or a.has("underline"),
                        invert=st.invert or a.has("invert"),
                        mono=st.mono or a.has("mono"),
                        font=a.kv.get("font", st.font),
                        size=a.kv.get("size", st.size),
                    ),
                )
            elif t == "link":
                walk(c, st)
            elif t == "image":
                out.append(Run(**{**st.__dict__, "text": c.content or ""}))
            else:
                if c.children:
                    walk(c, st)
                elif c.content:
                    out.append(Run(**{**st.__dict__, "text": c.content}))

    walk(node, base)
    return [r for r in out if r.text]


def _strip_tail_attrs(inline_node) -> Attrs | None:
    """Removes a trailing `{...}` from the last text child (heading/paragraph attributes). A value from --set/--data
    is still a placeholder here, so its braces never match: data stays literal (FORMAT §7.4)."""
    kids = inline_node.children
    if not kids or kids[-1].type != "text":
        return None
    m = ATTR_TAIL.search(kids[-1].content)
    if not m:
        return None
    a = parse_attrs(m.group(1))
    if a is None:
        return None
    kids[-1].token.content = kids[-1].content[: m.start()]
    return a


class _Lines:
    """Some of an inline node's children, read like the node itself (inline_runs, _strip_tail_attrs)."""

    def __init__(self, children: list):
        self.children = children


BREAKS = ("softbreak", "hardbreak")


def _breaks_in(kids) -> int:
    """The source lines these children end, so far: their line breaks, and the newlines inside a code span (which
    has none: _code_lines counts them)."""
    n = 0
    for k in kids:
        if k.type in BREAKS:
            n += 1
        elif k.type == "code_inline":
            n += k.token.meta.get("newlines", 0)
        else:
            n += _breaks_in(k.children)
    return n


def _code_lines(inline) -> None:
    """Each code span's newlines (its content has spaces for them), found in the paragraph's source in order, kept
    on its token for _breaks_in."""
    raw, pos = inline.content, 0

    def spans(kids):
        for k in kids:
            if k.type == "code_inline":
                yield k
            else:
                yield from spans(k.children)

    for k in spans(inline.children):
        body = r"[ \n]".join(re.escape(part) for part in k.content.split(" "))
        tick = re.escape(k.token.markup)
        m = re.compile(rf"(?<!`){tick}(?!`)[ \n]?{body}[ \n]?{tick}(?!`)").search(raw, pos)
        if m:
            k.token.meta["newlines"] = m.group(0).count("\n")
            pos = m.end()


def _trim(kids: list) -> list:
    """Without the line breaks and empty text at the end (left by an attribute line of its own)."""
    while kids and (kids[-1].type in BREAKS or (kids[-1].type == "text" and not kids[-1].content.strip(" "))):
        kids = kids[:-1]
    return kids


def _segments(inline, nudges: Nudges, ln: int) -> list[tuple[list, Attrs | None, int]]:
    """A paragraph's lines cut after each inner line that ends in a standalone `{…}` with a class or a key (an
    empty {} or an id alone stays text there): that attribute closes the lines above it, as the last line's closes
    the paragraph; checked at its own line. [(children, attributes, lines before them)]; one segment (attributes
    None) when no inner line has one."""
    kids = inline.children
    out, start = [], 0
    for i, k in enumerate(kids):
        if k.type not in BREAKS or i == 0 or kids[i - 1].type != "text":
            continue
        prev = kids[i - 1]
        m = ATTR_TAIL.search(prev.content)
        a = parse_attrs(m.group(1)) if m else None
        if a is None or not (a.classes or set(a.kv) - {"id"}):
            continue
        alone = not _trim(kids[start : i - 1]) and not prev.content[: m.start()].strip()
        if alone and not out:
            continue  # a first line that is only {…}: nothing above it to close, it stays text
        prev.token.content = prev.content[: m.start()]
        check_attrs(a, ln + _breaks_in(kids[:i]), nudges)
        if alone:  # a line of its own right after a closed segment: it closes the same lines
            seg, a0, before = out[-1]
            out[-1] = (seg, a0.merged(a), before)
        else:
            out.append((_trim(kids[start:i]), a, _breaks_in(kids[:start])))
        start = i + 1
    if not out:
        return [(kids, None, 0)]
    return [*out, (kids[start:], None, _breaks_in(kids[:start]))]


def _line(node, offset: int) -> int:
    return (node.map[0] + 1 + offset) if node.map else 0


BROKEN_IMAGE = re.compile(r"!\[([^\]]*)\]\(((?!<)[^)\n]*\s[^)\n]*)\)")


FROM_DATA = {  # what data rendered as Markdown may not bring: (code, what the problem says)
    "raw": ("M121", "a raw block was removed from a value that is not the author's own (data or computed)"),
    "image": ("M122", "an image was removed from a value that is not the author's own (data or computed)"),
    "block": (
        "M123",
        "a code block, ::: line or link definition was removed from a value that is not the author's "
        "own (data or computed)",
    ),
    "kind": ("M123", "a code block's kind cannot come from a value that is not the author's own: printed as text"),
}
DATA_HINT = (
    "such a value brings text, lists, quotes, tables and headings; other markup: in the document, or a value of its "
    "front matter"
)
ATTR_GUARD = "\ue004"  # a { of data while its Markdown is read: never a {…} attribute (templating.RESERVED_CHARS)


class _Splice:
    """Values rendered as Markdown that are not the author's own ({{ value | markdown }} on data, a computed string,
    a number…: templating.MdData): placeholders in the document, as every value is, filled in once the document is
    parsed. A placeholder alone in its paragraph (with the author's {…} after it or not) becomes the value's blocks;
    one inside a paragraph, a heading, a list item or a table cell, its text with its emphasis and line breaks. In a
    code span, a code block or an attribute it stays the plain value (resolved later, as {{ d }})."""

    def __init__(self, values: list | None = None, nudges: Nudges | None = None, off: int = 0, lines=()):
        self.values, self.nudges, self.off = values or [], nudges, off
        self.line = 0  # the document line (1-based, offset) of the block being read: refusals inside it go there
        self.parsed: dict[str, tuple[list[Block], list[tuple[str, str]]]] = {}
        self.said: set[tuple[str, str]] = set()  # each refusal once per value (by its text: a loop repeats it)
        self.at: dict[int, int] = {}  # placeholder -> the document line it is written on
        if any(v.markdown for v in self.values):
            for k, text in enumerate(lines):
                for m in PH_RE.finditer(text):
                    self.at.setdefault(int(m.group(1)), k + 1 + off)
        self.direct = {i for i in self.at if self.markdown(i)}  # the ones to splice: written in the document

    def value(self, i: int):
        return self.values[i] if 0 <= i < len(self.values) else None

    def markdown(self, i: int) -> bool:
        v = self.value(i)
        return bool(v and v.markdown)

    def inline(self, text: str) -> bool:
        """`text` holds a placeholder to splice."""
        return bool(self.direct) and any(int(m.group(1)) in self.direct for m in PH_RE.finditer(text))

    def block(self, content: str) -> tuple[int, Attrs] | None:
        """(the placeholder, the author's {…} on its line or the lines under it) when a paragraph is only one
        placeholder to splice, else None. Read on the document's own text only."""
        if not self.direct or PH_OPEN not in content:
            return None
        lines = content.split("\n")
        a = Attrs()
        while len(lines) > 1 and (m := ATTRS_ONLY.fullmatch(lines[-1])) and (got := parse_attrs(m.group(1))):
            a = got.merged(a)
            lines.pop()
        if len(lines) != 1:
            return None
        line = lines[0]
        tail = ATTR_TAIL.search(line)
        if tail and (got := parse_attrs(tail.group(1))) is not None:
            a, line = got.merged(a), line[: tail.start()]
        m = PH_RE.fullmatch(line.strip())
        return (int(m.group(1)), a) if m and int(m.group(1)) in self.direct else None

    def blocks(self, i: int, line: int) -> list[Block]:
        """The value's blocks (copies), each at the document's `line`; its refusals said where it is written."""
        import copy

        if self.values[i].text not in self.parsed:  # by text: a loop parses it once
            self.parsed[self.values[i].text] = data_blocks(self.values[i].text)
        kept, refused = self.parsed[self.values[i].text]
        for code, message in refused:
            if (self.values[i].text, code) not in self.said:  # once per value (a loop too), where first written
                self.said.add((self.values[i].text, code))
                self.nudges.add(code, message, self.at.get(i, line), DATA_HINT)
        out = copy.deepcopy(kept)
        for b in _all_blocks(out):
            b.line = line
        return out

    def runs(self, i: int, st: Run) -> list[Run]:
        """The value as inline text: its blocks' runs, one line each, styled with the text around it."""
        out: list[Run] = []
        for r in _flat(self.blocks(i, self.at.get(i, self.line))):
            if r.text == "\n":
                out.append(r)
                continue
            out.append(replace(r, bold=r.bold or st.bold, italic=r.italic or st.italic, strike=r.strike or st.strike,
                               underline=r.underline or st.underline, invert=r.invert or st.invert,
                               mono=r.mono or st.mono, font=st.font, size=st.size))  # fmt: skip
        return out

    def kind(self, info: str) -> tuple[str, bool]:
        """A fence's info string with the author's own values in its kind word opened (```{{ 'qr' }}, ```{{ k }}
        with k from the front matter: a QR), and whether a value that is not the author's own is there instead
        (data does not choose what a block is)."""
        head = info.split("{", 1)[0].split()
        if not head or PH_OPEN not in head[0]:
            return info, False
        found = [self.value(int(m.group(1))) for m in PH_RE.finditer(head[0])]
        if not found or not all(v and v.trusted for v in found):
            return info, True
        word = PH_RE.sub(lambda m: self.values[int(m.group(1))].text, head[0])
        return info.replace(head[0], word, 1), False


_SPLICE: contextvars.ContextVar[_Splice] = contextvars.ContextVar("bobina_splice")  # per thread (the chat's too)


def _splice() -> _Splice:
    return _SPLICE.get(None) or _Splice()


def data_blocks(text: str) -> tuple[list[Block], list[tuple[str, str]]]:
    """A --data/--set value rendered as Markdown, parsed alone with the document's rules: (the blocks it may bring,
    the refusals to say). Kept: paragraphs, line breaks, emphasis, strike, inline code, links (as their text),
    headings, lists, quotes, tables, rules. Refused: code blocks of any kind (raw M121, image M122, the rest M123),
    images (M122), ::: blocks (their content stays) and link definitions (M123). Its { never starts an attribute:
    data does not set attributes, they print as written. No icons from data either."""
    refused: list[tuple[str, str]] = []
    env: dict = {}
    guarded = text.replace("\\{", ATTR_GUARD).replace("{", ATTR_GUARD)  # \{ too: it prints as {
    tokens = _md(icons=False).parse(guarded, env)
    if env.get("references") or any(t.type == "fenced_div" for t in tokens):  # a closer alone too
        refused.append(FROM_DATA["block"])
    if any(t.type == "inline" and any(c.type == "image" for c in t.children or []) for t in tokens):
        refused.append(FROM_DATA["image"])
    token = _SPLICE.set(_Splice())  # nothing to splice inside a value
    try:
        blocks = _blocks(SyntaxTreeNode(tokens).children, Nudges(), 0, _Source(guarded.split("\n")))
    finally:
        _SPLICE.reset(token)

    def keep(bs: list[Block]) -> list[Block]:
        out: list[Block] = []
        for b in bs:
            if isinstance(b, Fence):
                refused.append(FROM_DATA[b.kind if b.kind in ("raw", "image") else "block"])
            elif isinstance(b, Image):
                refused.append(FROM_DATA["image"])
            elif isinstance(b, Div):
                refused.append(FROM_DATA["block"])
                out += keep(b.children)
            else:
                if isinstance(b, Quote):
                    b.children = keep(b.children)
                for it in getattr(b, "items", []):
                    it.children = keep(it.children)
                b.attrs = Attrs()
                out.append(b)
        return out

    kept = keep(blocks)
    for r in _all_runs(kept):
        r.text = r.text.replace(ATTR_GUARD, "{")
    return kept, list(dict.fromkeys(refused))


def _all_blocks(blocks):
    for b in blocks:
        yield b
        if isinstance(getattr(b, "children", None), list):
            yield from _all_blocks(b.children)
        for it in getattr(b, "items", []):
            yield from _all_blocks(it.children)


def _all_runs(blocks):
    for b in _all_blocks(blocks):
        yield from getattr(b, "runs", [])
        if isinstance(b, Table):
            for cell in [*b.header, *(c for row in b.rows for c in row)]:
                yield from cell


def _flat(blocks: list[Block]) -> list[Run]:
    """Blocks as one text: each paragraph, heading, list item and table row on a line of its own."""
    lines: list[list[Run]] = []
    for b in blocks:
        if isinstance(b, (Paragraph, Heading)):
            lines.append(list(b.runs))
        elif isinstance(b, ListBlock):
            for k, it in enumerate(b.items):
                mark = f"{b.start + k}. " if b.ordered else "• "
                inner = _flat(it.children)
                lines.append([Run(mark), *inner])
        elif isinstance(b, Quote):
            lines.append(_flat(b.children))
        elif isinstance(b, Table):
            for row in [b.header, *b.rows]:
                cells = [c for c in row if c]
                line: list[Run] = []
                for c in cells:
                    line += ([Run(" | ")] if line else []) + list(c)
                lines.append(line)
    out: list[Run] = []
    for line in lines:
        out += ([Run("\n")] if out else []) + line
    return out


def parse(
    text: str,
    nudges: Nudges,
    line_offset: int = 0,
    base_dir: str = ".",
    meta: dict | None = None,
    values: list | None = None,
) -> Document:
    """values: the render's values (Rendered.values): those rendered as Markdown that are not the author's own are
    spliced in after the document is parsed, so they never meet its source (_Splice)."""
    token = _SPLICE.set(_Splice(values, nudges, line_offset, re.split(r"\r\n?|\n", text)))
    try:
        return _parse(text, nudges, line_offset, base_dir, meta)
    finally:
        _SPLICE.reset(token)


def _parse(text: str, nudges: Nudges, line_offset: int, base_dir: str, meta: dict | None) -> Document:
    lines = _Source(re.split(r"\r\n?|\n", text))  # as markdown-it counts them (its maps index these)
    tails = _title_tails(lines)
    while True:  # a {…} after a title row is taken out first: GFM would not see a table with one cell too many
        src = _Source(lines)
        for i, (row, _a) in tails.items():
            src[i] = row
        env: dict = {}
        tokens = _md().parse("\n".join(src) if tails else text, env)
        heads = {t.map[0] for t in tokens if t.type == "thead_open" and t.map}
        if set(tails) <= heads:
            break
        tails = {i: v for i, v in tails.items() if i in heads}  # not a table after all (a code block): as written
    src.title_rows = {i: a for i, (_row, a) in tails.items()}
    root = SyntaxTreeNode(tokens)
    doc = Document(meta=meta or {}, base_dir=base_dir)
    doc.blocks = _blocks(root.children, nudges, line_offset, src)
    _unknown_icons(env.get("icons_unknown", []), nudges, line_offset)
    return doc


def _unknown_icons(found: list[tuple[int, str]], nudges: Nudges, off: int) -> None:
    from . import icons

    seen = set()
    for line, name in found:
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        near = icons.closest(name)
        nudges.add(
            "M161",
            f"no icon called ':{name}:': printed as written",
            line + 1 + off,
            (f"did you mean {', '.join(f':{n}:' for n in near)}? " if near else "") + "the names: bobina help icons",
        )


class _DivGroup:
    """The nodes between a ::: opener and its closer (or the end of what holds them), in the node tree's place."""

    type = "div_group"

    def __init__(self, opener, closed: bool = True):
        self.opener, self.children, self.closed = opener, [], closed
        self.map = opener.map

    @property
    def columns(self) -> bool:
        """It opens :::: {.columns} (or ::: columns)."""
        return bool(COLUMNS_INFO.search(_div_info(self.opener)))


def _div_info(node) -> str:
    """What follows the colons, without the colons a fence may end with (::: {.box} :::)."""
    return re.sub(r"\s*:+$", "", node.info or "").strip()


def _divs(nodes, nudges: Nudges, off: int, src=None) -> list:
    """A container's nodes with each ::: opener and what follows it, up to the line of colons that closes it, as a
    _DivGroup: a closer closes the innermost open block. A block never closed runs to the end of the container
    (M105, said once its blocks are known); a closer with nothing open is ignored (M101)."""
    if not any(n.type == "fenced_div" for n in nodes):
        return list(nodes)
    stack = [_DivGroup(nodes[0])]  # the container itself
    for n in nodes:
        if n.type != "fenced_div":
            stack[-1].children.append(n)
        elif _div_info(n):
            stack.append(_DivGroup(n))
        elif len(stack) > 1:
            done = stack.pop()
            stack[-1].children.append(done)
            outer = done.opener.markup
            if done.columns and len(n.markup) < len(outer):  # often a line meant to open the next column
                nudges.add("M101", f"this {n.markup} closes the {outer} {{.columns}} of line {_line(done.opener, off)}",
                           _line(n, off), f"to close the columns write {outer} (as many colons as the opening); to "
                           "open another column write ::: {.column}")  # fmt: skip
        else:
            nudges.add("M101", f"a line of {n.markup} with no ::: block open: ignored", _line(n, off),
                       "a line of colons only closes the ::: {…} above it; remove this one")  # fmt: skip
    while len(stack) > 1:
        done = stack.pop()
        done.closed = False
        stack[-1].children.append(done)
    return stack[0].children


WORD = re.compile(r"[\w-]+")


def div_attrs(info: str, line: int, nudges: Nudges) -> Attrs:
    """A ::: opener's settings: {…}, or one word (::: box is .box, as in Pandoc). Read as far as they can be: a
    value with spaces and no quotes keeps its words (title=MESA GRANDE), settings without braces are read too;
    each is said (M101) with the way to write it."""
    if WORD.fullmatch(info):
        return Attrs({info})
    braced = info.startswith("{") and info.endswith("}")
    inner = info[1:-1] if braced else info
    a = parse_attrs(inner)
    if a is None:
        a, last, odd = Attrs(), None, []
        for word in re.findall(r"""(?:[^\s"']+|"[^"]*"|'[^']*')+""", inner):
            got = parse_attrs(word)
            if got is not None and (got.classes or got.kv):
                a = a.merged(got)
                bare = got.kv and word.split("=", 1)[1][:1] not in "\"'"
                last = next(iter(got.kv)) if bare else None
            elif last is not None:  # title=MESA GRANDE: the words after an unquoted value are part of it
                a.kv[last] += " " + word
            elif WORD.fullmatch(word) and not braced:  # ::: box shade: words are classes
                a.classes.add(word)
            else:
                odd.append(word)
        spaced = [f'{k}="{v}"' for k, v in a.kv.items() if " " in v and f'"{v}"' not in inner and f"'{v}'" not in inner]
        if spaced:
            nudges.add("M101", f"{', '.join(q.replace(chr(34), '') for q in spaced)}: a value with spaces goes in "
                       "quotes", line, " ".join(spaced))  # fmt: skip
        if odd:
            nudges.add("M101", f"::: {info}: {' '.join(odd)} is not a setting (ignored)", line,
                       '::: {.box title="TABLE 4" width=half}')  # fmt: skip
    if not braced:
        nudges.add("M101", f"::: {info}: the settings go in braces", line, f"::: {{{inner}}}")
    return a


# boxes' and columns' own keys and classes;
DIV_KEYS = frozenset({"title", "title-style", "wrap", "valign", "gap", "length"})
DIV_CLASSES = frozenset({"box", "shade", "columns", "column"})  # the rest of a ::: {…}: check_attrs
COLUMNS_INFO = re.compile(r"^columns$|(?:^|[\s{])\.columns(?=[\s}]|$)")  # what opens :::: {.columns}


def _what(b: Block) -> str:
    """A block as a problem names it: "the heading 109", "the list at line 4"."""
    at = f"at line {b.line}"
    if isinstance(b, Heading):
        text = "".join(r.text for r in b.runs).strip()
        return f"the heading {text}" if text and len(text) <= 24 and text.isprintable() else f"the heading {at}"
    if isinstance(b, Div):
        kind = next((k for k in ("box", "columns", "column") if b.attrs.has(k)), "")
        return f"the {kind} {at}" if kind else f"the ::: block {at}"
    if isinstance(b, Fence):
        names = {"qr": "QR code", "barcode": "barcode", "pay": "payment code", "contact": "contact code",
                 "image": "image", "datamatrix": "Data Matrix", "pdf417": "PDF417"}  # fmt: skip
        return f"the {names.get(b.kind, 'code block')} {at}"
    kinds = {Paragraph: "text", ListBlock: "list", Table: "table", Quote: "quote", Divider: "divider", Image: "image"}
    return f"the {kinds.get(type(b), 'block')} {at}"


def _trapped(blocks: list[Block]) -> str:
    """What a block never closed holds, for M105: "the heading 109 and the columns at line 4 are"."""
    names = [_what(b) for b in blocks if not (isinstance(b, Paragraph) and b.follows)]
    if len(names) > 4:
        names = [*names[:3], f"{len(names) - 3} more blocks"]
    said = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"{said} {'is' if len(names) == 1 else 'are'}"


def _div(g: _DivGroup, nudges: Nudges, off: int, src: list[str]) -> Div:
    ln = _line(g.opener, off)
    info = _div_info(g.opener)
    fence = f"{g.opener.markup} {info}"
    a = div_attrs(info, ln, nudges)
    check_attrs(a, ln, nudges, extra=DIV_KEYS, classes=DIV_CLASSES)
    kids = _blocks(g.children, nudges, off, src)
    if not g.closed:
        inside = f": {_trapped(kids)} inside it" if kids else ", and nothing follows it"
        nudges.add("M105", f"{fence[:40]} at line {ln} is never closed{inside}", ln,
                   "add a line of ::: where it should end")  # fmt: skip
    if a.has("columns"):
        kids = _columns(kids, nudges)
    return Div(line=ln, attrs=a, children=kids, fence=fence, closed=g.closed)


COLUMN_OWN = ("width", "valign")  # what a box right inside :::: {.columns} gives the column it is


def _columns(kids: list[Block], nudges: Nudges) -> list[Block]:
    """The blocks of a :::: {.columns} as its columns, left to right: each ::: {…} in it is one (::: {.column}, or
    any other; a box is a column drawn as a box, its width= and valign= are the column's; columns right inside
    columns are a column holding them). Blocks outside any column become a column of their own, said (M101)."""
    out: list[Block] = []
    loose: list[Block] = []

    def flush() -> None:
        if loose:
            first = loose[0]
            what = _what(first).replace(f" at line {first.line}", "")  # the line is said with the problem
            nudges.add("M101", f"{what} is inside :::: {{.columns}} but outside any column: printed as a column of its "
                       "own", first.line, "open each column with ::: {.column} and close it with :::")  # fmt: skip
            out.append(Div(line=first.line, attrs=Attrs({"column"}), children=list(loose), fence="::: {.column}"))
            loose.clear()

    for b in kids:
        if not isinstance(b, Div):
            loose.append(b)
            continue
        flush()
        if b.attrs.has("box") or b.attrs.has("columns"):  # ::: {.column .box}: the column it becomes says .column
            b.attrs.classes.discard("column")
        if b.attrs.has("columns"):
            out.append(Div(line=b.line, attrs=Attrs({"column"}), children=[b], fence=b.fence))
        elif b.attrs.has("box"):
            own = {k: b.attrs.kv.pop(k) for k in COLUMN_OWN if k in b.attrs.kv}
            out.append(Div(line=b.line, attrs=Attrs({"column"}, own), children=[b], fence=b.fence))
        else:
            out.append(b)
    flush()
    return out


def _blocks(nodes, nudges: Nudges, off: int, src: list[str]) -> list[Block]:
    out: list[Block] = []
    for n in _divs(nodes, nudges, off, src):
        if isinstance(n, _DivGroup):
            out.append(_div(n, nudges, off, src))
            continue
        ln = _line(n, off)
        sp = _splice()
        sp.line = ln
        t = n.type
        if t == "paragraph" and (hit := sp.block(n.children[0].content)) is not None:
            i, a = hit  # a value as Markdown, alone in its paragraph: its blocks, with the author's {…} on each
            check_attrs(a, ln, nudges)
            for b in sp.blocks(i, ln):
                b.attrs = b.attrs.merged(a)
                out.append(b)
            continue
        if t == "heading":
            inline = n.children[0]
            a = _strip_tail_attrs(inline) or Attrs()
            check_attrs(a, ln, nudges)
            out.append(Heading(line=ln, attrs=a, level=int(n.tag[1]), runs=inline_runs(inline)))
        elif t == "paragraph":
            inline = n.children[0]
            raw = inline.content
            for m in BROKEN_IMAGE.finditer(raw):  # Markdown drops ![](a b.png): say why, not just "word split"
                nudges.add(
                    "I107",
                    f"'{m.group(0)[:50]}' is not an image: the path has a space",
                    ln,
                    f"write it as ![{m.group(1)}](<{m.group(2).strip()}>)",
                )
            am = ATTRS_ONLY.fullmatch(raw)
            if am and out and (a0 := parse_attrs(am.group(1))) is not None:  # attribute line: applies above
                check_attrs(a0, ln, nudges, extra=TABLE_ONLY if isinstance(out[-1], Table) else frozenset())
                out[-1].attrs = out[-1].attrs.merged(a0)
                if isinstance(out[-1], Table):
                    _attr_lines(out[-1], a0, ln)
                continue
            dm = DIVIDER_RE.match(raw)
            if dm and (a := parse_attrs(dm.group(1))) is not None:
                check_attrs(a, ln, nudges)
                out.append(Divider(line=ln, attrs=a))
                continue
            kids = [k for k in inline.children if not (k.type == "text" and not k.content.strip())]
            extra = None
            if len(kids) == 2 and kids[0].type == "image" and kids[1].type == "text":
                m2 = re.fullmatch(r"\{([^{}]*)\}\s*", kids[1].content)  # {width=50%}: values mdit rejects
                extra = parse_attrs(m2.group(1)) if m2 else None
                if extra is not None:
                    kids = kids[:1]
            if len(kids) == 1 and kids[0].type == "image":
                img = kids[0]
                ia = _span_attrs(img).merged(extra) if extra else _span_attrs(img)
                check_attrs(
                    Attrs(ia.classes, {k: v for k, v in ia.kv.items() if k not in ("src", "alt", "title")}), ln, nudges,
                    extra=IMAGE_KEYS,
                )  # fmt: skip
                for k in ("src", "alt", "title"):
                    ia.kv.pop(k, None)
                out.append(Image(line=ln, attrs=ia, src=unquote(img.attrs.get("src", "")), alt=img.content))
                continue
            paras: list[Paragraph] = []
            _code_lines(inline)
            for seg, a, before in _segments(inline, nudges, ln):
                if a is None and (a := _strip_tail_attrs(_Lines(seg))) is not None:
                    check_attrs(a, ln + raw.count("\n"), nudges)  # the last line's
                    seg = _trim(seg)
                    if not seg and paras:  # "A {.right}\n{.center}": the last line closes the lines above
                        paras[-1].attrs = paras[-1].attrs.merged(a)
                        continue
                a = a or Attrs()
                paras.append(Paragraph(line=ln + before, attrs=a, runs=inline_runs(_Lines(seg)), follows=bool(paras)))
            out.extend(paras)
        elif t in ("bullet_list", "ordered_list"):
            lb = ListBlock(line=ln, ordered=t == "ordered_list", start=int((n.attrs or {}).get("start", 1)))
            for li in n.children:
                kids = _blocks(li.children, nudges, off, src)
                task = None
                if kids and isinstance(kids[0], Paragraph) and kids[0].runs:
                    first = kids[0].runs[0]
                    m = TASK_RE.match(first.text)
                    if m:
                        task = m.group(1) != " "
                        first.text = first.text[m.end() :]
                        kids[0].runs = [r for r in kids[0].runs if r.text]
                lb.items.append(Item(children=kids, task=task))
            out.append(lb)
        elif t == "blockquote":
            out.append(Quote(line=ln, children=_blocks(n.children, nudges, off, src)))
        elif t == "hr":
            out.append(Divider(line=ln))
        elif t in ("fence", "code_block"):
            info, chosen = _splice().kind((n.info or "").strip())
            kind, a, arg = info, Attrs(), ""
            m = re.match(r"^([\w-]*)(?:\s+([\w.+\-]+))?\s*(?:\{(.*)\})?\s*$", info)  # : {{ x }}
            if m and (m.group(2) is None or m.group(1).lower() in WORD_BLOCKS):
                kind, arg = m.group(1), m.group(2) or ""
                if m.group(3) is not None:
                    a = parse_attrs(m.group(3)) or Attrs()
            elif info.split(maxsplit=1)[0].lower() in WORD_BLOCKS:  # ```contact whatsapp business: the block
                kind, rest = info.split(maxsplit=1)  # still says what is wrong (Q112), never prints as text
                attrs = re.search(r"\{(.*)\}\s*$", rest)
                arg = rest[: attrs.start()].strip() if attrs else rest.strip()
                a = (parse_attrs(attrs.group(1)) if attrs else None) or Attrs()
            k = kind.lower()  # pay and contact check their own keys; the old pix gets one clear warning
            if chosen:  # ```{{ lang }}: only the author chooses what a block is
                nudges.add(*FROM_DATA["kind"], ln, "write the kind in the document: ```qr, ```text")
                kind, k, a, arg = "text", "text", Attrs(), ""
            check_attrs(
                a, ln, nudges, keys=k not in ("pay", "pix", "contact"),
                extra=IMAGE_KEYS if k == "image" else CAPTION_KEYS if k in CODES else frozenset(),
            )  # fmt: skip
            out.append(Fence(line=ln, attrs=a, kind=kind.lower(), content=n.content, arg=arg))
        elif t == "table":
            out.append(_table(n, ln, nudges, src))
        elif n.children:
            out.extend(_blocks(n.children, nudges, off, src))
    return out


def _attr_lines(tb: Table, a: Attrs, line: int) -> None:
    """The line each of a table's attributes was written on (.compact, width=): problems are said there."""
    tb.attr_lines.update({**{f".{c}": line for c in a.classes}, **{f"{k}=": line for k in a.kv}})


def _row_attrs(tr, src: list[str]) -> Attrs | None:
    """The attributes of a table's last "row" that is only `{…}`, with no pipe (GFM goes on with the table on the
    line right under it; with a blank line between it is an attribute line already). None: a real row."""
    if not tr.map or tr.map[0] >= len(src):
        return None
    m = ATTRS_ONLY.fullmatch(re.sub(r"^[\s>]*", "", src[tr.map[0]]))
    return parse_attrs(m.group(1)) if m else None


COLUMN_KEYS = ("width", "prefix", "suffix")  # a column's settings, at the end of its title cell
COLUMN_HINT = 'a title cell takes width=, prefix= and suffix= for its column: | Price {width=9ch prefix="R$ "} |'


ROW_PREFIX = re.compile(r"^(?:\s*(?:>|[-+*](?=\s)|\d{1,9}[.)](?=\s)))*\s*")  # what holds a table row: > - 1.
DELIMITER_ROW = re.compile(r"\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?")  # |---|--:| under a table's titles


class _Source(list):
    """The document's lines, and the {…} written after a table's title row (its line index -> Attrs)."""

    title_rows: dict[int, Attrs]

    def __init__(self, lines=()):
        super().__init__(lines)
        self.title_rows = {}


def _braces(segments: list[str]) -> Attrs | None:
    """Segments that are each only {…}, merged (none dropped); None when one is not, or when together they say
    nothing bobina reads (an empty {} or an id alone stays text, as in a cell)."""
    out = Attrs()
    for seg in segments:
        m = ATTRS_ONLY.fullmatch(seg)
        a = parse_attrs(m.group(1)) if m else None
        if a is None:
            return None
        out = out.merged(a)
    return out if segments and _meant(out) else None


def _row_tail(raws: list[str], line: str, ncol: int) -> tuple[Attrs | None, int]:
    """A row's own {…} and how many of its last segments it takes: (a) the cells past the title row's count, when
    each is only {…} (GFM drops them: they can only mean the row), with or without the outer pipes; else (b) on a
    row written with its leading pipe, the {…} after the pipe that closes it, with nothing after it (a short row,
    a span's). Otherwise a last cell that is only {…} is a cell: `| a | {.shade} |`, `Coffee | {.shade}`."""
    if len(raws) > ncol >= 1 and (a := _braces(raws[ncol:])) is not None:
        return a, len(raws) - ncol
    s = ROW_PREFIX.sub("", line).strip()
    if len(raws) >= 2 and s.startswith("|") and not s.endswith("|") and (a := _braces(raws[-1:])) is not None:
        return a, 1
    return None, 0


def _cut_cells(line: str, keep: int) -> str:
    """A row's line cut after its first `keep` cells (and the pipe that closes them)."""
    start = len(line) - len(ROW_PREFIX.sub("", line).lstrip())
    seen, esc = -1 if line[start : start + 1] == "|" else 0, False
    for i in range(start, len(line)):
        if line[i] == "|" and not esc:
            seen += 1
            if seen == keep:
                return line[: i + 1]
        esc = line[i] == "\\" and not esc
    return line


def _title_tails(lines: list[str]) -> dict[int, tuple[str, Attrs]]:
    """Title rows with more cells than their delimiter row, the extra ones each only {…}: (the row without them,
    their attributes), by line index. With or without the outer pipes."""
    out = {}
    for i in range(len(lines) - 1):
        under = ROW_PREFIX.sub("", lines[i + 1]).strip()
        if "|" not in under or not DELIMITER_ROW.fullmatch(under) or "|" not in lines[i]:
            continue
        n = len(_raw_cells(lines[i + 1]))
        raws = _raw_cells(lines[i])
        if len(raws) > n and (a := _braces(raws[n:])) is not None:
            out[i] = (_cut_cells(lines[i], n), a)
    return out


def _raw_cells(line: str) -> list[str]:
    """A table row's source line in its cells as written (backslashes kept), split at the pipes GFM splits at:
    the unescaped ones. The container prefix before it goes first: quote bars and list markers (- * + 1. 1))."""
    s = ROW_PREFIX.sub("", line).strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    cells, cur, esc = [], "", False
    for ch in s:
        if ch == "|" and not esc:
            cells.append(cur)
            cur = ""
        else:
            cur += ch
        esc = ch == "\\" and not esc
    return [*cells, cur]


EMPTY_SPAN = re.compile(r"(?<![\w-])span=(?=\s|$)")
ESCAPED_TAIL = re.compile(r"(\\*)\{[^{}]*?(\\*)\}\s*$")


def _escaped_tail(raw: str | None) -> bool:
    """The `{…}` at the end of a cell was written \\{…} (or …\\}): markdown-it already made it a plain brace, so
    only the source tells. It stays text."""
    m = ESCAPED_TAIL.search(raw or "")
    return bool(m) and (len(m.group(1)) % 2 == 1 or len(m.group(2)) % 2 == 1)


def _cell_attrs(inline, raw: str | None, want) -> Attrs | None:
    """The `{…}` at the end of a cell when want(attrs) says it is meant for bobina, taken out of its text; None
    otherwise (it stays text: an escaped brace, or what want refuses). raw: the cell as written. A value from
    --set/--data is still a placeholder here: its braces never match (FORMAT §7.4)."""
    kids = inline.children if inline is not None else []
    if not kids or kids[-1].type != "text" or _escaped_tail(raw):
        return None
    m = ATTR_TAIL.search(kids[-1].content)
    a = parse_attrs(m.group(1)) if m else None
    if a is None and m and EMPTY_SPAN.search(m.group(1)):  # {span=}: said as an empty value (M101), not kept
        a = parse_attrs(EMPTY_SPAN.sub('span=""', m.group(1)))
    if a is None or not want(a):
        return None
    kids[-1].token.content = kids[-1].content[: m.start()]
    return a


CELL_CLASSES = frozenset({"bold", "italic", "underline", "strike", "invert", "shade", "left", "center", "right"})
ROW_CLASSES = CELL_CLASSES - {"strike"}  # what a row's {…} takes, after its closing pipe
CELL_KEYS = frozenset({*COLUMN_KEYS, "span"})  # keys a cell's {…} is read for (said where they do nothing)
CELL_TAKES = "a cell takes .bold .italic .underline .strike .invert .shade .left .center .right, and span= in the body"
ROW_HINT = "a row takes .bold .italic .underline .invert .shade .left .center .right: | TOTAL | 61,00 | {.invert .bold}"


def _idle_names(a: Attrs, used: tuple[str, ...], classes: frozenset = CELL_CLASSES) -> list[str]:
    """The known classes and keys in a cell's {…} that do nothing there (check_attrs says the unknown ones)."""
    return [f".{c}" for c in sorted(a.classes & (KNOWN_CLASSES | CELL_CLASSES) - classes)] + [
        f"{k}=" for k in sorted(a.kv) if k in KNOWN_KEYS | CELL_KEYS and k not in used
    ]


def _meant(a: Attrs) -> bool:
    """A cell's {…} is bobina's when it has a class or a key; an empty {} or an id alone stays text."""
    return bool(a.classes or set(a.kv) - {"id"})


def _title_settings(cell, raw: str | None, ln: int, nudges: Nudges) -> tuple[Attrs, Attrs]:
    """A title cell's column settings (width= prefix= suffix=) and its own classes (.bold .invert .right…); the
    rest of its {…} is said (M101): span= spans nothing in a title. An empty {} or an id alone stays text."""
    inline = cell.children[0] if cell.children else None
    a = _cell_attrs(inline, raw, _meant)
    if a is None:
        return Attrs(), Attrs()
    check_attrs(a, ln, nudges, extra=CELL_KEYS, classes=CELL_CLASSES)
    if "span" in a.kv:
        nudges.add("M101", f"span={a.kv['span']} in a title cell: a title spans nothing (ignored)", ln,
                   "span= goes at the end of a body cell: | | Discount {span=all} |")  # fmt: skip
    idle = _idle_names(a, (*COLUMN_KEYS, "span"))
    if idle:
        nudges.add("M101", f"{', '.join(idle)} at the end of a title cell {'does' if len(idle) == 1 else 'do'} "
                   "nothing", ln, f"{COLUMN_HINT}; {CELL_TAKES}")  # fmt: skip
    return Attrs(set(), {k: v for k, v in a.kv.items() if k in COLUMN_KEYS}), Attrs(a.classes & CELL_CLASSES)


def _body_settings(cell, raw: str | None, at: int, nudges: Nudges) -> Attrs:
    """A body cell's own classes and span=, taken out of its text; width=, prefix=, suffix= there are said
    (M101). An empty {} or an id alone stays text."""
    inline = cell.children[0] if cell.children else None
    a = _cell_attrs(inline, raw, _meant)
    if a is None:
        return Attrs()
    check_attrs(a, at, nudges, extra=CELL_KEYS, classes=CELL_CLASSES)
    names = [f"{k}=" for k in COLUMN_KEYS if k in a.kv]
    if names:
        nudges.add("M101", f"{', '.join(names)} {'works' if len(names) == 1 else 'work'} at the end of a title "
                   "cell, for its column", at, f"move it to the title cell of that column ({COLUMN_HINT})")  # fmt: skip
    idle = _idle_names(a, tuple(CELL_KEYS))
    if idle:
        nudges.add("M101", f"{', '.join(idle)} at the end of a table cell {'does' if len(idle) == 1 else 'do'} "
                   "nothing", at, CELL_TAKES)  # fmt: skip
    return Attrs(a.classes & CELL_CLASSES, {k: v for k, v in a.kv.items() if k == "span"})


def _row_style(a: Attrs, at: int, nudges: Nudges) -> Attrs:
    """A row's {…} (after its closing pipe): its classes; every key, and what a row does not take, said (M101)."""
    check_attrs(a, at, nudges, extra=CELL_KEYS, classes=CELL_CLASSES)
    idle = _idle_names(a, (), ROW_CLASSES)
    if idle:
        nudges.add("M101", f"{', '.join(idle)} after a table row {'does' if len(idle) == 1 else 'do'} nothing", at,
                   ROW_HINT)  # fmt: skip
    return Attrs(a.classes & ROW_CLASSES)


TITLE_ROW_NOTE = "a {…} after the title row makes GitHub and Obsidian show the table as text"
TITLE_ROW_HINT = "style=header-invert or classes at the end of each title cell print the same and stay a table there"


def _table(n, ln, nudges: Nudges, src: list[str]) -> Table:
    tb = Table(line=ln)
    body = n.children[-1] if n.children and n.children[-1].type == "tbody" else None
    if body and body.children and (a := _row_attrs(body.children[-1], src)) is not None:
        at = _line(body.children[-1], ln - _line(n, 0))
        check_attrs(a, at, nudges, extra=TABLE_ONLY)
        tb.attrs = a
        _attr_lines(tb, a, at)
        body.children.pop()
    titles = getattr(src, "title_rows", {})
    for section in n.children:
        for tr in section.children:
            cells, aligns, styles = [], [], []
            at = _line(tr, ln - _line(n, 0)) or ln
            source = src[tr.map[0]] if tr.map and tr.map[0] < len(src) else ""
            raws = _raw_cells(source) if source else []
            tail, taken = (None, 0) if section.type == "thead" else _row_tail(raws, source, len(tb.header))
            row = _row_style(tail, at, nudges) if tail is not None else Attrs()
            if section.type == "thead" and tr.map and tr.map[0] in titles:
                row = _row_style(titles[tr.map[0]], at, nudges)
                nudges.add("M104", TITLE_ROW_NOTE, at, TITLE_ROW_HINT)
            for k, cell in enumerate(tr.children):
                style = (cell.attrs or {}).get("style", "")
                aligns.append("right" if "right" in style else "center" if "center" in style else "left")
                raw = raws[k] if k < len(raws) else None
                if tail is not None and k >= len(raws) - taken:  # the row's {…}, which GFM read as a cell
                    cells.append([])
                    styles.append(Attrs())
                    continue
                if section.type == "thead":
                    column, own = _title_settings(cell, raw, ln, nudges)
                    tb.columns.append(column)
                    styles.append(own)
                else:
                    styles.append(_body_settings(cell, raw, at, nudges))
                cells.append(inline_runs(cell.children[0]) if cell.children else [])
            if section.type == "thead":
                tb.header, tb.aligns, tb.heads, tb.head_row = cells, aligns, styles, row
            else:
                tb.rows.append(cells)
                tb.row_lines.append(at)
                tb.cells.append(styles)
                tb.row_attrs.append(row)
    return tb
