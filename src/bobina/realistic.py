"""Realistic preview: the exact bitmap as thermal paper shows it (ink spread, paper tone, faded start).

Parameters live in the profile under [preview.realistic]. Until they are fitted from photographed
calibration tickets (R6 ramps) the profile says calibrated = false and the preview is
an estimate."""

from __future__ import annotations

from PIL import Image, ImageFilter

DEFAULTS = {
    "spread_px": 0.6,
    "gain": 1.25,
    "ink": [38, 36, 42],
    "paper": [247, 245, 239],
    "fade_dots": 0,
    "fade_strength": 0.0,
    "scale": 2,
}


def render(bw: Image.Image, profile) -> Image.Image:
    p = {**DEFAULTS, **(profile.get("preview.realistic", {}) or {})}
    s = int(p["scale"])
    dens = Image.eval(bw.convert("L"), lambda v: 255 - v)  # 255 = dot
    dens = dens.resize((bw.width * s, bw.height * s), Image.NEAREST)
    if p["spread_px"]:
        dens = dens.filter(ImageFilter.GaussianBlur(p["spread_px"] * s))
    g = float(p["gain"])
    dens = dens.point(lambda v: min(255, int(v * g)))
    fade = int(p["fade_dots"]) * s
    if fade and p["fade_strength"]:
        ramp = Image.new("L", (1, dens.height), 255)
        for y in range(min(fade, dens.height)):
            ramp.putpixel((0, y), int(255 * (1 - p["fade_strength"] * (1 - y / fade))))
        from PIL import ImageChops

        dens = ImageChops.multiply(dens, ramp.resize(dens.size))
    paper = Image.new("RGB", dens.size, tuple(p["paper"]))
    ink = Image.new("RGB", dens.size, tuple(p["ink"]))
    return Image.composite(ink, paper, dens)
