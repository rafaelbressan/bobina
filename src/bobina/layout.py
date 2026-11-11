"""Document -> rows, guided by the printer profile. bobina decides every line break."""

from __future__ import annotations

import re
import unicodedata

from PIL import Image, ImageOps

from . import imaging, rasterfont, scriptfonts, sources
from .emulator import CHECKBOX, Emulator
from .model import Divider, Document, Fence, Heading, ListBlock, Paragraph, Quote, Run, Table
from .model import Image as ImageBlock
from .nudges import Nudges, SecurityError
from .rows import BarcodeRow, BitmapRow, Cell, FeedRow, QRRow, RawRow, TextRow
from .templating import PH_RE, Rendered

NO_CAPTION = {"", "auto", "none", "no", "false", "off"}  # caption= words that print no caption on a plain QR
PAY_HINT = 'write ```pay {scheme=pix to="your key" name="Shop" city="Rio" amount=10.00} (bobina help pay)'

# CLDR dates/currencies use no-break and narrow spaces ("6:44\u202fPM", "R$\u00a04,50"): the printer font has
# no glyph for them, so the whole line would become an image. They print as a plain space.
SPACES = str.maketrans({c: " " for c in "\u00a0\u2007\u2009\u202f\u2002\u2003\u205f"})
CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")  # never let text carry printer commands
SIZE_RE = re.compile(r"^(\d)x(?:(\d))?$")
UNIT_RE = re.compile(r"^(\d+(?:\.\d+)?)(px|mm)$")


def is_wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


_IMAGES: dict = {}  # finished image rows (local files, data: URIs) of this process; oldest dropped first
_IMAGES_MAX = 64


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


def _remember(key, value) -> None:
    if len(_IMAGES) >= _IMAGES_MAX:
        _IMAGES.pop(next(iter(_IMAGES)))
    _IMAGES[key] = value


class Layout:
    def __init__(self, profile, doc: Document, rendered: Rendered | None, nudges: Nudges, net: bool = False):
        self.p, self.doc, self.r, self.n = profile, doc, rendered, nudges
        self.net = net  # https images allowed (only from the command line: --allow-net)
        self.em = Emulator(profile)
        self.W = profile.width_dots
        self.cols = profile.columns
        meta = doc.meta
        self.align = str(meta.get("align", "left"))
        self.size = str(meta.get("size", "normal"))
        tasks = meta.get("tasks") or {}
        self.done = str(tasks.get("done", "strike")) if isinstance(tasks, dict) else "strike"
        img = meta.get("image") or {}
        self.img = img if isinstance(img, dict) else {}
        fonts = meta.get("fonts") or {}
        self.fonts = {**rasterfont.DEFAULT_ROLES, **(fonts if isinstance(fonts, dict) else {})}
        self._judged: set = set()
        lang = str(meta.get("locale") or meta.get("lang") or "")
        self.scripts = scriptfonts.Resolver(nudges, lang)  # fonts for other scripts, downloaded once

    # ------------------------------------------------------------ helpers
    def text(self, s: str) -> str:
        if self.r is not None:
            s = self.r.resolve(s)
        return CTRL.sub("", s.replace("\t", "    ")).translate(SPACES)

    def scale_for(self, size: str | None, line: int) -> tuple[int, int]:
        if not size:
            size = self.size
        named = self.p.get("native.sizes", {})
        if size in named:
            return tuple(named[size])
        m = SIZE_RE.match(size)
        if m:
            w = int(m.group(1))
            h = int(m.group(2) or m.group(1))
            return (w, h)
        m = UNIT_RE.match(size)
        if m:
            v = float(m.group(1))
            dots = v if m.group(2) == "px" else self.p.mm_to_dots(v)
            s = max(1, min(4, round(dots / self.p.cell[1])))
            self.n.add(
                "F303",
                f"size {size} printed natively at {s}x",
                line,
                "set a raster font (fonts: body: Atkinson Hyperlegible) for exact sizes",
            )
            return (s, s)
        self.n.add("M101", f"unknown size '{size}'", line, "small, normal, large, title, huge, 2x, 1x2, 20px, 3mm")
        return (1, 1)

    def cells_from_runs(self, runs: list[Run], extra: dict) -> list[Cell | None]:
        """Runs -> cells; None marks a forced line break."""
        out: list[Cell | None] = []
        for r in runs:
            if r.text == "\n":
                out.append(None)
                continue
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
                    )
                )
        return out

    def wrap(self, cells: list[Cell | None], cap: int, hang: int, line: int) -> list[list[Cell]]:
        """Greedy word wrap on columns; `hang` columns already used on continuation lines."""
        lines: list[list[Cell]] = []
        para: list[Cell] = []

        def flush(p: list[Cell]):
            words, cur = [], []
            for c in p:
                if c.ch == " ":
                    if cur:
                        words.append(cur)
                        cur = []
                    words.append([c])
                else:
                    cur.append(c)
            if cur:
                words.append(cur)
            line_cells: list[Cell] = []
            width = 0
            avail = cap
            for w in words:
                ww = sum(2 if c.wide else 1 for c in w)
                if w[0].ch == " ":
                    if width and width + 1 <= avail:
                        line_cells += w
                        width += 1
                    continue
                if width + ww > avail and width:
                    while line_cells and line_cells[-1].ch == " ":
                        line_cells.pop()
                    lines.append(line_cells)
                    line_cells, width, avail = [], 0, cap - hang
                while ww > avail:  # a word longer than a full line
                    self.n.add(
                        "L101",
                        f"word '{''.join(c.ch for c in w)[:20]}…' split at {avail} columns",
                        line,
                        "shorten it or use a smaller size",
                    )
                    take, k = 0, 0
                    while k < len(w) and take + (2 if w[k].wide else 1) <= avail - width:
                        take += 2 if w[k].wide else 1
                        k += 1
                    line_cells += w[:k]
                    lines.append(line_cells)
                    line_cells, width, avail = [], 0, cap - hang
                    w = w[k:]
                    ww = sum(2 if c.wide else 1 for c in w)
                line_cells += w
                width += ww
            while line_cells and line_cells[-1].ch == " ":
                line_cells.pop()
            lines.append(line_cells)

        for c in cells:
            if c is None:
                flush(para)
                para = []
            else:
                para.append(c)
        flush(para)
        return lines

    def native_ok(self, cells: list[Cell]) -> str:
        """'' if the line can be printed natively, else the reason."""
        for c in cells:
            if c.italic:
                return "italic"
            if c.strike:
                return "strike"
            if c.ch in CHECKBOX:
                return "checkbox"
            if c.ch != " " and not self.p.native_glyph(c.ch):
                return f"glyph {c.ch}"
        return ""

    def drawn_whole(self, runs) -> str:
        """The first letter that makes a native block go raster as a whole ('' for none): one the printer lacks
        and that cannot be drawn cell by cell (a script that shapes or runs right to left), or that only a
        script font has (Chinese on a printer without it)."""
        decided: dict[str, tuple[bool, bool]] = {}  # script -> (shapes, a script font draws it): once per script
        for r in runs:
            for ch in self.text(r.text):
                if ch.isspace() or self.p.native_glyph(ch) or ch in CHECKBOX:
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
                parts = [(piece, path)]
                if cm and any(ord(ch) not in cm for ch in piece if not ch.isspace()):
                    parts = self.script_parts(piece, path, fallback, line, context)
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
                pimg = rasterfont.draw_tok(t, asc, asc + desc)
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
        im, texts = rasterfont.render_block(
            toks, self.W, align, leading, pimg, indent * self.p.cell[0] + indent_dots, rtl=rtl
        )
        view_rows = [
            TextRow([Cell(ch) for ch in t[: self.cols]], (1, 1), "left" if align == "justify" else align, line)
            for t in texts
        ]
        if attrs.has("invert"):
            m = int(self.p.get("raster.invert_margin_dots", 4))
            band = Image.new("L", (self.W, im.height + 2 * m), 255)
            band.paste(im.convert("L"), (0, m))
            if px < int(self.p.get("raster.invert_min_px", 20)) or not bold:
                self.n.add(
                    "F204",
                    f"inverted text at {px}px{'' if bold else ' (not bold)'} closes up",
                    line,
                    "use bold and ≥ 20px",
                    "R2-12",
                )
            return [BitmapRow(ImageOps.invert(band).convert("1", dither=Image.NONE), line, "band", view_rows)]
        return [BitmapRow(im, line, "text", view_rows)]

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
        tracking = self.attr_dots(attrs, "tracking", line, 32) or 0
        leading = self.attr_dots(attrs, "leading", line, 200)
        raw_indent = str(attrs.kv.get("indent", ""))
        indent_dots = self.attr_dots(attrs, "indent", line, self.W // 2) or 0
        indent_is_columns = raw_indent.isdigit()  # indent=4 means 4 columns; 4px / 2mm are physical
        fam = self.raster_family(attrs, role, runs)
        if fam is not None:
            named = {1: "title", 2: "large", 3: "normal"}.get(level) if role == "title" else None
            size = attrs.kv.get("size") or named or self.size
            px = rasterfont.px_for(size, self.p, 20, self.n, line)
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
        if scale[0] not in self.p.get("native.scales_ok", [1, 2, 3, 4]) or scale[1] not in self.p.get(
            "native.scales_ok", [1, 2, 3, 4]
        ):
            self.n.add("F303", f"size {scale[0]}x{scale[1]} is jagged on this printer", line, "use up to 4x", "N1")
        align = attrs.kv.get("align") or next(
            (a for a in ("center", "right", "left", "justify") if attrs.has(a)), self.align
        )
        cells = self.cells_from_runs(runs, extra)
        prefix = prefix or []
        pw = sum(2 if c.wide else 1 for c in prefix)
        advance = self.p.cell[0] * scale[0] + self.p.tracking_gap(tracking, scale[0])  # as the printer spaces them
        if indent_dots:
            indent += indent_dots if indent_is_columns else round(indent_dots / advance)
        cap = self.W // advance - indent
        if cap - pw < 1:
            self.n.add(
                "L101", "indent and letter spacing leave no room on the line", line, "reduce indent= or tracking="
            )
            cap = pw + 1
        if leading is not None and self.p.cell[1] * scale[1] + leading > 255:
            self.n.add("M101", f"leading={leading} too large for {scale[1]}x height", line)
        lines = self.wrap(cells, cap - pw, 0, line)
        rows = []
        for i, lc in enumerate(lines):
            if align == "justify" and i < len(lines) - 1:
                lc = _justify(lc, cap - pw)
            lead = [Cell(" ")] * indent + (prefix if i == 0 else [Cell(" ")] * pw)
            cells_line = lead + lc
            reason = self.native_ok(cells_line)
            if reason.startswith("glyph"):
                self.n.add(
                    "F301",
                    f"{reason} is not in the printer font: line printed as an image",
                    line,
                    "keep it (fine) or use a character from the native set",
                )
                for c in cells_line:
                    if c.ch != " " and c.ch not in CHECKBOX and not self.em.has_glyph(c.ch):
                        self.n.add("F302", f"glyph {c.ch} is missing in every font: printed as a box", line)
            rows.append(
                TextRow(
                    cells_line,
                    scale,
                    "left" if align == "justify" else align,
                    line,
                    native=not reason,
                    reason=reason,
                    tracking=tracking,
                    gap=leading,
                )
            )
        if attrs.has("invert"):
            return [self.band(rows, line)]
        return rows

    def band(self, rows: list[TextRow], line: int) -> BitmapRow:
        """Continuous inverted band (GS B leaves spaces white, so it goes raster)."""
        m = int(self.p.get("raster.invert_margin_dots", 4))
        imgs = [self.em.render_row(r, self.W).convert("L") for r in rows]
        h = sum(i.height for i in imgs) + 2 * m
        out = Image.new("L", (self.W, h), 255)
        y = m
        for i in imgs:
            out.paste(i, (0, y))
            y += i.height
        return BitmapRow(ImageOps.invert(out).convert("1", dither=Image.NONE), line, "band", rows)

    # ------------------------------------------------------------ blocks
    def run(self) -> list:
        rows: list = [FeedRow(int(self.p.get("margins.top_dots", 24)))]
        gap = int(self.p.get("margins.block_gap_dots", 12))
        first = True
        for b in self.doc.blocks:
            out = self.block(b, 0)
            if not out:
                continue
            if not first:
                rows.append(FeedRow(gap))
            rows += out
            first = False
        feed = int(self.p.get("margins.feed_after_dots", 96))
        tear_at = None
        if self.p.get("marks", "none") in ("tear", "both"):  # printed so that the feed leaves it on the tear bar
            tear_at = max(0, feed - min(feed, max(1, int(self.p.get("margins.tear_dots", 40)))))  # 1 dot after it
        rows.append(FeedRow(feed, mark="tear", tear_at=tear_at))
        return rows

    def block(self, b, indent: int) -> list:
        rows = self._block(b, indent)
        a = getattr(b, "attrs", None)
        if a is None or not rows:
            return rows
        rot = a.kv.get("rotate")
        if a.has("flip") and not rot:
            if all(isinstance(r, TextRow) and r.native for r in rows):
                for r in rows:
                    r.upside_down = True
                return list(reversed(rows))
            rot = "180"
        if rot:
            try:
                ang = float(rot)
            except ValueError:
                self.n.add("M101", f"rotate={rot}", b.line, "0, 90, 180, 270 or degrees")
                return rows
            if ang % 360:
                return [self.rotate(rows, ang, a, b.line)]
        return rows

    def compose(self, rows) -> Image.Image:
        from . import preview

        parts = [im.convert("L") for im in (preview.row_image(r, self.p, self.em) for r in rows) if im is not None]
        out = Image.new("L", (self.W, max(1, sum(p.height for p in parts))), 255)
        y = 0
        for p in parts:
            out.paste(p, (0, y))
            y += p.height
        return out

    def rotate(self, rows, ang: float, attrs, line: int) -> BitmapRow:
        im = self.compose(rows)
        box = ImageOps.invert(im).getbbox()
        if box:
            im = im.crop(
                (max(0, box[0] - 4), max(0, box[1] - 4), min(im.width, box[2] + 4), min(im.height, box[3] + 4))
            )
        im = im.rotate(
            -ang,
            expand=True,
            fillcolor=255,  # minus: clockwise, like CSS
            resample=Image.NEAREST if ang % 90 == 0 else Image.BICUBIC,
        )
        if im.width > self.W:
            self.n.add(
                "L104",
                f"rotated block is {im.width} dots wide: cropped to {self.W}",
                line,
                "shorten the lines or use rotate=90/270",
            )
            im = im.crop(((im.width - self.W) // 2, 0, (im.width - self.W) // 2 + self.W, im.height))
        if ang % 90:
            self.n.add(
                "B102", f"rotate={ang:g}: slanted strokes look jagged at {self.p.dpi} dpi", line, "prefer 90/180/270"
            )
        align = attrs.kv.get("align") or next((x for x in ("left", "right", "center") if attrs.has(x)), "center")
        bw = im.point(lambda v: 0 if v < 128 else 255).convert("1", dither=Image.NONE)
        return BitmapRow(imaging.place(bw, self.W, align), line, "rotated")

    def _block(self, b, indent: int) -> list:
        if isinstance(b, Heading):
            h = self.p.get(f"native.headings.h{min(b.level, 3)}", {"scale": [1, 1], "bold": True})
            scale = self.scale_for(b.attrs.kv["size"], b.line) if "size" in b.attrs.kv else tuple(h["scale"])
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
        if isinstance(b, Quote):
            rows = []
            for c in b.children:
                for r in self.block(c, indent):
                    if isinstance(r, TextRow) and r.scale == (1, 1):
                        r.cells = [Cell("│"), Cell(" ")] + r.cells
                    rows.append(r)
            return rows
        if isinstance(b, Divider):
            return [self.divider(b)]
        if isinstance(b, Fence):
            return self.fence(b, indent)
        if isinstance(b, ImageBlock):
            return self.image(b.src, b.attrs, b.line)
        if isinstance(b, Table):
            return self.table(b, indent)
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
            pw = sum(2 if c.wide else 1 for c in prefix)
            for k, child in enumerate(it.children):
                if k == 0 and isinstance(child, Paragraph):
                    strike = it.task is True and self.done == "strike"
                    rows += self.text_block(
                        child.runs,
                        line=child.line,
                        attrs=child.attrs,
                        prefix=prefix,
                        indent=indent,
                        extra={"strike": strike},
                    )
                else:
                    rows += self.block(child, indent + pw)
        return rows

    def divider(self, b) -> BitmapRow:
        style = next((s for s in ("solid", "dashed", "dotted", "double", "wavy", "cut") if b.attrs.has(s)), "solid")
        t = int(b.attrs.kv.get("thickness", 2))
        if t < int(self.p.get("raster.min_stroke_dots", 2)):
            self.n.add("B101", f"divider thickness {t} prints broken", b.line, "use thickness=2")
        return BitmapRow(imaging.divider(self.W, style, t), b.line, "divider")

    def fence(self, f: Fence, indent: int) -> list:
        kind = f.kind
        if kind == "qr":
            return self.qr(f)
        if kind == "barcode":
            return self.barcode(f)
        if kind == "pay":
            return self.pay(f)
        if kind == "pix":  # Pix is a pay scheme now: say so loudly, a payment code is missing from the print
            self.n.add("Q111", "the pix block is gone: Pix is pay {scheme=pix}, nothing printed", f.line, PAY_HINT)
            return []
        if kind in ("datamatrix", "pdf417"):
            return self.matrix_code(f, kind)
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
            self.n.add("M102", f"block type '{kind}' is not supported (yet): printed as text", f.line)
        rows = []
        cap = self.cols - indent
        for ln in f.content.rstrip("\n").split("\n"):
            cells = [Cell(ch, wide=is_wide(ch)) for ch in self.text(ln)]
            while True:
                if sum(2 if c.wide else 1 for c in cells) > cap:
                    self.n.add("L103", f"line longer than {cap} columns wrapped", f.line)
                piece, rest, w = [], [], 0
                for i, c in enumerate(cells):
                    cw = 2 if c.wide else 1
                    if w + cw > cap:
                        rest = cells[i:]
                        break
                    piece.append(c)
                    w += cw
                cl = [Cell(" ")] * indent + piece
                reason = self.native_ok(cl)
                rows.append(TextRow(cl, (1, 1), "left", f.line, native=not reason, reason=reason))
                if not rest:
                    break
                cells = rest
        return rows

    def fit_module(self, size: str, units: int, default: int, hi: int, line: int) -> int:
        """Integer module so that `units` modules fill a target width: size=full|half|third|NNmm.
        Integer modules keep codes scannable (no uneven bars)."""
        target = {"full": self.W, "half": self.W // 2, "third": self.W // 3}.get(str(size))
        if target is None:
            m = UNIT_RE.match(str(size))
            if not m:
                self.n.add("M101", f"code size '{size}'", line, "full, half, third or a width like 30mm")
                return default
            target = float(m.group(1)) if m.group(2) == "px" else self.p.mm_to_dots(float(m.group(1)))
        return max(1, min(hi, int(min(target, self.W) // units)))

    def qr(self, f: Fence, resolved: bool = False) -> list:
        """A QR code, and under it the caption= line if there is one (1 mm of air: glued, it reads as part of it)."""

        rows = self._qr_code(f, resolved)
        caption = self.text(str(f.attrs.kv.get("caption", ""))).strip()
        if caption.lower() in NO_CAPTION:  # auto: a plain QR has nothing to say on its own
            caption = ""
        return rows + self.caption_rows(caption, f.line) if rows else rows

    def caption_rows(self, text: str, line: int) -> list:
        from .model import Attrs, Run

        if not text:
            return []
        return [FeedRow(self.p.mm_to_dots(1)), *self.text_block([Run(text)], line=line, attrs=Attrs({"center"}))]

    def _qr_code(self, f: Fence, resolved: bool = False) -> list:
        data = f.content if resolved else self.text(f.content.strip("\n"))
        ecc = f.attrs.kv.get("ecc", self.p.get("qr.default_ecc", "M")).upper()
        mod = int(f.attrs.kv.get("module", self.p.get("qr.default_module", 4)))
        align = next((a for a in ("left", "right", "center") if f.attrs.has(a)), f.attrs.kv.get("align", "center"))
        render = f.attrs.kv.get("render", "native" if self.p.get("qr.native") else "raster")
        if ecc == "L":
            self.n.add("Q102", "QR with ECC L", f.line, "use ecc=M")
        if ecc not in ("L", "M", "Q", "H"):
            self.n.add("M101", f"unknown ecc '{ecc}'", f.line, "L, M, Q or H")
            ecc = "M"
        lo = int(self.p.get(f"qr.min_module_{render}", 4))
        if mod < lo:
            self.n.add("Q101", f"QR module {mod} in {render} mode", f.line, f"use module={lo}")
        try:
            n = len(imaging.qr_matrix(data, ecc))
        except Exception as e:  # noqa: BLE001 - segno: DataOverflowError and friends
            self.n.add(
                "Q109",
                f"QR cannot hold {len(data)} characters at ECC {ecc}: {type(e).__name__}",
                f.line,
                "less data or ecc=L",
            )
            return []
        if "size" in f.attrs.kv:
            mod = self.fit_module(f.attrs.kv["size"], n, mod, 16 if render == "native" else 64, f.line)
            if mod < lo:
                self.n.add(
                    "Q101",
                    f"size={f.attrs.kv['size']} gives module {mod} in {render} mode",
                    f.line,
                    f"a larger size or less data (module ≥ {lo})",
                )
        while n * mod > self.W and mod > 1:
            mod -= 1
            self.n.add("Q103", f"QR does not fit: module reduced to {mod}", f.line, "shorten the content")
        if render == "native":
            return [QRRow(data, mod, ecc, align, f.line)]
        return [BitmapRow(imaging.place(imaging.qr_image(data, mod, ecc, border=2), self.W, align), f.line, "qr")]

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
        align = next((a for a in ("left", "right", "center") if f.attrs.has(a)), f.attrs.kv.get("align", "center"))
        orientation = f.attrs.kv.get("orientation", "auto")
        stretch = f.attrs.kv.get("width") == "full" or f.attrs.has("justify")
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
        if units and stretch and orientation != "vertical":
            mod = max(mod, min(6, self.W // units))  # GS w accepts 1..6
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
            bar_len = self.W - 8 if stretch else height
            # drawn by bobina, not by the firmware: the readable 3:1 Code39, whatever the printer's GS k does
            im = codes.image(kind, data, mod, bar_len, text, self.em, wide=3).rotate(-90, expand=True)
            quiet = int(self.p.get("barcode.quiet_modules", 10)) * mod
            padded = Image.new("1", (im.width, im.height + 2 * quiet), 1)
            padded.paste(im, (0, quiet))
            if orientation == "auto":  # the length of the image just drawn, quiet zones included
                self.n.add(
                    "Q110",
                    f"{kind} '{data[:24]}' is {wide_dots} dots wide (paper {self.W}): "
                    f"it will print VERTICALLY, about {padded.height / (self.p.dpi / 25.4):.0f} mm along the paper",
                    f.line,
                    "keep it (fine), set orientation=vertical to silence this, "
                    "or orientation=horizontal (it would be cut) — or use a QR code",
                )
            return [BitmapRow(imaging.place(padded, self.W, align), f.line, "barcode")]
        if too_wide:
            self.n.add(
                "Q104",
                f"{units * mod} dots wide (paper {self.W}): it will be cut",
                f.line,
                "orientation=auto prints it vertically",
            )
        return [BarcodeRow(kind, data, mod, height, text, align, f.line)]

    def matrix_code(self, f: Fence, kind: str) -> list:
        """2D codes the printer cannot draw natively: always raster (R5: module >= 4 for square codes)."""
        data = self.text(f.content.strip("\n"))
        default = 4 if kind == "datamatrix" else 2
        mod = int(f.attrs.kv.get("module", default))
        if kind == "datamatrix" and mod < int(self.p.get("qr.min_module_raster", 4)):
            self.n.add("Q101", f"datamatrix module {mod} in raster", f.line, "use module=4")
        align = next((a for a in ("left", "right", "center") if f.attrs.has(a)), f.attrs.kv.get("align", "center"))
        if kind == "datamatrix" and "size" in f.attrs.kv:
            try:
                from ppf.datamatrix import DataMatrix

                units = len(DataMatrix(data).matrix[0]) + 4
                mod = self.fit_module(f.attrs.kv["size"], units, mod, 64, f.line)
            except Exception:  # noqa: BLE001 - reported below by the encoder
                pass
        try:
            if kind == "datamatrix":
                im = imaging.datamatrix_image(data, mod)
            else:
                im = imaging.pdf417_image(data, mod, int(f.attrs.kv.get("ratio", 3)), int(f.attrs.kv.get("columns", 4)))
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
        return [BitmapRow(imaging.place(im, self.W, align), f.line, kind)]

    def pay(self, f: Fence) -> list:
        """A payment QR code (```pay {scheme=…}): the payload from pay.py, a QR, and a caption line."""
        from babel import numbers as bnumbers

        from . import pay
        from .model import Attrs
        from .templating import (
            ambiguity_message,
            has_locale,
            is_negative,
            money_locale,
            parse_number,
            resolve_locale,
            two_readings,
        )

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
            if k not in s.attrs and k not in pay.QR_ATTRS and k != "amount" and str(kv[k]).strip():  # empty: unused
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
        loc = resolve_locale(self.doc.meta)
        amount = None
        if str(kv.get("amount") or "").strip() and not carries:
            self.n.add("M156", f"{label} cannot carry an amount: the payer types it", f.line, "show the price as text")
        elif str(kv.get("amount") or "").strip():
            raw = kv["amount"]
            mloc = money_locale(pay.currency(s, kv), loc, has_locale(self.doc.meta))
            negative = is_negative(raw)  # its own error below (also -R$ 10,00 and −10), not "reads two ways"
            both = None if negative else two_readings(raw, s.decimals)
            if both:  # 1.890: R$ 1,89 or R$ 1.890? a payment never guesses, whatever the locale
                msg, hint = ambiguity_message(raw, *both)
                self.n.add("Q111", f"{label}: {msg}", f.line, hint)
                return []
            n = parse_number(raw, bnumbers.get_decimal_symbol(mloc))  # read as the caption writes it
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
        caption = str(kv.get("caption", "auto")).strip()
        if caption.lower() == "auto":
            caption = pay.caption(s, amount, kv, loc, has_locale(self.doc.meta))  # computed text: never a keyword
        elif caption.lower() in NO_CAPTION:
            caption = ""
        keep = {k: v for k, v in f.attrs.kv.items() if k in pay.QR_ATTRS - {"caption", "scheme"}}
        rows = self._qr_code(Fence(line=f.line, attrs=Attrs(set(f.attrs.classes), keep), kind="qr", content=payload),
                             resolved=True)  # fmt: skip
        return rows + self.caption_rows(caption, f.line) if rows else rows

    def image(self, src: str, attrs, line: int) -> list:
        if self.r is not None and self.r.tainted_in(src):
            raise SecurityError("M312", "an image path cannot come from --data/--set values", line)
        src = self.text(src)
        width = attrs.kv.get("width")
        if width and str(width).endswith("%"):
            w = int(self.W * float(str(width)[:-1]) / 100)
        elif width:
            w = int(str(width).removesuffix("px"))
        else:
            w = self.W
        if w > self.W:
            self.n.add("I102", f"image width {w} reduced to {self.W}", line)
            w = self.W
        try:
            page = int(attrs.kv.get("page", 1))
        except ValueError:
            page = 1
        settings = tuple(self.p.get(k) for k in ("image.dither", "image.gamma", "image.gamma_atkinson"))
        key = _image_key(src, self.doc.base_dir, attrs, (w, page, self.W, self.net, repr(self.img), settings))
        if key is not None and key in _IMAGES:  # a batch of 1000 labels with the same logo decodes it once
            host, row_im = _IMAGES[key]
            if host:
                self.n.add("I104", f"fetched {host}", line, "that server can see when you print")
            return [BitmapRow(row_im, line, "image")]
        try:
            im = imaging.open_image(src, self.doc.base_dir, width=max(8, w), page=page, allow_net=self.net)
        except sources.ImageError as e:
            self.n.add(e.code, f"image '{src[:60]}': {e}", line, e.hint or "check the path (relative to the document)")
            return []
        except Exception as e:  # noqa: BLE001
            self.n.add("I101", f"image '{src[:60]}': {e.__class__.__name__}", line, "check the path")
            return []
        if im.info.get("bobina.host"):
            self.n.add("I104", f"fetched {im.info['bobina.host']}", line, "that server can see when you print")
        vector = im.info.get("bobina.kind") == "vector"
        default_dither = "threshold" if vector else self.img.get("dither", self.p.get("image.dither", "fs"))
        kind = imaging.DITHERS.get(str(attrs.kv.get("dither", default_dither)), "fs")
        default_gamma = (
            self.p.get("image.gamma_atkinson", 1.5) if kind == "atkinson" else self.p.get("image.gamma", 1.8)
        )
        gamma = float(attrs.kv.get("gamma", self.img.get("gamma", default_gamma)))
        align = next((a for a in ("left", "right", "center") if attrs.has(a)), attrs.kv.get("align", "center"))
        bw = imaging.photo(im, max(8, w), gamma, kind)
        placed = imaging.place(bw, self.W, align)
        if key is not None:
            _remember(key, (im.info.get("bobina.host"), placed))
        return [BitmapRow(placed, line, "image")]

    def table(self, t: Table, indent: int) -> list:
        """Monospace grid: columns line up exactly in the native font."""

        def txt(runs):
            return "".join(self.text(r.text) for r in runs).replace("\n", " ").strip()

        head = [txt(c) for c in t.header]
        body = [[txt(c) for c in r] for r in t.rows]
        ncol = len(head)
        widths = [max([len(head[i])] + [len(r[i]) if i < len(r) else 0 for r in body]) for i in range(ncol)]
        cap = self.cols - indent - (ncol - 1)
        while sum(widths) > cap:
            i = widths.index(max(widths))
            widths[i] -= 1
        if not t.attrs.has("compact") and sum(widths) < cap:  # stretch: last column at the paper edge
            widths[0] += cap - sum(widths)
        rows = []

        def emit(cells_text, bold):
            wrapped = []
            for i in range(ncol):
                s = cells_text[i] if i < len(cells_text) else ""
                parts = [s[k : k + widths[i]] for k in range(0, max(1, len(s)), widths[i])] or [""]
                wrapped.append(parts)
            for k in range(max(len(p) for p in wrapped)):
                line = ""
                for i in range(ncol):
                    s = wrapped[i][k] if k < len(wrapped[i]) else ""
                    al = t.aligns[i] if i < len(t.aligns) else "left"
                    s = (
                        s.rjust(widths[i])
                        if al == "right"
                        else s.center(widths[i])
                        if al == "center"
                        else s.ljust(widths[i])
                    )
                    line += s + (" " if i < ncol - 1 else "")
                cells = [Cell(" ")] * indent + [Cell(ch, bold=bold) for ch in line.rstrip()]
                reason = self.native_ok(cells)
                rows.append(TextRow(cells, (1, 1), "left", t.line, native=not reason, reason=reason))

        emit(head, True)
        rows.append(BitmapRow(imaging.divider(self.W, "solid", 2, pad=3), t.line, "divider"))
        for r in body:
            emit(r, False)
        return rows


def _justify(cells: list[Cell], cap: int) -> list[Cell]:
    width = sum(2 if c.wide else 1 for c in cells)
    gaps = [i for i, c in enumerate(cells) if c.ch == " "]
    extra = cap - width
    if not gaps or extra <= 0:
        return cells
    add = {g: extra // len(gaps) + (1 if k < extra % len(gaps) else 0) for k, g in enumerate(gaps)}
    out = []
    for i, c in enumerate(cells):
        out.append(c)
        if i in add:
            out += [Cell(" ")] * add[i]
    return out
