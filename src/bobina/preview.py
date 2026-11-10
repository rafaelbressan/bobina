"""Rows -> the exact bitmap the printer receives (mode '1', paper width)."""

from __future__ import annotations

from PIL import Image

from . import imaging
from .emulator import Emulator
from .rows import BarcodeRow, BitmapRow, FeedRow, QRRow, TextRow


def row_image(r, profile, em: Emulator):
    W = profile.width_dots
    if isinstance(r, FeedRow):
        if not r.dots:
            return None
        im = Image.new("1", (W, r.dots), 1)
        if r.tear_at is not None:
            im.paste(imaging.mark_line(W), (0, min(r.tear_at, r.dots - 1)))
        return im
    if isinstance(r, TextRow):
        return em.render_row(r, W)
    if isinstance(r, BitmapRow):
        return r.image
    if isinstance(r, QRRow):
        return imaging.place(imaging.qr_image(r.data, r.module, r.ecc), W, r.align)
    if isinstance(r, BarcodeRow):
        return imaging.place(barcode_image(r, em), W, r.align)
    return None


def barcode_image(r, em):
    from . import codes

    try:
        return codes.image(r.kind, r.data, r.module, r.height, r.text, em)
    except ValueError:  # no encoder: placeholder box of the configured height
        from PIL import ImageDraw

        im = Image.new("1", (min(300, 24 * len(r.data)), r.height), 1)
        ImageDraw.Draw(im).rectangle((0, 0, im.width - 1, im.height - 1), outline=0, width=2)
        return im


def render(rows, profile, em: Emulator | None = None) -> Image.Image:
    em = em or Emulator(profile)
    parts = [im for im in (row_image(r, profile, em) for r in rows) if im is not None]
    h = sum(p.height for p in parts)
    out = Image.new("1", (profile.width_dots, max(1, h)), 1)
    y = 0
    for p in parts:
        out.paste(p, (0, y))
        y += p.height
    return out


MAX_PAGE_DOTS = 20000  # ~2.5 m at 203 dpi: taller PNGs do not open in most image viewers


def split_pages(rows, profile, em: Emulator | None = None, max_h: int | None = None) -> list[list]:
    """The rows grouped into pages of at most max_h dots, cut between rows (a single taller row gets its own
    page). Only heights are computed here: nothing is drawn."""
    em = em or Emulator(profile)
    max_h = max_h or MAX_PAGE_DOTS
    pages, page, h = [], [], 0
    for r in rows:
        rh = heights([r], profile, em)
        if page and h + rh > max_h:
            pages.append(page)
            page, h = [], 0
        page.append(r)
        h += rh
    pages.append(page)
    return pages


def heights(rows, profile, em: Emulator | None = None) -> int:
    em = em or Emulator(profile)
    total = 0
    for r in rows:
        if isinstance(r, FeedRow):
            total += r.dots
        elif isinstance(r, TextRow):
            total += em.row_height(r)
        elif isinstance(r, BitmapRow):
            total += r.image.height
        elif isinstance(r, QRRow):
            total += len(imaging.qr_matrix(r.data, r.ecc)) * r.module
        elif isinstance(r, BarcodeRow):
            total += barcode_image(r, em).height
    return total
