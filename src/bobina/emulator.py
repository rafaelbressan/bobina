"""Draws text rows the way the printer does: a 12x24 cell grid, GS ! nearest-neighbour scaling,
double-strike bold, underline that skips spaces, GS B inversion that leaves spaces white.

Glyphs come from Spleen 12x24 (closest free match to font A). Rows that cannot be printed
natively (italic, strike, glyphs the printer lacks, drawn checkboxes) are rendered with the same
emulator plus fallbacks, so they blend with native lines."""

from __future__ import annotations

from functools import cache

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

from . import icons, paths
from .rows import Cell, TextRow

CHECKBOX = {"☐": None, "☑": "check", "☒": "cross"}
FALLBACKS = ["DejaVuSans.ttf"]


@cache
def _font(name: str, size: int):
    return ImageFont.truetype(str(paths.fonts_dir() / name), size)


@cache
def _cmap(name: str) -> frozenset[int]:
    return frozenset(TTFont(str(paths.fonts_dir() / name), lazy=True).getBestCmap())


class Emulator:
    def __init__(self, profile):
        self.p = profile
        self.cw, self.ch = profile.cell
        self.font_name = profile.get("native.emulation_font", "spleen-12x24.otf")
        self.font = _font(self.font_name, self.ch)
        self._glyphs: dict[tuple[str, bool], Image.Image] = {}

    def has_glyph(self, ch: str) -> bool:
        return ord(ch) in _cmap(self.font_name) or any(ord(ch) in _cmap(f) for f in FALLBACKS)

    def glyph(self, ch: str, wide: bool) -> Image.Image:
        """One cell (or two for wide) as mode 'L', black ink on white (cached per emulator)."""
        key = (ch, wide)
        if key not in self._glyphs:
            self._glyphs[key] = self._draw_glyph(ch, wide)
        return self._glyphs[key]

    def _draw_glyph(self, ch: str, wide: bool) -> Image.Image:
        w = self.cw * (2 if wide else 1)
        im = Image.new("L", (w, self.ch), 255)
        d = ImageDraw.Draw(im)
        if ch in CHECKBOX:
            self._checkbox(d, w, CHECKBOX[ch])
            return im
        name = icons.name_of(ch)
        if name:
            return _icon_cell(name, w, self.ch)
        if ch == " ":
            return im
        if ord(ch) in _cmap(self.font_name):
            d.text((0, 0), ch, font=self.font, fill=0)
            return im.point(lambda v: 0 if v < 128 else 255)
        for fb in FALLBACKS:
            if ord(ch) in _cmap(fb):
                f = _font(fb, self.ch - 4)
                left, top, right, bottom = f.getbbox(ch)
                d.text(((w - (right - left)) / 2 - left, (self.ch - (bottom - top)) / 2 - top), ch, font=f, fill=0)
                return im.point(lambda v: 0 if v < 140 else 255)
        d.rectangle((2, 3, w - 3, self.ch - 4), outline=0, width=1)  # .notdef box
        return im

    def _checkbox(self, d, w, mark):
        s = 16  # 2-dot strokes (R4: 1 dot prints broken)
        x0, y0 = (w - s) // 2, (self.ch - s) // 2 + 1
        d.rectangle((x0, y0, x0 + s - 1, y0 + s - 1), outline=0, width=2)
        if mark == "check":
            d.line((x0 + 3, y0 + 8, x0 + 7, y0 + 12, x0 + 13, y0 + 3), fill=0, width=3)
        elif mark == "cross":
            d.line((x0 + 3, y0 + 3, x0 + 12, y0 + 12), fill=0, width=2)
            d.line((x0 + 12, y0 + 3, x0 + 3, y0 + 12), fill=0, width=2)

    def line_image(self, cells: list[Cell], tracking: int = 0) -> Image.Image:
        """1x row of cells -> mode 'L' image (cells*12 x 24, plus `tracking` dots after each cell)."""
        widths = [self.cw * (2 if c.wide else 1) for c in cells]
        im = Image.new("L", (max(1, sum(widths) + tracking * len(cells)), self.ch), 255)
        x = 0
        for c, w in zip(cells, widths, strict=True):
            g = self.glyph(c.ch, c.wide)
            if c.bold and c.ch not in CHECKBOX and not icons.is_icon(c.ch):  # double strike: shifted by one dot
                g2 = Image.new("L", g.size, 255)
                g2.paste(g, (1, 0))
                g = _darker(g, g2)
            if c.italic:
                g = g.transform(
                    g.size,
                    Image.AFFINE,
                    (1, 0.22, -0.22 * self.ch * 0.6, 0, 1, 0),
                    resample=Image.NEAREST,
                    fillcolor=255,
                )
            if c.invert and c.ch != " ":
                g = g.point(lambda v: 255 - v)
            im.paste(g, (x, 0))
            if c.underline and c.ch != " ":
                ImageDraw.Draw(im).line((x, self.ch - 2, x + w - 1, self.ch - 2), fill=0, width=1)
            if c.strike:
                y = self.ch // 2 + 1
                ImageDraw.Draw(im).rectangle((x, y, x + w - 1, y + 1), fill=0)
            x += w + tracking
        return im

    def _gapped(self, cells: list[Cell], tracking: int, sw: int, sh: int) -> Image.Image:
        """Glyphs scaled by GS !, then `tracking` dots after each one, as they are (Profile.tracking_gap)."""
        glyphs = self.line_image(cells, 0)
        glyphs = glyphs.resize((glyphs.width * sw, glyphs.height * sh), Image.NEAREST)
        widths = [self.cw * (2 if c.wide else 1) * sw for c in cells]
        im = Image.new("L", (max(1, sum(widths) + tracking * len(cells)), glyphs.height), 255)
        src = 0
        for x, w in zip(self.lefts(cells, sw, tracking, True), widths, strict=True):
            im.paste(glyphs.crop((src, 0, src + w, glyphs.height)), (x, 0))
            src += w
        return im

    def lefts(self, cells: list[Cell], k: int, tracking: int, gapped: bool) -> list[int]:
        """Where each cell starts in a row scaled k times: gapped, `tracking` dots after each scaled glyph
        (_gapped); else the 1x row with its tracking, scaled as a whole (line_image, then GS !)."""
        out, x = [], 0
        for i, c in enumerate(cells):
            out.append(x * k + tracking * i if gapped else (x + tracking * i) * k)
            x += self.cw * (2 if c.wide else 1)
        return out

    def row_height(self, row: TextRow) -> int:
        gap = row.gap if row.gap is not None else int(self.p.get("native.line_gap_dots", 6))
        return min(255, self.ch * row.scale[1] + gap)

    def render_row(self, row: TextRow, width: int) -> Image.Image:
        """Full-width mode '1' image of a text row, aligned and scaled like GS ! does."""
        sw, sh = row.scale
        gap = self.p.tracking_gap(row.tracking, sw)
        if gap != row.tracking * sw:  # the printer does not scale ESC SP at this width (MTP-II at 2x)
            li = self._gapped(row.cells, gap, sw, sh)
        else:
            li = self.line_image(row.cells, row.tracking)
            if (sw, sh) != (1, 1):
                li = li.resize((li.width * sw, li.height * sh), Image.NEAREST)
        if sw == sh > 1:
            li = self._sharp_icons(li, row, sw, gap)
        h = self.row_height(row)
        out = Image.new("L", (width, h), 255)
        lw = min(li.width, width)
        x = {"center": (width - lw) // 2, "right": width - lw}.get(row.align, 0)
        out.paste(li.crop((0, 0, lw, li.height)), (x, 0))
        if row.upside_down:
            out = out.rotate(180)
        return out.convert("1", dither=Image.NONE)

    def _sharp_icons(self, li: Image.Image, row: TextRow, k: int, gap: int) -> Image.Image:
        """At 2x-4x the printer scales letters dot by dot; an icon is drawn again from its own size, so its curves
        stay smooth (same stroke width). Inverted, underlined, struck or slanted icons keep the scaled drawing."""
        if not any(icons.is_icon(c.ch) for c in row.cells):
            return li
        gapped = gap != row.tracking * k
        for left, c in zip(self.lefts(row.cells, k, gap if gapped else row.tracking, gapped), row.cells, strict=True):
            name = icons.name_of(c.ch)
            if name and not (c.invert or c.underline or c.strike or c.italic):
                li.paste(_icon_cell(name, self.cw * (2 if c.wide else 1) * k, self.ch * k), (left, 0))
        return li


def _icon_cell(name: str, w: int, h: int) -> Image.Image:
    """An icon as a square, centred in a cell w x h (mode L)."""
    s = min(w, h)
    cell = Image.new("L", (w, h), 255)
    cell.paste(icons.load(name, s).convert("L"), ((w - s) // 2, (h - s) // 2))
    return cell


def _darker(a: Image.Image, b: Image.Image) -> Image.Image:
    from PIL import ImageChops

    return ImageChops.darker(a, b)
