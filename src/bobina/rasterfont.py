"""Raster text: blocks whose font is not the printer's own (front matter `fonts:` roles and aliases).

Fonts resolve to bundled files first (same result on every machine), then to system fonts via
fontconfig. Sizes are physical (named sizes -> mm -> dots for the profile's dpi). Quality is judged
from the font test registry (docs/printers/mtp-ii-58.md, tests F1/F2/R5) or, for untested fonts,
by measuring the stem."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from . import paths

SIZES_MM = {"small": 1.5, "normal": 2.5, "large": 3.5, "title": 5.0, "huge": 8.0}

# family -> (regular, bold) bundled files
BUNDLED = {
    "atkinson hyperlegible": ("AtkinsonHyperlegible-Regular.ttf", "AtkinsonHyperlegible-Bold.ttf"),
    "ibm plex mono": ("IBMPlexMono-Regular.ttf", "IBMPlexMono-Bold.ttf"),
    "barlow condensed": ("BarlowCondensed-Regular.ttf", "BarlowCondensed-SemiBold.ttf"),
    "terminus": ("TerminusTTF-4.49.3.ttf", "TerminusTTF-Bold-4.49.3.ttf"),
    "spleen": ("spleen-12x24.otf", "spleen-12x24.otf"),
    "dejavu sans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
}
# tested minimum px at 203 dpi (F1, F2, R5): below this, a nudge with the evidence
TESTED_MIN = {
    "terminus": (12, "R5-04"),
    "spleen": (12, "F2"),
    "atkinson hyperlegible": (14, "F2"),
    "ibm plex mono": (16, "F1"),
    "barlow condensed": (20, "F2"),
    "z003": (28, "F1-16"),
    "dejavu sans": (16, "F1"),
    "liberation sans narrow": (20, "F2"),
    "charter": (20, "F2"),
}
DEFAULT_ROLES = {"body": "native", "title": "native", "code": "IBM Plex Mono"}


@dataclass
class FontRef:
    family: str
    path: str
    bundled: bool


@lru_cache(maxsize=64)  # each unknown family runs fc-match once; bounded for long-running callers
def resolve(family: str, bold: bool = False) -> FontRef | None:
    key = family.strip().lower()
    if key in BUNDLED:
        f = BUNDLED[key][1 if bold else 0]
        return FontRef(family, str(paths.fonts_dir() / f), True)
    if not shutil.which("fc-match"):
        return None
    pattern = f"{family}:style=Bold" if bold else family
    try:
        r = subprocess.run(["fc-match", "-f", "%{family}\n%{file}", pattern], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = r.stdout.splitlines()
    if len(lines) < 2:
        return None
    fams = [x.strip().lower() for x in lines[0].split(",")]
    if key not in fams and not any(key in x for x in fams):
        return None  # fontconfig substituted another font: treat as missing
    return FontRef(family, lines[1], False)


@lru_cache(maxsize=64)  # a document cannot grow memory with 1000 sizes (sizes are clamped too, px_for)
def load(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


PX_MIN, PX_MAX = 6, 400  # 400 px = 50 mm: taller than the paper is wide


def px_for(size: str | None, profile, default_px: int = 20, nudges=None, line: int | None = None) -> int:
    px = _px(size, profile, default_px)
    if PX_MIN <= px <= PX_MAX:
        return px
    clamped = min(max(px, PX_MIN), PX_MAX)
    if nudges is not None:
        nudges.add("F205", f"font size {size} is out of range: using {clamped}px", line, f"use {PX_MIN} to {PX_MAX}px")
    return clamped


def _px(size, profile, default_px: int) -> int:
    if not size:
        return default_px
    s = str(size)
    if s in SIZES_MM:
        return profile.mm_to_dots(SIZES_MM[s])
    if s.endswith("px") and s[:-2].replace(".", "").isdigit():
        return int(float(s[:-2]))
    if s.endswith("mm") and s[:-2].replace(".", "").isdigit():
        return profile.mm_to_dots(float(s[:-2]))
    if s.isdigit():
        return int(s)
    return default_px


def stem_width(path: str, size: int) -> int:
    """Measured thickness (dots) of the vertical stem of 'l' at this size."""
    f = load(path, size)
    im = Image.new("L", (size * 2, size * 2), 255)
    ImageDraw.Draw(im).text((size // 2, size // 4), "l", font=f, fill=0)
    bw = im.point(lambda v: 0 if v < 128 else 255)
    box = Image.eval(bw, lambda v: 255 - v).getbbox()
    if not box:
        return 0
    y = (box[1] + box[3]) // 2
    row = [bw.getpixel((x, y)) for x in range(box[0], box[2])]
    best = run = 0
    for v in row:
        run = run + 1 if v == 0 else 0
        best = max(best, run)
    return best


def user_registry() -> dict:
    """Fonts the user tested and marked: ~/.config/bobina/fonts.toml  {family: {min_px, note}}."""
    import tomllib

    p = paths.config_dir() / "fonts.toml"
    try:
        return {k.lower(): v for k, v in tomllib.loads(p.read_text()).items() if isinstance(v, dict)}
    except (OSError, ValueError):
        return {}


def mark(family: str, min_px: int, note: str = ""):
    reg = user_registry()
    reg[family.lower()] = {"family": family, "min_px": int(min_px), "note": note}
    lines = []
    for k, v in reg.items():
        lines.append(f'["{v.get("family", k)}"]')
        lines.append(f"min_px = {int(v['min_px'])}")
        if v.get("note"):
            lines.append('note = "' + str(v["note"]).replace('"', "'") + '"')
        lines.append("")
    p = paths.config_dir() / "fonts.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines))


def judge(family: str, ref: FontRef, px: int, bold: bool, nudges, line: int):
    key = family.lower()
    user = user_registry().get(key)
    if user:
        if px < int(user["min_px"]):
            nudges.add(
                "F201",
                f'font "{family}" at {px}px is below the minimum you marked',
                line,
                f"use ≥ {user['min_px']}px",
                "fonts.toml",
            )
        return
    if key in TESTED_MIN:
        lo, ev = TESTED_MIN[key]
        if px < lo:
            nudges.add("F201", f'font "{family}" at {px}px is below its tested minimum', line, f"use ≥ {lo}px", ev)
        return
    w = stem_width(ref.path, px)
    if w < 2:
        nudges.add(
            "F202",
            f'untested font "{family}" at {px}px: stems {w} dot(s) thick print broken',
            line,
            "use a larger size or a bold weight; or test it: bobina fonts test",
            "R4-01",
        )


@lru_cache(maxsize=64)
def cmap(path: str) -> frozenset[int]:
    from fontTools.ttLib import TTFont

    try:
        return frozenset(TTFont(path, lazy=True, fontNumber=0).getBestCmap())
    except Exception:  # noqa: BLE001 - Type1 and odd formats: assume full coverage
        return frozenset()


@dataclass
class Tok:
    text: str
    path: str
    px: int
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    invert: bool = False
    space: bool = False
    brk: bool = False
    tracking: int = 0

    @property
    def font(self):
        return load(self.path, self.px)

    def width(self) -> int:
        w = self.font.getlength(self.text) + self.tracking * len(self.text)
        return int(round(w + (self.px * 0.1 if self.italic and not self.space else 0)))


def draw_tok(t: Tok, ascent: int, line_h: int) -> Image.Image:
    w = max(1, t.width())
    im = Image.new("L", (w, line_h), 255)
    d = ImageDraw.Draw(im)
    if t.invert:
        d.rectangle((0, 0, w - 1, line_h - 1), fill=0)
    fa, _ = t.font.getmetrics()
    ink = 255 if t.invert else 0
    if not t.space:
        pieces = [(0.0, t.text)]
        if t.tracking:  # letter spacing: glyph by glyph (kerning is dropped, as it would be anyway)
            pieces, x = [], 0.0
            for ch in t.text:
                pieces.append((x, ch))
                x += t.font.getlength(ch) + t.tracking
        for x, txt in pieces:
            d.text((x, ascent - fa), txt, font=t.font, fill=ink)
            if t.bold and "bold" not in t.path.lower():  # synthetic bold for fonts without a bold file
                d.text((x + 1, ascent - fa), txt, font=t.font, fill=ink)
    if t.italic:
        im = im.transform(
            im.size,
            Image.AFFINE,
            (1, 0.2, -0.2 * ascent, 0, 1, 0),
            resample=Image.BICUBIC,
            fillcolor=0 if t.invert else 255,
        )
    th = max(2, t.px // 12)
    if t.underline:
        d = ImageDraw.Draw(im)
        d.rectangle((0, ascent + 2, w - 1, ascent + 1 + th), fill=ink)
    if t.strike:
        d = ImageDraw.Draw(im)
        y = ascent - int(t.px * 0.3)
        d.rectangle((0, y, w - 1, y + th - 1), fill=ink)
    return im


def checkbox(px: int, done: bool) -> Image.Image:
    s = max(10, int(px * 0.75))
    im = Image.new("L", (s + 6, s), 255)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, s - 1, s - 1), outline=0, width=2)
    if done:
        d.line((3, s // 2, s // 2 - 1, s - 4, s - 3, 3), fill=0, width=max(2, s // 6))
    return im


def layout_lines(toks: list[Tok], width: int, hang: int) -> list[list[Tok]]:
    lines, cur, cw, avail = [], [], 0, width
    for t in toks:
        if t.brk:
            lines.append(cur)
            cur, cw, avail = [], 0, width - hang
            continue
        tw = t.width()
        if t.space:
            if cur:
                cur.append(t)
                cw += tw
            continue
        if cur and cw + tw > avail:
            while cur and cur[-1].space:
                cw -= cur.pop().width()
            lines.append(cur)
            cur, cw, avail = [], 0, width - hang
        cur.append(t)
        cw += tw
    while cur and cur[-1].space:
        cur.pop()
    lines.append(cur)
    return lines


def render_block(
    toks: list[Tok], width: int, align: str, leading: int, prefix: Image.Image | None, indent: int = 0
) -> tuple[Image.Image, list[str]]:
    pw = prefix.width if prefix else 0
    lines = layout_lines(toks, width - indent - pw, 0)
    imgs, texts = [], []
    for i, ln in enumerate(lines):
        ascent = max([t.font.getmetrics()[0] for t in ln] or [toks[0].font.getmetrics()[0] if toks else 16])
        descent = max([t.font.getmetrics()[1] for t in ln] or [4])
        h = ascent + descent + leading
        row = Image.new("L", (width, h), 255)
        x0 = indent + pw
        avail = width - x0
        parts = [draw_tok(t, ascent, ascent + descent) for t in ln]
        used = sum(p.width for p in parts)
        gaps = [k for k, t in enumerate(ln) if t.space]
        extra = {}
        if align == "justify" and i < len(lines) - 1 and gaps:
            slack = avail - used
            extra = {g: slack // len(gaps) + (1 if n < slack % len(gaps) else 0) for n, g in enumerate(gaps)}
        x = {"center": x0 + (avail - used) // 2, "right": x0 + avail - used}.get(align, x0)
        if i == 0 and prefix is not None:
            row.paste(prefix, (indent, max(0, (ascent + descent - prefix.height) // 2 + 1)))
        for k, p in enumerate(parts):
            row.paste(p, (int(x), 0))
            x += p.width + extra.get(k, 0)
        imgs.append(row)
        texts.append("".join(t.text for t in ln))
    out = Image.new("L", (width, sum(i.height for i in imgs)), 255)
    y = 0
    for im in imgs:
        out.paste(im, (0, y))
        y += im.height
    return out.point(lambda v: 0 if v < 128 else 255).convert("1", dither=Image.NONE), texts
