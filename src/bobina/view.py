"""Terminal preview. Native text rows are shown as text on the real 32-column grid; images,
QR codes and other raster rows as braille, where one character = 2x4 dots of 6x6 px, i.e. exactly
one native cell (12x24) — so text and images keep their true proportions side by side."""

from __future__ import annotations

import os
import sys
import unicodedata
from dataclasses import replace

from PIL import Image

from . import icons, preview
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


QUOTE_BAR = "│"  # the bar of a > quote (layout.QUOTE_BAR)
TEAR_MARK = " ⟶ "
TURNED_TABLE = " ↻ table printed turned, header on the right "  # the terminal shows its text standing
TURNED_COLUMNS = (" ↻ columns printed turned, top on the right ", " ↻ turned, top on the right ", " ↻ turned ",
                  "↻")  # over turned columns, standing: the longest mark that fits the label  # fmt: skip


def colors_off(env=None, flag: bool = False) -> str:
    """Why there must be no colours ("" when colours may be used): NO_COLOR, --no-color (flag), TERM=dumb. One rule
    for the previews and the chat screen."""
    env = os.environ if env is None else env
    if env.get("NO_COLOR"):
        return "NO_COLOR is set"
    if flag:
        return "--no-color"
    if env.get("TERM") == "dumb":
        return "TERM=dumb"
    return ""


def use_color(stream=sys.stdout) -> bool:
    return stream.isatty() and not colors_off()


def braille(im: Image.Image, cell=(12, 24), specks: bool = False) -> list[str]:
    """Mode '1' image -> braille lines, one char per native cell. specks: a line of ink too small for a dot (a
    dotted rule's 2x2 dots) as one dot in every other cell, where it is: lighter than a dashed one, never blank."""
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
                if specks and (c % 2 or x or code):
                    continue
                if px[c * 2 + x, r * 4 + y] < (255 if specks else 190):  # >= ~25% ink in the 6x6 block
                    code |= bit
            line.append(chr(0x2800 + code) if code else " ")
        out.append("".join(line))
    return out


def _sgr(cell, color: bool, dark: bool = False) -> tuple[str, str]:
    """A cell's escapes. dark: it is drawn in a reversed area (an inverted box), so a reversed cell shows plain and
    every reset goes back to reversed."""
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
        codes.append("27" if dark else "7")
    if cell.strike:
        codes.append("9")
    return (f"\x1b[{';'.join(codes)}m", BASE[dark]) if codes else ("", "")


def text_lines(row: TextRow, cols: int, color: bool, dark: bool = False) -> list[str]:
    """A text row as terminal lines: a letter at N× width takes N columns, at N× height N lines. A row whose spans
    have their own size (Um [BRS]{size=2x} dois) shows every letter on its last line, the baseline they share on
    paper, under the blank lines its taller letters take. dark: inside an inverted box (the colour view)."""
    parts, width = [], 0
    cells = list(reversed(row.cells)) if row.upside_down else row.cells
    align = {"left": "right", "right": "left"}.get(row.align, row.align) if row.upside_down else row.align
    for c in cells:
        sw = row.scale_of(c)[0]
        on, off = _sgr(c, color, dark)
        ch = icons.shown(c.ch)  # the terminal cannot draw an icon: a mark in its two columns
        glyph = ch + (" " if c.wide and unicodedata.east_asian_width(ch) not in ("W", "F") else "")
        parts.append(on + glyph + off + " " * (sw - 1) * (2 if c.wide else 1))
        width += (2 if c.wide else 1) * sw
    pad = {"center": (cols - width) // 2, "right": cols - width}.get(align, 0)
    line = " " * max(0, pad) + "".join(parts) + " " * max(0, cols - width - max(0, pad))
    if not row.mixed():
        return [line] + [" " * cols] * (row.height() - 1)
    bars = "".join(c.ch if c.ch == QUOTE_BAR else " " * ((2 if c.wide else 1) * row.scale_of(c)[0]) for c in cells)
    above = (" " * max(0, pad) + bars).ljust(cols)  # a quote's bars go up the taller line, as on paper
    return [above] * (row.height() - 1) + [line]


def width(rows, profile) -> int:
    """The view's columns: the paper's, or more when a table or text drawn in a smaller font needs more character
    columns than the paper has (BitmapRow.wide_view): the frame grows to its widest line, so every letter shows."""
    wide = [tr.columns() for r in rows if isinstance(r, BitmapRow) and r.wide_view for tr in r.text_rows or []]
    wide += [r.box.left + 2 + _box_view(r.box, profile)[2] for r in rows if isinstance(r, BitmapRow) and r.box]
    wide += [_columns_view(r.columns, profile)[1] for r in rows if isinstance(r, BitmapRow) and r.columns]
    return max([profile.columns, *wide])


def fit(row: TextRow, cols: int) -> TextRow:
    """A line of drawn text in the frame's `cols` columns: as it is, or cut with "…" (text in a smaller font widens
    the frame instead: BitmapRow.wide_view)."""
    if row.width() <= cols:
        return row
    kept, used = [], 0
    for c in row.cells:
        w = (2 if c.wide else 1) * row.scale_of(c)[0]
        if used + w > cols - row.scale[0]:
            break
        kept.append(c)
        used += w
    last = kept[-1] if kept else row.cells[0]
    dots = type(last)(**{**last.__dict__, "ch": "…", "wide": False, "scale": None})  # at the row's size: as reserved
    return replace(row, cells=[*kept, dots])


def lines(rows, profile, color: bool = False, max_feed_lines: int = 1, frame: int | None = None,
          dark: bool = False) -> list[str]:  # fmt: skip
    """The rows as terminal lines, each `frame` columns wide (width()); the paper's text, rules and images keep the
    paper's columns. Text drawn as an image reads as text, reversed only where the paper is white on black (a band;
    inverted words are reversed by their own cells). A table in a raster font is a map of the paper when it fits
    the paper's columns (Layout.paper_map), else its own wider grid, every cell whole (wide_view). dark: inside an
    inverted box, already reversed (_sgr)."""
    cols = profile.columns
    frame = frame or width(rows, profile)
    more = " " * (frame - cols)  # past the paper's columns, in a frame widened for a table in a smaller font
    em = None
    out: list[str] = []
    for r in rows:
        if isinstance(r, FeedRow) and r.mark == "tear":
            out.append(TEAR_MARK.center(frame, "┄"))  # the paper goes to the tear bar here (decided 08/11:
        elif isinstance(r, FeedRow) and r.mark == "cut":  # symbols only, no words); a --compact cut, printed or not
            out.append(("✂ " + "┄" * frame)[:frame])
        elif isinstance(r, FeedRow):
            n = min(max_feed_lines, r.dots // profile.cell[1])
            out += [" " * frame] * n
        elif isinstance(r, BitmapRow) and r.kind == "cut":  # the printed cut line between --compact labels
            out.append(("✂ " + "┄" * frame)[:frame])  # (not --- rules or table rules: those are "divider")
        elif isinstance(r, TextRow):
            out += [ln + more for ln in text_lines(r, cols, color, dark)]
        elif isinstance(r, BitmapRow) and r.box is not None:
            used = r.box.left + 2 + _box_view(r.box, profile)[2]
            out += [ln + " " * max(0, frame - used) for ln in box_lines(r.box, profile, color, dark)]
        elif isinstance(r, BitmapRow) and r.columns is not None:
            used = _columns_view(r.columns, profile)[1]
            out += [ln + " " * max(0, frame - used) for ln in columns_lines(r.columns, profile, color, dark)]
        elif isinstance(r, BitmapRow) and r.kind == "table" and r.text_rows:  # a turned table: its text, standing
            out.append(TURNED_TABLE.center(frame, "┄")[:frame])
            for tr in r.text_rows:
                standing = TextRow(_within(tr.cells, cols // tr.scale[0]), tr.scale, "left")  # cut before drawing
                out += [ln + more for ln in text_lines(standing, cols, color, dark)]
        elif isinstance(r, BitmapRow) and r.text_rows:
            trs = r.text_rows if r.wide_view else [fit(tr, frame) for tr in r.text_rows]  # wide_view: never cut
            room = max([cols, *(tr.width() for tr in trs)])  # a smaller font's paper line: wider
            for tr in trs:
                if r.kind == "band":  # white on black on paper, from edge to edge
                    tr = TextRow([type(c)(**{**c.__dict__, "invert": True}) for c in tr.cells], tr.scale, tr.align)
                ls = [ln + " " * (frame - room) for ln in text_lines(tr, room, color, dark)]
                out += [f"{FLIP[dark]}{ln}{BASE[dark]}" if color and r.kind == "band" else ln for ln in ls]
        elif isinstance(r, RawRow):
            out.append(f"[raw: {len(r.data)} bytes, not previewed]".center(cols) + more)
        else:
            from .emulator import Emulator

            em = em or Emulator(profile)
            im = preview.row_image(r, profile, em)
            if im is not None:
                ls = braille(im, profile.cell)
                if getattr(r, "kind", "") == "divider" and not "".join(ls).strip():  # a dotted rule: dots too small
                    ls = braille(im, profile.cell, specks=True)
                ls = [ln.ljust(frame) for ln in ls]
                out += _kept(ls, r.keep, profile.cell) if color and dark and getattr(r, "keep", ()) else ls
    return out


def _within(cells: list, cols: int) -> list:
    """The cells that fit in `cols` columns (a wide one takes 2)."""
    out, used = [], 0
    for c in cells:
        used += 2 if c.wide else 1
        if used > cols:
            break
        out.append(c)
    return out


def _kept(lines: list[str], rects, cell) -> list[str]:
    """Braille lines of a row drawn in an inverted box, plain again over its codes' white tiles (BitmapRow.keep),
    as on paper: the rest of the line stays reversed."""
    cw, ch = cell
    out = []
    for i, ln in enumerate(lines):
        spans = sorted(
            {(round(x0 / cw), round(x1 / cw)) for x0, y0, x1, y1 in rects if y0 < (i + 1) * ch and y1 > i * ch}
        )
        for a, b in reversed(spans):
            ln = ln[:a] + FLIP[True] + ln[a:b] + BASE[True] + ln[b:]
        out.append(ln)
    return out


FRAMES = {"solid": "─│┌┐└┘", "dashed": "╌╎┌┐└┘", "dotted": "┈┊┌┐└┘", "double": "═║╔╗╚╝"}  # a ::: box's line
DARK_FRAME = "━┃┏┓┗┛"  # a ::: {.box .invert}: black to its edges (in colour, reversed too)
FLIP = {False: "\x1b[7m", True: "\x1b[27m"}  # reversed, or plain again inside a reversed area
BASE = {False: "\x1b[0m", True: "\x1b[0;7m"}  # a reset, outside or inside a reversed area


def _box_view(b, profile):
    """A box's content as the views draw it: (the profile at its inner width, the columns its lines take, the
    columns between its │ and │). A table in a smaller font inside it widens both, as it widens the paper's frame."""
    from dataclasses import replace

    sub = replace(profile, width_dots=b.inner)
    inner = width(b.rows, sub)
    return sub, inner, b.cols - 2 + inner - sub.columns


def box_lines(b, profile, color: bool = False, dark: bool = False) -> list[str]:
    """A ::: box where it is on the paper: ┌─ TITLE ─┐, what it holds between │ and │ (its own rows, drawn by
    lines() at the box's inner width: a box in a box too), └──┘; a turned one standing, under a ↻ mark. Each line
    is b.left + 2 + the room _box_view gives columns wide. An inverted box: heavy lines and, in colour, reversed from
    side to side (white on black, as a band of text is), what is reversed in it plain again (cell by cell)."""
    from .layout import is_wide

    h, v, tl, tr, bl, br = DARK_FRAME if b.invert else FRAMES.get(b.style, FRAMES["solid"])
    sub, inner, room = _box_view(b, profile)
    left = (b.cols - 2 - sub.columns) // 2  # a thick frame takes two letters each side: the content in the middle
    lead = b.lead + " " * (b.left - len(b.lead))
    title = f" {b.title} " if b.title else ""
    run = room - sum(2 if is_wide(c) else 1 for c in title)
    marks = (f" ↻ box printed turned {b.turned:g}° ", f" ↻ {b.turned:g}° ", "↻")  # the longest that fits the box
    mark = next((m for m in marks if len(m) <= room + 2), "↻")
    out = [lead + mark.center(room + 2, "┄")] if b.turned else []
    cut = lead + v + "┄" * room + v  # the side of a piece of a box cut across turned labels
    out.append(cut if b.open_top else lead + tl + h * (run // 2) + title + h * (run - run // 2) + tr)
    inside = dark != b.invert
    for ln in lines(b.rows, sub, color, max_feed_lines=0, frame=inner, dark=inside):
        out.append(lead + v + " " * left + ln + " " * (room - left - inner) + v)
    out.append(cut if b.open_bottom else lead + bl + h * room + br)
    if not (b.invert and color):
        return out
    k, skip = len(lead), 1 if b.turned else 0  # the ↻ mark above a turned box stays as it is
    return [*out[:skip], *(ln[:k] + FLIP[dark] + ln[k:] + BASE[dark] for ln in out[skip:])]


def _columns_view(cv, profile):
    """Where each column of a row is drawn: ([(its profile at its width, the column it starts at, its width in the
    view)], the columns the row takes). A column whose text needs more letters than its paper columns (a table or a
    paragraph in a smaller font) is drawn wider, the columns after it moved right: the frame widens, nothing is cut."""
    from dataclasses import replace

    out, shift = [], 0
    for c in cv.columns:
        sub = replace(profile, width_dots=c.inner)
        drawn = [tr.width() for r in c.rows if isinstance(r, BitmapRow) and r.text_rows
                 and r.kind != "table" for tr in r.text_rows]  # fmt: skip
        w = max([width(c.rows, sub), *drawn])
        out.append((sub, c.left + shift, w))
        shift += w - sub.columns
    return out, max([0, *(x + w for _, x, w in out)])


def columns_lines(cv, profile, color: bool = False, dark: bool = False) -> list[str]:
    """A row of :::: {.columns} as a map of the paper: each column's own rows (drawn by lines() at its width: a box
    or columns in it too) at its place on the paper, side by side, moved down as valign= placed it. A label of
    turned columns is drawn standing, as it is read, under a ↻ mark (as a turned table is)."""
    placed, used = _columns_view(cv, profile)
    drawn = [lines(c.rows, sub, color, max_feed_lines=0, frame=w, dark=dark)
             for c, (sub, _, w) in zip(cv.columns, placed, strict=True)]  # fmt: skip
    tall = max([cv.lines, *(len(ls) for ls in drawn)])  # valign= in the view's own lines, as on paper among dots
    cols = []
    for c, (_, x, w), ls in zip(cv.columns, placed, drawn, strict=True):
        free = tall - len(ls)
        down = {"middle": free // 2, "bottom": free, "top": 0}.get(c.valign, round(c.top / profile.cell[1]))
        cols.append((x, w, [" " * w] * down + ls))
    out = []
    for y in range(max(len(ls) for _, _, ls in cols)):
        line, at = cv.lead, len(cv.lead)
        for x, w, ls in cols:
            line += " " * (x - at) + (ls[y] if y < len(ls) else " " * w)
            at = x + w
        out.append(line + " " * (used - at))
    if cv.turned:
        mark = next(m for m in TURNED_COLUMNS if len(m) <= used or m == "↻")
        out.insert(0, mark.center(used, "┄"))
    return out


def boxed(body: list[str], cols: int, title: str, color: bool = False) -> str:
    dim, rst = ("\x1b[2m", "\x1b[0m") if color else ("", "")
    t = f" {title} "
    top = dim + "┌─" + t + "─" * max(0, cols - len(t) - 1) + "┐" + rst
    bot = dim + "└" + "─" * cols + "┘" + rst
    return "\n".join([top] + [f"{dim}│{rst}{ln}{dim}│{rst}" for ln in body] + [bot])


def render(rows, profile, title: str, color: bool = False) -> str:
    frame = width(rows, profile)
    return boxed(lines(rows, profile, color, frame=frame), frame, title, color)


def image_box(im: Image.Image, profile, title: str, color: bool = False) -> str:
    return boxed(braille(im, profile.cell), profile.columns, title, color)


__all__ = ["render", "image_box", "braille", "use_color", "BitmapRow", "QRRow"]
