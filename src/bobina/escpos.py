"""Rows -> ESC/POS bytes."""

from __future__ import annotations

from .emulator import Emulator
from .imaging import mark_line
from .profile import code_page_for, plain_ascii
from .rows import BarcodeRow, BitmapRow, FeedRow, QRRow, RawRow, TextRow

ESC, GS = b"\x1b", b"\x1d"
ALIGN = {"left": 0, "center": 1, "right": 2}


def feed(dots: int) -> bytes:
    out = b""
    while dots > 0:
        n = min(255, dots)
        out += ESC + b"J" + bytes([n])
        dots -= n
    return out


def raster(im, band: int = 64) -> bytes:
    """Mode '1' image (width multiple of 8) -> GS v 0 bands."""
    w, h = im.size
    wb = (w + 7) // 8
    raw = bytes(b ^ 0xFF for b in im.tobytes())  # PIL: 1 = white; printer: 1 = black
    out = bytearray(ESC + b"a\x00")
    for y in range(0, h, band):
        n = min(band, h - y)
        out += GS + b"v0\x00" + bytes([wb & 0xFF, wb >> 8, n & 0xFF, n >> 8]) + raw[y * wb : (y + n) * wb]
    return bytes(out)


def cut(profile) -> bytes:
    """GS V 0 (full) or 1 (partial), function A: cut where the paper is. The final feed has already moved the end of
    the label past the blade; function B (65/66) would feed again first. ⚠ not tested on paper (features "cutter")."""
    kind = profile.get("cutter", "none")
    return GS + b"V" + bytes([0 if kind == "full" else 1]) if kind in ("full", "partial") else b""


def blank_rows(width_dots: int, dots: int, band: int = 64) -> bytes:
    """Paper feed as white GS v 0 bands: printers that ignore ESC J after an image still print these."""
    wb = (width_dots + 7) // 8
    out = bytearray(ESC + b"a\x00")
    for y in range(0, dots, band):
        n = min(band, dots - y)
        out += GS + b"v0\x00" + bytes([wb & 0xFF, wb >> 8, n & 0xFF, n >> 8]) + bytes(wb * n)
    return bytes(out)


def qr(data: str, module: int, ecc: str) -> bytes:
    def k(p: bytes) -> bytes:
        return GS + b"(k" + bytes([len(p) & 0xFF, len(p) >> 8]) + p

    e = {"L": 48, "M": 49, "Q": 50, "H": 51}[ecc]
    d = data.encode("utf-8")
    return k(b"1A2\x00") + k(b"1C" + bytes([module])) + k(b"1E" + bytes([e])) + k(b"1P0" + d) + k(b"1Q0")


def text_row(row: TextRow, em: Emulator) -> bytes:
    sw, sh = row.scale
    out = bytearray()
    if row.upside_down:
        out += ESC + b"{\x01"
    out += ESC + b"3" + bytes([em.row_height(row)])
    out += ESC + b"a" + bytes([ALIGN.get(row.align, 0)])
    out += GS + b"!" + bytes([((sw - 1) << 4) | (sh - 1)])
    if row.tracking:
        out += ESC + b" " + bytes([min(255, row.tracking)])
    state = (False, False, False)
    pages = em.p.codepages() if em.p.get("encoding") == "codepage" else ()
    page = None
    for c in row.cells:
        st = (c.bold, c.underline, c.invert)
        if st != state:
            if st[0] != state[0]:
                out += ESC + b"E" + bytes([st[0]])
            if st[1] != state[1]:
                out += ESC + b"-" + bytes([st[1]])
            if st[2] != state[2]:
                out += GS + b"B" + bytes([st[2]])
            state = st
        if pages and not plain_ascii(c.ch):  # ⚠ not tested on paper: features.py "codepage"
            found = code_page_for(c.ch, pages) or (pages[0][0], pages[0][1])
            if found != page:
                out += ESC + b"t" + bytes([found[1]])
                page = found
            out += c.ch.encode(page[0], "replace")
        else:
            out += c.ch.encode("ascii") if pages else c.ch.encode("utf-8")
    out += b"\n"
    out += GS + b"!\x00" + ESC + b"E\x00" + ESC + b"-\x00" + GS + b"B\x00" + ESC + b"a\x00"
    if row.tracking:
        out += ESC + b" \x00"
    if row.upside_down:
        out += ESC + b"{\x00"
    return bytes(out)


def encode(rows, profile, em: Emulator | None = None) -> bytes:
    em = em or Emulator(profile)
    band = int(profile.get("transport.band_rows", 64))
    # safe by default (decided 08/11): a profile or a calibrated printer turns it off when ESC J works after images
    blank_after_raster = bool(profile.get("escpos.blank_rows_after_raster", True))
    after_raster = False  # the last thing printed was a graphic (image, raster text, QR, barcode)

    def move(dots: int) -> bytes:
        """Paper feed. Right after an image some printers ignore ESC J (the MTP-II, 08/11): there, blank raster rows,
        which they do print."""
        if dots <= 0:
            return b""
        if blank_after_raster and after_raster:
            return blank_rows(profile.width_dots, dots, band)
        return feed(dots)

    out = bytearray(ESC + b"@")
    for r in rows:
        if isinstance(r, FeedRow) and r.tear_at is not None and r.dots:
            out += move(r.tear_at) + raster(mark_line(profile.width_dots), band)
            after_raster = True
            out += move(r.dots - r.tear_at - 1)
            out += cut(profile) if r.mark == "tear" else b""
            continue
        if isinstance(r, FeedRow):
            out += move(r.dots)
            out += cut(profile) if r.mark == "tear" else b""
            continue
        # QR and barcodes are graphics too, and raw bytes may hold an image: treated as images (untested on paper)
        after_raster = (
            isinstance(r, (BitmapRow, QRRow, BarcodeRow))
            or (isinstance(r, TextRow) and not r.native)
            or (isinstance(r, RawRow) and GS + b"v0" in r.data)
        )
        if isinstance(r, TextRow):
            out += text_row(r, em) if r.native else raster(em.render_row(r, profile.width_dots), band)
        elif isinstance(r, BitmapRow):
            out += raster(r.image, band)
        elif isinstance(r, QRRow):
            out += ESC + b"a" + bytes([ALIGN.get(r.align, 1)]) + qr(r.data, r.module, r.ecc) + ESC + b"a\x00"
        elif isinstance(r, BarcodeRow):
            from . import codes

            out += (
                ESC + b"a" + bytes([ALIGN.get(r.align, 1)]) + codes.native(r.kind, r.data, r.module, r.height, r.text)
            )
            out += ESC + b"a\x00"
        elif isinstance(r, RawRow):
            out += r.data
    return bytes(out)
