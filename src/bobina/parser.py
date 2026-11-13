"""`.bob.md` text -> Document. Markdown via markdown-it (CommonMark + tables + strikethrough),
Pandoc-style attributes `{.class key=value}`, fenced objects. Jinja runs before this (templating)."""

from __future__ import annotations

import re
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.attrs import attrs_plugin

from .model import Attrs, Block, Divider, Document, Fence, Heading, Image, Item, ListBlock, Paragraph, Quote, Run, Table
from .nudges import Nudges

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
    "mirror",  # images: left-right
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
DIVIDER_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*\{([^{}]*)\}\s*$")
TASK_RE = re.compile(r"^\[([ xX])\]\s+")
TOKEN_RE = re.compile(r"""\.[\w-]+|\#[\w-]+|[\w-]+=(?:"[^"]*"|'[^']*'|[^\s"']+)""")


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


def check_attrs(a: Attrs, line: int, nudges: Nudges, keys: bool = True, extra: frozenset = frozenset()):
    """keys=False: the block checks its own keys (pay: each scheme names the ones it takes); extra: keys only this
    block takes (caption= on a QR)."""
    for c in a.classes - KNOWN_CLASSES:
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
    from .templating import PH_CLOSE, PH_OPEN

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


def _md() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"breaks": True, "html": False})
    md.enable(["table", "strikethrough"])
    md.use(attrs_plugin, spans=True)
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
            if t == "text":
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
    """Removes a trailing `{...}` from the last text child (heading/paragraph attributes)."""
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


def _line(node, offset: int) -> int:
    return (node.map[0] + 1 + offset) if node.map else 0


BROKEN_IMAGE = re.compile(r"!\[([^\]]*)\]\(((?!<)[^)\n]*\s[^)\n]*)\)")


def parse(text: str, nudges: Nudges, line_offset: int = 0, base_dir: str = ".", meta: dict | None = None) -> Document:
    env: dict = {}
    root = SyntaxTreeNode(_md().parse(text, env))
    doc = Document(meta=meta or {}, base_dir=base_dir)
    doc.blocks = _blocks(root.children, nudges, line_offset)
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


def _blocks(nodes, nudges: Nudges, off: int) -> list[Block]:
    out: list[Block] = []
    for n in nodes:
        ln = _line(n, off)
        t = n.type
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
            am = re.fullmatch(r"\s*\{([^{}]*)\}\s*", raw)
            if am and out and (a0 := parse_attrs(am.group(1))) is not None:  # attribute line: applies above
                check_attrs(a0, ln, nudges)
                out[-1].attrs = out[-1].attrs.merged(a0)
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
                    Attrs(ia.classes, {k: v for k, v in ia.kv.items() if k not in ("src", "alt", "title")}), ln, nudges
                )
                for k in ("src", "alt", "title"):
                    ia.kv.pop(k, None)
                out.append(Image(line=ln, attrs=ia, src=unquote(img.attrs.get("src", "")), alt=img.content))
                continue
            a = _strip_tail_attrs(inline) or Attrs()
            check_attrs(a, ln, nudges)
            out.append(Paragraph(line=ln, attrs=a, runs=inline_runs(inline)))
        elif t in ("bullet_list", "ordered_list"):
            lb = ListBlock(line=ln, ordered=t == "ordered_list", start=int((n.attrs or {}).get("start", 1)))
            for li in n.children:
                kids = _blocks(li.children, nudges, off)
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
            out.append(Quote(line=ln, children=_blocks(n.children, nudges, off)))
        elif t == "hr":
            out.append(Divider(line=ln))
        elif t in ("fence", "code_block"):
            info = (n.info or "").strip()
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
            check_attrs(
                a, ln, nudges, keys=k not in ("pay", "pix", "contact"),
                extra=frozenset({"caption"}) if k == "qr" else frozenset(),
            )  # fmt: skip
            out.append(Fence(line=ln, attrs=a, kind=kind.lower(), content=n.content, arg=arg))
        elif t == "table":
            out.append(_table(n, ln))
        elif n.children:
            out.extend(_blocks(n.children, nudges, off))
    return out


def _table(n, ln) -> Table:
    tb = Table(line=ln)
    for section in n.children:
        for tr in section.children:
            cells, aligns = [], []
            for cell in tr.children:
                style = (cell.attrs or {}).get("style", "")
                aligns.append("right" if "right" in style else "center" if "center" in style else "left")
                cells.append(inline_runs(cell.children[0]) if cell.children else [])
            if section.type == "thead":
                tb.header, tb.aligns = cells, aligns
            else:
                tb.rows.append(cells)
    return tb
