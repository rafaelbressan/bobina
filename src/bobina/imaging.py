"""Raster objects: photos (R6 defaults), dividers, QR in raster mode."""

from __future__ import annotations

import functools
import io
import math

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

Image.MAX_IMAGE_PIXELS = 40_000_000  # far above any photo a 58/80 mm roll needs; refuses bombs early

DITHERS = {"floyd-steinberg": "fs", "fs": "fs", "atkinson": "atkinson", "bayer": "bayer", "threshold": "threshold"}


RASTER_FORMATS = ["PNG", "JPEG", "GIF", "BMP", "WEBP", "TIFF"]  # no EPS/PS: Pillow would run Ghostscript


def open_image(
    src: str, base_dir: str, *, width: int | None = None, page: int = 1, allow_net: bool = False, confine=None
):
    """Opens a photo, a PDF page or an SVG (rendered at `width` dots). Above MAX_IMAGE_PIXELS a raster is
    refused (Pillow alone only warns below 2x the limit). info['bobina.kind'|'bobina.host'] tell the caller
    what it got. Raises sources.ImageError."""
    import warnings

    from . import sources

    s = sources.load(src, base_dir, allow_net=allow_net, confine=confine)
    if s.kind == "pdf":
        im = sources.render_pdf(s.data, width or 384, page)
    elif s.kind == "svg":
        im = sources.render_svg(s.data, width or 384)
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            try:
                im = Image.open(io.BytesIO(s.data), formats=RASTER_FORMATS)
                if width and im.format == "JPEG":  # decode at 1/2, 1/4 or 1/8 when that still covers the paper
                    im.draft("L", (width, width))  # (square: any EXIF rotation keeps >= width)
                im.load()
            except Image.DecompressionBombWarning:
                raise sources.ImageError("I101", "image too large (decompression bomb guard)") from None
            except Exception as e:  # noqa: BLE001
                raise sources.ImageError(
                    "I101",
                    f"not a supported image format ({e.__class__.__name__})",
                    "supported: PNG, JPEG, GIF, BMP, WebP, TIFF, SVG, PDF; export other formats as PDF or PNG",
                ) from None
    im.info["bobina.kind"] = "vector" if s.kind in ("pdf", "svg") else "raster"
    im.info["bobina.host"] = s.host
    return im


def dither(im: Image.Image, kind: str) -> Image.Image:
    """'L' -> '1'. kind: fs | atkinson | bayer | threshold."""
    if kind == "fs":
        return im.convert("1")
    if kind == "threshold":
        return im.point(lambda p: 255 if p >= 128 else 0).convert("1", dither=Image.NONE)
    w, h = im.size
    px = list(im.tobytes())
    if kind == "bayer":
        B = [
            [0, 32, 8, 40, 2, 34, 10, 42],
            [48, 16, 56, 24, 50, 18, 58, 26],
            [12, 44, 4, 36, 14, 46, 6, 38],
            [60, 28, 52, 20, 62, 30, 54, 22],
            [3, 35, 11, 43, 1, 33, 9, 41],
            [51, 19, 59, 27, 49, 17, 57, 25],
            [15, 47, 7, 39, 13, 45, 5, 37],
            [63, 31, 55, 23, 61, 29, 53, 21],
        ]
        out = [0 if px[y * w + x] < (B[y % 8][x % 8] + 0.5) * 4 else 255 for y in range(h) for x in range(w)]
    else:  # atkinson: spreads 6/8 of the error -> lighter, keeps contrast
        buf = [float(v) for v in px]
        out = [255] * (w * h)
        for y in range(h):
            row = y * w
            for x in range(w):
                i = row + x
                old = buf[i]
                new = 0 if old < 128 else 255
                out[i] = new
                err = (old - new) / 8
                if err:
                    for dx, dy in ((1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (0, 2)):
                        xx, yy = x + dx, y + dy
                        if 0 <= xx < w and yy < h:
                            buf[yy * w + xx] += err
    o = Image.new("L", (w, h))
    o.putdata(out)
    return o.convert("1", dither=Image.NONE)


def photo(im: Image.Image, width: int, gamma: float, kind: str, brightness: float = 1.0) -> Image.Image:
    """Prepared like the R6 winners: autocontrast, gamma, unsharp, dither."""
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert("L")
    h = max(1, round(im.height * width / im.width))
    im = im.resize((width, h), Image.LANCZOS)
    if kind != "threshold":
        im = ImageOps.autocontrast(im, cutoff=1)
        if gamma != 1.0:
            lut = [round(255 * (i / 255) ** (1 / gamma)) for i in range(256)]
            im = im.point(lut)
        if brightness != 1.0:
            im = ImageEnhance.Brightness(im).enhance(brightness)
        im = im.filter(ImageFilter.UnsharpMask(radius=1.5, percent=80, threshold=2))
    return dither(im, kind)


def place(im: Image.Image, width: int, align: str = "center") -> Image.Image:
    """Pads a '1' image to the full paper width."""
    out = Image.new("1", (width, im.height), 1)
    x = {"left": 0, "right": width - im.width}.get(align, (width - im.width) // 2)
    out.paste(im, (max(0, x), 0))
    return out


@functools.lru_cache(maxsize=8)
def mark_line(width: int) -> Image.Image:
    """The printed cut/tear mark (--marks): 1 dot, 4 on / 4 off. Chosen on paper 08/11 among 11 shapes: the most
    discreet, and cutting or tearing on it leaves only faint dots on either piece. Cached: do not modify it."""
    row = (bytes([0x0F]) * (width // 8 + 1))[: (width + 7) // 8]  # mode '1': 0 bits are black
    return Image.frombytes("1", (width, 1), row)


def divider(width: int, style: str = "solid", thickness: int = 2, pad: int = 6) -> Image.Image:
    t = max(1, thickness)
    h = pad * 2 + (t * 3 if style == "double" else t * 3 if style == "wavy" else t)
    im = Image.new("1", (width, h), 1)
    d = ImageDraw.Draw(im)
    y = pad
    if style == "dashed" or style == "cut":
        x0 = 28 if style == "cut" else 0
        for x in range(x0, width, 12):
            d.rectangle((x, y, min(x + 7, width - 1), y + t - 1), fill=0)
    elif style == "dotted":
        step = max(6, t * 3)
        for x in range(0, width, step):
            d.rectangle((x, y, x + t - 1, y + t - 1), fill=0)
    elif style == "double":
        d.rectangle((0, y, width - 1, y + t - 1), fill=0)
        d.rectangle((0, y + 2 * t, width - 1, y + 3 * t - 1), fill=0)
    elif style == "wavy":
        amp, per = t, 16
        pts = [(x, y + amp + amp * math.sin(2 * math.pi * x / per)) for x in range(width)]
        d.line(pts, fill=0, width=t)
    else:
        d.rectangle((0, y, width - 1, y + t - 1), fill=0)
    if style == "cut":
        _scissors(d, 2, y + t // 2)
    return im


def _scissors(d, x, y):
    # two rings and crossing blades, 2-dot strokes
    d.ellipse((x, y - 9, x + 7, y - 2), outline=0, width=2)
    d.ellipse((x, y + 2, x + 7, y + 9), outline=0, width=2)
    d.line((x + 6, y - 4, x + 22, y + 4), fill=0, width=2)
    d.line((x + 6, y + 4, x + 22, y - 4), fill=0, width=2)


@functools.lru_cache(maxsize=256)
def qr_matrix(data: str, ecc: str) -> tuple:
    """Cached: layout, preview heights and drawing each need the matrix (3 encodings per label before)."""
    import segno

    q = segno.make(data, error=ecc.lower(), micro=False)
    return tuple(tuple(r) for r in q.matrix)


def qr_image(data: str, module: int, ecc: str, border: int = 0) -> Image.Image:
    m = qr_matrix(data, ecc)
    n = len(m) + 2 * border
    im = Image.new("1", (n * module, n * module), 1)
    d = ImageDraw.Draw(im)
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                X, Y = (x + border) * module, (y + border) * module
                d.rectangle((X, Y, X + module - 1, Y + module - 1), fill=0)
    return im


def matrix_image(m, module: int, border: int = 2) -> Image.Image:
    n_h, n_w = len(m) + 2 * border, len(m[0]) + 2 * border
    im = Image.new("1", (n_w * module, n_h * module), 1)
    d = ImageDraw.Draw(im)
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                X, Y = (x + border) * module, (y + border) * module
                d.rectangle((X, Y, X + module - 1, Y + module - 1), fill=0)
    return im


def datamatrix_image(data: str, module: int) -> Image.Image:
    from ppf.datamatrix import DataMatrix

    return matrix_image(DataMatrix(data).matrix, module)


def pdf417_image(data: str, module: int, ratio: int = 3, columns: int = 4) -> Image.Image:
    import pdf417gen

    codes = pdf417gen.encode(data, columns=columns, security_level=2)
    return pdf417gen.render_image(codes, scale=module, ratio=ratio, padding=4).convert("1", dither=Image.NONE)
