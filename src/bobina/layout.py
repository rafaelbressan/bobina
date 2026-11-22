"""Document -> rows, guided by the printer profile. bobina decides every line break."""

from __future__ import annotations

import contextlib
import functools
import math
import re
import unicodedata
from dataclasses import dataclass, field, replace

from PIL import Image, ImageChops, ImageDraw, ImageOps

from . import charts, icons, imaging, preview, rasterfont, scriptfonts, sources
from .emulator import CHECKBOX, Emulator
from .model import Attrs, Div, Divider, Document, Fence, Heading, ListBlock, Paragraph, Quote, Run, Table
from .model import Image as ImageBlock
from .nudges import Nudges, SecurityError, not_a_value
from .rows import BarcodeRow, BitmapRow, Boxed, Cell, Column, Columned, FeedRow, QRRow, RawRow, TextRow, columns
from .templating import PH_RE, RESERVED_CHARS, Rendered

NO_CAPTION = {"", "auto", "none", "no", "false", "off"}  # caption= words that print no caption on a plain QR
PAY_HINT = 'write ```pay {scheme=pix to="your key" name="Shop" city="Rio" amount=10.00} (bobina help pay)'

# CLDR dates/currencies use no-break and narrow spaces ("6:44\u202fPM", "R$\u00a04,50"): the printer font has
# no glyph for them, so the whole line would become an image. They print as a plain space.
SPACES = str.maketrans({c: " " for c in "\u00a0\u2007\u2009\u202f\u2002\u2003\u205f"})
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")  # never let text carry printer commands
SIZE_RE = rasterfont.SIZE_RE
UNIT_RE = re.compile(r"^(\d+(?:\.\d+)?)(px|mm)$")
QUOTE_BAR = "│"  # in front of the lines of a > quote, in the gutter it leaves (checked like any glyph: F301)
GS_MAX = 8  # the largest multiplier GS ! takes, in width and in height
MULTIPLIER_RE = re.compile(r"^(\d+)x(?:(\d+))?$")  # 2x, 1x2, and those GS ! cannot take (0x, 17x)
MULTIPLIER_HINT = "2x, 3x, 1x2 or a name: small, normal, large, title, huge"
QUOTE_GUTTER = 2  # columns (at 1x) a quote takes: its bar and a space
TABLE_MIN = 6  # orientation=auto turns a table whose columns cannot keep this many characters (or their own width)
TURN_FREE_MM = 80  # … when the turned table is no longer than this, or than twice the standing one
TABLE_TEXT = ("bold", "italic", "underline")  # on a table's {…} line: every cell's text, titles too (they add up)
TABLE_CLASSES = {"compact", "left", "center", "right", "flip", *TABLE_TEXT}  # what a table takes; the rest: M101
TABLE_KEYS = {"align", "orientation", "width", "rotate", "id", "font", "size", "style"}
TABLE_STYLES = ("plain", "receipt", "lines", "grid", "header-invert", "zebra")  # style= on a table; plain: the default
CELL_HINT = (
    "a cell prints in its table's font: **bold**, *italic*, ~~strike~~, .underline and .invert work in it; font= and "
    "size= go on the table's {…} line, for the whole table"
)
TABLE_HINT = (
    "a table takes "
    + ", ".join([*(f".{c}" for c in sorted(TABLE_CLASSES)), *(f"{k}=" for k in sorted(TABLE_KEYS - {"id"}))])
    + " and #id (docs/guides/tables.md); a chart: chart=line|bar|area|sparkline, data=FILE (bobina help chart)"
)
OBJECT_WIDTH_HINT = "full, half, third, 50%, 30mm or dots (200)"
BOX_LINES = ("solid", "dashed", "dotted", "double")  # a box's frame: the divider's lines
TITLE_STYLES = ("border", "inside", "band")  # title-style=: on the top line (the default), first line, black band
BOX_TAKES = (frozenset({"box", *BOX_LINES, "left", "center", "right", "shade", "flip", "invert"}),
             frozenset({"title", "title-style", "thickness", "width", "align", "rotate", "id"}))  # fmt: skip
BLOCK_TAKES = (frozenset({"flip"}), frozenset({"rotate", "id"}))  # a ::: block that is not a box
BOX_HINT = (
    'a box takes title="…" title-style=border|inside|band .solid .dashed .dotted .double thickness= width= .center '
    ".right .shade .invert (docs/guides/layout.md)"
)
BOX_WIDTH_HINT = "full, half, third, 50%, 30mm or 16ch (letters)"
COLUMNS_TAKES = (frozenset({"columns", "flip"}),
                 frozenset({"wrap", "valign", "gap", "rotate", "id", "orientation", "length"}))  # fmt: skip
COLUMN_TAKES = (frozenset({"column"}), frozenset({"width", "valign", "id"}))
COLUMNS_HINT = (":::: {.columns wrap=nowrap|wrap|wrap-reverse valign=top|middle|bottom gap=1ch "
                "orientation=horizontal|vertical length=72mm} holds the columns "
                "(docs/guides/layout-columns.md)")  # fmt: skip
TURNED_LENGTH_MM = 72  # orientation=vertical on columns: a label this long along the roll, unless length= says
TURNED_MOST_MM = 300  # … and never longer than this (length=auto too: a column's content measured up to it)
LENGTH_HINT = "72mm (the default), 7.2cm, 575 (dots) or auto (as long as the columns' content needs)"
CODE_KINDS = frozenset({"qr", "barcode", "datamatrix", "pdf417"})  # rows a turned label never resamples (fit_label)
LABEL_GAP_MM = 3  # between two turned labels, each side of the dashed line that parts them (between_labels)
BAR_MIN_DOTS = 40  # a barcode fitted to a turned label keeps bars this tall (5 mm), else Q108: on paper 18/11, a
# standing EAN-13 with 40-dot bars scanned (MTP-II)
COLUMN_HINT = "a column takes width=auto|40%|30mm|12ch and valign=top|middle|bottom (docs/guides/layout-columns.md)"
WRAPS = ("nowrap", "wrap", "wrap-reverse")  # wrap= on columns: CSS flex-wrap's names
VALIGNS = {"top": "top", "middle": "middle", "center": "middle", "bottom": "bottom"}  # center (CSS's word): middle
GAP_HINT = "1ch (letters: the default), 0, 2ch, 3mm or dots"
# what a column's content says when it is squeezed below its minimum (a word cut, a QR below the module that scans,
# a table narrowed or turned, a box title cut, a turned block cropped, …): wrap=wrap moves a column that would say
# one of them
SQUEEZED = frozenset({"L101", "L103", "L104", "L106", "L107", "L109", "Q101", "Q104", "Q108", "Q110", "I102"})
BOX_ROOM = 10  # dots of paper between a box's frame and what it holds, above and below (at least: ink is measured)
BOX_MIN_SIDE = 6  # … and beside it: the frame and this room take whole letters, so the text keeps the paper's grid
COLUMN_CH_RE = re.compile(r"(\d+(?:\.\d+)?)ch")  # width=7ch at the end of a title cell; other units: object_width
COLUMN_WIDTH_HINT = "auto, 7ch, 20mm, 30% (of the text room) or dots (96); the column shares what is left (auto)"
ICON_SPLIT = f"([{chr(icons.PUA)}-\U0010fffd])"  # one icon character, kept by re.split


def is_wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F") or icons.is_icon(ch)  # an icon is a square: 2 columns


def fit_columns(s: str, cols: int) -> str:
    """The start of s that fits in cols columns (wide characters and icons take 2)."""
    used = 0
    for i, ch in enumerate(s):
        used += 2 if is_wide(ch) else 1
        if used > cols:
            return s[:i]
    return s


def _groups(cells: list[Cell]) -> list[list[Cell]]:
    """Cells as runs of spaces and of the rest: words and the gaps between them."""
    out: list[list[Cell]] = []
    for c in cells:
        if out and (out[-1][0].ch == " ") == (c.ch == " "):
            out[-1].append(c)
        else:
            out.append([c])
    return out


def _pieces(word: list[Cell]) -> list[list[Cell]]:
    """A word in the pieces a table cell may wrap between: after . - / between two letters (VL.|TOTAL, e-|mail),
    before a ( after a letter (UNIT|(R$)), never inside a number (18,00, 15/11)."""
    out, start = [], 0
    for k in range(1, len(word) - 1):
        if word[k].ch in ".-/" and word[k - 1].ch.isalpha() and word[k + 1].ch.isalpha():
            out.append(word[start : k + 1])
            start = k + 1
        elif word[k].ch == "(" and word[k - 1].ch.isalpha() and k > start:
            out.append(word[start:k])
            start = k
    return [*out, word[start:]]


def _longest(cells_list, measure=columns) -> int:
    """The widest piece of word in these cells: what a column keeps whole when it can."""
    return max([0, *(measure(p) for c in cells_list for g in _groups(c) if g[0].ch != " " for p in _pieces(g))])


def word_tokens(cells: list[Cell], pieces: bool = False) -> list[tuple[list[Cell], list[Cell]]]:
    """Cells as (the spaces before a word, the word); pieces: a table cell's words in their pieces (_pieces), with
    nothing between them."""
    out, gap = [], []
    for g in _groups(cells):
        if g[0].ch == " ":
            gap = g
            continue
        for k, p in enumerate(_pieces(g) if pieces else [g]):
            out.append((gap if k == 0 else [], p))
        gap = []
    return out


def wrap_words(tokens, cap: int, hang: int, split, measure=columns) -> list[list[Cell]]:
    """Greedy word wrap of word_tokens into lines of at most cap columns (cap - hang after the first): the spaces
    before a word that starts a line are dropped. A word longer than a line is cut, never between the two columns
    of a wide character: right after the last / ? & = - _ . # that leaves the line at least half full
    (rasterfont.soft_break: an address reads gov.|br/consulta?|chave=…), else at the last letter that fits;
    split(word, room) is called once for each word that was cut (to say it: L101). A wide
    character on a line narrower than itself is put there whole (it sticks out: nothing to cut). measure: how wide
    cells are, in the unit of cap (columns; a table in a raster font measures in its own unit)."""
    lines: list[list[Cell]] = []
    cur: list[Cell] = []
    width, avail = 0, cap
    for gap, word in tokens:
        ww = measure(word)
        if cur and width + measure(gap) + ww > avail:
            lines.append(cur)
            cur, width, avail = [], 0, cap - hang
        elif cur:
            cur += gap
            width += measure(gap)
        whole, room, done = word, avail, 0
        text = "".join(c.ch[:1] or " " for c in word)  # one letter per cell: soft_break's offsets are cells
        while ww > avail and len(word) > 1:  # a word longer than a full line
            k, take = 0, 0
            while k < len(word) and take + measure(word[k : k + 1]) <= avail:
                take += measure(word[k : k + 1])
                k += 1
            k = max(k, 1)  # a wide character on a line of one column: on a line of its own, never lost
            for j in range(k, 0, -1):  # the last soft place that leaves the line at least half full
                if 2 * measure(word[:j]) < avail:
                    break
                if rasterfont.soft_break(text, done + j):
                    k = j
                    break
            lines.append(word[:k])
            word, avail, done = word[k:], cap - hang, done + k
            ww = measure(word)
        if word is not whole:
            split(whole, room)
        cur += word
        width += ww
    lines.append(cur)
    return lines


_IMAGES: dict = {}  # finished image rows (local files, data: URIs) of this process; oldest dropped first
_IMAGES_MAX = 64
IMAGE_ONLY = ("mirror", "threshold", "dither")  # attributes that only images read (as classes or keys)
CROP_HINT = "x,y,width,height: pixels of the file or percentages, crop=0,0,25%,15%"
MASK_RADIUS = "10%"  # mask=rounded without radius=: of the shorter side
MIRRORS = {"x": (True, False), "y": (False, True), "xy": (True, True), "yx": (True, True)}
OBJECTS = ("qr", "barcode", "pay", "contact", "datamatrix", "pdf417")  # and images: sized by width=, placed by .left…
FRACTIONS = {"full": 1.0, "half": 1 / 2, "third": 1 / 3}  # width=full|half|third on every object
SAID_BY_OBJECT = {"size", "align"}  # object_words already says what to write instead (no second warning)


def _turn(ang: float) -> tuple[float, float]:
    """|cos| and |sin| of a clockwise turn in degrees, exact at right angles (the turned box: w·cos + h·sin)."""
    if ang % 90 == 0:
        return (0.0, 1.0) if ang % 180 else (1.0, 0.0)
    rad = math.radians(ang)
    return abs(math.cos(rad)), abs(math.sin(rad))


def _image_key(src: str, base_dir: str, attrs, extra: tuple):
    """Same file (path, size, modification time) or same URL/data, same attributes -> same dots. None: not cached
    (the file cannot be read now: open_image reports why)."""
    import hashlib
    from pathlib import Path

    attrs_key = tuple(sorted((str(k), str(v)) for k, v in attrs.kv.items())) + tuple(sorted(map(str, attrs.classes)))
    if src.startswith(("https://", "http://")):
        return None  # the download cache (sources) decides when a URL is fetched again; never cached here
    if src.startswith("data:"):
        ident = ("data", hashlib.sha256(src.encode()).hexdigest())
    else:
        try:
            p = (Path(base_dir) / Path(src).expanduser()).resolve()
            st = p.stat()
        except (OSError, ValueError):
            return None
        ident = ("file", str(p), st.st_size, st.st_mtime_ns)
    return ident, attrs_key, extra


def _real(folder):
    from pathlib import Path

    return Path(folder).expanduser().resolve()


def _remember(key, value) -> None:
    if len(_IMAGES) >= _IMAGES_MAX:
        _IMAGES.pop(next(iter(_IMAGES)))
    _IMAGES[key] = value


class Layout:
    def __init__(self, profile, doc: Document, rendered: Rendered | None, nudges: Nudges, net: bool = False,
                 locale=None, image_dirs: tuple[str, ...] | None = None):  # fmt: skip
        self.p, self.doc, self.r, self.n = profile, doc, rendered, nudges
        self.net = net  # https images allowed (only from the command line: --allow-net)
        # --sandbox / MCP: local images only from these folders (None: anywhere)
        self.image_dirs = None if image_dirs is None else tuple(_real(d) for d in image_dirs)
        self.locale = locale  # the job's locales.Choice (payment captions), the same as its templates use
        self.em = Emulator(profile)
        self.W = profile.width_dots
        self.cols = profile.columns
        meta = doc.meta
        self.align = str(meta.get("align", "left"))
        self.size = self.document_size(meta)
        tasks = meta.get("tasks") or {}
        self.done = str(tasks.get("done", "strike")) if isinstance(tasks, dict) else "strike"
        img = meta.get("image") or {}
        self.img = img if isinstance(img, dict) else {}
        fonts = meta.get("fonts") or {}
        self.fonts = {**rasterfont.DEFAULT_ROLES, **(fonts if isinstance(fonts, dict) else {})}
        self._judged: set = set()
        lang = str(meta.get("locale") or meta.get("lang") or "")
        self.scripts = scriptfonts.Resolver(nudges, lang)  # fonts for other scripts, downloaded once
        self.bars: tuple[int, ...] = ()  # the column (at 1x) of the bar of each quote being laid out, outermost first
        self.within = ""  # "column": laid out in a column of :::: {.columns} (narrow)
        self.wrapping = False  # those columns move what does not fit (wrap=wrap): a hint does not suggest it
        self.tall_max: int | None = None  # in a turned label: its height, which a code is laid out to fit
        self.dark = False  # laid out inside a ::: {.box .invert}: printed white on black
        self.dark_lost = False  # ... and in turned columns there: a code's tile is turned with them, not kept

    # ------------------------------------------------------------ quotes
    def bars_in(self, gutter: int) -> list[int]:
        """The quote bars that a row indented `gutter` columns (at 1x) has room for: only the quotes it is inside
        of, never over its own text (a code's caption laid out at no indent in a quote gets none)."""
        return [c for c in self.bars if c + QUOTE_GUTTER <= gutter]

    def lead(self, cols: int, gutter: int | None = None) -> list[Cell]:
        """`cols` blank cells for the start of a 1x line, with the bar │ of each quote it is inside of."""
        cells = [Cell(" ") for _ in range(cols)]
        for c in self.bars_in(cols if gutter is None else gutter):
            cells[c] = Cell(QUOTE_BAR)
        return cells

    def draw_bars(self, im: Image.Image, gutter: int, ink: int, rtl: bool = False) -> Image.Image:
        """The quote bars drawn into a row printed as an image, where the printer font draws │ in a 1x cell (right
        to left: mirrored, on the side where the text starts). ink 0 is black; 255 white, across an inverted band."""
        cw = self.p.cell[0]
        stroke = max(2, int(self.p.get("raster.min_stroke_dots", 2)))
        draw = ImageDraw.Draw(im)
        for c in self.bars_in(gutter):
            x = c * cw + cw // 2 - 1
            x = im.width - x - stroke if rtl else x
            draw.rectangle((x, 0, x + stroke - 1, im.height - 1), fill=ink)
        return im

    def view_with_bars(self, cells: list[Cell], gutter: int, rtl: bool = False) -> list[Cell]:
        """What the terminal views show for a row printed as an image: its words after the bars (before them, right
        to left), every letter (a smaller font has more of them than the paper's columns: the views widen)."""
        lead = self.lead(gutter)
        if not any(c.ch == QUOTE_BAR for c in lead):
            return cells
        return [*cells, *reversed(lead)] if rtl else [*lead, *cells]

    # ------------------------------------------------------------ helpers
    def document_size(self, meta: dict) -> str:
        """The front matter's size: (normal when absent). One it cannot read is said once, at its line, and every
        block uses normal instead (never one problem per block)."""
        size = str(meta.get("size", "normal"))
        m = MULTIPLIER_RE.match(size)
        if m and not all(1 <= int(k) <= GS_MAX for k in m.groups(m.group(1))):
            self.n.add("M101", f"size: {size} in the front matter: the printer font takes 1x to {GS_MAX}x, normal is "
                       "used", self.doc.meta_lines.get("size"), MULTIPLIER_HINT)  # fmt: skip
            return "normal"
        if size in self.p.get("native.sizes", {}) or rasterfont.readable(size, self.p):
            return size
        self.n.add("M101", f"size: {size} in the front matter is not a size: normal is used",
                   self.doc.meta_lines.get("size"), rasterfont.SIZE_HINT)  # fmt: skip
        return "normal"

    def text(self, s: str) -> str:
        if self.r is not None:
            s = self.r.resolve(s)
        s = RESERVED_CHARS.sub("", s)  # a placeholder a template cut in two: never printed as a glyph
        return CTRL.sub("", s.replace("\t", "    ")).translate(SPACES)

    def scale_for(self, size: str | None, line: int, fallback: tuple[int, int] | None = None,
                  span: bool = False) -> tuple[int, int]:  # fmt: skip
        """A size= as printer-font multipliers (width, height). A multiplier GS ! cannot take (0x, 9x): M101 and
        `fallback` (a span: its line's; a heading: its own), else the document's size. span: said as a span's."""
        if not size:
            size = self.size
        named = self.p.get("native.sizes", {})
        if size in named:
            return tuple(named[size])
        m = MULTIPLIER_RE.match(size)
        if m:
            w = int(m.group(1))
            h = int(m.group(2) or m.group(1))
            if 1 <= w <= GS_MAX and 1 <= h <= GS_MAX:
                return (w, h)
            where = " on a span" if span else ""
            self.n.add("M101", f"size={size}{where}: the printer font takes 1x to {GS_MAX}x", line, MULTIPLIER_HINT)
            return fallback or (self.scale_for(None, line) if size != self.size else (1, 1))
        m = UNIT_RE.match(size)
        if m:
            v = float(m.group(1))
            dots = v if m.group(2) == "px" else self.p.mm_to_dots(v)
            s = max(1, min(4, round(dots / self.p.cell[1])))
            said = f"on a span: the printer font's nearest, {s}x" if span else f"printed natively at {s}x"
            self.n.add("F303", f"size {size} {said}", line,
                       "set a raster font (fonts: body: Atkinson Hyperlegible) for exact sizes")  # fmt: skip
            return (s, s)
        self.n.add("M101", f"unknown size '{size}'", line, "small, normal, large, title, huge, 2x, 1x2, 20px, 3mm")
        return (1, 1)

    @staticmethod
    def stretch(size) -> tuple[int, int] | None:
        """(width, height) of a printer multiplier taller than wide or wider than tall (1x2, 2x1): the printer font
        stretches its cells (GS !) and keeps its columns, where a raster font can only scale evenly (F303)."""
        m = SIZE_RE.match(str(size or ""))
        wh = (int(m.group(1)), int(m.group(2))) if m and m.group(2) else (0, 0)
        return wh if min(wh) > 0 and wh[0] != wh[1] else None  # 1x0: a size of nothing (F205, as before)

    def jagged(self, scale: tuple[int, int], line: int) -> None:
        """F303 for a multiplier the printer draws jagged (above 4x on most)."""
        ok = self.p.get("native.scales_ok", [1, 2, 3, 4])
        if scale[0] not in ok or scale[1] not in ok:
            self.n.add("F303", f"size {scale[0]}x{scale[1]} is jagged on this printer", line, "use up to 4x", "N1")

    def cells_from_runs(self, runs: list[Run], extra: dict, sized=None) -> list[Cell | None]:
        """Runs -> cells; None marks a forced line break. sized(run): the GS ! size of a span's own size= (None:
        the line's), kept on each of its cells."""
        out: list[Cell | None] = []
        for r in runs:
            if r.text == "\n":
                out.append(None)
                continue
            own = sized(r) if sized and r.size else None
            for ch in self.text(r.text):
                if ch == "\n":
                    out.append(None)
                    continue
                out.append(
                    Cell(
                        ch,
                        bold=r.bold or extra.get("bold", False),
                        underline=r.underline or extra.get("underline", False),
                        invert=r.invert,
                        italic=r.italic or extra.get("italic", False),
                        strike=r.strike or extra.get("strike", False),
                        wide=is_wide(ch),
                        scale=own,
                    )
                )
        return out

    def wrap(self, cells: list[Cell | None], cap: int, hang: int, line: int, measure=columns,
             unit: int = 1) -> list[list[Cell]]:  # fmt: skip
        """Greedy word wrap on columns; `hang` columns already used on continuation lines. measure, unit: a line
        whose spans have their own size is measured in dots (cap too), `unit` dots to a column of the line."""

        def split(word, at):
            hint = "shorten it or use a smaller size"
            self.said_cut("".join(c.ch for c in word), f"{at // unit} columns", line, hint)

        lines: list[list[Cell]] = []
        para: list[Cell] = []
        for c in cells:
            if c is None:
                lines += wrap_words(word_tokens(para), cap, hang, split, measure)
                para = []
            else:
                para.append(c)
        return lines + wrap_words(word_tokens(para), cap, hang, split, measure)

    def said_cut(self, word: str, at: str, line: int, hint: str, around: str = "") -> None:
        """L101 for a word longer than the line, cut to fill lines (`at`: the line's width, as it is counted); an
        address is better carried by a QR code (looked for in `around` too: a table cell's whole text, as its words
        reach wrap_words in pieces)."""
        if any(m in (word + " " + around).lower() for m in ("://", "www.")):
            hint += "; a ```qr block carries the address whole"
        self.n.add("L101", f"word '{''.join(icons.shown(ch) for ch in word)[:20]}…' split at {at}", line, hint)

    def native_ok(self, cells: list[Cell]) -> str:
        """'' if the line can be printed natively, else the reason. Letters of a span's own size: GS ! would stand
        each size on its cells' feet, not on one baseline, so the line is drawn in the printer font's look."""
        icon = False
        for c in cells:
            if c.italic:
                return "italic"
            if c.strike:
                return "strike"
            if c.ch in CHECKBOX:
                return "checkbox"
            if icons.is_icon(c.ch):
                icon = True  # drawn; a glyph the printer lacks later in the line must still be said (F301)
                continue
            if c.ch != " " and not self.p.native_glyph(c.ch):
                return f"glyph {c.ch}"
        if any(c.scale for c in cells):  # after the reasons that are said (a glyph the printer lacks: F301)
            return "sizes"
        return "icon" if icon else ""

    def drawn_whole(self, runs) -> str:
        """The first letter that makes a native block go raster as a whole ('' for none): one the printer lacks
        and that cannot be drawn cell by cell (a script that shapes or runs right to left), or that only a
        script font has (Chinese on a printer without it)."""
        decided: dict[str, tuple[bool, bool]] = {}  # script -> (shapes, a script font draws it): once per script
        for r in runs:
            for ch in self.text(r.text):
                if ch.isspace() or self.p.native_glyph(ch) or ch in CHECKBOX or icons.is_icon(ch):
                    continue
                s = scriptfonts.script_of(ch)
                if s not in decided:
                    decided[s] = (s not in scriptfonts.SIMPLE, bool(scriptfonts.packs_for(s)))
                shapes, has_font = decided[s]
                if shapes or (has_font and not self.em.has_glyph(ch)):
                    return ch
        return ""

    def attr_dots(self, attrs, key: str, line: int, hi: int) -> int | None:
        """`key=N` (dots), `Npx` or `Nmm` -> dots, or None when absent/invalid (M101)."""
        v = attrs.kv.get(key)
        if v is None:
            return None
        m = UNIT_RE.match(str(v)) or re.match(r"^(\d+)()$", str(v))
        if not m:
            self.n.add("M101", f"{key}={v}", line, f"{key}=4, {key}=4px or {key}=1mm")
            return None
        n = float(m.group(1))
        dots = self.p.mm_to_dots(n) if m.group(2) == "mm" else round(n)
        if dots > hi:
            self.n.add("M101", f"{key}={v} is too large: using {hi} dots", line)
            dots = hi
        return int(dots)

    def family(self, name: str | None) -> str:
        name = name or "native"
        return str(self.fonts.get(name, name))

    def raster_family(self, attrs, role: str, runs) -> str | None:
        """Font family for a raster block, or None when the block stays native."""
        render = attrs.kv.get("render")
        if render == "native":  # explicit: printer font, even if a role says otherwise
            return None
        fam = self.family(attrs.kv.get("font") or self.fonts.get(role, "native"))
        span_fonts = any(r.font and self.family(r.font).lower() != "native" for r in runs)
        if fam.lower() == "native":
            return "Spleen" if (span_fonts or render == "raster") else None
        return fam

    def font_path(self, family: str, bold: bool, px: int, line: int) -> str:
        ref = rasterfont.resolve(family, bold)
        if ref is None:
            self.n.add(
                "F203",
                f'font "{family}" not found: using Atkinson Hyperlegible',
                line,
                "install it, or use a bundled font (bobina fonts list)",
            )
            ref = rasterfont.resolve("Atkinson Hyperlegible", bold)
        key = (family.lower(), px, bold)
        if key not in self._judged:
            self._judged.add(key)
            rasterfont.judge(family, ref, px, bold, self.n, line)
        return ref.path

    def script_parts(self, piece: str, path: str, fallback: str, line, context: str) -> list[tuple[str, str]]:
        """A word the block's font cannot draw -> [(text, font file)]: the block's font, the bundled fallback,
        else the font for that script (downloaded once, scriptfonts). Mixed text (Olá(สวัสดี)) picks per run;
        digits and punctuation the script font lacks come from the block's font."""
        fb = rasterfont.cmap(fallback)
        if all(ord(ch) in fb for ch in piece if not ch.isspace()):
            return [(piece, fallback)]
        parts: list[tuple[str, str]] = []

        def add(txt: str, pth: str):
            if parts and parts[-1][1] == pth:
                parts[-1] = (parts[-1][0] + txt, pth)
            else:
                parts.append((txt, pth))

        for script, txt in scriptfonts.split_runs(piece):
            own = next((f for f in (path, fallback) if scriptfonts.covers(f, txt)), None)
            if own is not None:
                add(txt, own)
                continue
            pth = None if script in scriptfonts.NEUTRAL else self.scripts.path(script, txt, line, context)
            told = pth is None and bool(scriptfonts.packs_for(script))  # F305 said why: no F302 on top of it
            miss = []
            for ch in txt:
                if parts and unicodedata.category(ch).startswith("M"):  # a mark stays with its letter
                    add(ch, parts[-1][1])
                    continue
                f = next((f for f in (pth, path, fallback) if f and scriptfonts.covers(f, ch)), None)
                if f is None:
                    f = pth or fallback
                    miss.append(ch)
                add(ch, f)
            if miss and not told:
                self.n.add(
                    "F302",
                    f"glyph(s) {''.join(dict.fromkeys(miss))} missing in every font",
                    line,
                    self.scripts.hints.get(script, ""),
                )
        return parts

    def raster_block(
        self,
        runs,
        fam: str,
        *,
        line,
        attrs,
        px: int,
        bold: bool,
        extra: dict,
        prefix: list[Cell] | None,
        indent: int,
        tracking: int = 0,
        leading: int | None = None,
        indent_dots: int = 0,
    ) -> list:
        toks: list = []
        fallback = rasterfont.resolve("DejaVu Sans").path
        context = "".join(r.text for r in runs)  # Han next to kana is Japanese (scriptfonts.packs_for)
        for r in runs:
            if r.text == "\n":
                toks.append(rasterfont.Tok("", fallback, px, brk=True))
                continue
            rfam = self.family(r.font) if r.font else (self.family("code") if r.mono else fam)
            if rfam.lower() == "native":
                rfam = "Spleen"
            b = r.bold or bold or extra.get("bold", False)
            rpx = rasterfont.px_for(r.size, self.p, px, self.n, line) if r.size else px
            path = self.font_path(rfam, b, rpx, line)
            text = self.text(r.text)
            for piece in re.split(r"( +|\n)", text):
                if not piece:
                    continue
                if piece == "\n":
                    toks.append(rasterfont.Tok("", path, rpx, brk=True))
                    continue
                cm = rasterfont.cmap(path)
                parts = []
                for seg in re.split(ICON_SPLIT, piece):  # icons: their own tokens, glued to the word around them
                    if not seg:
                        continue
                    if icons.is_icon(seg):
                        parts.append((seg, path))
                    elif cm and any(ord(ch) not in cm for ch in seg if not ch.isspace()):
                        parts += self.script_parts(seg, path, fallback, line, context)
                    else:
                        parts.append((seg, path))
                for k, (txt, pth) in enumerate(parts):
                    toks.append(
                        rasterfont.Tok(
                            txt,
                            pth,
                            rpx,
                            bold=b,
                            italic=r.italic or extra.get("italic", False),
                            underline=r.underline or extra.get("underline", False),
                            strike=r.strike or extra.get("strike", False),
                            invert=r.invert,
                            space=txt.isspace(),
                            glue=k > 0,  # the parts of one word stay on one line
                            icon=icons.name_of(txt) or "" if len(txt) == 1 else "",
                        )
                    )
        rtl = scriptfonts.base_rtl(self.text(context))
        pimg = None
        if prefix:
            ptxt = "".join(c.ch for c in prefix)
            if rtl:  # the bullet goes on the right: its space between it and the first letter
                ptxt = " " * (len(ptxt) - len(ptxt.rstrip())) + ptxt.rstrip()
            if prefix[0].ch in CHECKBOX:
                pimg = rasterfont.checkbox(px, prefix[0].ch != "☐")
                if rtl:  # its gap on the inner side, next to the first letter
                    box = pimg.crop((0, 0, pimg.width - 6, pimg.height))
                    pimg = Image.new("L", pimg.size, 255)
                    pimg.paste(box, (6, 0))
            else:
                t = rasterfont.Tok(ptxt, self.font_path(fam, False, px, line), px)
                asc, desc = t.font.getmetrics()
                pimg = rasterfont.draw_tok(t, asc, asc + desc, px)
        align = attrs.kv.get("align") or next(
            (a for a in ("center", "right", "left", "justify") if attrs.has(a)),
            "right" if rtl and "align" not in self.doc.meta else self.align,  # Arabic, Hebrew: from the right
        )
        if leading is None:
            leading = max(2, round(px * 0.25))
        for t in toks:  # letters that join or stack are never spaced apart: tracking stays off for them
            t.tracking = 0 if tracking and scriptfonts.shaped(t.text) else tracking
        if tracking and any(scriptfonts.shaped(t.text) for t in toks):
            self.n.add(
                "M103",
                "tracking= is ignored for letters that join, stack or run right to left (Thai, Arabic, Devanagari…)",
                line,
                "nothing to fix; the other words keep their spacing",
            )
        if not toks:
            return []

        def split(word, room):  # a word wider than the line, cut: its width in columns of its font (its digit)
            t = next((t for t in word if not t.icon), word[0])
            cols = room * 10 // max(1, replace(t, text="0" * 10, icon="", italic=False).width())  # no slant
            name = f"{fam} {t.px}px"  # the block's font: a word in a run of another font= is rare
            smaller = "use a smaller size (size=12px) or " if t.px > 12 else ""
            self.said_cut("".join(x.text for x in word), f"{cols} columns in {name}", line,
                          f"{smaller}add a space or a hyphen to the word")  # fmt: skip

        room = self.W - indent * self.p.cell[0] - indent_dots - (pimg.width if pimg else 0)  # render_block's
        if room < rasterfont.letter_width(toks):  # as the printer font says it (layout_lines cuts nothing then)
            self.n.add(
                "L101", "indent and letter spacing leave no room on the line", line, "reduce indent= or tracking="
            )
        im, texts = rasterfont.render_block(
            toks, self.W, align, leading, pimg, indent * self.p.cell[0] + indent_dots, rtl=rtl, split=split
        )
        view_rows = [
            TextRow(
                self.view_with_bars(self.view_cells(t, room), indent, rtl),
                (1, 1),
                "left" if align == "justify" else align,
                line,
            )  # fmt: skip
            for t in texts
        ]
        wide = self.smaller_font(toks) and any(r.columns() > self.cols for r in view_rows)  # the views widen
        if (attrs.has("invert") or self.dark) and (px < int(self.p.get("raster.invert_min_px", 20)) or not bold):
            self.n.add(  # white on black, in its own band or in an inverted box
                "F204",
                f"inverted text at {px}px{'' if bold else ' (not bold)'} closes up",
                line,
                "use bold and ≥ 20px",
                "R2-12",
            )
        if attrs.has("invert"):
            m = int(self.p.get("raster.invert_margin_dots", 4))
            band = Image.new("L", (self.W, im.height + 2 * m), 255)
            band.paste(im.convert("L"), (0, m))
            band = self.draw_bars(band, indent, 0, rtl)  # black here: white once the band is inverted
            return [BitmapRow(ImageOps.invert(band).convert("1", dither=Image.NONE), line, "band", view_rows,
                              wide_view=wide)]  # fmt: skip
        return [BitmapRow(self.draw_bars(im, indent, 0, rtl), line, "text", view_rows, wide_view=wide)]

    def view_cells(self, toks, room: int) -> list[Cell]:
        """A line of drawn text as cells for the terminal views, every letter the paper shows (in a smaller font,
        more than the paper's columns: the views widen), a letter or icon wider than the line's `room` dots (left
        whole by layout_lines, which cuts longer words onto new lines) cut where the paper cuts it. Inverted words
        stay inverted (the rest of a drawn line is plain, as on paper)."""
        out, x = [], 0
        for t in toks:
            w = t.width()
            k = len(t.text)
            while k and x + w > room and replace(t, text=t.text[:k]).width() > room - x:
                k -= 1  # the letters whose advance ends on the paper (render_block draws past it: the paper cuts it)
            out += [Cell(ch, wide=is_wide(ch), invert=t.invert) for ch in t.text[:k]]
            x += w
        return out

    def smaller_font(self, toks) -> bool:
        """Text drawn in a smaller font than the printer's: a digit narrower than a printer column (Terminus 16px: 8
        dots of 12), so its lines can hold more letters than the paper's columns and the views widen for them. A
        proportional font at the same size or larger keeps the paper's columns (a long line cut with …). An icon
        (two columns in the views) counts when it is drawn narrower than two printer columns."""
        drawn = [t for t in toks if t.text.strip()]
        cell = self.p.cell[0]
        return bool(drawn) and all(t.width() < 2 * cell if t.icon else replace(t, text="0").width() < cell
                                   for t in drawn)  # fmt: skip

    def text_block(
        self,
        runs,
        *,
        line,
        attrs,
        scale=None,
        bold=False,
        prefix: list[Cell] | None = None,
        indent: int = 0,
        extra=None,
        role: str = "body",
        level: int = 0,
    ) -> list:
        extra = dict(extra or {})
        if self.dark and attrs.has("invert"):  # its band would print black on white in the box's black
            self.n.add("M101", ".invert does nothing inside an inverted box: its text is white on black already",
                       line, "remove .invert here")  # fmt: skip
            attrs = Attrs(attrs.classes - {"invert"}, dict(attrs.kv))
        tracking = self.attr_dots(attrs, "tracking", line, 32) or 0
        leading = self.attr_dots(attrs, "leading", line, 200)
        raw_indent = str(attrs.kv.get("indent", ""))
        indent_dots = self.attr_dots(attrs, "indent", line, self.W // 2) or 0
        indent_is_columns = raw_indent.isdigit()  # indent=4 means 4 columns; 4px / 2mm are physical
        fam = self.raster_family(attrs, role, runs)
        # render=raster on the printer font at 1x2 or 2x1: its stretched cells, drawn as the printer draws them
        # (a raster font cannot stretch: it would scale evenly)
        emulated = bool(
            fam == "Spleen"
            and attrs.kv.get("render") == "raster"
            and self.stretch(attrs.kv.get("size"))
            and self.family(attrs.kv.get("font") or self.fonts.get(role, "native")).lower() == "native"
            and not any(r.font or r.mono or r.size for r in runs)
        )  # a span's own font or size: raster
        if emulated:
            fam = None
        if fam is not None:
            named = {1: "title", 2: "large", 3: "normal"}.get(level) if role == "title" else None
            fallback = rasterfont.px_for(named or self.size, self.p, 20)  # an unreadable size= falls back to it
            px = rasterfont.px_for(attrs.kv.get("size") or named or self.size, self.p, fallback, self.n, line)
            return self.raster_block(
                runs,
                fam,
                line=line,
                attrs=attrs,
                px=px,
                bold=bold or attrs.has("bold"),
                extra={**extra, **{k: True for k in ("italic", "underline", "strike") if attrs.has(k)}},
                prefix=prefix,
                indent=indent,
                tracking=tracking,
                leading=leading,
                indent_dots=indent_dots * (self.p.cell[0] if indent_is_columns else 1),
            )
        drawn = self.drawn_whole(runs)
        if drawn:  # Thai, Arabic, Devanagari…: letters join, stack or run right to left, so never cell by cell
            scale = scale or self.scale_for(attrs.kv.get("size"), line)
            self.n.add(
                "F301",
                f"glyph {drawn} is not in the printer font: line printed as an image",
                line,
                "keep it (fine) or use a character from the native set",
            )
            return self.raster_block(
                runs,
                "Spleen",  # the printer font's look for the letters it has
                line=line,
                attrs=attrs,
                px=self.p.cell[1] * scale[1],
                bold=bold or attrs.has("bold"),
                extra={**extra, **{k: True for k in ("italic", "underline", "strike") if attrs.has(k)}},
                prefix=prefix,
                indent=indent,
                tracking=tracking,
                leading=leading,
                indent_dots=indent_dots * (self.p.cell[0] if indent_is_columns else 1),
            )
        if bold or attrs.has("bold"):
            extra["bold"] = True
        for k in ("italic", "underline", "strike"):
            if attrs.has(k):
                extra[k] = True
        scale = scale or self.scale_for(attrs.kv.get("size"), line)
        self.jagged(scale, line)
        align = attrs.kv.get("align") or next(
            (a for a in ("center", "right", "left", "justify") if attrs.has(a)), self.align
        )
        sizes: dict[str, tuple[int, int]] = {}

        def sized(r: Run) -> tuple[int, int] | None:  # a span's size= as the line's size= maps it (F303, M101)
            if r.size not in sizes:
                own = self.scale_for(r.size, line, scale, span=True)  # one GS ! cannot take: the line's
                self.jagged(own, line)
                sizes[r.size] = own
            return None if sizes[r.size] == scale else sizes[r.size]

        cells = self.cells_from_runs(runs, extra, sized)
        prefix = prefix or []
        pw = columns(prefix)
        advance = self.p.cell[0] * scale[0] + self.p.tracking_gap(tracking, scale[0])  # as the printer spaces them
        measure, unit = columns, 1  # columns of the line's size; spans of their own size: dots
        if any(c is not None and c.scale for c in cells):

            def measure(cs: list[Cell]) -> int:
                return sum((2 if c.wide else 1) * self.p.cell[0] * (c.scale or scale)[0]
                           + self.p.tracking_gap(tracking, (c.scale or scale)[0]) for c in cs)  # fmt: skip

            unit = advance
        gutter = indent  # columns at 1x: quote gutters and list indents
        quoted = bool(self.bars_in(gutter))
        drawn_bars = quoted and scale[0] > 1  # a 2x line cannot hold a 1x │: drawn into it as an image
        if drawn_bars:  # the same gutter in wider columns: only as much as it takes, not 2x of it
            indent = -(-indent // scale[0])
        if indent_dots:
            indent += indent_dots if indent_is_columns else round(indent_dots / advance)
        cap = self.W // advance - indent
        if cap - pw < 1:
            self.n.add(
                "L101", "indent and letter spacing leave no room on the line", line, "reduce indent= or tracking="
            )
            cap = pw + 1
        tallest = max([scale[1], *(c.scale[1] for c in cells if c is not None and c.scale)])
        if leading is not None and self.p.cell[1] * tallest + leading > 255:
            self.n.add("M101", f"leading={leading} too large for {tallest}x height", line)
        lines = self.wrap(cells, (cap - pw) * unit, 0, line, measure, unit)
        rows = []
        for i, lc in enumerate(lines):
            if align == "justify" and i < len(lines) - 1:
                lc = _justify(lc, (cap - pw) * unit, measure, unit)
            lead = (self.lead(indent, gutter) if not drawn_bars else [Cell(" ")] * indent) + (
                prefix if i == 0 else [Cell(" ")] * pw
            )
            row_align = "left" if align == "justify" else align
            if quoted and row_align != "left":  # centred in the room after the bar, never the bar with it
                free = max(0, (cap - pw) * unit - measure(lc)) // unit
                lead += [Cell(" ")] * (free // 2 if row_align == "center" else free)
                row_align = "left"
            cells_line = lead + lc
            own, line_scale = {c.scale for c in cells_line}, scale
            if len(own) == 1 and None not in own:  # a line all of one span's size: that size is the line's
                line_scale = own.pop()
                cells_line = [replace(c, scale=None) for c in cells_line]
            reason = self.native_ok(cells_line)
            if reason.startswith("glyph"):
                self.n.add(
                    "F301",
                    f"{reason} is not in the printer font: line printed as an image",
                    line,
                    "keep it (fine) or use a character from the native set",
                )
                for c in cells_line:
                    if c.ch != " " and c.ch not in CHECKBOX and not icons.is_icon(c.ch) and not self.em.has_glyph(c.ch):
                        self.n.add("F302", f"glyph {c.ch} is missing in every font: printed as a box", line)
            rows.append(
                TextRow(
                    cells_line,
                    line_scale,
                    row_align,
                    line,
                    native=not reason,
                    reason=reason,
                    tracking=tracking,
                    gap=leading,
                )
            )
        if emulated and not attrs.has("invert") and not drawn_bars:
            return [BitmapRow(self.em.render_row(r, self.W), line, "text", [r]) for r in rows]
        if attrs.has("invert"):
            band = self.band(rows, line)
            self.draw_bars(band.image, gutter, 255)  # white, from edge to edge of the band (its margins too)
            return [band]
        if drawn_bars:
            return [
                BitmapRow(
                    self.draw_bars(self.em.render_row(r, self.W), gutter, 0),
                    line,
                    "text",
                    [self.quoted_view(r, indent, gutter)],
                )
                for r in rows
            ]
        if quoted:  # a span's size= makes a line taller than its │: the bars drawn its whole height, as at 2x
            return [self.tall_quoted(r, gutter) if r.height() > r.scale[1] else r for r in rows]
        return rows

    def quoted_view(self, row: TextRow, indent: int, gutter: int) -> TextRow:
        """What the views show for a quoted line wider than 1x (its bars drawn into it): its letters at 1x after
        the bars; with spans of their own size, every letter at its size (the line's letters at the line's)."""
        cells = row.cells[indent:]
        if row.mixed():
            cells = [c if c.scale else replace(c, scale=row.scale) for c in cells]
        return replace(row, cells=[*self.lead(gutter), *cells], scale=(1, 1), align="left")

    def tall_quoted(self, row: TextRow, gutter: int) -> BitmapRow:
        """A quoted line taller than its 1x │ (a span's own size): printed as an image with the quote bars drawn
        from its top to its foot; the views show its letters as they are, the bars on each of their lines."""
        bare = replace(row, cells=[replace(c, ch=" ") if c.ch == QUOTE_BAR else c for c in row.cells])
        return BitmapRow(self.draw_bars(self.em.render_row(bare, self.W), gutter, 0), row.line, "text", [row])

    def band(self, rows: list[TextRow], line: int) -> BitmapRow:
        """Continuous inverted band (GS B leaves spaces white, so it goes raster)."""
        m = int(self.p.get("raster.invert_margin_dots", 4))
        imgs = [self.em.render_row(r, self.W).convert("L") for r in rows]
        out = imaging.vstack(imgs, self.W, "L", margin=m)
        return BitmapRow(ImageOps.invert(out).convert("1", dither=Image.NONE), line, "band", rows)

    # ------------------------------------------------------------ blocks
    def run(self) -> list:
        rows: list = [FeedRow(int(self.p.get("margins.top_dots", 24))), *self.blocks(self.doc.blocks, 0)]
        feed = int(self.p.get("margins.feed_after_dots", 96))
        tear_at = None
        if self.p.get("marks", "none") in ("tear", "both"):  # printed so that the feed leaves it on the tear bar
            tear_at = max(0, feed - min(feed, max(1, int(self.p.get("margins.tear_dots", 40)))))  # 1 dot after it
        rows.append(FeedRow(feed, mark="tear", tear_at=tear_at))
        return rows

    def blocks(self, blocks, indent: int) -> list:
        """Blocks one under the other, the block gap between them (none before a paragraph's next lines): the
        document's, and the ones inside a ::: block."""
        rows: list = []
        gap = int(self.p.get("margins.block_gap_dots", 12))
        for b in blocks:
            out = self.block(b, indent)
            if not out:
                continue
            if rows and not (isinstance(b, Paragraph) and b.follows):
                rows.append(FeedRow(gap))
            rows += out
        return rows

    @contextlib.contextmanager
    def narrow(self, width: int, within: str = ""):
        """Lays out as if the paper were `width` dots wide (inside a box or a column): text wraps, objects fit and %
        sizes are of that width. A QR code there is part of the box's image, so it is sized as an image (qr.native
        off). within: "column" when a wider room is the fix a problem suggests (a QR squeezed in a column)."""
        saved = self.p, self.W, self.cols, self.bars, self.within
        qr = {**(self.p.get("qr") or {}), "native": False}
        self.p = replace(self.p, width_dots=width, data={**self.p.data, "qr": qr})
        self.W, self.cols, self.bars, self.within = width, self.p.columns, (), within
        try:
            yield
        finally:
            self.p, self.W, self.cols, self.bars, self.within = saved

    def block(self, b, indent: int) -> list:
        rows = self._block(b, indent)
        a = getattr(b, "attrs", None)
        if a is None or not rows:
            return rows
        if isinstance(b, ImageBlock) or (isinstance(b, Fence) and (b.kind or "").lower() == "image"):
            return rows  # images turn their source (Layout.turn): the paper width applies after the turn
        for name in IMAGE_ONLY:  # mirror= is not a key of other blocks: the parser already said "unknown key"
            if a.has(name) or (name in a.kv and name != "mirror"):
                self.n.add("M101", f"'{name}' works on images only: it does nothing here", b.line, "remove it")
        if isinstance(b, Div) and b.attrs.has("box") and getattr(rows[0], "kind", "") == "box":
            return rows  # a box turns itself (Layout.box): placed as written, the quote bars upright
        if isinstance(b, Div) and b.attrs.has("columns") and any(isinstance(r, BitmapRow) and r.columns
                                                                and r.columns.turned for r in rows):  # fmt: skip
            return rows  # turned columns are a turned label already: rotate= and .flip ignored (columns_orientation)
        raws = [r for r in rows if isinstance(r, RawRow)]  # bytes cannot be turned: sent after the turned block
        rows = [r for r in rows if not isinstance(r, RawRow)]
        if not rows:
            return raws
        if a.has("flip") and not a.kv.get("rotate") and all(isinstance(r, TextRow) and r.native for r in rows):
            for r in rows:
                r.upside_down = True
            return [*reversed(rows), *raws]
        ang = self.angle(a, b.line)
        return [self.rotate(rows, ang, a, b.line), *raws] if ang % 360 else [*rows, *raws]

    def angle(self, attrs, line: int, image: bool = False) -> float:
        """rotate= (clockwise, like CSS; any angle, B102 when not a right angle) or .flip (180), in degrees. An
        image turned by any angle is fitted to the paper whole (I110 says when its corners make it smaller)."""
        rot = attrs.kv.get("rotate")
        if not rot:
            return 180.0 if attrs.has("flip") else 0.0
        try:
            ang = float(rot)
            if not math.isfinite(ang):  # nan, inf: no turn PIL can draw (it raised)
                raise ValueError
        except ValueError:
            self.n.add("M101", not_a_value("rotate", rot, "not turned"), line, "0, 90, 180, 270 or degrees")
            return 0.0
        if ang % 90 and not image:
            self.n.add("B102", f"rotate={ang:g}: slanted strokes look jagged at {self.p.dpi} dpi", line,
                       "prefer 90/180/270")  # fmt: skip
        return ang

    def compose(self, rows) -> Image.Image:
        return self.stacked([preview.row_image(r, self.p, self.em) for r in rows], self.W)

    def rotate(self, rows, ang: float, attrs, line: int) -> BitmapRow:
        pics = [preview.row_image(r, self.p, self.em) for r in rows]
        im = self.stacked(pics, self.W)
        codes = _code_spans(rows, pics)
        keep, darks = _stacked_rects(rows, pics, "keep"), _stacked_rects(rows, pics, "dark")
        box = ImageOps.invert(im).getbbox()
        if box:
            im = im.crop(
                (max(0, box[0] - 4), max(0, box[1] - 4), min(im.width, box[2] + 4), min(im.height, box[3] + 4))
            )
            codes = tuple((a - max(0, box[1] - 4), b - max(0, box[1] - 4), k) for a, b, k in codes)
            dx, dy = -max(0, box[0] - 4), -max(0, box[1] - 4)
            keep, darks = _moved(keep, dx, dy), _moved(darks, dx, dy)
        size = im.size
        im = im.rotate(
            -ang,
            expand=True,
            fillcolor=255,  # minus: clockwise, like CSS
            resample=Image.NEAREST if ang % 90 == 0 else Image.BICUBIC,
        )
        keep, darks = self.turned_rects(keep, size, ang, line), _turned_rects(darks, size, ang) or ()
        if im.width > self.W:
            self.n.add(
                "L104",
                f"rotated block is {im.width} dots wide: cropped to {self.W}",
                line,
                "shorten the lines or use rotate=90/270",
            )
            cut = (im.width - self.W) // 2
            im = im.crop((cut, 0, cut + self.W, im.height))
            keep, darks = _moved(keep, -cut, 0), _moved(darks, -cut, 0)
        align = attrs.kv.get("align") or next((x for x in ("left", "right", "center") if attrs.has(x)), "center")
        bw = im.point(lambda v: 0 if v < 128 else 255).convert("1", dither=Image.NONE)
        marks = tuple(sorted({u for r in rows if isinstance(r, BitmapRow) for u in r.untested}))  # P301 stays
        spans = _turned_spans(codes, bw.height, ang)
        at = max(0, {"left": 0, "right": self.W - bw.width}.get(align, (self.W - bw.width) // 2))
        return BitmapRow(imaging.place(bw, self.W, align), line, "rotated", untested=marks, code_spans=spans,
                         keep=_moved(keep, at, 0), dark=_moved(darks, at, 0))  # fmt: skip

    def _block(self, b, indent: int) -> list:
        if isinstance(b, Heading):
            h = self.p.get(f"native.headings.h{min(b.level, 3)}", {"scale": [1, 1], "bold": True})
            scale = tuple(h["scale"])
            scale = self.scale_for(b.attrs.kv["size"], b.line, scale) if "size" in b.attrs.kv else scale
            return self.text_block(
                b.runs,
                line=b.line,
                attrs=b.attrs,
                scale=scale,
                bold=h.get("bold", True),
                indent=indent,
                role="title",
                level=b.level,
            )
        if isinstance(b, Paragraph):
            return self.text_block(b.runs, line=b.line, attrs=b.attrs, indent=indent)
        if isinstance(b, ListBlock):
            return self.list_block(b, indent)
        if isinstance(b, Quote):  # the children wrap QUOTE_GUTTER columns in; the bar goes in the first of them
            outer = self.bars
            self.bars = (*outer, indent)
            try:
                return [r for c in b.children for r in self.block(c, indent + QUOTE_GUTTER)]
            finally:
                self.bars = outer
        if isinstance(b, Divider):
            return [self.divider(b)]
        if isinstance(b, Fence):
            return self.fence(b, indent)
        if isinstance(b, ImageBlock):
            return self.image(b.src, b.attrs, b.line, b.alt)
        if isinstance(b, Table):  # a chart, or rows from a data= file: charts.py
            return charts.table_block(self, b, indent) if charts.claims(b) else self.table(b, indent)
        if isinstance(b, Div):
            if b.attrs.has("columns"):
                return self.columns(b, indent)
            if b.attrs.has("box"):
                return self.box(b, indent)
            takes = BLOCK_TAKES
            if b.attrs.has("column"):  # a column outside columns: what it holds, one block under the other
                self.n.add("M101", "::: {.column} outside :::: {.columns}: its blocks print one under the other",
                           b.line, "put the columns in :::: {.columns} … ::::")  # fmt: skip
                takes = (takes[0] | COLUMN_TAKES[0], takes[1] | COLUMN_TAKES[1])  # said once, by the line above
            self.idle(b.attrs, b.line, takes, "on a ::: block without .box",
                      "::: {.box} draws a frame around blocks (docs/guides/layout.md)")  # fmt: skip
            return self.blocks(b.children, indent)  # a ::: block bobina does not draw: what it holds, as it is
        return []

    def list_block(self, b: ListBlock, indent: int) -> list:
        rows = []
        n = b.start
        numw = len(f"{b.start + len(b.items) - 1}.")
        for it in b.items:
            if it.task is not None:
                if self.done == "plain":
                    prefix = [Cell(c) for c in ("[x] " if it.task else "[ ] ")]
                else:
                    prefix = [Cell("☑" if it.task else "☐", wide=True), Cell(" ")]
            elif b.ordered:
                prefix = [Cell(c) for c in f"{n}.".rjust(numw) + " "]
            else:
                prefix = [Cell("•"), Cell(" ")]
            n += 1
            pw = columns(prefix)
            strike = it.task is True and self.done == "strike"  # a done task: its first paragraph struck
            first = False  # the item's first paragraph, every line of it (after an inner line's {…} too): one path
            for k, child in enumerate(it.children):
                if isinstance(child, Paragraph) and (k == 0 or (first and child.follows)):
                    first = True
                    self.item_text_attrs(child)
                    rows += self.text_block(
                        child.runs,
                        line=child.line,
                        attrs=child.attrs,
                        prefix=prefix if k == 0 else None,
                        indent=indent if k == 0 else indent + pw,
                        extra={"strike": strike},
                    )
                else:  # a loose paragraph or any other block: laid out as a block of its own, never struck
                    first = False
                    rows += self.block(child, indent + pw)
        return rows

    def item_text_attrs(self, p: Paragraph) -> None:
        """rotate= and .flip do nothing on the first text of a list item (it is laid out with its bullet): M101."""
        idle = [x for x, on in (("rotate=", "rotate" in p.attrs.kv), (".flip", p.attrs.has("flip"))) if on]
        if idle:
            self.n.add("M101", f"{' and '.join(idle)} {'does' if len(idle) == 1 else 'do'} nothing on a list item's "
                       "text", p.line, "a {…} line after the list turns the whole list")  # fmt: skip

    def divider(self, b) -> BitmapRow:
        style = next((s for s in ("solid", "dashed", "dotted", "double", "wavy", "cut") if b.attrs.has(s)), "solid")
        t = int(b.attrs.kv.get("thickness", 2))
        if t < int(self.p.get("raster.min_stroke_dots", 2)):
            self.n.add("B101", f"divider thickness {t} prints broken", b.line, "use thickness=2")
        return BitmapRow(imaging.divider(self.W, style, t), b.line, "divider")

    # ------------------------------------------------------------ boxes (::: {.box})
    def idle(self, a: Attrs, line: int, takes: tuple, where: str, hint: str) -> None:
        """The classes and keys bobina knows that a ::: block does not take, said once (M101). Unknown ones: the
        parser; the images' own ones: block()."""
        from .parser import DIV_CLASSES, DIV_KEYS, KNOWN_CLASSES, KNOWN_KEYS

        classes, keys = takes
        names = [f".{c}" for c in sorted(a.classes & (KNOWN_CLASSES | DIV_CLASSES) - classes - set(IMAGE_ONLY))]
        names += [f"{k}=" for k in sorted(a.kv) if k in KNOWN_KEYS | DIV_KEYS and k not in keys | set(IMAGE_ONLY)]
        if names:
            self.n.add("M101", f"{', '.join(names)} {'does' if len(names) == 1 else 'do'} nothing {where}", line, hint)

    def box(self, d: Div, indent: int) -> list:
        """A frame around blocks (::: {.box}). What it holds is laid out at the width inside the frame by the usual
        engine, then drawn with the frame, its title and its grey as one image: the frame's sides share the rows
        with the text, so the text inside is drawn too (in the printer font's look, the same dots). Never wider
        than the room it has, and always 4 letters inside: a frame too thick for its box is made thinner, and where
        there is no room for even the thinnest one (boxes deep in boxes) the blocks print without it. The frame and
        the room beside it take whole letters, so the text stays on the paper's grid (a full box holds 30 of the
        32 letters of 58 mm). rotate= and .flip turn the box here, before it is placed and the quote bars drawn."""
        a, line = d.attrs, d.line
        self.idle(a, line, BOX_TAKES, "on a box", BOX_HINT)
        cw, ch = self.p.cell
        raw = str(a.kv.get("title", ""))
        title = " ".join(self.text(raw).split())
        how = a.kv.get("title-style", "border")
        if how not in TITLE_STYLES:
            self.n.add("M101", not_a_value("title-style", how, "border, the default"), line, "border, inside or band")
            how = "border"
        if "title-style" in a.kv and not title:
            self.n.add("M101", f"title-style={how} with no title=: nothing to place", line, 'title="TABLE 4"')
        room = self.W - indent * cw
        least = _box_least(cw)
        if room < least:
            self.n.add("L111", f"no room for a box here ({room // cw} letters, a box needs {least // cw}): what it "
                       "holds prints without its frame", line, "fewer boxes inside each other here")  # fmt: skip
            head = [Paragraph(line=line, runs=[Run(raw, bold=True)])] if title else []
            return self.blocks([*head, *d.children], indent)
        drawn = [s for s in BOX_LINES if a.has(s)]
        style = drawn[0] if drawn else "solid"
        if len(drawn) > 1:
            self.n.add("M101", f"{' '.join('.' + s for s in drawn)}: a box has one line, .{style} is used", line,
                       "keep one of .solid .dashed .dotted .double")  # fmt: skip
        t = self.attr_dots(a, "thickness", line, 12)
        t = 2 if t is None else t
        if t < int(self.p.get("raster.min_stroke_dots", 2)):
            self.n.add("B101", f"box thickness {t} prints broken", line, "use thickness=2")
        t = max(1, t)
        width = self.box_width(a, line, room)
        asked = t
        while t > 2 and 2 * _box_side(t, style, cw) + 4 * cw > width:  # 4 letters inside, whatever the line
            t -= 1
        if style == "double" and 2 * _box_side(t, style, cw) + 4 * cw > width:  # a small cell: one line
            self.n.add("M101", f".double: no room for two lines in a {width // cw}-letter box, one is drawn", line,
                       "a wider box")  # fmt: skip
            style = "solid"
        if t < asked:
            self.n.add("M101", f"thickness={a.kv['thickness']}: no room for that line in a {width // cw}-letter "
                       f"box, {t} dots used", line, "a wider box, or a thinner line")  # fmt: skip
        dark = a.has("invert")  # all black, frame and room too; what it holds white
        if dark and self.dark:
            self.n.add("M101", ".invert does nothing on a box inside an inverted box: it is white on black already",
                       line, "remove .invert here")  # fmt: skip
            dark = False
        if dark and a.has("shade"):
            self.n.add("M101", ".shade does nothing on an inverted box: it is black", line, "remove .shade")
        if dark and (drawn or "thickness" in a.kv):
            names = [*(f".{s}" for s in drawn), *(["thickness="] if "thickness" in a.kv else [])]
            self.n.add("M101", f"{' '.join(names)}: an inverted box has no line to draw, it is black to its edges",
                       line, f"remove {' '.join(names)}")  # fmt: skip
        stroke = 3 * t if style == "double" else t
        side = _box_side(t, style, cw)
        inner = width - 2 * side
        kids = d.children
        if title and how == "inside":  # the first line inside, bold: a paragraph like any other, it wraps
            kids = [Paragraph(line=line, runs=[Run(raw, bold=True)]), *kids]
        on_border = bool(title) and how == "border"
        top = max(0, (ch - stroke) // 2) if on_border else 0  # the title sits across the top line, never clipped
        title_y = max(0, top + stroke // 2 - ch // 2)
        ang = self.angle(a, line) % 360
        outer, was_dark, was_lost = self.tall_max, self.dark, self.dark_lost
        try:
            with self.narrow(inner):
                self.dark = False  # the band is the box's own: inside an inverted box it prints the other way round
                band = (self.text_block([Run(raw)], line=line, attrs=Attrs({"invert", "center"}), bold=True)
                        if title and how == "band" else [])  # fmt: skip
                band_pics = [preview.row_image(r, self.p, self.em) for r in band]
                band_im = self.stacked(band_pics, self.W) if band else None
                if outer and ang % 180 != 90:  # in a turned label: what the frame, its room and a border or band
                    above = max(top + stroke + (band_im.height if band_im else 0) + BOX_ROOM,  # title take off
                                title_y + ch + 2 if on_border else 0)  # fmt: skip
                    self.tall_max = max(1, outer - above - BOX_ROOM - stroke)  # (turned 90: its width; the cuts)
                self.dark, self.dark_lost = was_dark or dark, was_lost and not dark  # its own tiles: kept here
                rows = self.blocks(kids, 0)
                raws = [r for r in rows if isinstance(r, RawRow)]
                rows = [r for r in rows if not isinstance(r, RawRow)]
                pics = [preview.row_image(r, self.p, self.em) for r in rows]
                body = self.stacked(pics, inner) if any(not isinstance(r, FeedRow) for r in rows) else None
        finally:
            self.tall_max, self.dark, self.dark_lost = outer, was_dark, was_lost
        codes = _code_spans(rows, pics)
        keep, darks = _stacked_rects(rows, pics, "keep"), _stacked_rects(rows, pics, "dark")
        if raws:
            self.n.add("M101", "a ```raw block cannot go inside a box: its bytes are sent after the box", raws[0].line,
                       "put the raw block after the ::: line that closes the box")  # fmt: skip
        y = top + stroke
        parts = []
        tops = _tops(band_pics, y) if band_im is not None else []  # where each row is, for a box cut in pieces
        if band_im is not None:  # black from side to side of the frame, the title centred in it
            black = Image.new("L", (width - 2 * stroke, band_im.height), 0)
            black.paste(band_im, (side - stroke, 0))
            parts.append((black, stroke, y))
            y += black.height
        shade_top = y
        if body is not None:  # BOX_ROOM of white between the ink and the frame, above and below
            lead, trail = _blank_edges(body)
            under = title_y + ch + 2 - y - lead if on_border else 0  # and clear of a border title's letters
            y += max(2, BOX_ROOM - lead, under)
            parts.append((body, side, y))
            codes = tuple((y + a, y + b, k) for a, b, k in codes)
            keep, darks = _moved(keep, side, y), _moved(darks, side, y)
            tops += _tops(pics, y)
            y += body.height + max(2, BOX_ROOM - trail)
        else:
            y += BOX_ROOM
        height = y + stroke
        im = Image.new("L", (width, height), 255) if dark else imaging.frame(width, height, style, t, top).convert("L")
        for part, x, py in parts:
            im.paste(part, (x, py))
        if a.has("shade") and not dark:  # the whole inside, 2 dots clear of the frame; the halo: off the letters
            im = imaging.shade(im, (stroke + 2, shade_top + 2, width - stroke - 2, height - stroke - 2))
        shown = self.border_title(im, title, line, top, stroke, title_y) if on_border else ""
        if dark:  # one black band from edge to edge, no white between its blocks; a band title stays as it is
            plain, im = im, ImageOps.invert(im)
            for part, x, py in parts[:1] if band_im is not None else ():
                im.paste(part, (x, py))
            for rect in keep:  # each code's white tile, laid out with its quiet zone (code_tile): black on white
                im.paste(plain.crop(rect), rect[:2])
            if keep:
                self.n.add("Q114", "a code in an inverted box prints black on white, in its white margin, so it scans",
                           line, "put it outside the box for an unbroken band")  # fmt: skip
            keep, darks = [], [(0, 0, width, height)]
        if ang:
            exact = Image.NEAREST if ang % 90 == 0 else Image.BICUBIC
            size = im.size
            im = im.rotate(-ang, expand=True, fillcolor=255, resample=exact)
            codes = _turned_spans(codes, im.height, ang)
            keep, darks = self.turned_rects(keep, size, ang, line), _turned_rects(darks, size, ang) or []
            if im.width > room:
                self.n.add("L104", f"turned box is {im.width} dots wide: cropped to {room}", line,
                           "a narrower box, or rotate=90/270 of a short one")  # fmt: skip
                cut = (im.width - room) // 2
                im = im.crop((cut, 0, cut + room, im.height))
                keep, darks = _moved(keep, -cut, 0), _moved(darks, -cut, 0)
        self.align_word(a, line)
        if a.kv.get("align") == "justify":  # spreads text; a box is only placed
            self.n.add("M101", "align=justify", line, "left, center or right")
        align = self.object_align(a, "left")

        def place(w: int) -> int:  # where a box w dots wide starts on the paper: on a letter when it can
            free = room - w
            return indent * cw + {"left": 0, "center": free // cw // 2 * cw, "right": free}[align]

        full = Image.new("L", (self.W, im.height), 255)
        full.paste(im, (place(im.width), 0))
        full = self.draw_bars(full, indent, 0)  # after the turn: the bars stay upright, beside the box
        marks = {u for r in [*band, *rows] if isinstance(r, BitmapRow) for u in r.untested} | {"box"}
        marks |= {"inverted-box"} if dark else set()
        lead = "".join(c.ch for c in self.lead(indent))
        left = min(place(im.width), indent * cw + room - width) // cw  # where it is, as far as it fits standing
        view = Boxed([*band, *rows], inner, left, width // cw, shown, style, lead, ang,
                     tuple(tops) if not ang and len(tops) == len(band) + len(rows) else (), invert=dark)  # fmt: skip
        at = place(im.width)
        return [BitmapRow(_bw(full), line, "box", untested=tuple(sorted(marks)), box=view, code_spans=codes,
                          keep=_moved(keep, at, 0), dark=_moved(darks, at, 0)), *raws]  # fmt: skip

    def box_width(self, a: Attrs, line: int, room: int) -> int:
        """width= of a box, of the room it has (a quote's or a list's is narrower than the paper): full, half,
        third, 50%, 16ch (letters), or 30mm and dots. In whole letters, the room when absent, never more (M101
        when asked), never less than _box_least (4 letters inside)."""
        cw = self.p.cell[0]
        given = a.kv.get("width")
        w = room
        if given is not None:
            text = str(given).strip().lower().replace(",", ".")
            letters = COLUMN_CH_RE.fullmatch(text)
            pct = re.fullmatch(r"(\d+(?:\.\d+)?)%", text)
            if letters:
                w = round(float(letters.group(1)) * cw)
            elif text in FRACTIONS:
                w = int(room * FRACTIONS[text])
            elif pct:
                w = int(room * float(pct.group(1)) / 100)
            else:
                w = self.object_width(given, line, BOX_WIDTH_HINT) or room
            if w > room:
                self.n.add("M101", f"width={given}: wider than the {room // cw} letters there are, the box takes them",
                           line, "width=full, or less")  # fmt: skip
                w = room
        least = _box_least(cw)
        if w // cw * cw < least:
            self.n.add("M101", f"width={given}: a box needs {least // cw} letters (4 inside)", line, BOX_WIDTH_HINT)
        return max(least, w // cw * cw)

    def border_title(self, im: Image.Image, title: str, line: int, top: int, stroke: int, y: int) -> str:
        """The title across a box's top line (its letters from `y` down), centred, bold in the printer font's look,
        the line cut around it (half a letter each side); longer than the line holds: cut with … (L109). Returns
        it as printed."""
        cw = self.p.cell[0]
        most = max(1, im.width // cw - 6)  # three letters of line each side, as the views draw ┌─ TITLE ─┐
        if columns([Cell(c, wide=is_wide(c)) for c in title]) > most:
            self.n.add("L109", f'title "{title[:40]}" is longer than the border holds ({most} letters): cut with …',
                       line, "title-style=band or title-style=inside wrap a long title into lines")  # fmt: skip
            title = fit_columns(title, most - 1).rstrip() + "…"
        cells = [Cell(c, bold=True, wide=is_wide(c)) for c in title]
        drawn = self.em.line_image(cells)
        x, gap = (im.width - drawn.width) // 2, cw // 2
        im.paste(255, (x - gap, top, x + drawn.width + gap, top + stroke))
        im.paste(0, (x, y), ImageOps.invert(drawn))  # its ink only: nothing under it is wiped
        return title

    # ------------------------------------------------------------ columns (:::: {.columns})
    def columns(self, d: Div, indent: int) -> list:
        """Columns side by side (:::: {.columns}; each ::: {.column} in it is one, left to right). Each column is laid
        out at its width by the usual engine, then a row of columns is drawn side by side as one image (the text in
        them in the printer font's look, as in a box). Widths are whole letters, so the text keeps the paper's grid:
        width=40% is of the text room (the room less the gaps: 40% and 60% fill it), 12ch letters, 30mm and dots as
        many letters as fit, auto (the default) shares what is left; never wider than the room. wrap=nowrap (the
        default) keeps one row and squeezes the content (text wraps, codes and images shrink: Q101 when a QR gets
        too small to scan); wrap=wrap starts a new row with a column that does not fit (column_rows), wrap-reverse
        puts each new row above the one before (L110 says when a column moves). orientation=vertical lays them out
        along the roll instead, a label read sideways (columns_turned)."""
        a, line = d.attrs, d.line
        self.idle(a, line, COLUMNS_TAKES, "on :::: {.columns}", COLUMNS_HINT)
        turned = self.columns_orientation(a, line, indent) == "vertical"
        cols = [c for c in d.children if isinstance(c, Div)]  # the parser made each child a column
        cw = self.p.cell[0]
        room = (self.W - indent * cw) // cw
        if not cols:
            return []
        if room < 1:
            self.n.add("L111", "no room for columns here (not a letter left): what they hold prints one under the "
                       "other", line, "fewer quotes, lists or boxes around the columns")  # fmt: skip
            return self.blocks([b for c in cols for b in c.children], indent)
        wrap = a.kv.get("wrap", "nowrap")
        if wrap not in WRAPS:
            self.n.add(
                "M101",
                not_a_value("wrap", wrap, "nowrap, the default"),
                line,
                "nowrap (squeezed side by side: the default), wrap or wrap-reverse",
            )
            wrap = "nowrap"
        valign = self.valign(a, line, "top")
        gap = self.column_gap(a, line)
        for c in cols:
            self.idle(c.attrs, c.line, COLUMN_TAKES, "on a column", COLUMN_HINT)
        asked = [self.column_width(c) for c in cols]
        aligns = [self.valign(c.attrs, c.line, valign) for c in cols]
        outer, self.wrapping = self.wrapping, wrap != "nowrap"
        if turned:
            lost, self.dark_lost = self.dark_lost, self.dark_lost or self.dark  # turned: their tiles are not kept
            try:
                return self.columns_turned(cols, asked, aligns, gap, wrap, a, line)
            finally:
                self.wrapping, self.dark_lost = outer, lost
        try:
            rows = self.column_rows(cols, asked, room, gap, wrap, line)
            if wrap == "wrap-reverse":
                rows.reverse()
            out: list = []
            for row in rows:
                if out:
                    out.append(FeedRow(int(self.p.get("margins.block_gap_dots", 12))))
                out += self.column_row([cols[i] for i in row], [asked[i] for i in row], [aligns[i] for i in row],
                                       indent, room, gap, a, line)  # fmt: skip
        finally:
            self.wrapping = outer
        return out

    def valign(self, a: Attrs, line: int, default: str) -> str:
        """valign=top|middle|bottom (center is middle, as CSS says it), or `default`."""
        given = a.kv.get("valign")
        if given is None:
            return default
        if given in VALIGNS:
            return VALIGNS[given]
        self.n.add("M101", not_a_value("valign", given, "the default"), line, "top, middle or bottom")
        return default

    def column_gap(self, a: Attrs, line: int) -> int:
        """gap= on columns, in whole letters: 1ch (the default), 0, 2ch; 3mm, a % of the paper and dots as the
        nearest whole letters."""
        given = a.kv.get("gap")
        if given is None:
            return 1
        text = str(given).strip().lower().replace(",", ".")
        if m := COLUMN_CH_RE.fullmatch(text):
            return math.floor(float(m.group(1)))
        if re.fullmatch(r"0+(?:\.0*)?(?:mm|px|dots|%)?", text):
            return 0
        dots, _ = self.trial(lambda: self.object_width(given, line, GAP_HINT))  # said below, as gap=
        if dots is None:
            self.n.add("M101", not_a_value("gap", given, "a gap of one column"), line, GAP_HINT)
            return 1
        return round(dots / self.p.cell[0])

    def column_width(self, c: Div) -> int | float | None:
        """A column's width=: letters (12ch; 30mm and dots as many as fit), a share of the text room (40%, half), or
        None: auto (absent, auto, or unreadable: M101)."""
        given = c.attrs.kv.get("width")
        if given is None or given == "auto":
            return None
        if given != given.lower():
            self.n.add("M101", f"width={given}: values are lowercase", c.line,
                       f"write width={given.lower()} (the column shares what is left until then)")  # fmt: skip
            return None
        return self.column_units(given, _NativeInk(self), c.line)

    def row_widths(self, asked: list, room: int, gap: int) -> tuple[list[int], int, int]:
        """The letters each column of a row gets: (widths, the gap used, the letters the widths ask for). A share is
        of the text room (column_shares: 40% and 60% fill it exactly), letters as asked, and the auto columns share
        what is left (the first ones get a letter more). Asked for more than there is, the widths shrink in
        proportion, each auto column keeping a letter. A gap too wide for one letter per column gets narrower."""
        n = len(asked)
        g = gap if n == 1 else min(gap, max(0, (room - n) // (n - 1)))
        text = max(n, room - g * (n - 1))
        got = self.column_shares(list(asked), text)
        fixed = [k for k, w in enumerate(got) if w is not None]
        autos = [k for k, w in enumerate(got) if w is None]
        need = sum(got[k] for k in fixed) + len(autos)
        if need > text:
            for k, w in zip(fixed, _shrink([got[k] for k in fixed], text - len(autos)), strict=True):
                got[k] = w
        left = text - sum(got[k] for k in fixed)
        for j, k in enumerate(autos):
            got[k] = left // len(autos) + (1 if j < left % len(autos) else 0)
        return [max(1, w) for w in got], g, need

    def column_rows(self, cols: list[Div], asked: list, room: int, gap: int, wrap: str, line: int,
                    tall: int | None = None) -> list[list[int]]:  # fmt: skip
        """Which columns go on each row, top to bottom: all on one row (wrap=nowrap), or, with wrap=wrap, a new row
        from the first column that does not fit beside the ones before it: their widths ask for more letters than
        there are, or a column's content does not fit the width it would get (content_fits). L110 says each new
        row. More columns than letters (1 each and the gaps) never stand side by side: the rest go on new rows.
        Turned columns (tall: the label's height in dots) start a new label instead, after this one."""
        n = len(cols)
        most = max(1, (room + gap) // (1 + gap))
        row = "label" if tall else "row"
        if wrap == "nowrap":
            rows = [list(range(i, min(n, i + most))) for i in range(0, n, most)]
            if len(rows) > 1:
                self.n.add("L110", f"{n} columns do not fit across {room} letters, even of one letter each: the ones "
                           f"after column {most} print on new {row}s", line, "fewer columns, or gap=0")  # fmt: skip
            return rows
        rows, cur = [], []
        for i in range(n):
            why = self.row_misfit(cols, asked, [*cur, i], room, gap, tall) if cur else ""
            if not why:
                cur.append(i)
                continue
            rows.append(cur)
            cur = [i]
            if tall:
                where = "a new label, " + ("after this one" if wrap == "wrap" else "before this one")
            else:
                where = "a new row of columns, " + ("under them" if wrap == "wrap" else "above them")
            fix = ("a smaller gap= keeps" if why.startswith("the gap") else "smaller widths or a smaller gap= keep"
                   if why.startswith("the widths and the gap") else "smaller widths keep")  # fmt: skip
            self.n.add("L110", f"column {i + 1} does not fit beside column {i} ({why}): it starts {where}",
                       cols[i].line, f"wrap=nowrap keeps the columns side by side, squeezed; {fix} them on one "
                       f"{row}")  # fmt: skip
        rows.append(cur)
        return rows

    def row_misfit(self, cols: list[Div], asked: list, idx: list[int], room: int, gap: int,
                   tall: int | None = None) -> str:  # fmt: skip
        """Why these columns do not fit side by side in `room` letters ("" when they do)."""
        widths, _, need = self.row_widths([asked[i] for i in idx], room, gap)
        between = gap * (len(idx) - 1)  # the gap asked for, as CSS flex-wrap keeps it: one too wide moves a column
        if need + between > room and (need > room or all(asked[i] is None for i in idx)):
            if need <= room:
                return (f"the gap of {gap} letter{'s' if gap != 1 else ''} between {len(idx)} columns leaves "
                        f"{max(0, room - between)} of the {room} letters for them")  # fmt: skip
            return f"the widths ask for {need + between} of the {room} letters"
        if need + between > room:
            return (f"the widths and the gap of {gap} letter{'s' if gap != 1 else ''} ask for {need + between} of "
                    f"the {room} letters")  # fmt: skip
        for i, w in zip(idx, widths, strict=True):
            alone = self.row_widths([asked[i]], room, gap)[0][0]  # what it gets on a row of its own
            if not self.content_fits(cols[i], w, alone, tall):
                return f"{'its' if i == idx[-1] else f'column {i + 1}'} content does not fit in {w} letters"
        return ""

    def content_fits(self, col: Div, w: int, alone: int, tall: int | None = None) -> bool:
        """Whether a column's content fits w letters: laid out at that width it has no problem of being squeezed
        (SQUEEZED: its longest word cut, a QR below the smallest module that scans, a table narrowed, an image
        given in mm or dots made smaller, a turned block cropped, …) that it does not have at `alone`, the width it
        would get on a row of its own, as well: a column squeezed even there gains nothing by moving, so it stays.
        Turned columns (tall: the label's height in dots) must also be no taller than the label, unless even alone
        they are."""

        if tall is None:
            return self.column_squeezed(col, w) <= self.column_squeezed(col, alone)

        def high(letters: int) -> bool:
            return self.column_height(col, letters, tall)[0] > tall

        squeezed = self.column_height(col, w, tall)[1] <= self.column_height(col, alone, tall)[1]
        return squeezed and (not high(w) or high(alone))

    def column_squeezed(self, col: Div, letters: int) -> frozenset:
        """The SQUEEZED problems a standing column has laid out at `letters` (a trial: nothing drawn)."""
        cache = self.__dict__.setdefault("_squeezed", {})
        key = (id(col), letters, self.tall_max)
        if key not in cache:
            _, said = self.probe(lambda: self.laid_column(col, letters, pictures=False))
            cache[key] = frozenset({x.code for x in [*said, *said.check_only]} & SQUEEZED)
        return cache[key]

    def column_height(self, col: Div, letters: int, tall: int) -> tuple[int, frozenset]:
        """A column of a turned label `tall` dots high, laid out at `letters` as a trial: (its height in dots, the
        SQUEEZED problems it has)."""
        cache = self.__dict__.setdefault("_heights", {})
        key = (id(col), letters, tall)
        if key not in cache:

            def build() -> int:
                _, _, pics = self.laid_column(col, letters, tall)
                return sum(im.height for im in pics if im is not None)

            height, said = self.probe(build)
            cache[key] = (height, frozenset({x.code for x in [*said, *said.check_only]} & SQUEEZED))
        return cache[key]

    def laid_column(self, col: Div, letters: int, tall: int | None = None, pictures: bool = True):
        """A column laid out `letters` wide by the usual engine, its codes no taller than `tall` (a turned label's
        height): (its rows, the raw ones apart; its raw rows; each row's picture, None for a row that draws nothing,
        when `pictures`). What column_row, the trials and turned_label draw from."""
        outer = self.tall_max
        self.tall_max = outer if tall is None else tall  # nested in a turned label, its codes still fit it
        try:
            with self.narrow(letters * self.p.cell[0], "column"):
                rows = self.blocks(col.children, 0)
                raws = [r for r in rows if isinstance(r, RawRow)]
                rows = [r for r in rows if not isinstance(r, RawRow)]
                pics = [preview.row_image(r, self.p, self.em) for r in rows] if pictures else []
        finally:
            self.tall_max = outer
        return rows, raws, pics

    @staticmethod
    def stacked(pics: list, width: int) -> Image.Image:
        """Row pictures one under the other, `width` dots wide (mode L)."""
        return imaging.vstack([im.convert("L") for im in pics if im is not None], width, "L")

    def probe(self, build) -> tuple:
        """trial(), and what it judged (a font's size, said once) forgotten: the layout that prints says it."""
        judged = set(self._judged)
        try:
            return self.trial(build)
        finally:
            self._judged = judged

    def said_widths(self, asked: list, room: int, gap: int, a: Attrs, line: int, row: str,
                    content: bool = False) -> tuple[list[int], int]:  # fmt: skip
        """row_widths (the widths and the gap used), saying a gap with no room and widths asking for more letters
        than there are (M101); `row` is what wrap=wrap would move a column to: a row, or a turned label. content:
        the widths are what the content needs (length=auto), so the content is what asks for too much."""
        widths, g, need = self.row_widths(asked, room, gap)
        n = len(asked)
        if g < gap:
            said = f"gap={a.kv['gap']}" if "gap" in a.kv else "the gap (1 letter, the default)"
            self.n.add("M101", f"{said}: no room for it between {n} columns in {room} letters, {g} used", line,
                       "a smaller gap=, or fewer columns")  # fmt: skip
        part = sum(w for w in asked if isinstance(w, float))
        if need + g * (n - 1) > room and content and part > 1:
            self.n.add("M101", f"the columns' % widths add up to {part:.0%}, more than the label: each narrowed to "
                       f"{' + '.join(map(str, widths))}", line, "smaller % widths: 100% at most")  # fmt: skip
        elif need + g * (n - 1) > room and content:
            self.n.add("M101", f"the columns' content needs {need + g * (n - 1)} letters, more than the "
                       f"{TURNED_MOST_MM} mm ({room} letters) a label can have: each narrowed to "
                       f"{' + '.join(map(str, widths))}", line, "less text or smaller sizes"
                       + ("" if self.wrapping else ", or wrap=wrap for a label of its own"))  # fmt: skip
        elif need + g * (n - 1) > room and any(w is not None for w in asked):
            move = "" if self.wrapping else f", or wrap=wrap to move a column that does not fit to a new {row}"
            self.n.add("M101", f"the columns' widths ask for {need + g * (n - 1)} of the {room} letters: each "
                       f"narrowed to {' + '.join(map(str, widths))}", line, "smaller width=" + move)  # fmt: skip
        return widths, g

    def column_row(self, cols: list[Div], asked: list, aligns: list[str], indent: int, room: int, gap: int,
                   a: Attrs, line: int) -> list:  # fmt: skip
        """One row of columns as one image across the paper: each column laid out at its width, placed by valign=
        (by its ink: middle centres it on the tallest column's ink), the quote bars beside them."""
        cw = self.p.cell[0]
        widths, g = self.said_widths(asked, room, gap, a, line, "row")
        parts, raws, rects = [], [], []
        for c, w in zip(cols, widths, strict=True):
            rows, raw, pics = self.laid_column(c, w)
            raws += raw
            im = self.stacked(pics, w * cw) if any(not isinstance(r, FeedRow) for r in rows) else None
            lead, trail = _blank_edges(im) if im is not None else (0, 0)
            keep = _stacked_rects(rows, pics, "keep")
            if keep:  # a code's white tile is part of it, never white to leave out
                lead, trail = min(lead, *(r[1] for r in keep)), min(trail, *(im.height - r[3] for r in keep))
            parts.append((rows, im, lead, 0 if im is None else im.height - lead - trail, _code_spans(rows, pics)))
            rects.append((keep, _stacked_rects(rows, pics, "dark")))
        if raws:
            self.n.add("M101", "a ```raw block cannot go inside a column: its bytes are sent after the columns",
                       raws[0].line, "put the raw block after the line of colons that closes the columns")  # fmt: skip
        inked = [(lead, h) for _, _, lead, h, _ in parts if h > 0]
        if not inked:
            return raws
        top, tall = min(lead for lead, _ in inked), max(h for _, h in inked)
        ys = []
        for (_, _, lead, h, _), va in zip(parts, aligns, strict=True):
            at = top + {"top": 0, "middle": (tall - h) // 2, "bottom": tall - h}[va]
            ys.append(at - lead if h else 0)  # only the white above a column's ink goes past the top
        height = max(top + tall, *(y + im.height for (_, im, _, h, _), y in zip(parts, ys, strict=True) if h))
        full = Image.new("L", (self.W, height), 255)
        x, views, keep, darks = indent * cw, [], (), ()
        for (rows, im, _, h, _), w, y, va, (k, dk) in zip(parts, widths, ys, aligns, rects, strict=True):
            if h:
                full.paste(im, (x, y))
                keep, darks = keep + _moved(k, x, y), darks + _moved(dk, x, y)
            views.append(Column(rows, w * cw, x // cw, max(0, y), va))
            x += (w + g) * cw
        full = self.draw_bars(full, indent, 0)
        marks = {u for rows, *_ in parts for r in rows if isinstance(r, BitmapRow) for u in r.untested} | {"columns"}
        lead = "".join(c.ch for c in self.lead(indent))
        view = Columned(views, lead)
        spans = tuple((y + a, y + b, k) for (*_, codes), y in zip(parts, ys, strict=True) for a, b, k in codes)
        return [BitmapRow(_bw(full), line, "columns", untested=tuple(sorted(marks)), columns=view, code_spans=spans,
                          keep=keep, dark=darks), *raws]  # fmt: skip

    def columns_orientation(self, a: Attrs, line: int, indent: int) -> str:
        """orientation= on columns: horizontal (the default: across the paper) or vertical (along the roll, a label
        read sideways: columns_turned). Said: length= on columns that do not turn; rotate=90/270 on standing ones,
        which turns their picture and is rarely what is meant (L113); rotate= and .flip on turned ones, which are
        ignored (block() does not turn the label again)."""
        given = a.kv.get("orientation", "horizontal")
        if given not in ("horizontal", "vertical"):
            self.n.add("M101", not_a_value("orientation", given, "across the paper, the default"), line,
                       "horizontal (across the paper: the default) or vertical (along the roll)")  # fmt: skip
            given = "horizontal"
        if given == "vertical" and indent:  # a quote's bar or a list's indent cannot follow a turned label
            self.n.add("M101", "orientation=vertical: only columns outside quotes and lists turn", line,
                       "move the columns out of the quote or list")  # fmt: skip
            given = "horizontal"
        if given != "vertical" and "length" in a.kv:
            self.n.add("M101", f"length={a.kv['length']} does nothing on columns across the paper", line,
                       "orientation=vertical lays them out along the roll, length= long")  # fmt: skip
        rot = a.kv.get("rotate")
        if given == "vertical":
            for name, on in ((f"rotate={rot}", rot is not None), (".flip", a.has("flip"))):
                if on:
                    self.n.add("M101", f"orientation=vertical already turns the label: {name} ignored", line,
                               f"remove {name.split('=')[0] + ('=' if '=' in name else '')}")  # fmt: skip
            return given
        try:
            quarter = rot is not None and float(rot) % 180 == 90
        except ValueError:
            quarter = False  # angle() says it
        if quarter:
            self.n.add("L113", f"rotate={rot} turns the picture of the columns as they stand across the paper", line,
                       "orientation=vertical lays them out along the roll instead: a label read sideways, 72 mm "
                       "long unless length= says")  # fmt: skip
        return given

    def columns_turned(self, cols: list[Div], asked: list, aligns: list[str], gap: int, wrap: str, a: Attrs,
                       line: int) -> list:  # fmt: skip
        """Columns along the roll (orientation=vertical): a label length= long (72 mm by default; auto: as long as
        the columns' content needs) and as tall as the paper is wide, read sideways. Its widths share the label's
        length as standing columns share the paper's width; each column is laid out at its width by the usual
        engine and placed by valign= within the label's height; then the label is turned 90 degrees clockwise, like
        a turned table: its top on the right of the paper, its first column printed first. With wrap=wrap a column
        that does not fit (the widths, or its content too tall for the label) starts a new label after this one
        (wrap-reverse: before it, L110); content taller than the label otherwise goes on in more labels."""
        tall, cw = self.W, self.p.cell[0]
        most = self.p.mm_to_dots(TURNED_MOST_MM) // cw
        length = self.label_length(a, line)
        if length is None:
            asked = [self.column_need(c) if w is None else w for c, w in zip(cols, asked, strict=True)]
            room = min(most, self.auto_room(cols, asked, gap))
        else:
            room = length // cw
        labels = self.column_rows(cols, asked, room, gap, wrap, line, tall)
        if wrap == "wrap-reverse":
            labels.reverse()
        out: list = []
        for idx in labels:
            sub, mine = [cols[i] for i in idx], [asked[i] for i in idx]
            here = room if length is not None or len(idx) == len(cols) else min(most, self.auto_room(sub, mine, gap))
            if out:
                out += self.between_labels(line)
            out += self.turned_label(sub, mine, [aligns[i] for i in idx], here, gap,
                                     length or here * cw, a, line, auto=length is None)  # fmt: skip
        return out

    def between_labels(self, line: int) -> list:
        """What parts two turned labels on the paper, so one is seen to end: 3 mm, a dashed line across, 3 mm."""
        gap = self.p.mm_to_dots(LABEL_GAP_MM)
        return [FeedRow(gap), BitmapRow(imaging.divider(self.W, "dashed", 2, pad=0), line, "divider"), FeedRow(gap)]

    def label_length(self, a: Attrs, line: int) -> int | None:
        """length= of turned columns, in dots along the roll: 72mm (the default, 575 dots at 203 dpi), 7.2cm, 480 or
        480dots (dots), or None for auto. Never shorter than a letter, never longer than TURNED_MOST_MM (M101 says
        what is used)."""
        default = self.p.mm_to_dots(TURNED_LENGTH_MM)
        given = a.kv.get("length")
        if given is None:
            return default
        text = str(given).strip().replace(",", ".")
        if text != text.lower():
            self.n.add("M101", f"length={given}: values are lowercase", line, f"write length={text.lower()}")
            text = text.lower()
        if text == "auto":
            return None
        m = re.fullmatch(r"(\d+(?:\.\d+)?)(mm|cm|px|dots)?", text)
        dots = 0
        if m:
            n, unit = float(m.group(1)), m.group(2)
            dots = self.p.mm_to_dots(n * 10 if unit == "cm" else n) if unit in ("mm", "cm") else int(n)
        most = self.p.mm_to_dots(TURNED_MOST_MM)
        if dots < self.p.cell[0]:  # unreadable, or not even a letter long
            self.n.add("M101", f"length={given}: {TURNED_LENGTH_MM} mm used", line, LENGTH_HINT)
            return default
        if dots > most:
            self.n.add("M101", f"length={given}: longer than {TURNED_MOST_MM} mm, {TURNED_MOST_MM} mm used", line,
                       "a shorter length=")  # fmt: skip
            return most
        return dots

    def column_need(self, col: Div) -> int:
        """length=auto: the letters a column's content needs: the fewest at which it is as tall as at the longest
        label (no line wraps that need not, no code drawn smaller) and squeezed no more. Content that grows with its
        width (an image without width= fills its column) would be too tall there: it gets the most letters at which
        it still fits the label's height (its text wraps less as it widens, its image grows: tried at a few widths,
        then the last one that fits narrowed down to the letter)."""
        most, tall = self.p.mm_to_dots(TURNED_MOST_MM) // self.p.cell[0], self.W

        def probe(letters: int) -> tuple[int, frozenset]:
            return self.column_height(col, letters, tall)

        best = probe(most)

        def least(ok, lo: int, hi: int) -> int:  # the first letters in lo..hi at which ok() holds, and above them
            while lo < hi:
                mid = (lo + hi) // 2
                lo, hi = (lo, mid) if ok(*probe(mid)) else (mid + 1, hi)
            return lo

        if best[0] > tall:
            tries = sorted({min(most, round(math.sqrt(2) ** k)) for k in range(40)})
            fits = [w for w in tries if probe(w)[0] <= tall]
            if fits:
                after = next((w for w in tries if w > fits[-1]), most)
                return least(lambda height, _: height > tall, fits[-1], after) - 1  # the last letters that fit
        return least(lambda height, squeezed: height == best[0] and squeezed <= best[1], 1, most)

    def auto_room(self, cols: list[Div], asked: list, gap: int) -> int:
        """length=auto: the letters of a label just long enough for these columns side by side: each at least a
        letter, the letters they ask for, and each share (40%) of the text room no narrower than its content needs
        (column_need); shares adding up to more than 100% are narrowed as row_widths does, never below that. The
        caller keeps it within TURNED_MOST_MM."""
        n, most = len(asked), self.p.mm_to_dots(TURNED_MOST_MM) // self.p.cell[0]
        between = gap * (n - 1)
        text = max(n, sum(w for w in asked if isinstance(w, int)))
        shares = {i: self.column_need(c) for i, (c, w) in enumerate(zip(cols, asked, strict=True))
                  if isinstance(w, float)}  # fmt: skip
        part = sum(asked[i] for i in shares)
        if shares and part < 1:
            text = max(text, math.ceil(text / (1 - part)))  # what the letters leave is the shares' room
        while shares and text < most:
            widths, g, need = self.row_widths(list(asked), text + between, gap)
            if g == gap and all(widths[i] >= w for i, w in shares.items()) and (part > 1 or need <= text):
                break
            text += 1
        return text + between

    def turned_label(self, cols: list[Div], asked: list, aligns: list[str], room: int, gap: int, length: int,
                     a: Attrs, line: int, auto: bool = False) -> list:  # fmt: skip
        """One label of turned columns, `length` dots along the roll and as tall as the paper is wide, then
        turned: each column laid out at its width (its codes no taller than the label) and placed by valign=
        within the label's height, as read. Content taller than the label is never cut off: it goes on in more
        labels after this one, each column at its place (label_bands)."""
        cw, tall = self.p.cell[0], self.W
        widths, g = self.said_widths(asked, room, gap, a, line, "label", content=auto)
        stacks, raws = [], []
        for k, (c, w) in enumerate(zip(cols, widths, strict=True)):
            rows, raw, pics = self.laid_column(c, w, tall)
            raws += raw
            bands, height, cut = self.label_bands(rows, pics, tall, w * cw, k + 1)
            stacks.append(bands)
            if len(bands) - 1 > cut:  # labels its cut blocks do not account for (fit_label said those)
                more = len(bands) - 1
                alone = ", too tall even on a label of its own" if self.wrapping else ""
                move = "" if self.wrapping else "; wrap=wrap moves a column to a label of its own"
                self.n.add("L112", f"column {k + 1} is taller than the label ({height} of the {tall} dots across the "
                           f"paper{alone}): what does not fit goes on in {more} more label{'s' if more > 1 else ''} "
                           "after it", c.line,
                           f"a longer length= (or length=auto), less text or smaller sizes{move}")  # fmt: skip
        if raws:
            self.n.add("M101", "a ```raw block cannot go inside a column: its bytes are sent after the columns",
                       raws[0].line, "put the raw block after the line of colons that closes the columns")  # fmt: skip
        out: list = []
        for b in range(max(len(s) for s in stacks)):
            canvas = Image.new("L", (length, tall), 255)
            views, x = [], 0
            for bands, w, va in zip(stacks, widths, aligns, strict=True):
                rows, im = bands[b][:2] if b < len(bands) else ([], None)
                lead, trail = _blank_edges(im) if im is not None else (0, 0)
                h = 0 if im is None else im.height - lead - trail
                y = {"top": 0, "middle": (tall - h) // 2, "bottom": tall - h}[va] - lead if h else 0
                if h:
                    canvas.paste(im, (x, y))
                views.append(Column(rows, w * cw, x // cw, max(0, y), va))
                x += (w + g) * cw
            if out:
                out += self.between_labels(line)
            marks = {u for bands in stacks for rows, *_ in bands for r in rows if isinstance(r, BitmapRow)
                     for u in r.untested} | {"columns", "turned-columns"}  # fmt: skip
            turned = canvas.rotate(-90, expand=True)  # clockwise, like a turned table: the top goes to the right
            view = Columned(views, "", turned=True, lines=round(tall / self.em.row_height(TextRow([Cell(" ")]))))
            spans = _turned_spans([s for bands in stacks if b < len(bands) for s in bands[b][2]], turned.height, 90)
            out.append(BitmapRow(_bw(turned), line, "columns", untested=tuple(sorted(marks)), columns=view,
                                 code_spans=spans))  # fmt: skip
        return [*out, *raws]

    def label_bands(self, rows: list, pics: list, tall: int, width: int, column: int = 0) -> tuple[list, int, int]:
        """A turned column's rows in bands no taller than the label (tall dots): (each band's rows, its picture and
        the codes in it; the column's whole height; the labels added by cutting a row too tall, which fit_label
        said). Cut between rows, never inside one; a gap at a band's edge is left out. A row taller than the label
        is fitted to it, or cut into pieces that go on in the next labels (fit_label)."""
        bands, cur, used, height, cut = [], [], 0, 0, 0

        def close() -> int:
            while cur and isinstance(cur[-1][0], FeedRow):
                cur.pop()
            if cur:
                rs, ims = [r for r, _ in cur], [im for _, im in cur]
                bands.append((rs, self.stacked(ims, width), _code_spans(rs, ims)))
            cur.clear()
            return 0

        for r, im in zip(rows, pics, strict=True):
            if im is None:
                continue
            height += im.height
            pieces = [(r, im)]
            if im.height > tall and not isinstance(r, FeedRow):
                pieces = self.fit_label(r, im, tall, width, column)
                cut += len(pieces) - 1
            for k, (piece, pic) in enumerate(pieces):
                if cur and (used + pic.height > tall or k):  # a piece cut at a label's edge starts the next label
                    used = close()
                if isinstance(piece, FeedRow) and not cur:
                    continue
                cur.append((piece, pic))
                used += pic.height
        close()
        return bands, height, cut

    def fit_label(self, r, im: Image.Image, tall: int, width: int,
                  column: int = 0) -> list[tuple[BitmapRow, Image.Image]]:  # fmt: skip
        """A row taller than a turned label (its ink), as pieces no taller than the label, each fact said once,
        naming its column:
        - a photo or drawing (an image) is drawn smaller to fit it (L112);
        - anything else holds text or a code, never resampled (18/11: a box drawn at 75% printed "texto" as
          "texlo"; a code is laid out to fit the label already, laid_column): it goes on in the next labels, cut
          where no code is: at a blank line near each cut
          (a box's side lines aside) or at a code's edge, a clean cut (L112, a note); across its lines when there is
          no such place (L114, a warning); through a code only when the code itself is taller than the label
          (Q101, Q108 for a barcode: it will not scan). A block cut both ways says both."""
        line = getattr(r, "line", 0)
        g = im.convert("L")
        box = ImageOps.invert(g).getbbox() or (0, 0, im.width, im.height)
        ink = g.crop(box)
        align = "left" if box[0] == 0 else "right" if box[2] >= im.width else "center"
        spans = [(a - box[1], b - box[1], k) for a, b, k in _code_spans([r], [im])]
        photo = isinstance(r, BitmapRow) and r.kind == "image" and not spans
        kind = r.kind if isinstance(r, BitmapRow) else spans[0][2] if spans else "text"
        mark = getattr(r, "untested", ())
        framed = getattr(r, "box", None)
        sides = (ink.width - framed.inner) // 2 if framed and framed.turned % 180 != 90 else 0  # a box's side lines

        def row(piece: Image.Image, top: int = 0) -> tuple[BitmapRow, Image.Image]:
            small = imaging.place(_bw(piece), width, align)
            inside = tuple((max(0, a - top), min(piece.height, b - top), k) for a, b, k in spans
                           if b > top and a < top + piece.height)  # fmt: skip
            view = None
            if framed and framed.row_tops:  # a piece of a box: the view draws its rows, its cut sides open
                first, last = top == 0, top + piece.height >= ink.height
                at, ends = top + box[1], (*framed.row_tops[1:], im.height)
                mids = [(t + e) / 2 for t, e in zip(framed.row_tops, ends, strict=True)]  # a row: where its middle is
                keep = [x for x, m in zip(framed.rows, mids, strict=True)
                        if (first or m >= at) and (last or m < at + piece.height)]  # fmt: skip
                view = replace(framed, rows=keep, title=framed.title if first else "", row_tops=(),
                               open_top=not first, open_bottom=not last)  # fmt: skip
            return BitmapRow(small, line, kind, untested=mark, code_spans=inside, box=view), small

        if ink.height <= tall:  # only the white around it was too tall
            return [row(ink)]
        who = f"column {column}: " if column else ""
        what = (f"{who}{'a picture' if photo else 'a block'} {ink.height} dots tall at line {line} is taller than the "
                f"label ({tall} dots across the paper)")  # fmt: skip
        if photo:
            self.n.add("L112", f"{what}: drawn smaller to fit it", line, "a smaller width= for it")
            return [row(ink.resize((max(1, round(ink.width * tall / ink.height)), tall), Image.BOX))]

        def free(y: int) -> bool:  # a row that cuts no code
            return not any(a < y < b for a, b, _ in spans)

        darks = _moved(getattr(r, "dark", ()), -box[0], -box[1])  # inverted boxes: their blank lines are black

        def clean(y: int) -> bool:  # a blank line (inside a box's side lines), or a code's edge
            return _blank_row(ink, y, sides, darks) or any(y in (a, b) for a, b, _ in spans)

        pieces, top, across, through = [], 0, False, []
        while ink.height - top > tall:
            cut = top + tall
            at = next((y for y in range(cut, top + tall * 2 // 3, -1) if free(y) and clean(y)), None)
            if at is None:  # no clean place near the edge: the lowest place that cuts no code, else the edge
                at = next((y for y in range(cut, top, -1) if free(y)), None)
                if at is None:
                    at = cut
                    through += [s for s in spans if s[0] < cut < s[1] and s not in through]
                else:
                    across = across or not clean(at)
            pieces.append((top, ink.crop((0, top, ink.width, at))))
            top = at
        pieces.append((top, ink.crop((0, top, ink.width, ink.height))))
        more = f"{len(pieces) - 1} more label{'s' if len(pieces) > 2 else ''}"
        for a, b, k in through:
            name = {"qr": "QR code", "datamatrix": "Data Matrix", "pdf417": "PDF417"}.get(k, "barcode")
            turn = ", or orientation=horizontal on the barcode" if name == "barcode" else ""
            labels = sum(1 for t, p in pieces if t < b and a < t + p.height)  # the labels the code itself is on
            self.n.add("Q108" if name == "barcode" else "Q101", f"{who}a {name} at line {line} is cut across "
                       f"{labels} turned labels: it will not scan", line,
                       f"a longer length=, a smaller module={turn}")  # fmt: skip
        if across:
            self.n.add("L114", f"{what}: it goes on in {more}, cut across its lines", line,
                       "read the labels together; a smaller size= or width=, or less in it")  # fmt: skip
        elif not through:
            self.n.add("L112", f"{what}: it goes on in {more}, cut between its lines", line,
                       "a smaller size= or width=, or less in it")  # fmt: skip
        return [row(p, t) for t, p in pieces]

    def fence(self, f: Fence, indent: int) -> list:
        kind = f.kind
        if kind in OBJECTS:  # an image says it in image(), for both ![](…) and ```image
            self.object_words(f.attrs, f.line)
        if kind == "qr":
            return self.qr(f)
        if kind == "barcode":
            rows = self.barcode(f)
            return rows + self.caption_for(f.attrs, f.line, rows)
        if kind == "pay":
            return self.pay(f)
        if kind == "contact":
            return self.contact(f)
        if kind == "pix":  # Pix is a pay scheme now: say so loudly, a payment code is missing from the print
            self.n.add("Q111", "the pix block is gone: Pix is pay {scheme=pix}, nothing printed", f.line, PAY_HINT)
            return []
        if kind in ("datamatrix", "pdf417"):
            rows = self.matrix_code(f, kind)
            return rows + self.caption_for(f.attrs, f.line, rows)
        if kind == "raw":
            if PH_RE.search(f.content):
                raise SecurityError("M314", "variables cannot be used inside raw blocks", f.line)
            hexs = re.sub(r"#.*", "", f.content)
            try:
                data = bytes.fromhex("".join(hexs.split()))
            except ValueError:
                raise ValueError(f"line {f.line}: raw block must contain hex bytes") from None
            self.n.add("P201", f"{len(data)} raw bytes sent as-is", f.line)
            return [RawRow(data, f.line)]
        if kind == "image":
            return self.image(f.content.strip(), f.attrs, f.line)
        if kind not in ("", "text", "txt", "plain"):
            hint = None
            if kind in ("chart", "graph", "plot", "sparkline", "vega", "vega-lite"):  # charts are tables here
                hint = "a chart is a table with {chart=line} under it: bobina help chart, docs/guides/charts.md"
            self.n.add("M102", f"block type '{kind}' is not supported (yet): printed as text", f.line, hint)
        rows = []
        cap = self.cols - indent
        for ln in f.content.rstrip("\n").split("\n"):
            cells = [Cell(ch, wide=is_wide(ch)) for ch in self.text(ln)]
            while True:
                if columns(cells) > cap:
                    self.n.add("L103", f"line longer than {cap} columns wrapped", f.line)
                piece, rest, w = [], [], 0
                for i, c in enumerate(cells):
                    cw = columns([c])
                    if w + cw > cap:
                        rest = cells[i:]
                        break
                    piece.append(c)
                    w += cw
                cl = self.lead(indent) + piece
                reason = self.native_ok(cl)
                rows.append(TextRow(cl, (1, 1), "left", f.line, native=not reason, reason=reason))
                if not rest:
                    break
                cells = rest
        return rows

    def fit_module(self, target: int, units: int, default: int, hi: int) -> int:
        """Integer module so that `units` modules fill `target` dots (width=). Integer modules keep codes scannable
        (no uneven bars)."""
        return max(1, min(hi, int(min(target, self.W) // units))) if target else default

    def object_width(
        self, value, line: int, hint: str = OBJECT_WIDTH_HINT, then: str = "the default width"
    ) -> int | None:
        """width= on any object (image, QR, barcode, Data Matrix, PDF417, pay, contact): full, half, third, 50%,
        30mm or dots (200, 200px). None when absent or unreadable (M101, with `hint`: a table column's says ch)."""
        if value is None or str(value).strip() == "":
            return None
        text = str(value).strip().lower().replace(",", ".")
        try:
            if text in FRACTIONS:
                w = int(self.W * FRACTIONS[text])
            else:
                unit = next((u for u in ("%", "mm", "px", "dots") if text.endswith(u)), "")
                n = float(text.removesuffix(unit))
                if not math.isfinite(n):  # inf, nan: no width (int() of them raised)
                    raise ValueError
                w = int(self.W * n / 100) if unit == "%" else self.p.mm_to_dots(n) if unit == "mm" else int(n)
            if w < 1:
                raise ValueError
        except ValueError:
            self.n.add("M101", not_a_value("width", value, then), line, hint)
            return None
        return w

    def object_align(self, attrs, default: str = "center") -> str:
        """left, center (the default for objects; a box's is left) or right: the classes .left .center .right, or
        align=."""
        given = next((a for a in ("left", "right", "center") if attrs.has(a)), attrs.kv.get("align"))
        return given if given in ("left", "right", "center") else default

    def caption_align(self, attrs, line: int) -> str:
        """caption-align=left|center|right; by default the caption follows its object."""
        given = attrs.kv.get("caption-align")
        if given is None:
            return self.object_align(attrs)
        if given in ("left", "center", "right"):
            return given
        self.n.add(
            "M101", not_a_value("caption-align", given, "aligned like what it is under"), line, "left, center or right"
        )
        return self.object_align(attrs)

    def caption_for(self, attrs, line: int, rows: list, auto: str = "", alt: str | None = None) -> list:
        """The caption line under an object that printed (none when it did not): caption="text", caption=auto (the
        block's own text: a payment's scheme and amount, a contact's network; none for the others), caption=alt
        (an image's alt text), none/no/off: no line. Placed by caption-align=, else as its object. A value from
        --data/--set is laid out as text: never Markdown, never an icon."""
        if not rows:
            return []
        raw = attrs.kv.get("caption", "auto" if auto else "")
        text = self.text(str(raw)).strip()
        word = text.lower()
        if word == "auto":
            text = auto
        elif word == "alt" and alt is not None:
            text = self.text(alt).strip()
            if not text:
                self.n.add("M101", "caption=alt: this image has no alt text", line, "write it: ![Shop sign](logo.png)")
        elif word in NO_CAPTION:
            text = ""
        return self.caption_rows(text, line, self.caption_align(attrs, line)) if text else []

    def object_words(self, attrs, line: int) -> None:
        """One way to size and place an object: width= and .left/.center/.right. size= is a text size and .justify
        spreads text: on an object they say what to write instead."""
        if "size" in attrs.kv:
            size = attrs.kv["size"]
            self.n.add("M101", f"size={size} is a text size", line, f"for an object: width={size}")
        if attrs.has("justify") or attrs.kv.get("align") == "justify":
            self.n.add("M101", ".justify spreads text", line, "an object fills the paper with width=full")
        self.align_word(attrs, line)

    def align_word(self, attrs, line: int) -> None:
        """align= on an object or a box that is not a placement: said (object_align then uses the default)."""
        given = attrs.kv.get("align")
        if given is not None and given not in ("left", "center", "right", "justify"):
            self.n.add("M101", not_a_value("align", given, "the default"), line, "left, center or right")

    def qr(self, f: Fence, resolved: bool = False) -> list:
        """A QR code, and under it the caption= line if there is one (1 mm of air: glued, it reads as part of it)."""

        rows = self._qr_code(f, resolved)
        return rows + self.caption_for(f.attrs, f.line, rows)  # auto: a plain QR has nothing to say on its own

    def caption_rows(self, text: str, line: int, align: str = "center") -> list:
        """The line under a code or an image, aligned as its object (1 mm of air: glued, it reads as part of it)."""
        from .model import Attrs, Run

        if not text:
            return []
        return [FeedRow(self.p.mm_to_dots(1)), *self.text_block([Run(text)], line=line, attrs=Attrs({align}))]

    def _qr_code(self, f: Fence, resolved: bool = False) -> list:
        """The form first (the printer's own code, or an image), then one sizing path. A fixed-module printer's own
        code (profile.FixedQR) is drawn as it prints; a size it cannot give or more data than it prints: an image."""
        kv = f.attrs.kv
        data = f.content if resolved else self.text(f.content.strip("\n"))
        ecc = kv.get("ecc", self.p.get("qr.default_ecc", "M")).upper()
        mod = int(kv.get("module", self.p.get("qr.default_module", 4)))
        align = self.object_align(f.attrs)
        render = kv.get("render", "native" if self.p.get("qr.native") else "raster")
        if self.dark:  # in an inverted box: an image on its white tile (a box is one image anyway)
            render = "raster"
        if ecc == "L":
            self.n.add("Q102", "QR with ECC L", f.line, "use ecc=M")
        if ecc not in ("L", "M", "Q", "H"):
            self.n.add("M101", f"unknown ecc '{ecc}'", f.line, "L, M, Q or H")
            ecc = "M"
        fixed = self.p.qr_fixed() if render == "native" else None
        try:  # a fixed-module printer's code is sized by its versions; any other by its matrix
            versions = imaging.qr_versions(data, ecc) if fixed else None
            m = None if fixed else imaging.qr_matrix(data, ecc, 0)
        except Exception as e:  # noqa: BLE001 - segno: DataOverflowError and friends
            self.n.add(
                "Q109",
                f"QR cannot hold {len(data)} characters at ECC {ecc}: {type(e).__name__}",
                f.line,
                "less data or ecc=L",
            )
            return []
        target = self.object_width(kv.get("width"), f.line)
        if fixed:
            row = self._fixed_native_qr(f, data, ecc, versions, target, fixed, align)
            if row:
                return [row]
            render, m = "raster", imaging.qr_matrix(data, ecc, 0)  # an image: the smallest version, as any raster QR
            if "module" not in kv:  # no size asked: the printer's own module, as its codes, if it fits the paper
                mod = max(1, min(fixed.dots, self.W // (len(m) + 4)))
        border = 4 if self.dark else 2  # an image carries its quiet zone; in an inverted box, a white tile of 4
        units = len(m) + (0 if render == "native" else 2 * border)
        lo = int(self.p.get(f"qr.min_module_{render}", 4))
        cannot = units * lo > self.W  # even the smallest module that scans would not fit the paper
        less = f"less data or ecc=L (module {lo} would not fit the paper)"
        if self.within:  # squeezed in a column: the room is the column's
            need = -(-units * lo // self.p.cell[0])
            less = f"a wider {self.within}: module {lo} needs {need} letters; or " + (
                "less data" if self.wrapping else "wrap=wrap, less data"
            )
        asked = mod = self.fit_module(target, units, mod, 16 if render == "native" else 64)
        while units * mod > self.W and mod > 1:  # the paper, or the column it is in: the largest module that fits
            mod -= 1
        if mod < asked:  # said once, for the module it gets
            self.n.add("Q103", f"QR does not fit: module reduced to {mod}", f.line,
                       less if self.within else "shorten the content")  # fmt: skip
        fitted = mod
        if self.tall_max and units * mod > self.tall_max and mod > 1:  # a turned label: the largest whole module
            mod = max(1, self.tall_max // units)  # that fits its height (never resampled: fit_label)
        if mod < lo:  # below what scans: said once, for the module printed, never as if fine
            if mod < fitted:
                self.n.add("Q101", f"QR module {mod} in {render} mode, to fit the turned label's height: it may not "
                           "scan", f.line, "less data or ecc=L; or take the QR out of the turned columns")  # fmt: skip
            elif mod < asked:  # the paper took it below what scans
                self.n.add("Q101", f"QR module {mod} in {render} mode: it may not scan", f.line, less)
            else:
                what = f"width={kv['width']} gives module {mod}" if target else f"QR module {mod}"
                hint = f"a larger width or less data (module ≥ {lo})" if target else f"use module={lo}"
                self.n.add("Q101", f"{what} in {render} mode" + (": it may not scan" if cannot else ""), f.line,
                           less if cannot else hint)  # fmt: skip
        if render == "native":
            return [QRRow(data, mod, ecc, align, f.line)]
        if self.dark:
            return [self.code_tile(imaging.qr_image(data, mod, ecc), "qr", align, f.line, mod, 4)]
        return [BitmapRow(imaging.place(imaging.qr_image(data, mod, ecc, border=2), self.W, align), f.line, "qr")]

    def turned_rects(self, keep, size: tuple[int, int], ang: float, line: int) -> tuple:
        """Code tiles (BitmapRow.keep) turned with their block; at a slant they are lost: inside an inverted box the
        codes print white on black (Q115)."""
        turned = _turned_rects(keep, size, ang)
        if turned is None:
            self.n.add("Q115", f"a code turned rotate={ang:g} inside an inverted box prints white on black: it may not "
                       "scan", line, "rotate=90, 180 or 270, or the code outside the inverted box")  # fmt: skip
            return ()
        return turned

    def code_tile(self, code: Image.Image, kind: str, align: str, line: int, mod: int, side: int, ends: int = 4,
                  core: int = 0) -> BitmapRow:  # fmt: skip
        """A code laid out in an inverted box (self.dark): on a white tile with its quiet zone, `side` modules left and
        right of its `core` (a barcode's bars: its text may be wider; all of it otherwise) and `ends` above and below,
        the tile kept black on white when the box turns the rest white on black (BitmapRow.keep). Wider than the room:
        the margin left is said (Q115) with the modules it has; in turned columns the tile cannot be kept (Q115)."""
        name = {"qr": "QR code", "datamatrix": "Data Matrix", "pdf417": "PDF417"}.get(kind, "barcode")
        core = core or code.width
        want = max(code.width, core + 2 * side * mod)
        w = min(self.W, want)
        if self.dark_lost:  # turned with its label: the margin stays, but the box turns it white on black
            self.n.add("Q115", f"a {name} in turned columns inside an inverted box prints white on black: it may not "
                       "scan", line, "put the code outside the inverted box")  # fmt: skip
        elif w < want and side:
            self.n.add("Q115", f"a {name} in an inverted box: {max(0, (w - core) // 2) // mod} modules of white beside "
                       f"it, {side} wanted ({want} dots, the room has {self.W})", line,
                       "a smaller module= or width=, or the code outside the box")  # fmt: skip
        tile = Image.new("1", (w, code.height + 2 * ends * mod), 1)
        tile.paste(code, ((w - code.width) // 2, ends * mod))
        x = max(0, {"left": 0, "right": self.W - w}.get(align, (self.W - w) // 2))
        keep = () if self.dark_lost else ((x, 0, x + w, tile.height),)
        return BitmapRow(imaging.place(tile, self.W, align), line, kind, keep=keep)

    def _fixed_native_qr(self, f: Fence, data: str, ecc: str, versions, target, fixed, align: str) -> QRRow | None:
        """The printer's own code on a fixed-module firmware (profile.FixedQR), for content that needs versions
        (segno's mode choice, the worst case in byte mode). None when it must be an image instead: content that may
        need more than the firmware prints (Q113), module= other than its own (Q113), or a readable width= (silent: the
        image is exactly that wide). With render=native the code stays and Q113 says module=/width= do nothing."""
        kv = f.attrs.kv
        needed, worst = versions
        explicit = kv.get("render") == "native"
        code = fixed.code(needed, worst)
        if code is None:
            bytes_ = f", {worst} if the printer encodes it as bytes" if worst > needed else ""
            self.n.add(
                "Q113",
                ("render=native ignored: " if explicit else "")
                + f"QR version {needed}{bytes_} ({len(data)} characters at ECC {ecc}); this printer's own QR stops at "
                f"version {fixed.content_max_version}: printed as an image",
                f.line,
                "nothing to fix: the image prints exactly; less data gives the printer's own code",
            )
            return None
        module = "module" in kv and int(kv["module"]) != fixed.dots  # module=5 (or 05): what it gives anyway
        width = target is not None  # an unreadable width= (M101) asks for nothing
        asked = [f"{k}={kv[k]}" for k, on in (("module", module), ("width", width)) if on]
        names = " and ".join(a.split("=")[0] + "=" for a in asked)
        if asked and explicit:
            self.n.add(
                "Q113",
                f"render=native: {' '.join(asked)} has no effect, this printer's own QR always has {fixed.dots}-dot "
                "modules",
                f.line,
                f"remove {names}, or remove render=native to print that size as an image",
            )
        elif module:
            self.n.add(
                "Q113",
                f"this printer's own QR always has {fixed.dots}-dot modules: module={kv['module']} printed as an image",
                f.line,
                f"remove module= for the printer's own code ({fixed.dots}-dot modules), or keep it: the image prints "
                "exactly",
            )
            return None
        elif width:
            return None
        param, printed = code
        return QRRow(data, fixed.dots, ecc, align, f.line, version=printed, param=param)

    def barcode(self, f: Fence) -> list:
        from . import codes

        data = self.text(f.content.strip())
        kind = f.attrs.kv.get("type", "code128").lower()
        if kind not in codes.TYPES:
            self.n.add(
                "Q109",
                f"unknown barcode type '{kind}'",
                f.line,
                ", ".join(sorted({k for k in codes.TYPES if "-" not in k})),
            )
            return []
        kind = codes.TYPES[kind][1] or kind.replace("-", "")
        data = "".join(ch for ch in data if 32 <= ord(ch) < 127)
        if not data or len(data) > 250:
            self.n.add(
                "Q109",
                f"{kind}: {len(data)} printable ASCII characters (1–250 allowed)",
                f.line,
                "use a QR code for long or non-ASCII content",
            )
            return []
        if kind in self.p.get("barcode.unsupported", []):
            self.n.add("Q106", f"{kind} does not print on {self.p.id}", f.line, "use ean13/ean8/upca or code128")
            return []
        if kind in self.p.get("barcode.weak", []):
            self.n.add(
                "Q107", f"{kind}: phones detect but often cannot read it", f.line, "use code128, or module=3 height=120"
            )
        mod = int(f.attrs.kv.get("module", self.p.get("barcode.default_module", 2)))
        if mod < int(self.p.get("barcode.min_module", 2)):
            self.n.add("Q108", f"module {mod}", f.line, f"use module={self.p.get('barcode.min_module', 2)}")
        height = int(f.attrs.kv.get("height", self.p.get("barcode.default_height", 80)))
        text = f.attrs.kv.get("text", "below")
        align = self.object_align(f.attrs)
        orientation = f.attrs.kv.get("orientation", "auto")
        target = self.object_width(f.attrs.kv.get("width"), f.line)
        pattern = None
        try:
            pattern, _ = codes.bars(kind, data, self.p.code39_wide())  # the firmware's GS k width
        except ValueError as e:
            if "no preview encoder" in str(e):
                self.n.add("Q105", f"{kind}: preview shows a placeholder", f.line)
            else:
                self.n.add("Q109", f"{kind} '{data}': {e}", f.line)
                return []
        except Exception as e:  # noqa: BLE001 - python-barcode raises various errors for bad input
            self.n.add("Q109", f"{kind} '{data}': {e}", f.line)
            return []
        units = len(pattern) if pattern else 0
        if units and target and orientation != "vertical":
            fitted = self.fit_module(target, units, mod, 6)  # GS w accepts 1..6
            lo = int(self.p.get("barcode.min_module", 2))
            if fitted < lo:
                self.n.add("Q108", f"width={f.attrs.kv['width']} would give module {fitted}: too thin to scan", f.line,
                           f"module {lo} is kept; a larger width or less data")  # fmt: skip
            mod = max(lo, fitted)
        if self.tall_max is not None and pattern and orientation != "vertical":  # in a turned label
            mod = self.feed_module(kind, units, mod, f.line)
            quiet = int(self.p.get("barcode.quiet_modules", 10)) * mod
            im = codes.image(kind, data, mod, height, text, self.em, wide=3)  # drawn by bobina, as a vertical one
            over = im.height + (2 * 2 * mod if self.dark else 0) - self.tall_max  # an inverted box's tile: 2 modules
            if over > 0:  # shorter bars to fit the label's height, their widths untouched
                im = codes.image(kind, data, mod, max(1, height - over), text, self.em, wide=3)
                if height - over < BAR_MIN_DOTS:
                    self.n.add("Q108", f"bars {max(1, height - over)} dots tall, to fit the turned label's height: "
                               "too short to scan reliably", f.line, "text=none, or take the barcode out of the turned "
                               "columns")  # fmt: skip
            if self.dark:
                drawn = len(codes.bars(kind, data, 3)[0]) * mod  # the bars as drawn here, 3:1 (units: the firmware's)
                return [self.code_tile(im, "barcode", align, f.line, mod, quiet // mod, 2, drawn)]
            padded = Image.new("1", (im.width + 2 * quiet, im.height), 1)
            padded.paste(im, (quiet, 0))
            return [BitmapRow(imaging.place(padded, self.W, align), f.line, "barcode")]
        too_wide = bool(units) and units * mod > self.W
        if orientation == "vertical" or (orientation == "auto" and too_wide):
            if not pattern:
                self.n.add("Q104", f"{kind} cannot be drawn vertically (no encoder)", f.line, "use code128")
                return []
            lo_feed = int(self.p.get("barcode.min_module_feed", 3))
            wide_dots = units * mod  # what made it too wide: the firmware's horizontal code
            if mod < lo_feed:
                if "module" in f.attrs.kv:
                    self.n.add(
                        "Q108",
                        f"module {mod} along the paper (vertical barcode) did not scan",
                        f.line,
                        f"use module={lo_feed}",
                        "05/11 codes ticket",
                    )
                else:
                    mod = lo_feed  # feed direction blurs more than the head direction
            bar_len = max(16, min(self.W, target) - 8) if target else height
            # drawn by bobina, not by the firmware: the readable 3:1 Code39, whatever the printer's GS k does
            im = codes.image(kind, data, mod, bar_len, text, self.em, wide=3).rotate(-90, expand=True)
            quiet = int(self.p.get("barcode.quiet_modules", 10)) * mod
            if self.dark:  # its quiet zones at its ends, above and below
                out = self.code_tile(im, "barcode", align, f.line, mod, 0, quiet // mod)
            else:
                padded = Image.new("1", (im.width, im.height + 2 * quiet), 1)
                padded.paste(im, (0, quiet))
                out = BitmapRow(imaging.place(padded, self.W, align), f.line, "barcode")
            if orientation == "auto":  # the length of the image just drawn, quiet zones included
                self.n.add(
                    "Q110",
                    f"{kind} '{data[:24]}' is {wide_dots} dots wide (paper {self.W}): "
                    f"it will print VERTICALLY, about {out.image.height / (self.p.dpi / 25.4):.0f} mm along the paper",
                    f.line,
                    "keep it (fine), set orientation=vertical to silence this, "
                    "or orientation=horizontal (it would be cut) — or use a QR code",
                )
            return [out]
        quiet = int(self.p.get("barcode.quiet_modules", 10))
        if self.dark and pattern:  # bars as the preview draws them, the thinnest that scan if the tile needs it
            asked, lo = mod, int(self.p.get("barcode.min_module", 2))
            while mod > lo and (units + 2 * quiet) * mod > self.W:
                mod -= 1
            too_wide = units * mod > self.W
            if mod < asked:
                self.n.add("Q104", f"{kind}: module {asked} made {mod} so that its white margin fits the inverted box",
                           f.line, "a wider box, or less data")  # fmt: skip
        if too_wide:
            self.n.add(
                "Q104",
                f"{units * mod} dots wide (paper {self.W}): it will be cut",
                f.line,
                "orientation=auto prints it vertically",
            )
        if self.dark:  # the bars (or the preview's placeholder) on their tile
            row = BarcodeRow(kind, data, mod, height, text, align, f.line)
            im = preview.barcode_image(row, self.em)
            return [self.code_tile(im, "barcode", align, f.line, mod, quiet, 2, units * mod if pattern else 0)]
        return [BarcodeRow(kind, data, mod, height, text, align, f.line)]

    def feed_module(self, kind: str, units: int, mod: int, line: int) -> int:
        """The module of a code whose bars run along the paper once its turned label turns (a barcode, PDF417), as a
        vertical barcode's do, so the same rule measured on paper: at least barcode.min_module_feed (05/11: modules 2
        and 3 did not scan, 4 did; 18/11: an EAN-13 at module 2 in a turned label did not), and
        barcode.quiet_modules of white each side, within its column. A column too narrow for that is said (Q108) with
        the width the code needs; it then gets the largest module that fits."""
        lo, quiet = int(self.p.get("barcode.min_module_feed", 4)), int(self.p.get("barcode.quiet_modules", 10))
        mod = max(mod, lo)
        fits = self.W // (units + 2 * quiet)
        if fits < mod:
            per = self.p.dpi / 25.4
            self.n.add("Q108", f"{kind} in a turned label: its bars run along the paper, so it needs module {lo} and "
                       f"{quiet} modules of white each side, {(units + 2 * quiet) * lo / per:.0f} mm across its "
                       f"column, which has {self.W / per:.0f} mm: it may not scan", line,
                       "a wider column, a longer length=, or the code in a label of its own",
                       "05/11 codes ticket; 18/11 shelf label")  # fmt: skip
            mod = max(1, fits)
        return mod

    def matrix_code(self, f: Fence, kind: str) -> list:
        """2D codes the printer cannot draw natively: always raster (R5: module >= 4 for square codes)."""
        data = self.text(f.content.strip("\n"))
        default = 4 if kind == "datamatrix" else 2
        mod = int(f.attrs.kv.get("module", default))
        if kind == "datamatrix" and mod < int(self.p.get("qr.min_module_raster", 4)):
            self.n.add("Q101", f"datamatrix module {mod} in raster", f.line, "use module=4")
        align = self.object_align(f.attrs)
        target = self.object_width(f.attrs.kv.get("width"), f.line)

        def draw(m):  # in an inverted box without a margin of its own: code_tile gives it one
            if kind == "datamatrix":
                return imaging.datamatrix_image(data, m, 0 if self.dark else 2)
            return imaging.pdf417_image(data, m, int(f.attrs.kv.get("ratio", 3)), int(f.attrs.kv.get("columns", 4)),
                                        0 if self.dark else 4)  # fmt: skip

        side = 4  # modules of white beside it in an inverted box (code_tile)
        try:
            im = draw(mod)
            if target:  # the largest integer module whose code fits the asked width
                fitted = self.fit_module(target, max(1, im.width // mod), mod, 64)
                if fitted != mod:
                    mod, im = fitted, draw(fitted)
                lo = int(self.p.get("qr.min_module_raster", 4))
                if kind == "datamatrix" and mod < lo:
                    self.n.add("Q101", f"width={f.attrs.kv['width']} gives datamatrix module {mod}", f.line,
                               f"a larger width or less data (module ≥ {lo})")  # fmt: skip
            stepped, ends = False, 4 if self.dark else 0  # an inverted box's tile: 4 modules above and below
            while self.tall_max and im.height + 2 * ends * mod > self.tall_max and mod > 1:  # a turned label: whole
                mod, stepped = mod - 1, True  # modules
                im = draw(mod)
            if stepped and kind == "datamatrix" and mod < int(self.p.get("qr.min_module_raster", 4)):
                self.n.add("Q101", f"datamatrix module {mod}, to fit the turned label's height", f.line,
                           "less data, or take it out of the turned columns")  # fmt: skip
            if self.tall_max is not None and kind == "pdf417":  # its rows of bars run along the paper once turned
                units = max(1, im.width // mod)
                turned = self.feed_module(kind, units, mod, f.line)
                if turned != mod:
                    mod, im = turned, draw(turned)
                side = int(self.p.get("barcode.quiet_modules", 10))  # beside its bars (the tile's, in an inverted box)
                if not self.dark:
                    padded = Image.new("1", (im.width + 2 * side * mod, im.height), 1)
                    padded.paste(im, (side * mod, 0))
                    im = padded
            asked, lo = mod, min(mod, 4 if kind == "datamatrix" else 2)
            while self.dark and mod > lo and im.width + 2 * side * mod > self.W:  # its tile beside it
                mod -= 1
                im = draw(mod)
            if mod < asked:
                self.n.add("Q104", f"{kind}: module {asked} made {mod} so that its white margin fits the inverted box",
                           f.line, "a wider box, a smaller width= or less data")  # fmt: skip
        except Exception as e:  # noqa: BLE001
            self.n.add("Q109", f"{kind}: {e}", f.line)
            return []
        if im.width > self.W:
            self.n.add(
                "Q104",
                f"{kind} {im.width} dots wide (paper {self.W})",
                f.line,
                "less data, smaller module or fewer columns",
            )
            im = im.crop((0, 0, self.W, im.height))
        if self.dark:
            return [self.code_tile(im, kind, align, f.line, mod, side)]
        return [BitmapRow(imaging.place(im, self.W, align), f.line, kind)]

    def pay(self, f: Fence) -> list:
        """A payment QR code (```pay {scheme=…}): the payload from pay.py, a QR, and a caption line."""
        from babel import numbers as bnumbers

        from . import pay
        from .locales import choose
        from .model import Attrs
        from .templating import ambiguity_message, is_negative, parse_number, two_readings

        kv = {k: self.text(v) for k, v in f.attrs.kv.items()}
        name = (kv.get("scheme") or "").strip().lower()
        s = pay.SCHEMES.get(name)
        if s is None:
            near = pay.closest(name) if name else ""
            what = f"unknown scheme '{name}'" if name else "pay needs scheme="
            hint = (f"did you mean scheme={near}? " if near else "") + "schemes: " + ", ".join(pay.SCHEMES)
            self.n.add("Q111", f"pay: {what}", f.line, hint)
            return []
        label = f"pay scheme={s.name}"
        example = s.block.replace("\n", " ")
        carries = "amount" in s.attrs
        for k in kv:
            if k not in s.attrs and k not in pay.QR_ATTRS | SAID_BY_OBJECT and k != "amount" and str(kv[k]).strip():
                hint = f"write {pay.OLD_NAMES[k]}= (the old Pix name)" if k in pay.OLD_NAMES else ""
                takes = f"it takes {', '.join(s.attrs)} (bobina help pay {s.name})"
                self.n.add("M101", f"{label} does not use '{k}='", f.line, hint or takes)
        body = self.text(f.content.strip())
        if s.name == "other":
            kv["payload"] = body
        elif body:
            self.n.add(
                "M101",
                f"{label}: the block body is ignored",
                f.line,
                "attributes only; a pasted payload needs scheme=other",
            )
        loc = (self.locale or choose(self.doc.meta)).locale  # the job's one locale, as in its dates and prices
        amount = None
        if str(kv.get("amount") or "").strip() and not carries:
            self.n.add("M156", f"{label} cannot carry an amount: the payer types it", f.line, "show the price as text")
        elif str(kv.get("amount") or "").strip():
            raw = kv["amount"]
            negative = is_negative(raw)  # its own error below (also -R$ 10,00 and −10), not "reads two ways"
            both = None if negative else two_readings(raw, s.decimals)
            if both:  # 1.890: R$ 1,89 or R$ 1.890? a payment never guesses, whatever the locale
                msg, hint = ambiguity_message(raw, *both)
                self.n.add("Q111", f"{label}: {msg}", f.line, hint)
                return []
            n = parse_number(raw, bnumbers.get_decimal_symbol(loc))  # read as the caption writes it
            problem = (
                f"amount '{raw}' is not a number" if n is None
                else f"amount {raw} cannot be negative" if n < 0
                else f"amount {raw} has more than {s.decimals} decimals" if round(n, s.decimals) != n
                else ""
            )  # fmt: skip
            if problem:
                hint = f"use {round(n, s.decimals)}" if n and n > 0 else "digits, like 10.00 or 10,00"
                self.n.add("Q111", f"{label}: {problem}", f.line, hint)
                return []
            amount = float(n) if n else None  # 0: an open amount (the payer types it), as Pix always took it
        try:
            payload = s.build(kv, amount)
        except ValueError as e:
            hint = getattr(e, "hint", "") or f"example: {example}"
            self.n.add("Q111", f"{label}: {e}", f.line, f"{hint} · fields and limits: bobina help pay {s.name}")
            return []
        if not s.tested:
            why = "bobina reprints the pasted payload without checking it" if s.name == "other" else (
                f"nobody has scanned this code with {s.app or f'the {s.title} app'} yet")  # fmt: skip
            self.n.add(
                "P302", f"{label}: {why} ({pay.MARK})", f.line, "scan a printed code with the app before using it"
            )
        keep = {k: v for k, v in f.attrs.kv.items() if k in pay.QR_ATTRS - {"caption", "scheme"}}
        rows = self._qr_code(Fence(line=f.line, attrs=Attrs(set(f.attrs.classes), keep), kind="qr", content=payload),
                             resolved=True)  # fmt: skip
        return rows + self.caption_for(f.attrs, f.line, rows, auto=pay.caption(s, amount, kv, loc))

    def contact(self, f: Fence) -> list:
        """A contact or profile QR code (```contact NETWORK, the value in the body): the link from contact.py, a QR
        and a caption line. A value that makes no link: Q112, and the code is left out (the rest prints)."""
        from . import contact
        from .model import Attrs

        name = self.text(f.arg).strip().lower()
        n = contact.find(name) if name else None
        if n is None:
            near = contact.closest(name) if name else ""
            what = f"unknown network '{name}'" if name else "contact needs a network: ```contact whatsapp"
            hint = (f"did you mean {near}? " if near else "") + "networks: " + ", ".join(contact.NETWORKS)
            self.n.add("Q112", f"contact: {what}", f.line, hint)
            return []
        label = f"contact {n.name}"
        kv = {k: self.text(v) for k, v in f.attrs.kv.items()}
        for k in kv:
            if k not in contact.QR_ATTRS | SAID_BY_OBJECT and k not in (n.attrs or {}):
                takes = ", ".join([*(n.attrs or {}), "caption", "width", "module", "ecc"])
                self.n.add("M101", f"{label} does not use '{k}='", f.line, f"it takes {takes} (bobina help contact "
                           f"{n.name})")  # fmt: skip
        body = self.text(f.content).strip()
        value = body if n.group == "card" else body.split("\n")[0].strip()
        if n.group != "card" and "\n" in body:
            self.n.add("M101", f"{label}: only the first line of the block is used", f.line,
                       "one value per block: another network, another block")  # fmt: skip
        try:
            if not value:
                raise contact.ContactError(f"{label} needs a value in the block body", f"for example: {n.example}")
            payload, detail, *more = n.build(value, kv)
            for msg, hint in more[0] if more else []:  # a card line it cannot use, text= on a group link
                self.n.add("M101", msg, f.line, hint)
        except contact.ContactError as e:
            hint = e.hint or f"for example: {n.example}"
            msg = str(e) if str(e).startswith("contact ") else f"contact {e}"  # "contact whatsapp: '11 …' has …"
            self.n.add("Q112", msg, f.line, f"{hint} · bobina help contact {n.name}")
            return []
        if not n.tested:
            why = f"nobody has scanned this code with {n.app or f'the {n.title} app'} yet"
            if n.proprietary:
                why += f"; {n.proprietary}"
            self.n.add("P303", f"{label}: {why} ({contact.MARK})", f.line,
                       "scan a printed code with the app before handing it out")  # fmt: skip
        keep = {k: v for k, v in f.attrs.kv.items() if k in contact.QR_ATTRS - {"caption"}}
        rows = self._qr_code(Fence(line=f.line, attrs=Attrs(set(f.attrs.classes), keep), kind="qr", content=payload),
                             resolved=True)  # fmt: skip
        return rows + self.caption_for(f.attrs, f.line, rows, auto=contact.caption(n, detail))

    def image_width(self, width, line: int) -> int:
        """width= of an image (object_width: full, half, third, 50%, 30mm, dots); the paper width when absent."""
        w = self.object_width(width, line)
        if w is None:
            return self.W
        if w > self.W:
            self.n.add("I102", f"image width {w} reduced to {self.W}", line)
            w = self.W
        return w

    def image(self, src: str, attrs, line: int, alt: str = "") -> list:
        if self.r is not None and self.r.tainted_in(src):
            raise SecurityError("M312", "an image path cannot come from --data/--set values", line)
        src = self.text(src)
        self.object_words(attrs, line)
        rows = self._image(src, attrs, line)
        return rows + self.caption_for(attrs, line, rows, alt=alt or "")

    def _image(self, src: str, attrs, line: int) -> list:
        w = self.image_width(attrs.kv.get("width"), line)
        try:
            page = int(attrs.kv.get("page", 1))
        except ValueError:
            page = 1
        settings = tuple(self.p.get(k) for k in ("image.dither", "image.gamma", "image.gamma_atkinson"))
        extra = (w, page, self.W, self.net, self.image_dirs, repr(self.img), settings)  # --sandbox: its own entry
        key = _image_key(src, self.doc.base_dir, attrs, extra)
        if key is not None and key in _IMAGES:  # a batch of 1000 labels with the same logo decodes it once
            host, row_im, notes = _IMAGES[key]
            if host:
                self.n.add("I104", f"fetched {host}", line, "that server can see when you print")
            for code, msg, hint in notes:
                self.n.add(code, msg, line, hint)
            return [BitmapRow(row_im, line, "image")]
        mark = len(self.n)  # the notes of this image, said again when its cached dots are reused
        ang = self.angle(attrs, line, image=True) % 360
        cos, sin = _turn(ang)
        crop = self.crop_spec(attrs, line)
        shape = self.mask_shape(attrs, line)
        vbox = None  # a vector's crop=, in dots of the drawing as rendered

        def opened(width: int):
            return imaging.open_image(src, self.doc.base_dir, width=width, page=page, allow_net=self.net,
                                      confine=self.image_dirs, draft=crop is None)  # fmt: skip

        try:
            im = opened(max(8, w))
            vector = im.info.get("bobina.kind") == "vector"
            part = self.vector_crop(crop, attrs, line) if crop and vector else None  # fractions of the drawing
            if vector and (ang or part):  # drawn again so that what prints (the part kept, turned) is w dots wide
                fw, fh = (part[2] - part[0], part[3] - part[1]) if part else (1.0, 1.0)
                aspect = im.height * fh / max(1, im.width * fw)
                wide = min(4096, max(8, round(w / (cos + sin * aspect) / fw)))
                if wide != im.width:
                    im = opened(wide)
            if part:
                vbox = tuple(round(f * n) for f, n in zip(part, (*im.size, *im.size), strict=True))
        except sources.ImageError as e:
            self.n.add(e.code, f"image '{src[:60]}': {e}", line, e.hint or "check the path (relative to the document)")
            return []
        except Exception as e:  # noqa: BLE001
            self.n.add("I101", f"image '{src[:60]}': {e.__class__.__name__}", line, "check the path")
            return []
        if im.info.get("bobina.host"):
            self.n.add("I104", f"fetched {im.info['bobina.host']}", line, "that server can see when you print")
        vector, host = im.info.get("bobina.kind") == "vector", im.info.get("bobina.host")
        im = imaging.flatten(im)  # as an image viewer shows it (EXIF turn): the pixels crop= counts
        if crop and vector:
            im = im.crop(vbox) if vbox else im
        elif crop:
            box = self.raster_crop(crop, attrs, im.size, line)
            im = im.crop(tuple(round(v) for v in box)) if box else im
        if attrs.has("invert"):  # black and white swapped, before the turn (its corners stay paper) and the mask
            im = ImageOps.invert(im)
        across = im.width * cos + im.height * sin  # how wide the turned image is: what is fitted to the paper
        if ang % 90:
            right = im.width if cos >= sin else im.height  # the nearest right angle would fit this side
            kept = right / max(1.0, across)
            if kept < 0.9:
                said = attrs.kv.get("rotate")
                self.n.add("I110", f"rotate={said}: the image prints at {kept:.0%} of its size so its corners stay"
                           " on the paper", line, "a right angle (90, 180, 270) keeps it bigger")  # fmt: skip
        if across > 2 * w and min(im.size) > 1:  # a 40 MP photo: turned and sampled small, never at full size
            f = max(1, int(across // (2 * w)))
            im = im.reduce(f) if f > 1 else im
        kind, level = self.treatment(im, attrs, vector, line, src)  # on the source: a slant's soft edges never decide
        im = self.turn(im, ang, attrs, line)
        default_gamma = (
            self.p.get("image.gamma_atkinson", 1.5) if kind == "atkinson" else self.p.get("image.gamma", 1.8)
        )
        gamma = float(attrs.kv.get("gamma", self.img.get("gamma", default_gamma)))
        align = self.object_align(attrs)
        bw = imaging.photo(im, max(8, w), gamma, kind, level=level, flat=True)
        if shape:  # at the printed size: a clean edge, paper outside
            bw = imaging.masked(bw, shape, self.mask_radius(attrs, bw.size, line) if shape == "rounded" else 0)
        placed = imaging.place(bw, self.W, align)
        notes = tuple((n.code, n.message, n.suggestion) for n in list(self.n)[mark:] if n.code != "I104")
        if key is not None:
            _remember(key, (host, placed, notes))
        return [BitmapRow(placed, line, "image")]

    def crop_spec(self, attrs, line: int):
        """crop=x,y,w,h parsed (imaging.parse_crop), or None: absent, or not four numbers (M101)."""
        given = attrs.kv.get("crop")
        if given is None:
            return None
        spec = imaging.parse_crop(given)
        if spec is None:
            self.n.add("M101", not_a_value("crop", given, "the image prints whole"), line, CROP_HINT)
        return spec

    def raster_crop(self, spec, attrs, size: tuple[int, int], line: int):
        """The box crop= keeps of a photo `size` pixels big (as a viewer shows it); None: none of it is in the image,
        printed whole. Partly outside: kept to the image. Both said (I111), with the image's size."""
        box, clamped = imaging.crop_box(spec, size)
        given, (W, H) = attrs.kv["crop"], size
        if box is None:
            self.n.add("I111", f"crop={given} is outside the {W}x{H} px image or has no size: printed uncropped", line,
                       CROP_HINT)  # fmt: skip
        elif clamped:
            x0, y0, x1, y1 = (round(v) for v in box)
            self.n.add("I111", f"crop={given} goes past the {W}x{H} px image: cut to {x0},{y0},{x1 - x0},{y1 - y0}",
                       line, "x + width and y + height within the image's size")  # fmt: skip
        return box

    def vector_crop(self, spec, attrs, line: int):
        """crop= of an SVG or PDF page, in percentages of the drawing (it has no pixels: it is drawn at the size it
        prints), as fractions (left, top, right, bottom); None: printed whole (M101 for pixels, I111 outside)."""
        given = attrs.kv["crop"]
        if any(v and not pct for v, pct in spec):  # 0 is 0 in any unit
            self.n.add("M101", f"crop={given}: an SVG or PDF is cropped in percentages: printed uncropped", line,
                       "crop=0,0,50%,50% (the top-left quarter)")  # fmt: skip
            return None
        box, clamped = imaging.crop_box(spec, (100, 100))
        if box is None:
            self.n.add("I111", f"crop={given} is outside the drawing or has no size: printed uncropped", line,
                       CROP_HINT)  # fmt: skip
            return None
        if clamped:
            x0, y0, x1, y1 = box
            self.n.add("I111", f"crop={given} goes past the drawing: cut to {x0:g}%,{y0:g}%,{x1 - x0:g}%,"
                       f"{y1 - y0:g}%", line, "x + width and y + height within 100%")  # fmt: skip
        return tuple(v / 100 for v in box)

    def mask_shape(self, attrs, line: int) -> str | None:
        """mask=circle|ellipse|rounded, or None (absent, or unknown: M101 with the shapes). radius= goes with
        mask=rounded only (M101 otherwise)."""
        given = attrs.kv.get("mask")
        shape = None if given is None else str(given).strip().lower()
        if shape is not None and shape not in imaging.MASKS:
            self.n.add("M101", not_a_value("mask", given, "the image prints whole"), line,
                       "mask=circle, mask=ellipse or mask=rounded radius=3mm")  # fmt: skip
            shape = None
        if "radius" in attrs.kv and shape != "rounded":
            self.n.add("M101", "radius= does nothing without mask=rounded", line, "mask=rounded radius=3mm")
        return shape

    def mask_radius(self, attrs, size: tuple[int, int], line: int) -> int:
        """radius= of mask=rounded in dots: 12 (dots), 12px, 3mm, or 10% of the shorter side (the default)."""
        short = min(size)
        given = attrs.kv.get("radius")
        text = str(MASK_RADIUS if given is None else given).strip().lower().replace(",", ".")
        unit = next((u for u in ("%", "mm", "px", "dots") if text.endswith(u)), "")
        try:
            n = float(text.removesuffix(unit))
            if not (math.isfinite(n) and n >= 0):
                raise ValueError
        except ValueError:
            self.n.add(
                "M101",
                not_a_value("radius", given, "10% of the shorter side, the default"),
                line,
                "3mm, 12 (dots) or 10% (of the shorter side)",
            )
            n, unit = float(MASK_RADIUS.removesuffix("%")), "%"
        return round(short * n / 100) if unit == "%" else self.p.mm_to_dots(n) if unit == "mm" else round(n)

    def turn(self, im, ang: float, attrs, line: int = 0) -> Image.Image:
        """The source turned clockwise by `ang` (rotate=, .flip), then mirrored (mirror=x|y|xy, .mirror = x), before
        it is fitted to the paper: a tall photo turned sideways still fills the width, and a slanted one fits whole,
        its corners white."""
        if ang:
            exact = ang % 90 == 0
            im = im.rotate(-ang, expand=True, fillcolor=(255, 255, 255),
                           resample=Image.NEAREST if exact else Image.BICUBIC)  # fmt: skip
        across, down = self.mirror_axes(attrs, line)
        if across:
            im = ImageOps.mirror(im)
        return ImageOps.flip(im) if down else im

    def mirror_axes(self, attrs, line: int) -> tuple[bool, bool]:
        """(left-right, top-bottom) from mirror=x|y|xy, or .mirror (left-right)."""
        value = attrs.kv.get("mirror")
        if value is None:
            return attrs.has("mirror"), False
        axes = str(value).strip().lower()
        if axes in MIRRORS:
            return MIRRORS[axes]
        self.n.add(
            "M101", not_a_value("mirror", value, "not mirrored"), line, "x (left-right), y (top-bottom) or xy (both)"
        )
        return False, False

    def treatment(self, im, attrs, vector: bool, line: int, src: str) -> tuple[str, int | None]:
        """(dither kind, threshold level; None: the level between ink and paper, from the image). Written wins:
        threshold=N%, .threshold (level from the image), .dither (always a photo dither), dither=KIND; then the
        document's image: dither; vectors are line art; otherwise bobina looks (imaging.line_art): a logo prints
        sharp, a photo is dithered. dither=threshold written anywhere keeps its fixed cut at 128."""
        default = imaging.DITHERS.get(str(self.img.get("dither", self.p.get("image.dither", "fs"))), "fs")
        given = attrs.kv.get("threshold")
        if given is not None:
            try:
                pct = float(str(given).strip().removesuffix("%"))
                if not 0 < pct < 100:
                    raise ValueError
            except ValueError:
                self.n.add(
                    "M101",
                    not_a_value("threshold", given, "the default cut"),
                    line,
                    "a percentage from 1% to 99% (higher: more black)",
                )
                return "threshold", None
            return "threshold", round(255 * pct / 100)
        if attrs.has("threshold"):
            return "threshold", None
        if attrs.has("dither"):  # the photo look, even when the default is a threshold
            return (default if default != "threshold" else "fs"), None
        if "dither" in attrs.kv:
            name = str(attrs.kv["dither"])
            if name not in imaging.DITHERS:
                self.n.add(
                    "M101",
                    not_a_value("dither", name, "floyd-steinberg, the default"),
                    line,
                    "floyd-steinberg, atkinson, bayer or threshold",
                )
            kind = imaging.DITHERS.get(name, "fs")
            return kind, 128 if kind == "threshold" else None
        if vector:
            return "threshold", 128  # rendered at the paper width: crisp edges already
        if "dither" in self.img or default == "threshold":  # the document or the profile chose for every image
            return default, 128 if default == "threshold" else None
        from pathlib import PurePosixPath

        name = PurePosixPath(src).name if not src.startswith("data:") else "the image"
        name = name if len(name) <= 40 else "the image"
        if imaging.line_art(im):  # what bobina saw, what it did, and how to get the other look
            self.n.add("I109", f"{name} looks like a drawing: printed in black and white", line,
                       "{.dither} to dither it; {threshold=60%} moves the cut")  # fmt: skip
            return "threshold", None
        self.n.add("I109", f"{name} looks like a photo: dithered", line, "{.threshold} for black and white")
        return default, None

    def table(self, t: Table, indent: int) -> list:
        """Monospace grid: columns line up exactly in the native font. orientation=vertical turns it along the
        paper (table_turned); auto (the default) does so only at the top level, when the columns cannot keep
        TABLE_MIN characters each and the turned print is not much longer than the standing one. A header of
        empty cells is no header (Pandoc's headerless pipe table): no header line, no rule under it. style= draws it
        (table_pieces); font=/size= draw it as an image in that font, its columns as wide as the font's "0"."""
        self.table_attrs(t)
        style = self.table_style(t)
        face = self.table_font(t)
        ncol = len(t.header)
        given = self.table_columns(t, ncol)
        whole = Attrs({c for c in TABLE_TEXT if t.attrs.has(c)})  # .bold under the table: every row, titles too
        head = [
            _styled(self.table_cell(c, t.line, bold=style != "receipt"), _at(t.heads, i, Attrs()), t.head_row, whole)
            for i, c in enumerate(t.header)
        ]
        rows_at = [*t.row_lines, *[t.line] * (len(t.rows) - len(t.row_lines))]
        body = [
            [_styled(self.affixed(self.table_cell(c, at), *given[i][1:]), _cell(t, k, i), _row(t, k), whole)
             for i, c in enumerate([*r[:ncol], *[[]] * (ncol - len(r))])]
            for k, (r, at) in enumerate(zip(t.rows, rows_at, strict=True))
        ]  # fmt: skip
        spans = [self.table_spans(t, k, body[k], rows_at[k]) for k in range(len(body))]
        if not any(head):
            head = None
            if not body:
                return []
        every = [c for r in ([head] if head else []) + body for c in r]
        stretched = None if face else self.stretch(t.attrs.kv.get("size"))
        if face:
            ink = _FontInk(self, *face, self.said_at(t, "font=" if "font" in t.attrs.kv else "size="), every)
        else:
            ink = _NativeInk(self, stretched or (1, 1))
            if stretched:
                self.jagged(stretched, self.said_at(t, "size="))
        if face and style == "header-invert" and head and ink.px < int(self.p.get("raster.invert_min_px", 20)):
            self.n.add("F204", f"inverted titles at {ink.px}px close up", self.said_at(t, "style="),
                       "use size=20px or more, or style=receipt", "R2-12")  # fmt: skip
        self.table_title_marks(t, head, style)
        titles = head and style != "header-invert" and _any_class([t.head_row, *t.heads], "invert")
        inverted = [t.line] if titles else []
        shown = [[_cell(t, k, i) for i in range(ncol) if spans[k][i]] for k in range(len(body))]  # covered: none
        inverted += [at for k, at in enumerate(rows_at) if _any_class([_row(t, k), *shown[k]], "invert")]
        if face and inverted and ink.px < int(self.p.get("raster.invert_min_px", 20)):
            self.n.add("F204", f"inverted cells at {ink.px}px close up", inverted[0],
                       "use size=20px or more, or leave out .invert", "R2-12")  # fmt: skip
        # a cell spanning columns counts in none of them: its text wraps in their widths and the spaces between them
        cols = [[*([head[i]] if head else []), *(r[i] for r, s in zip(body, spans, strict=True) if s[i] == 1)]
                for i in range(ncol)]  # fmt: skip
        natural = [max([0, *(ink.units(c) for c in col)]) for col in cols]
        longest = [_longest(col, ink.units) for col in cols]
        in_body = [_longest(col[1:] if head else col, ink.units) for col in cols]  # a header word gives way first
        # what a column needs for its body cells whole and its title wrapped, never cut: a title wraps first
        titled = [min(n, max([_longest(col[:1], ink.units), *(ink.units(c) for c in col[1:])])) if head else n
                  for n, col in zip(natural, cols, strict=True)]  # fmt: skip
        if ink.native:  # the printer font's columns, fewer when stretched wider (2x1)
            room = self.cols // ink.wh[0] - ink.lead(indent)
        else:
            room = (self.W - indent * self.p.cell[0]) * 64 // ink.scale
        cap = room - (ncol - 1) - (1 if style == "grid" else 0)  # grid: half a column each side for the border
        fixed = self.column_shares([self.column_units(w, ink, t.line) for w, _, _ in given], cap)
        say = face is not None or stretched is not None or any(c.kv for c in t.columns)  # L108: settings, a size
        wide = [max([0, *(ink.units([c]) for cell in col for c in cell if c.wide)]) for col in cols]
        hard = [max(w, 1 if n or f else 0) for w, n, f in zip(wide, natural, fixed, strict=True)]
        lay = _Lay(fixed, [max(h, min(2, n)) for h, n in zip(hard, natural, strict=True)], hard, room, say)
        lay.head_slots = self.table_slots(t, t.heads, [1] * ncol, t.head_row, ncol)
        lay.slots = [self.table_slots(t, _at(t.cells, k, []), spans[k], _row(t, k), ncol) for k in range(len(body))]
        orientation = t.attrs.kv.get("orientation", "auto")
        if orientation not in ("auto", "horizontal", "vertical"):
            self.n.add(
                "M101",
                not_a_value("orientation", orientation, "auto, the default"),
                self.said_at(t, "orientation="),
                "auto, horizontal or vertical",
            )
            orientation = "auto"
        if indent and orientation == "vertical":  # a quote's bar or a list's indent cannot follow a turned table
            self.n.add("M101", "orientation=vertical: only a table outside quotes and lists turns",
                       self.said_at(t, "orientation="), "move the table out of the quote or list")  # fmt: skip
        if orientation == "vertical" and not indent:
            return self.table_turned(t, head, body, natural, style, ink, lay)
        # each way of printing it says its own problems; only the one that prints is heard
        floors = (longest, in_body, titled)
        standing, said = self.trial(
            lambda: self.table_standing(t, head, body, natural, floors, indent, cap, style, ink, lay)
        )
        # a table with column widths turns only when it cannot stand even with them shrunk to 1 column and the auto
        # ones at 2 (then it must: never past the paper's edge); otherwise L107 scales the widths down
        free = all(w is None for w in fixed)
        must = _fit_fixed(lay, cap)[2] in ("squeezed", "cut")  # standing, it would not fit at all
        cramped = free and sum(min(w, TABLE_MIN) for w in natural) > cap
        if orientation == "auto" and not indent and (must or cramped):
            turned, said_turned = self.trial(lambda: self.table_turned(t, head, body, natural, style, ink, lay))
            along = self.rows_height(turned)
            # never metres of paper where a few wrapped lines do: up to twice the standing length, or TURN_FREE_MM;
            # but columns of fewer than TABLE_MIN / 2 characters on average cannot be read standing: always turned
            if (
                must
                or cap < ncol * TABLE_MIN / 2
                or along <= max(2 * self.rows_height(standing), self.p.mm_to_dots(TURN_FREE_MM))
            ):
                self.hear(said_turned)
                self.n.add(
                    "L106",
                    f"a table of {ncol} columns does not fit across the paper: it prints VERTICALLY, about "
                    f"{along / (self.p.dpi / 25.4):.0f} mm along the paper",
                    t.line,
                    "read it with the header on the right; orientation=vertical silences this, "
                    "orientation=horizontal keeps it standing (narrow wrapped columns)",
                )
                return turned
        self.hear(said)
        if "width" in t.attrs.kv:
            self.n.add("M101", f"width={t.attrs.kv['width']}: a standing table always fills its width",
                       self.said_at(t, "width="),
                       "width= places a turned table (orientation=vertical); .compact keeps one narrow")  # fmt: skip
        return standing

    def trial(self, build) -> tuple:
        """What build() returns and the problems it found, kept apart from the job's (hear() adds them)."""
        outer, self.n = self.n, Nudges()
        try:
            return build(), self.n
        finally:
            self.n = outer

    def hear(self, said: Nudges) -> None:
        for x in [*said, *said.check_only]:
            self.n.add(x.code, x.message, x.line, x.suggestion, x.evidence)

    @staticmethod
    def said_at(t: Table, name: str) -> int:
        """The line a table's attribute (".compact", "width=") was written on: its problems are said there."""
        return t.attr_lines.get(name, t.line)

    def table_attrs(self, t: Table) -> None:
        """M101 for the attributes a table does not take (the parser already named the unknown ones, block() the
        image ones), one per line they were written on."""
        from .parser import KNOWN_CLASSES, KNOWN_KEYS

        a = t.attrs
        idle = [f".{c}" for c in sorted((a.classes & KNOWN_CLASSES) - TABLE_CLASSES - set(IMAGE_ONLY))]
        idle += [f"{k}=" for k in sorted(a.kv) if k in KNOWN_KEYS and k not in TABLE_KEYS and k not in IMAGE_ONLY]
        by_line: dict[int, list[str]] = {}
        for name in idle:
            by_line.setdefault(self.said_at(t, name), []).append(name)
        for line, names in sorted(by_line.items()):
            hint = TABLE_HINT
            kind = str(a.kv.get("type", "")).lower().rstrip("s")
            if "type=" in names and kind in ("line", "bar", "area", "sparkline"):  # a chart meant: chart= names it
                hint = f"chart={kind} draws the table as a chart (bobina help chart)"
            self.n.add("M101", f"{', '.join(names)} {'does' if len(names) == 1 else 'do'} nothing on a table", line,
                       hint)  # fmt: skip

    def table_style(self, t: Table) -> str:
        """style= on the table's {…} line; anything else is said (M101) and the table prints plain."""
        given = t.attrs.kv.get("style")
        if given is None or given in TABLE_STYLES:
            return given or "plain"
        at = self.said_at(t, "style=")
        if given.lower() in TABLE_STYLES:
            self.n.add("M101", f"style={given}: values are lowercase", at, f"write style={given.lower()} (printed "
                       "plain)")  # fmt: skip
        else:
            self.n.add("M101", f"style={given}: unknown style; {', '.join(TABLE_STYLES)}", at, "printed plain")
        return "plain"

    def table_font(self, t: Table) -> tuple[str, int] | None:
        """(family, px) when the table's {…} line gives font= or size=: it is drawn in that font at that size, as
        a raster paragraph is (rasterfont.px_for). size= alone keeps the body font; with the printer font it is
        Terminus (made for small sizes), or the printer font's own look (Spleen, cut for its height) at a whole
        multiple of that height. None: the printer font, natively."""
        kv = t.attrs.kv
        if "font" not in kv and "size" not in kv:
            return None
        fam = self.family(kv.get("font") or self.fonts.get("body", "native"))
        size = str(kv.get("size") or "")
        if fam.lower() == "native" and (not size or self.stretch(size)):
            return None  # 1x2, 2x1: the printer font's own cells, stretched (_NativeInk)
        doc_px = rasterfont.px_for(self.size, self.p, 20)  # an unreadable size= falls back to the document's
        px = rasterfont.px_for(size or self.size, self.p, doc_px, self.n, self.said_at(t, "size=" if size else "font="))
        if fam.lower() == "native":
            fam = "Spleen" if px % self.p.cell[1] == 0 else "Terminus"
        return fam, px

    def table_columns(self, t: Table, ncol: int) -> list[tuple[str | None, str, str]]:
        """Each column's settings from the end of its title cell: (width, prefix, suffix), width None for auto. A
        width in capitals is said (M101) and the column is auto."""
        out = []
        for i in range(ncol):
            kv = t.columns[i].kv if i < len(t.columns) else {}
            width = kv.get("width")
            if width == "auto":
                width = None
            elif width is not None and width != width.lower():
                self.n.add("M101", f"width={width}: values are lowercase", t.line,
                           f"write width={width.lower()} (the column shares what is left until then)")  # fmt: skip
                width = None
            out.append((width, kv.get("prefix", ""), kv.get("suffix", "")))
        return out

    def column_units(self, width: str | None, ink, line: int) -> int | float | None:
        """A column's width= in the ink's columns (the printer font's, or the "0" of a table's font): 7ch as it is;
        anything else as object_width reads it (one set of units and hints), 20mm and dots as many whole columns as
        fit in them; 30% (and half, third): the share of the table's text room, a float (column_shares). None:
        auto, or unreadable (M101)."""
        if width is None:
            return None
        m = COLUMN_CH_RE.fullmatch(width.replace(",", "."))
        if m:
            n = math.floor(float(m.group(1)))
            if n < 1:
                self.n.add("M101", not_a_value("width", width, "auto, the default"), line, COLUMN_WIDTH_HINT)
                return None
            return n
        dots = self.object_width(width, line, COLUMN_WIDTH_HINT, "auto, the default")
        if dots is None:
            return None
        if width in FRACTIONS:
            return FRACTIONS[width]
        if width.endswith("%"):  # object_width read it already
            return float(width[:-1].replace(",", ".")) / 100
        return max(1, ink.from_dots(dots))

    @staticmethod
    def column_shares(given: list, cap: int) -> list[int | None]:
        """The columns given a share of the text room (a float from column_units) in whole columns, at least 1:
        the floors of their shares, the largest remainders taking the rest, so shares adding up to 100% fill the
        text room exactly."""
        shares = [i for i, g in enumerate(given) if isinstance(g, float)]
        out = list(given)
        exact = {i: cap * given[i] for i in shares}
        for i in shares:
            out[i] = max(1, math.floor(exact[i]))
        left = math.floor(round(sum(exact.values()), 6)) - sum(out[i] for i in shares)
        for i in sorted(shares, key=lambda i: exact[i] - math.floor(exact[i]), reverse=True)[: max(0, left)]:
            out[i] += 1
        return out

    def affixed(self, cells: list[Cell], prefix: str, suffix: str) -> list[Cell]:
        """A body cell with its column's prefix= and suffix= (the author's text, in the style of the value's first
        and last letter); an empty cell gets neither. The value itself is never read again: data stays literal."""
        if not cells or not (prefix or suffix):
            return cells

        def made(text: str, like: Cell) -> list[Cell]:
            return [replace(like, ch=ch, wide=is_wide(ch)) for ch in self.text(text) if ch != "\n"]

        return [*made(prefix, cells[0]), *cells, *made(suffix, cells[-1])]

    def table_note(self, t: Table, head, widths: list[int], ink, lay: _Lay, style: str, turned: bool) -> None:
        """L108 (said only by bobina check): the width each column got and the spaces between them, in the ink's
        columns, for a table with column settings or a font."""
        if not lay.say:
            return
        names = []
        for i, w in enumerate(widths):
            title = "".join(icons.shown(c.ch) for c in head[i]).strip() if head and i < len(head) else ""
            names.append(f"{title or f'column {i + 1}'} {w}")
        gaps = len(widths) - 1
        border = 1 if style == "grid" else 0
        used = sum(widths) + gaps + border
        extra = f"+{gaps} gap{'s' if gaps != 1 else ''}" + (" +1 border" if border else "")
        if ink.native:
            unit = "" if ink.wh == (1, 1) else f" in printer-font {ink.wh[0]}x{ink.wh[1]} columns"
        else:
            unit = f" in {ink.fam} {ink.px}px columns"
        total = f"{used} along the paper" if turned else f"{used} of {lay.room}"
        what = "turned table, column widths" if turned else "column widths"
        self.n.add("L108", f"{what}{unit}: {' · '.join(names)} ({extra} = {total})", t.line,
                   'width= at the end of a title cell sets a column: | Price {width=9ch} |')  # fmt: skip

    def table_cell(self, runs, line: int, bold: bool = False) -> list[Cell]:
        """A cell's text as styled cells (**bold**, *italic*, ~~strike~~ as in a paragraph), on one line, without
        the spaces around it (any kind: a header of no-break spaces is empty). A span's size= or font= does nothing
        in a cell: M101."""
        idle = [k for k, on in (("size=", any(r.size for r in runs)), ("font=", any(r.font for r in runs))) if on]
        if idle:
            self.n.add("M101", f"{' and '.join(idle)} on a span in a table cell {'does' if len(idle) == 1 else 'do'} "
                       "nothing", line, CELL_HINT)  # fmt: skip
        cells = [c or Cell(" ") for c in self.cells_from_runs(runs, {"bold": bold})]
        while cells and cells[0].ch.isspace():
            cells.pop(0)
        while cells and cells[-1].ch.isspace():
            cells.pop()
        return cells

    def table_title_marks(self, t: Table, head, style: str) -> None:
        """What the title row's {…} or its cells' .invert and .shade cannot do, said (M101): a table whose titles
        are empty prints no title row to style; style=header-invert titles are white on black already."""
        names = sorted({f".{c}" for a in [t.head_row, *t.heads] for c in a.classes})
        if not head and names:
            self.n.add("M101", f"{' '.join(names)} on the title row: its titles are empty, no title row prints",
                       t.line, "style the rows instead: | TOTAL | 9,00 | {.bold}")  # fmt: skip
            return
        dark = [n for n in names if n in (".invert", ".shade")]
        if head and style == "header-invert" and dark:
            self.n.add("M101", f"{' '.join(dark)} on the titles does nothing with style=header-invert: they are "
                       "white on black already", t.line, "leave it out, or use another style=")  # fmt: skip

    def table_spans(self, t: Table, k: int, row: list[list[Cell]], at: int) -> list[int]:
        """How many columns each cell of body row k takes (span= at the end of a cell; 0: covered by the one
        before). It starts where it is written and goes to the end (all) or over N columns; past the end of the
        row it stops there, and before a covered cell with text (nothing disappears): both said (M101)."""
        ncol = len(row)
        styles = _at(t.cells, k, [])
        out = [1] * ncol
        i = 0
        while i < ncol:
            given = _at(styles, i, Attrs()).kv.get("span")
            n = 1 if given is None else self.span_value(given, ncol - i, at)
            left = ncol - i
            if n > left:
                self.n.add("M101", f"span={given}: {left} column{'s' if left != 1 else ''} from here to the end of the "
                           "row", at, "it spans to the end of the row (span=all says so)")  # fmt: skip
                n = left
            for j in range(i + 1, i + n):
                if row[j]:
                    shown = "".join(icons.shown(c.ch) for c in row[j])[:20]
                    self.n.add(
                        "M101", f"span={given} stops before '{shown}': that cell has text", at,
                        "leave the cells it covers empty, or out: a row may have fewer cells than the title",
                    )  # fmt: skip
                    n = j - i
                    break
            for j in range(i + 1, i + n):  # an empty covered cell's own {…} has no cell left to style: said
                own = _at(styles, j, Attrs())
                names = [f".{c}" for c in sorted(own.classes)] + [f"{k}=" for k in sorted(own.kv)]
                if names:
                    self.n.add("M101", f"{' '.join(names)} on a cell covered by span={given} does nothing", at,
                               f"put it at the end of the spanning cell, in its {{span={given} …}}")  # fmt: skip
            out[i : i + n] = [n] + [0] * (n - 1)
            i += n
        return out

    def span_value(self, given: str, left: int, at: int) -> int:
        """span=all (the columns left) or a whole number from 1; anything else is said (M101) and the cell keeps
        its own column."""
        if given == "all":
            return left
        if re.fullmatch(r"\d+", given) and int(given) >= 1:
            return int(given)
        if given.lower() == "all":
            self.n.add("M101", f"span={given}: values are lowercase: span=all", at, "the cell prints in its own column")
        else:
            self.n.add("M101", f"span={given}: a whole number from 1, or all", at, "the cell prints in its own column")
        return 1

    @staticmethod
    def table_slots(t: Table, styles: list[Attrs], spans: list[int], row: Attrs, ncol: int) -> list[_Slot]:
        """A row's cells on the columns: where each starts and ends (a span covers several), its alignment (its
        own .left/.center/.right, else its row's, else its column's) and whether it is inverted or shaded."""
        out, i = [], 0
        while i < ncol:
            own = _at(styles, i, Attrs())
            n = max(1, spans[i])
            align = next((a for a in ("left", "center", "right") if own.has(a)), None)
            align = align or next((a for a in ("left", "center", "right") if row.has(a)), None)
            out.append(_Slot(i, i + n - 1, align or _at(t.aligns, i, "left"), own.has("invert"), own.has("shade")))
            i += n
        return out

    def rows_height(self, rows: list) -> int:
        from . import preview

        return preview.heights(rows, self.p, self.em)

    def table_standing(self, t, head, body, natural, longest, indent: int, cap: int, style: str, ink, lay) -> list:
        """Columns as wide as their text; when the paper is narrower, a title wider than its column's body wraps
        first (the widest first, down to its body cells whole: `longest[2]`), then the widest gives way, down to its
        longest word (`longest`: with the header's, else the body's only, else the body's with its longest words
        cut), so a header word gives way before any data word: a cut word is said (L101). A column given a width
        keeps it and the others share the rest; widths wider than the paper shrink in proportion, the others keeping
        2 (L107)."""
        auto = [i for i, f in enumerate(lay.fixed) if f is None]
        widths, most, why = _fit_fixed(lay, cap)
        if why:
            self.table_squeezed(t, why, lay, style, ink)
        auto_natural = [natural[i] for i in auto]
        sub = self.share(auto_natural, [[ws[i] for i in auto] for ws in longest], max(0, cap - sum(widths)), most,
                         [lay.hard[i] for i in auto])  # fmt: skip
        for i, w in zip(auto, sub, strict=True):
            widths[i] = w
        keep = [max(h, min(n, w)) for h, n, w in zip(lay.hard, natural, longest[0], strict=True)]
        self.widen_for_spans(widths, body, lay, ink, max(0, cap - sum(widths)), keep)
        if auto and not t.attrs.has("compact") and sum(widths) < cap:  # stretch to the paper's edge: the spare
            # room goes to the widest auto column of text (ties: the first; none: the widest auto column): an
            # item's description, a total's label. Text: left-aligned, with a letter in a body cell (a column of
            # codes or numbers is not text, even left-aligned)
            text = [i for i in auto if _at(t.aligns, i, "left") == "left"
                    and any(c.ch.isalpha() for r in body if i < len(r) for c in r[i])] or auto  # fmt: skip
            widths[max(text, key=lambda i: natural[i])] += cap - sum(widths)
        free = max(0, cap - sum(widths))  # a .compact table is narrower than the paper: .center and .right place
        place = next((a for a in ("right", "center") if t.attrs.has(a)), t.attrs.kv.get("align"))  # a cut one: none
        shift = {"center": free // 2, "right": free}.get(place, 0) if t.attrs.has("compact") or not auto else 0
        self.table_note(t, head, widths, ink, lay, style, turned=False)
        geo = _Geo.of(t, style, ink, widths, self.W, ink.lead_dots(indent) + ink.dots(shift))
        hush = replace(lay, quiet=why in ("squeezed", "cut"))
        heads, rows = self.table_rows(t, head, body, widths, ink, hush)
        every = [*heads, *(ln for g in rows for ln in g)]
        # the terminal views: a table in a raster font is a map of the paper when every line of it fits there
        # with every letter (the same or a larger font), else on its own grid (a smaller font: a wider frame)
        maps = {} if ink.native or any(indent + ln.need > self.cols for ln in every) else {
            id(ln): self.paper_map(ln, geo, indent) for ln in every}  # fmt: skip
        maps = maps if maps and None not in maps.values() else None
        top, groups, between, bottom = self.table_pieces(heads, rows, geo)
        pieces = [*top, *(p for k, g in enumerate(groups) for p in [*(between if k else []), *g]), *bottom]
        return [self.table_row(p, geo, indent, shift, maps) for p in pieces]

    @staticmethod
    def widen_for_spans(widths: list[int], body, lay: _Lay, ink, free: int | None, keep=None) -> None:
        """After the columns are sized: a spanning cell that does not fit the columns it covers widens the last of
        them not given a width (all given one: it wraps in them, as asked). Standing, it needs its longest word: the
        free room first, then what the other auto columns have beyond `keep` (their longest word, or what an earlier
        span widened them to), never past the paper. When even that cannot keep the word whole, nothing changes and
        the word is cut (L101). Turned (free None) it needs its whole text: the length is free. A span that fits
        changes nothing."""
        keep = list(keep) if keep else [0] * len(widths)
        for row, slots in zip(body, lay.slots, strict=True):
            for s in slots:
                autos = [i for i in s.cols if lay.fixed[i] is None]
                if s.alone or not autos or not row[s.first]:
                    continue
                cells = row[s.first]
                need = (ink.units(cells) if free is None else _longest([cells], ink.units)) - _span(widths, s)
                if need <= 0:
                    continue
                if free is not None:
                    others = [i for i in range(len(widths)) if i not in s.cols and lay.fixed[i] is None]
                    take = min(need, free)
                    if take + sum(max(0, widths[i] - keep[i]) for i in others) < need:
                        continue  # it cannot be whole: the widths stay
                    free -= take
                    left = need - take
                    for j in sorted(others, key=lambda i: widths[i] - keep[i], reverse=True):  # most room first
                        give = min(left, max(0, widths[j] - keep[j]))
                        widths[j] -= give
                        left -= give
                widths[autos[-1]] += need
                for i in s.cols:  # a later span never takes back what this one needs
                    keep[i] = max(keep[i], widths[i])

    def table_squeezed(self, t: Table, why: str, lay: _Lay, style: str, ink) -> None:
        """L107: the columns did not fit across the paper as given. scaled: the widths given shrank in proportion
        (the auto columns keeping 2); squeezed: even so it did not fit (too many columns), every column narrowed;
        cut: not even 1 column each fits, the table is cut at the paper's edge."""
        ncol = len(lay.fixed)
        gaps = ncol - 1 + (1 if style == "grid" else 0)
        font = ", or a smaller font: {font=Terminus size=16px}" if ink.native else ", or a smaller size="
        if why == "scaled":
            asked = sum(f or lo for f, lo in zip(lay.fixed, lay.lo, strict=True)) + gaps
            auto = ", counting up to 2 for each auto column" if None in lay.fixed else ""
            hint = f"give the columns smaller width= (bobina check shows what each got){auto}{font}"
            self.n.add("L107", f"column widths add up to {asked} columns, the paper has {lay.room}: scaled down",
                       t.line, hint)  # fmt: skip
            return
        least = gaps + (
            sum(lay.hard)
            if why == "cut"
            else sum(h if f else lo for f, lo, h in zip(lay.fixed, lay.lo, lay.hard, strict=True))
        )
        said = "narrowed to fit" if why == "squeezed" else "cut at the paper's edge, even at its narrowest"
        self.n.add("L107", f"a table of {ncol} columns needs at least {least} columns standing, the paper has "
                   f"{lay.room}: {said}", t.line,
                   f"turn it (orientation=vertical), or leave out a column{font}")  # fmt: skip

    @staticmethod
    def share(natural: list[int], longest, cap: int, most: list[int] | None = None, hard=None) -> list[int]:
        """The widths of the auto columns in `cap`: as wide as their text; a title wider than its body wraps first
        (down to the body: longest[2]), then the widest gives way (see table_standing), down to 2, then to their
        hard minimum (1; 2 with a wide character) when the paper has no more room. most: what each may take at most
        (a squeezed table)."""
        widths = [min(n, m) for n, m in zip(natural, most, strict=True)] if most else list(natural)
        whole, data, titled = ([min(n, w) for n, w in zip(natural, ws, strict=True)] for ws in longest)
        kept = next((f for f in (whole, data) if sum(f) <= cap), None)
        if kept is None:  # not even the data's words fit: only the longest of them give way, the rest stay whole
            kept = list(data)
            while kept and sum(kept) > cap and max(kept) > 2:
                kept[kept.index(max(kept))] -= 1
        for floor in (titled, kept, [2] * len(widths), hard or [1] * len(widths)):
            while sum(widths) > cap:  # 2: a wide character always fits its column; then: nothing else fits
                wider = [i for i, w in enumerate(widths) if w > floor[i]]
                if not wider:
                    break
                widths[max(wider, key=lambda i: widths[i])] -= 1
        return widths

    def table_wrap(self, t: Table, cells_row: list[list[Cell]], widths: list[int], ink, lay=None, slots=None,
                   row: Attrs | None = None) -> list[_TLine]:  # fmt: skip
        """One table row as printed lines: each cell wrapped at its spaces to its width (in the ink's measure; a
        span's: the widths it covers and the spaces between them) and aligned (:-- --: :-:, or its class). A word
        longer than its column is cut and said (L101), but not in columns given a width: that is what was asked."""

        def split_in(cell: list[Cell]):
            around = "".join(c.ch for c in cell)

            def split(word, at):
                self.said_cut("".join(c.ch for c in word), f"{at // ink.scale} columns in a table", t.line,
                              "shorten it, leave out a column, or turn the table: orientation=vertical",
                              around)  # fmt: skip

            return split

        def quiet(word, at):
            pass

        slots = slots or [_Slot(i, i, _at(t.aligns, i, "left")) for i in range(len(widths))]
        wrapped = [
            wrap_words(
                word_tokens(_at(cells_row, s.first, []), pieces=True),
                _span(widths, s) * ink.scale,
                0,
                quiet
                if lay and (lay.quiet or all(lay.fixed[i] is not None for i in s.cols))
                else split_in(_at(cells_row, s.first, [])),
                ink.measure,
            )  # fmt: skip
            for s in slots
        ]
        return [_TLine([], [w[k] if k < len(w) else [] for w in wrapped], slots, row or Attrs())
                for k in range(max(len(p) for p in wrapped))]  # fmt: skip

    def table_rows(self, t: Table, head, body, widths: list[int], ink, lay=None):
        """The title's lines and each body row's lines (table_wrap), each also on a grid of character columns: the
        printer font's columns (what prints natively), or, for a table in a raster font, columns as wide as they
        print or as the widest text in them, whichever is more (a proportional font's letters; a span's text
        widening the last column it covers), so the terminal views show every cell whole, lined up. A standing
        table whose grid fits the paper's columns is shown as a map of the paper instead (paper_map)."""
        heads = self.table_wrap(t, head, widths, ink, lay, lay and lay.head_slots, t.head_row) if head else []
        groups = [self.table_wrap(t, r, widths, ink, lay, lay and _at(lay.slots, k), _row(t, k))
                  for k, r in enumerate(body)]  # fmt: skip
        every = [*heads, *(ln for g in groups for ln in g)]
        grid = list(widths)
        if not ink.native:
            alone = [(s.first, seg) for ln in every for s, seg in zip(ln.slots, ln.segs, strict=True) if s.alone]
            grid = [max([w, *(columns(seg) for i, seg in alone if i == c)]) for c, w in enumerate(widths)]
            for ln in every:
                for s, seg in zip(ln.slots, ln.segs, strict=True):
                    grid[s.last] += max(0, columns(seg) - _span(grid, s))
        for ln in every:
            ln.cells, ln.view = _padded(ln.slots, ln.segs, grid, ln.row.has("invert"))
            ln.need = sum(grid) + len(grid) - 1
        return heads, groups

    def table_pieces(self, head: list[_TLine], body: list[list[_TLine]], geo: _Geo) -> tuple[list, list, list, list]:
        """What a style= draws: (the pieces before the body, the pieces of each body row, the pieces between two
        rows of the same block, the pieces after the body). A piece is ("line", line): a line of text, native when
        the ink is the printer font; ("rule", style, pad): a divider across the canvas; ("image", image, lines,
        kind): a drawn piece, the lines it shows, and its kind: "drawn", "band" (white on black across the row),
        "zebra" (grey dots, not tested on paper), or both. A row with an inverted or shaded cell, or a {.invert} or
        {.shade} after it, is drawn. A table without titles gets no title band or rule."""
        style = geo.style

        def lines(ls):
            return [("line", ln) for ln in ls]

        def row(ls, zebra: bool = False):
            if zebra or _marked(ls):
                return [("image", self.table_marked(ls, geo, zebra), ls, _kind(ls, zebra))]
            return lines(ls)

        if style == "grid":
            top = [("image", self.grid_piece([], geo), [], "drawn")]
            top += [("image", self.grid_piece(head, geo), head, _kind(head))] if head else []
            return top, [[("image", self.grid_piece(g, geo), g, _kind(g))] for g in body], [], []
        top: list = []
        if head and style == "receipt":
            top = [("rule", "dashed", 3), *row(head), ("rule", "dashed", 3)]
        elif head and style == "header-invert":
            top = [("image", self.table_band(head, geo), head, "band")]
        elif head:
            top = [*row(head), ("rule", "solid", 3)]
        groups = [row(g, style == "zebra" and k % 2 == 1) for k, g in enumerate(body)]
        return top, groups, [("rule", "dotted", 2)] if style == "lines" else [], []

    def table_canvas(self, lines: list[_TLine], geo: _Geo, top: int = 0, extra: int = 0) -> Image.Image:
        """The lines drawn one under the other on a white canvas as wide as the paper (or the turned table), `top`
        dots down and `extra` dots taller (mode L)."""
        im = Image.new("L", (geo.width, top + sum(geo.ink.line_h for _ in lines) + extra), 255)
        y = top
        for ln in lines:
            im.paste(geo.strip(ln), (geo.x0 + geo.pad, y))
            y += geo.ink.line_h
        return im

    def table_band(self, head: list[_TLine], geo: _Geo) -> Image.Image:
        """style=header-invert: the titles white on one continuous black band, as wide as the table."""
        m = int(self.p.get("raster.invert_margin_dots", 4))
        im = self.table_canvas(head, geo, m, m)
        box = (max(0, geo.x0 - m), 0, min(geo.width, geo.x0 + geo.inner + m), im.height)
        im.paste(ImageOps.invert(im.crop(box)), box[:2])
        return _bw(im)

    def table_marked(self, lines: list[_TLine], geo: _Geo, zebra: bool = False) -> Image.Image:
        """A row drawn with its marks: an inverted row or cell white on one continuous black box (a little paper
        above and below the row, as a title band has), then the grey dots of zebra and .shade behind the text."""
        boxes = self.mark_boxes(lines, geo)
        m = int(self.p.get("raster.invert_margin_dots", 4)) if any(inverted for inverted, _ in boxes) else 0
        im = self.table_canvas(lines, geo, m, m)
        _invert_boxes(im, boxes, im.height)
        im = _bw(im)
        if zebra:  # the style's row: as wide as the table's text
            im = imaging.shade(im, (geo.x0, 0, geo.x0 + geo.inner, im.height))
        return _shade_boxes(im, boxes, im.height)

    def mark_boxes(self, lines: list[_TLine], geo: _Geo) -> list[tuple[bool, tuple[int, int]]]:
        """(inverted, (left, right)) for each box a row marks: the whole row for a {.invert} or {.shade} after it,
        else each such cell, from the middle of the space before it to the middle of the space after it (at the
        table's sides, a little past them; in a grid, to its border). An inverted row inverts every cell once."""
        if not lines:
            return []
        ink = geo.ink
        x, edge = geo.x0 + geo.pad, geo.pad if geo.style == "grid" else int(self.p.get("raster.invert_margin_dots", 4))
        last = len(geo.widths) - 1

        def side(at: int, inside: bool, outer: int) -> int:  # at: a column boundary in units, past the gap or not
            if not inside:
                return outer
            return x + ink.dots(at - 1) + (ink.dots(at) - ink.dots(at - 1)) // 2

        def box(s: _Slot) -> tuple[int, int]:
            start = sum(geo.widths[: s.first]) + s.first
            end = sum(geo.widths[: s.last + 1]) + s.last + 1
            lo = side(start, s.first > 0, x - edge)
            hi = side(end, s.last < last, x + geo.inner + edge)
            return max(0, lo), min(geo.width, hi)

        whole = (max(0, x - edge), min(geo.width, x + geo.inner + edge))
        mk = _marks_of(lines[0])
        return [*([(True, whole)] if mk.row_invert else []), *([(False, whole)] if mk.row_shade else []),
                *((True, box(s)) for s in mk.inverted), *((False, box(s)) for s in mk.shaded)]  # fmt: skip

    def grid_piece(self, lines: list[_TLine], geo: _Geo) -> Image.Image:
        """style=grid: one row of the table in its cells, the rule under it, the borders and the lines between the
        cells (none inside a span), each in the middle of the column of space between two columns; inverted and
        shaded cells inside the lines; no lines: the top border."""
        s = max(2, int(self.p.get("raster.min_stroke_dots", 2)))  # B101: thinner prints broken
        lift = max(2, (geo.ink.line_h - geo.ink.text_h) // 2) if lines else 0  # air above the text
        im = self.table_canvas(lines, geo, lift, s)
        boxes = self.mark_boxes(lines, geo)
        _invert_boxes(im, boxes, im.height - s)
        d = ImageDraw.Draw(im)
        left, right = geo.x0, geo.x0 + geo.inner + 2 * geo.pad - 1
        d.rectangle((left, im.height - s, right, im.height - 1), fill=0)
        xs = [left, right - s + 1]
        ends = {sl.last for sl in lines[0].slots} if lines else set(range(len(geo.widths)))
        at = 0
        for i, w in enumerate(geo.widths[:-1]):
            at += w
            gap = geo.x0 + geo.pad + geo.ink.dots(at)  # the column of space after this column
            if i in ends:
                xs.append(gap + (geo.ink.dots(at + 1) - geo.ink.dots(at) - s) // 2)
            at += 1
        for x in xs:
            d.rectangle((x, 0, x + s - 1, im.height - 1), fill=0)
        return _shade_boxes(_bw(im), boxes, im.height - s)

    def table_row(self, piece, geo: _Geo, indent: int, shift: int, maps: dict | None = None):
        """A piece of a standing table as the row that prints it: a native line, a divider across the paper, or a
        drawn piece (with the quote bars it is inside of, and its lines as text for the terminal views: `maps`,
        each line as a map of the paper, or None: the table's own grid)."""
        kind, t = piece[0], geo.t
        if kind == "rule":
            return BitmapRow(imaging.divider(self.W, piece[1], 2, pad=piece[2]), t.line, "divider")
        ink = geo.ink
        if kind == "line" and ink.native:
            lead = self.table_lead(ink, indent)
            cells = _cut(lead + [Cell(" ")] * shift + piece[1].cells, self.cols // ink.wh[0])
            reason = self.native_ok(cells)
            row = TextRow(cells, ink.wh, "left", t.line, native=not reason, reason=reason)
            if ink.wh[0] == 1 or not self.bars_in(indent):
                return row
            # a stretched line cannot hold a 1x │: the quote bars are drawn into it, as text_block does
            return BitmapRow(self.draw_bars(self.em.render_row(row, self.W), indent, 0), t.line, "text",
                             [self.native_view(ink, indent, shift, piece[1].view, t.line)])  # fmt: skip
        lines = [piece[1]] if kind == "line" else piece[2]
        im = _bw(self.table_canvas(lines, geo)) if kind == "line" else piece[1]
        wide = not ink.native and maps is None
        if ink.native:
            view = [self.native_view(ink, indent, shift, ln.view, t.line) for ln in lines]
        elif wide:  # a smaller font (more character columns than the paper's) or letters the map has no room for:
            view = [TextRow([*self.lead(indent), *ln.view], (1, 1), "left", t.line) for ln in lines]  # its own grid
        else:  # the same or a larger font: a map of the paper, every letter in it
            view = [TextRow(maps[id(ln)], (1, 1), "left", t.line) for ln in lines]
        band = kind == "image" and "band" in piece[3].split()
        return BitmapRow(self.draw_bars(im, indent, 0), t.line, "band" if band else "text", view,
                         untested=_marks([piece]), wide_view=wide)  # fmt: skip

    def native_view(self, ink, indent: int, shift: int, cells: list[Cell], line: int) -> TextRow:
        """A line of a printer-font table as the terminal views show it: at its scale, or, stretched wider (2x1) in
        a quote, every line at 1x after the quote's bars (a 1x │ cannot sit in a 2x row), drawn or not."""
        pad = [Cell(" ")] * shift
        if ink.wh[0] > 1 and self.bars_in(indent):
            return TextRow(_cut([*self.lead(indent), *pad, *cells], self.cols), (1, 1), "left", line)
        return TextRow(_cut([*self.table_lead(ink, indent), *pad, *cells], self.cols // ink.wh[0]), ink.wh, "left",
                       line)  # fmt: skip

    def table_lead(self, ink, indent: int) -> list[Cell]:
        """What comes before a native table line: the quote bars at 1x; stretched wider (2x1), blank cells as wide
        as the indent (the bars are drawn: table_row)."""
        return self.lead(indent) if ink.wh[0] == 1 else [Cell(" ")] * ink.lead(indent)

    def paper_map(self, ln: _TLine, geo: _Geo, indent: int) -> list[Cell] | None:
        """A line of a standing table drawn in a raster font (the same or a larger font than the printer's), as the
        terminal views show it: a map of the paper in printer-font columns. Each cell's text starts at the printer
        column nearest to where its column prints; a right-aligned one ends where it ends on paper, a centred one
        is centred there. None when a cell's text has more letters than its room has printer columns (a
        proportional font): the view then uses the table's own grid, which loses no letter."""
        cw, ink = self.p.cell[0], geo.ink
        out, col = list(self.lead(indent)), indent
        band = ln.row.has("invert")
        for s, seg in zip(ln.slots, ln.segs, strict=True):
            left = geo.x0 + geo.pad + (sum(geo.widths[: s.first]) + s.first) * ink.scale / 64
            right = left + _span(geo.widths, s) * ink.scale / 64
            lo = max(col, round(left / cw))
            hi = round(right / cw)
            if columns(seg) > hi - lo or hi > self.cols:
                return None
            at = _offset(s.align, hi - lo - columns(seg))
            part = [Cell(" ")] * at + seg + [Cell(" ")] * (hi - lo - at - columns(seg))
            gap = [Cell(" ", invert=band and col > indent)] * (lo - col)  # a band runs on between its cells
            out += gap + ([replace(c, invert=True) for c in part] if s.invert or band else part)
            col = hi
        while out and out[-1] == Cell(" "):
            out.pop()
        return out

    def table_turned(self, t: Table, head, body, natural: list[int], style: str, ink, lay) -> list:
        """The table drawn as an image and turned 90 degrees clockwise, like a book's spine: the header on the
        right, the text read from top to bottom, the paper's length as the table's width. Cells never wrap (the
        length is free) but in a column given a width, which keeps it along the paper; when the rows do not fit
        across the paper they go on in more turned blocks, the header repeated (a table without a header has none),
        each in the table's style. The rows are kept as text for the terminal views."""
        align = self.object_align(t.attrs)
        widths = [f or max(1, w) for w, f in zip(natural, lay.fixed, strict=True)]
        self.widen_for_spans(widths, body, lay, ink, None)  # the length is free: a span keeps its text on one line
        self.table_note(t, head, widths, ink, lay, style, turned=True)
        geo = _Geo.of(t, style, ink, widths, None, 0)
        heads, rows = self.table_rows(t, head, body, widths, ink, lay)
        top, groups, between, bottom = self.table_pieces(heads, rows, geo)
        top_im, sep_im, end_im = ([self.piece_image(p, geo) for p in ps] for ps in (top, between, bottom))
        sep_h = sum(p.height for p in sep_im)
        drawn = [[self.piece_image(p, geo) for p in g] for g in groups]
        top_h = sum(p.height for p in top_im + end_im)
        row_h = sum(p.height for p in drawn[0]) if drawn else ink.line_h
        avail = min(self.object_width(t.attrs.kv.get("width"), self.said_at(t, "width=")) or self.W, self.W)
        if avail < top_h + row_h:  # not even the header and one row across: the paper's width instead
            self.n.add("M101", f"width={t.attrs.kv.get('width')}: too narrow for a turned table",
                       self.said_at(t, "width="), "the paper's width is used")  # fmt: skip
            avail = self.W
        chunks: list[list[int]] = [[]]
        used = top_h
        for k, g in enumerate(drawn):  # the rules between rows only between two rows of the same block
            h = sum(p.height for p in g)
            if chunks[-1] and used + sep_h + h > avail:
                chunks.append([])
                used = top_h
            used += h + (sep_h if chunks[-1] else 0)
            chunks[-1].append(k)
        out = []
        for n, chunk in enumerate(chunks):
            parts = top_im + [p for j, k in enumerate(chunk) for p in [*(sep_im if j else []), *drawn[k]]] + end_im
            im = imaging.vstack(parts, geo.width)
            turned = im.rotate(-90, expand=True)  # clockwise: the header (the top) goes to the right
            if turned.width > self.W:  # wider than the paper even so (a huge font): never past its edge
                self.n.add("L104", f"turned table is {turned.width} dots across: cropped to {self.W}", t.line,
                           "fewer rows per table, or orientation=horizontal")  # fmt: skip
                turned = turned.crop((turned.width - self.W, 0, turned.width, turned.height))
            if n:
                out.append(FeedRow(int(self.p.get("native.line_gap_dots", 6)) * 4))
            view = [
                TextRow(ln.view, (1, 1), "left", t.line)
                for ln in heads + [ln for k in chunk for ln in _body_lines(groups[k])]
            ]
            marks = _marks([p for k in chunk for p in groups[k]])
            out.append(BitmapRow(imaging.place(turned, self.W, align), t.line, "table", view, untested=marks))
        return out

    def piece_image(self, piece, geo: _Geo) -> Image.Image:
        """A piece of a turned table drawn on its canvas (mode '1')."""
        if piece[0] == "rule":
            return imaging.divider(geo.width, piece[1], 2, pad=piece[2])
        if piece[0] == "line":
            return _bw(self.table_canvas([piece[1]], geo))
        return piece[1]


def _cut(cells: list[Cell], cols: int) -> list[Cell]:
    """A table line cut at the paper's edge, `cols` columns (a cut table says L107): never past it."""
    while columns(cells) > cols:
        cells = cells[:-1]
    return cells


def _body_lines(pieces: list) -> list[_TLine]:
    """The lines of text in a body row's pieces (for the terminal views)."""
    return [ln for p in pieces for ln in ([p[1]] if p[0] == "line" else p[2])]


UNTESTED_PIECES = {"zebra": "zebra"}  # a word of a drawn piece's kind -> the feature not tested on paper (P301)


def _marks(pieces: list) -> tuple[str, ...]:
    """The features not tested on paper these pieces draw (BitmapRow.untested)."""
    return tuple(sorted({UNTESTED_PIECES[w] for p in pieces if p[0] == "image" for w in p[3].split()
                         if w in UNTESTED_PIECES}))  # fmt: skip


def _bw(im: Image.Image) -> Image.Image:
    return im.point(lambda v: 0 if v < 128 else 255).convert("1", dither=Image.NONE)


def _box_side(t: int, style: str, cw: int) -> int:
    """Dots a box's frame (t dots; double: two lines, one line apart) and the room beside it take on each side: whole
    letters, at least BOX_MIN_SIDE dots of room."""
    stroke = 3 * t if style == "double" else t
    return cw * -(-(stroke + BOX_MIN_SIDE) // cw)


def _box_least(cw: int) -> int:
    """Dots of the narrowest box: its thinnest frame and room on each side, and 4 letters inside."""
    return 2 * _box_side(2, "solid", cw) + 4 * cw


def _code_spans(rows: list, pics: list) -> tuple:
    """The codes these rows draw, stacked as compose() stacks them: (top, bottom, kind) in dots of the stack. A turned
    label never resamples them nor cuts through them (fit_label)."""
    out, y = [], 0
    for r, im in zip(rows, pics, strict=True):
        if im is None:
            continue
        if isinstance(r, BitmapRow) and r.code_spans:
            out += [(y + a, y + b, k) for a, b, k in r.code_spans]
        elif isinstance(r, (QRRow, BarcodeRow)) or (isinstance(r, BitmapRow) and r.kind in CODE_KINDS):
            out.append((y, y + im.height, "qr" if isinstance(r, QRRow) else r.kind if r.kind in CODE_KINDS
                        else "barcode"))  # fmt: skip
        y += im.height
    return tuple(out)


def _turned_spans(spans, height: int, ang: float) -> tuple:
    """The codes of a picture `height` dots tall after it was turned `ang` degrees: where they were (0), mirrored
    (180), or, turned any other way, over its whole height (a code then runs across where it was)."""
    ang %= 360
    if not spans or ang == 0:
        return tuple(spans)
    if ang == 180:
        return tuple((height - b, height - a, k) for a, b, k in spans)
    return ((0, height, spans[0][2]),)


def _tops(pics: list, y: int) -> list[int]:
    """Where rows stacked from `y` start, one under the other (a row that draws nothing takes no room)."""
    out = []
    for im in pics:
        out.append(y)
        y += im.height if im is not None else 0
    return out


def _white_row(im: Image.Image, y: int, sides: int = 0) -> bool:
    """Whether row y of an image (mode L) has no ink between `sides` dots from each edge (a box's side lines): a
    place to cut it between lines."""
    return im.crop((sides, y, max(sides + 1, im.width - sides), y + 1)).getextrema()[0] >= 128


def _stacked_rects(rows: list, pics: list, name: str) -> tuple:
    """The rectangles (BitmapRow.keep or .dark) of rows stacked as compose() stacks them, in dots of the stack."""
    out, y = [], 0
    for r, im in zip(rows, pics, strict=True):
        if im is None:
            continue
        out += [(x0, y0 + y, x1, y1 + y) for x0, y0, x1, y1 in getattr(r, name, ())]
        y += im.height
    return tuple(out)


def _moved(rects, dx: int, dy: int) -> tuple:
    return tuple((x0 + dx, y0 + dy, x1 + dx, y1 + dy) for x0, y0, x1, y1 in rects)


def _turned_rects(rects, size: tuple[int, int], ang: float) -> tuple | None:
    """Rectangles of a picture `size` big after it is turned `ang` degrees clockwise (expanded); None: not a right
    angle, they no longer are rectangles."""
    w, h = size
    ang %= 360
    if ang % 90:
        return None if rects else ()
    turn = {0: lambda x0, y0, x1, y1: (x0, y0, x1, y1), 90: lambda x0, y0, x1, y1: (h - y1, x0, h - y0, x1),
            180: lambda x0, y0, x1, y1: (w - x1, h - y1, w - x0, h - y0),
            270: lambda x0, y0, x1, y1: (y0, w - x1, y1, w - x0)}[int(ang)]  # fmt: skip
    return tuple(turn(*r) for r in rects)


def _blank_row(im: Image.Image, y: int, sides: int, darks=()) -> bool:
    """_white_row, where an inverted box (darks: its rectangles) counts as blank when it is all black on that row."""
    lo, hi = sides, max(sides + 1, im.width - sides)
    over = [(max(lo, x0), min(hi, x1)) for x0, y0, x1, y1 in darks if y0 <= y < y1 and x0 < hi and x1 > lo]
    if not over:
        return _white_row(im, y, sides)
    cuts = sorted({lo, hi, *(x for pair in over for x in pair)})
    for a, b in zip(cuts, cuts[1:], strict=False):
        if b > a:
            least, most = im.crop((a, y, b, y + 1)).getextrema()
            if (most > 127) if any(x0 <= a and b <= x1 for x0, x1 in over) else (least < 128):
                return False
    return True


def _blank_edges(im: Image.Image) -> tuple[int, int]:
    """The white rows above and below the ink of an image (all of them above when it has none)."""
    box = ImageOps.invert(im.convert("L")).getbbox()
    return (box[1], im.height - box[3]) if box else (im.height, 0)


def _at(items: list, i: int, default=None):
    """items[i], or default past its end (a short row, a table built without cell settings)."""
    return items[i] if i is not None and 0 <= i < len(items) else default


def _cell(t: Table, k: int, i: int) -> Attrs:
    """The classes and span= of cell i of body row k, from the {…} at its end."""
    return _at(_at(t.cells, k, []), i, Attrs())


def _row(t: Table, k: int) -> Attrs:
    """The classes of body row k, from the {…} after its closing pipe."""
    return _at(t.row_attrs, k, Attrs())


def _styled(cells: list[Cell], *attrs: Attrs) -> list[Cell]:
    """A cell's text with the styles its own {…} and its row's give it (they add up)."""
    on = {k: any(a.has(k) for a in attrs) for k in ("bold", "italic", "underline", "strike")}
    if not any(on.values()):
        return cells
    return [replace(c, **{k: getattr(c, k) or v for k, v in on.items()}) for c in cells]


def _span(widths: list[int], s: _Slot) -> int:
    """The columns a cell takes: the widths it covers and the spaces between them."""
    return sum(widths[s.first : s.last + 1]) + s.last - s.first


@dataclass
class _RowMarks:
    """What a row marks: the whole row inverted or shaded ({.invert} {.shade} after it), and the cells inverted or
    shaded on their own (not again inside an inverted or shaded row)."""

    row_invert: bool = False
    row_shade: bool = False
    inverted: tuple = ()
    shaded: tuple = ()

    def __bool__(self) -> bool:
        return bool(self.row_invert or self.row_shade or self.inverted or self.shaded)


def _marks_of(ln: _TLine | None) -> _RowMarks:
    """The one place that reads a row's marks (drawn or not, its kind, its boxes)."""
    if ln is None:
        return _RowMarks()
    inv, shade = ln.row.has("invert"), ln.row.has("shade")
    return _RowMarks(inv, shade, tuple(s for s in ln.slots if s.invert and not inv),
                     tuple(s for s in ln.slots if s.shade and not shade))  # fmt: skip


def _marked(lines: list[_TLine]) -> bool:
    """Whether a row has an inverted or shaded cell, or an {.invert} or {.shade} after it: then it is drawn."""
    return bool(_marks_of(lines[0] if lines else None))


def _kind(lines: list[_TLine], zebra: bool = False) -> str:
    """A drawn row's kind (table_pieces): band when the whole row is white on black, zebra when it has grey dots."""
    mk = _marks_of(lines[0] if lines else None)
    words = ["band"] if mk.row_invert else []
    if zebra or mk.row_shade or mk.shaded:
        words.append("zebra")
    return " ".join(words) or "drawn"


def _invert_boxes(im: Image.Image, boxes: list, bottom: int) -> None:
    """A row's inverted boxes (mark_boxes) turned white on black, down to `bottom` (mode L, in place)."""
    for inverted, (lo, hi) in boxes:
        if inverted and hi > lo:
            box = (lo, 0, hi, bottom)
            im.paste(ImageOps.invert(im.crop(box)), box[:2])


def _shade_boxes(im: Image.Image, boxes: list, bottom: int) -> Image.Image:
    """The grey dots of a row's shaded boxes (imaging.shade: kept off the letters and off black)."""
    for inverted, (lo, hi) in boxes:
        if not inverted and hi > lo:
            im = imaging.shade(im, (lo, 0, hi, bottom))
    return im


def _any_class(attrs: list[Attrs], cls: str) -> bool:
    return any(a.has(cls) for a in attrs)


def _offset(align: str, free: int) -> int:
    """How far into its room a cell's text starts, `free` being the room it leaves (:-- --: :-:, or its class)."""
    return {"right": free, "center": free // 2}.get(align, 0)


def _padded(
    slots: list[_Slot], segs: list[list[Cell]], grid: list[int], band: bool = False
) -> tuple[list[Cell], list[Cell]]:
    """A table line on the column grid: each cell's text aligned in its width (a span's: the widths it covers and
    the spaces between them), one column of space between cells. And the same for the terminal views, an inverted
    cell's columns inverted, and every column of an inverted row (band)."""
    line: list[Cell] = []
    view: list[Cell] = []
    last = len(grid) - 1
    for s, seg in zip(slots, segs, strict=True):
        free = _span(grid, s) - columns(seg)
        left = _offset(s.align, free)
        part = [Cell(" ")] * left + seg + [Cell(" ")] * max(0, free - left)
        gap = [Cell(" ")] if s.last < last else []
        line += part + gap
        view += [replace(c, invert=True) for c in part + gap] if band else (
            ([replace(c, invert=True) for c in part] if s.invert else part) + gap)  # fmt: skip
    while line and line[-1] == Cell(" "):
        line.pop()
    while view and view[-1] == Cell(" "):
        view.pop()
    return line, view


@dataclass
class _Slot:
    """A cell of a row on the table's columns: the first and last column it takes (more than one: a span), how
    its text aligns, and whether it is inverted or shaded."""

    first: int
    last: int
    align: str = "left"
    invert: bool = False
    shade: bool = False

    @property
    def cols(self) -> range:
        return range(self.first, self.last + 1)

    @property
    def alone(self) -> bool:
        return self.first == self.last


@dataclass
class _Lay:
    """A table's column settings in the ink's columns: each column's width= (None: auto), what an auto column
    needs at least, the room the table has (its columns and the spaces between them) and whether bobina check says
    the widths it got (L108)."""

    fixed: list[int | None]
    lo: list[int]  # what each auto column asks at least: its text, up to 2 columns (a wide character)
    hard: list[int]  # what each column can never go below: its widest wide character, else 1; empty: 0
    room: int
    say: bool
    head_slots: list[_Slot] | None = None  # the title row's cells on the columns (table_slots)
    slots: list[list[_Slot]] = field(default_factory=list)  # each body row's
    quiet: bool = False  # a squeezed or cut table: L107 says it, its cut words are not said one by one (L101)


def _shrink(widths: list[int], cap: int, floors: list[int] | None = None) -> list[int]:
    """Widths scaled down in proportion to add up to at most cap, never below their floors (1 each by default):
    floors of their shares, the columns furthest over theirs giving back first, the largest remainders taking
    what is left. The sum never passes cap: when even the floors do not fit, the last columns give way below them
    (the caller says so: a cut table)."""
    n, total = len(widths), sum(widths)
    floors = [min(f, w) for f, w in zip(floors or [1] * n, widths, strict=True)]
    if total <= cap:
        return list(widths)
    exact = [w * cap / total for w in widths]
    out = [max(f, math.floor(x)) for f, x in zip(floors, exact, strict=True)]
    while sum(out) > cap:
        over = [i for i in range(n) if out[i] > floors[i]]
        if over:  # the floors given to tiny shares: taken back from the column most over its share
            out[max(over, key=lambda i: out[i] - exact[i])] -= 1
        else:  # not even the floors fit
            out[max(i for i in range(n) if out[i] > 0)] -= 1
    for i in sorted(range(n), key=lambda i: exact[i] - out[i], reverse=True):
        if sum(out) >= cap:
            break
        if out[i] < widths[i]:
            out[i] += 1
    return out


def _fit_fixed(lay: _Lay, cap: int) -> tuple[list[int], list[int] | None, str]:
    """How a table's columns fit in cap: (each column's width, 0 for the auto ones, which share the rest; at most
    what each auto column may take, None: no limit; why it changed). Each column keeps its hard minimum (a wide
    character always fits its column; an empty one costs nothing); an auto one asks lo (its text, up to 2). why:
    "" as given; "scaled": the widths given shrank in proportion; "squeezed": not even that fits, every column
    narrowed; "cut": not even every column at its minimum fits, the table is cut at the paper's edge."""
    fixed, lo, hard = lay.fixed, lay.lo, lay.hard
    mine = [i for i, f in enumerate(fixed) if f is not None]
    widths = [max(f, hard[i]) if f is not None else 0 for i, f in enumerate(fixed)]
    need = sum(lo[i] for i, f in enumerate(fixed) if f is None)
    if sum(widths) + need <= cap:
        return widths, None, ""
    if mine and sum(hard[i] for i in mine) + need <= cap:
        got = _shrink([widths[i] for i in mine], cap - need, [hard[i] for i in mine])
        for i, w in zip(mine, got, strict=True):
            widths[i] = w
        return widths, None, "scaled"
    if sum(hard) > cap:
        return (
            [hard[i] if f is not None else 0 for i, f in enumerate(fixed)],
            [hard[i] for i, f in enumerate(fixed) if f is None],
            "cut",
        )
    squeezed = _shrink([widths[i] if f is not None else lo[i] for i, f in enumerate(fixed)], cap, hard)
    most = [w for w, f in zip(squeezed, fixed, strict=True) if f is None]
    return [w if f is not None else 0 for w, f in zip(squeezed, fixed, strict=True)], most, "squeezed"


@dataclass
class _TLine:
    """A printed line of a table: on the column grid (native text, and what the terminal views show) and as each
    cell's text, for a table drawn in a raster font."""

    cells: list[Cell]
    segs: list[list[Cell]]  # each cell's text on this line, one per slot
    slots: list[_Slot] = field(default_factory=list)  # the row's cells on the columns
    row: Attrs = field(default_factory=Attrs)  # the classes after the row's closing pipe
    view: list[Cell] = field(default_factory=list)  # cells, with the inverted cells' columns inverted
    need: int = 0  # the character columns the table's view grid needs (wider than the paper: its own grid)


@dataclass
class _Geo:
    """Where a table is drawn: on a canvas `width` dots wide (the paper standing, the table turned), its first
    column `x0` dots in, its columns and the spaces between them `inner` dots wide, `pad` dots of border room on
    each side (style=grid)."""

    t: Table
    style: str
    ink: _NativeInk | _FontInk
    widths: list[int]
    width: int
    x0: int
    inner: int
    pad: int

    @classmethod
    def of(cls, t: Table, style: str, ink: _NativeInk | _FontInk, widths: list[int], width: int | None, x0: int):
        """width None: the table's own width (turned)."""
        pad = ink.unit // 2 if style == "grid" else 0
        inner = ink.dots(sum(widths) + len(widths) - 1)
        return cls(t, style, ink, widths, inner + 2 * pad if width is None else width, x0, inner, pad)

    def strip(self, ln: _TLine) -> Image.Image:
        return self.ink.strip(self.t, ln, self.widths, self.inner)


class _NativeInk:
    """A table in the printer font: a column is one character, `wh` times as wide and tall as at 1x (size=1x2
    keeps the columns, each line twice as tall; 2x1 has half the columns)."""

    native = True
    scale = 1  # measure units per column

    def __init__(self, lay: Layout, wh: tuple[int, int] = (1, 1)):
        self.em = lay.em
        self.wh = wh
        self.unit = lay.p.cell[0] * wh[0]
        self.line_h = lay.em.row_height(TextRow([Cell(" ")], wh))
        self.text_h = lay.p.cell[1] * wh[1]

    measure = staticmethod(columns)

    def units(self, cells: list[Cell]) -> int:
        return columns(cells)

    def dots(self, n: int) -> int:
        return n * self.unit

    def from_dots(self, d: int) -> int:
        """The whole columns that fit in d dots."""
        return d // self.unit

    def lead(self, indent: int) -> int:
        """The columns an indent of `indent` 1x columns (a quote, a list) takes: as many, or fewer wider ones."""
        return -(-indent // self.wh[0])

    def lead_dots(self, indent: int) -> int:
        return self.lead(indent) * self.unit

    def strip(self, t: Table, ln: _TLine, widths: list[int], width: int) -> Image.Image:
        return self.em.render_row(TextRow(ln.cells, self.wh, "left", t.line), width).convert("L")


@functools.lru_cache(maxsize=4096)
def _advance64(path: str, px: int, ch: str) -> int:
    return round(rasterfont.load(path, px).getlength(ch) * 64)


class _FontInk:
    """A table drawn in a raster font (font=, size= on its {…} line): cells measured in 1/64 dot, so a line's width
    is the sum of its letters' and wraps exactly; a column is as wide as the font's "0", and a proportional font's
    columns line up by the dot. The fonts are judged (F201, F202, F203) and every letter's font found once, here,
    so a table laid out twice (standing, turned) says its problems in either."""

    native = False

    def __init__(self, lay: Layout, fam: str, px: int, line: int, cells: list[list[Cell]]):
        self.lay, self.fam, self.px, self.line = lay, fam, px, line
        self.context = "".join(c.ch for cs in cells for c in cs)  # Han next to kana is Japanese
        self.fallback = rasterfont.resolve("DejaVu Sans").path
        self.fonts = {False: lay.font_path(fam, False, px, line)}
        if any(c.bold for cs in cells for c in cs):
            self.fonts[True] = lay.font_path(fam, True, px, line)
        self._paths: dict = {}
        base = rasterfont.load(self.fonts[False], px)
        self.scale = max(64, _advance64(self.fonts[False], px, "0"))
        self.unit = round(self.scale / 64)
        asc, desc = base.getmetrics()
        self.asc, self.text_h = asc, asc + desc
        self.line_h = self.text_h + max(2, round(px * 0.25))  # the leading of a raster paragraph
        for cs in cells:
            for c in cs:
                self.path(c)

    def path(self, c: Cell) -> str:
        key = (c.ch, c.bold)
        if key not in self._paths:
            base = self.fonts.get(c.bold) or self.fonts[False]
            cm = rasterfont.cmap(base)
            if c.ch.isspace() or icons.is_icon(c.ch) or not cm or ord(c.ch) in cm:
                self._paths[key] = base
            else:  # the bundled fallback, else the font for that script (F302 when none has it)
                self._paths[key] = self.lay.script_parts(c.ch, base, self.fallback, self.line, self.context)[0][1]
        return self._paths[key]

    def tok(self, c: Cell) -> rasterfont.Tok:
        return rasterfont.Tok(c.ch, self.path(c), self.px, bold=c.bold, italic=c.italic,
                              icon=icons.name_of(c.ch) or "" if icons.is_icon(c.ch) else "")  # fmt: skip

    def adv(self, c: Cell) -> int:
        if icons.is_icon(c.ch):
            return self.tok(c).width() * 64
        return _advance64(self.path(c), self.px, c.ch)

    def measure(self, cells: list[Cell]) -> int:
        return sum(self.adv(c) for c in cells)

    def units(self, cells: list[Cell]) -> int:
        return -(-self.measure(cells) // self.scale)

    def dots(self, n: int) -> int:
        return round(n * self.scale / 64)

    def from_dots(self, d: int) -> int:
        """The whole columns (each as wide as the font's "0") that fit in d dots."""
        return d * 64 // self.scale

    def lead_dots(self, indent: int) -> int:
        """Dots an indent of `indent` printer-font columns (a quote, a list) takes."""
        return indent * self.lay.p.cell[0]

    def strip(self, t: Table, ln: _TLine, widths: list[int], width: int) -> Image.Image:
        """One line of the table in the font: each cell's text aligned in its columns (mode L)."""
        im = Image.new("L", (width, self.line_h), 255)
        for s, seg in zip(ln.slots, ln.segs, strict=True):
            x64 = (sum(widths[: s.first]) + s.first) * self.scale
            self.draw(im, x64 + max(0, _offset(s.align, _span(widths, s) * self.scale - self.measure(seg))), seg)
        return im

    def draw(self, im: Image.Image, x64: int, cells: list[Cell]) -> None:
        """Cells drawn letter by letter where measure() put them; underline, strike and inverted words as one
        stroke or band per run of the same style."""
        runs: list[tuple[tuple, list[Cell]]] = []
        for c in cells:
            key = (c.italic, c.underline, c.strike, c.invert)
            if runs and runs[-1][0] == key:
                runs[-1][1].append(c)
            else:
                runs.append((key, [c]))
        for (italic, underline, strike, invert), run in runs:
            x, w = round(x64 / 64), max(1, round((x64 + self.measure(run)) / 64) - round(x64 / 64))
            x64 += self.measure(run)
            ri = Image.new("L", (w + (round(self.px * 0.2) if italic else 0), self.text_h), 255)
            at = 0
            for c in run:
                if not c.ch.isspace():
                    g = rasterfont.draw_tok(self.tok(c), self.asc, self.text_h, self.px)
                    gx = round(at / 64)
                    box = (gx, 0, min(ri.width, gx + g.width), self.text_h)
                    if box[2] > box[0]:
                        ri.paste(ImageChops.darker(ri.crop(box), g.crop((0, 0, box[2] - gx, self.text_h))), box[:2])
                at += self.adv(c)
            ink = 0
            if invert:
                ri, ink = ImageOps.invert(ri), 255
            th = max(2, self.px // 12)
            d = ImageDraw.Draw(ri)
            if underline:
                d.rectangle((0, self.asc + 2, w - 1, self.asc + 1 + th), fill=ink)
            if strike:
                y = self.asc - int(self.px * 0.3)
                d.rectangle((0, y, w - 1, y + th - 1), fill=ink)
            box = (x, 0, min(im.width, x + ri.width), self.text_h)
            if box[2] <= box[0]:
                continue
            part = ri.crop((0, 0, box[2] - x, self.text_h))
            im.paste(part if invert else ImageChops.darker(im.crop(box), part), box[:2])


def _justify(cells: list[Cell], cap: int, measure=columns, unit: int = 1) -> list[Cell]:
    """Spaces of the line's size added between words until the line is `cap` wide (in the unit of measure: columns,
    or dots for a line whose spans have their own size, `unit` dots to a space)."""
    gaps = [i for i, c in enumerate(cells) if c.ch == " "]
    extra = (cap - measure(cells)) // unit
    if not gaps or extra <= 0:
        return cells
    add = {g: extra // len(gaps) + (1 if k < extra % len(gaps) else 0) for k, g in enumerate(gaps)}
    out = []
    for i, c in enumerate(cells):
        out.append(c)
        if i in add:
            out += [Cell(" ")] * add[i]
    return out
