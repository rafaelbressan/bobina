"""Terminal preview. Native text rows are shown as text on the real 32-column grid; images,
QR codes and other raster rows as braille, where one character = 2x4 dots of 6x6 px, i.e. exactly
one native cell (12x24) — so text and images keep their true proportions side by side."""

from __future__ import annotations

import os
import sys
import unicodedata

from PIL import Image

from . import preview
from .rows import BitmapRow, FeedRow, QRRow, RawRow, TextRow

BRAILLE = [
    (0, 0, 0x01),
    (0, 1, 0x02),
    (0, 2, 0x04),
    (1, 0, 0x08),
    (1, 1, 0x10),
    (1, 2, 0x20),
    (0, 3, 0x40),
    (1, 3, 0x80),
]


TEAR_MARK = " ⟶ "


def use_color(stream=sys.stdout) -> bool:
    return stream.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"


def braille(im: Image.Image, cell=(12, 24)) -> list[str]:
    """Mode '1' image -> braille lines, one char per native cell."""
    g = im.convert("L")
    cw, ch = cell
    cols = (g.width + cw - 1) // cw
    rows = (g.height + ch - 1) // ch
    padded = Image.new("L", (cols * cw, rows * ch), 255)
    padded.paste(g, (0, 0))
    small = padded.resize((cols * 2, rows * 4), Image.BOX)
    px = small.load()
    out = []
    for r in range(rows):
        line = []
        for c in range(cols):
            code = 0
            for x, y, bit in BRAILLE:
                if px[c * 2 + x, r * 4 + y] < 190:  # >= ~25% ink in the 6x6 block
                    code |= bit
            line.append(chr(0x2800 + code) if code else " ")
        out.append("".join(line))
    return out


def _sgr(cell, color: bool) -> tuple[str, str]:
    if not color:
        return "", ""
    codes = []
    if cell.bold:
        codes.append("1")
    if cell.italic:
        codes.append("3")
    if cell.underline:
        codes.append("4")
    if cell.invert:
        codes.append("7")
    if cell.strike:
        codes.append("9")
    return (f"\x1b[{';'.join(codes)}m", "\x1b[0m") if codes else ("", "")


def text_lines(row: TextRow, cols: int, color: bool) -> list[str]:
    sw, sh = row.scale
    parts, width = [], 0
    cells = list(reversed(row.cells)) if row.upside_down else row.cells
    align = {"left": "right", "right": "left"}.get(row.align, row.align) if row.upside_down else row.align
    for c in cells:
        on, off = _sgr(c, color)
        glyph = c.ch + (" " if c.wide and unicodedata.east_asian_width(c.ch) not in ("W", "F") else "")
        parts.append(on + glyph + off + " " * (sw - 1) * (2 if c.wide else 1))
        width += (2 if c.wide else 1) * sw
    pad = {"center": (cols - width) // 2, "right": cols - width}.get(align, 0)
    line = " " * max(0, pad) + "".join(parts) + " " * max(0, cols - width - max(0, pad))
    return [line] + [" " * cols] * (sh - 1)


def lines(rows, profile, color: bool = False, max_feed_lines: int = 1) -> list[str]:
    cols = profile.columns
    em = None
    out: list[str] = []
    for r in rows:
        if isinstance(r, FeedRow) and r.mark == "tear":
            out.append(TEAR_MARK.center(cols, "┄"))  # the paper goes to the tear bar here (decided 08/11:
        elif isinstance(r, FeedRow) and r.mark == "cut":  # symbols only, no words); a --compact cut, printed or not
            out.append(("✂ " + "┄" * cols)[:cols])
        elif isinstance(r, FeedRow):
            n = min(max_feed_lines, r.dots // profile.cell[1])
            out += [" " * cols] * n
        elif isinstance(r, BitmapRow) and r.kind == "cut":  # the printed cut line between --compact labels
            out.append(("✂ " + "┄" * cols)[:cols])  # (not --- rules or table rules: those are "divider")
        elif isinstance(r, TextRow):
            out += text_lines(r, cols, color)
        elif isinstance(r, BitmapRow) and r.text_rows:
            for tr in r.text_rows:
                inv = TextRow([type(c)(**{**c.__dict__, "invert": True}) for c in tr.cells], tr.scale, tr.align)
                ls = text_lines(inv, cols, color)
                out += [f"\x1b[7m{ln}\x1b[0m" if color else ln for ln in ls]
        elif isinstance(r, RawRow):
            out.append(f"[raw: {len(r.data)} bytes, not previewed]".center(cols))
        else:
            from .emulator import Emulator

            em = em or Emulator(profile)
            im = preview.row_image(r, profile, em)
            if im is not None:
                out += [ln.ljust(cols) for ln in braille(im, profile.cell)]
    return out


def boxed(body: list[str], cols: int, title: str, color: bool = False) -> str:
    dim, rst = ("\x1b[2m", "\x1b[0m") if color else ("", "")
    t = f" {title} "
    top = dim + "┌─" + t + "─" * max(0, cols - len(t) - 1) + "┐" + rst
    bot = dim + "└" + "─" * cols + "┘" + rst
    return "\n".join([top] + [f"{dim}│{rst}{ln}{dim}│{rst}" for ln in body] + [bot])


def render(rows, profile, title: str, color: bool = False) -> str:
    return boxed(lines(rows, profile, color), profile.columns, title, color)


def image_box(im: Image.Image, profile, title: str, color: bool = False) -> str:
    return boxed(braille(im, profile.cell), profile.columns, title, color)


__all__ = ["render", "image_box", "braille", "use_color", "BitmapRow", "QRRow"]
