"""Writes the SVGs of the pictograms drawn for bobina (care symbols, packing, attestation marks) into
src/bobina/icons/pictograms. Geometric drawings of the meaning on Lucide's 24 grid (2-unit strokes), never a copy
of a standard's artwork. Then run tools/gen_icons.py (the bitmaps) and tools/gen_icon_docs.py (the guide).

Usage: python tools/draw_pictograms.py"""

import sys
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "src/bobina/icons/pictograms"
HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
)

# 7-segment digits in a 3.6 x 6.4 box (thin strokes: they sit inside a symbol)
SEG = {
    "a": (0, 0, 1, 0),
    "b": (1, 0, 1, 0.5),
    "c": (1, 0.5, 1, 1),
    "d": (0, 1, 1, 1),
    "e": (0, 0.5, 0, 1),
    "f": (0, 0, 0, 0.5),
    "g": (0, 0.5, 1, 0.5),
}
DIG = {"0": "abcdef", "3": "abcdg", "4": "fgbc", "5": "afgcd", "6": "afgedc", "9": "abcdfg"}


def digits(text, x, y, w=3.6, h=6.4, gap=1.6):
    out = []
    for i, ch in enumerate(text):
        x0 = x + i * (w + gap)
        segs = [SEG[s] for s in DIG[ch]]
        d = " ".join(f"M{x0 + a * w:.2f} {y + b * h:.2f}L{x0 + c * w:.2f} {y + e * h:.2f}" for a, b, c, e in segs)
        out.append(f'<path d="{d}" stroke-width="1.7"/>')
    return "".join(out)


def dots(xs, y, r=1.3):
    return "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="currentColor" stroke="none"/>' for x in xs)


CROSS = '<path d="M3 3l18 18M21 3L3 21"/>'

# wash: a tub with water
TUB = '<path d="M2 6l2.6 13h14.8L22 6"/><path d="M2 6c1.7 1.5 3.3 1.5 5 0s3.3-1.5 5 0 3.3 1.5 5 0 3.3-1.5 5 0"/>'
BAR1 = '<path d="M5 21.3h14" stroke-width="1.5"/>'
BAR2 = '<path d="M5 21h14M5 23.2h14" stroke-width="1.3"/>'
# a hand dipped in the water: the palm, four fingers going down, the thumb
HAND = (
    '<path d="M7.5 8.8c2-.9 5.5-.9 8.5 0l2.3-1.6" stroke-width="1.6"/>'
    '<path d="M8.6 9v4.6M10.9 8.6v6.2M13.2 8.6v6.2M15.5 9v5" stroke-width="1.6"/>'
)


def temp(n):
    return TUB + digits(n, 6.9, 9.3, w=4.2, h=6.8, gap=2)


# airing / drying: a square
SQ = '<rect x="3" y="3" width="18" height="18" rx="1"/>'
TUMBLE = '<circle cx="12" cy="12" r="6"/>'
# bleach: a triangle
TRI = '<path d="M12 3l9.5 17h-19z"/>'
# ironing: an iron, pointing left
IRON = '<path d="M2 18c.6-4 3-7 7-7h9a3 3 0 0 1 3 3v4z"/><path d="M8.5 11V8h9.5v3"/>'
# dry cleaning: a circle
CIRCLE = '<circle cx="12" cy="12" r="9"/>'

ICONS = {
    # wash
    "wash": TUB,
    "wash-30": temp("30"),
    "wash-40": temp("40"),
    "wash-60": temp("60"),
    "wash-95": temp("95"),
    "wash-30-gentle": temp("30") + BAR1,
    "wash-40-gentle": temp("40") + BAR1,
    "wash-30-very-gentle": temp("30") + BAR2,
    "wash-hand": TUB + HAND,
    "no-wash": TUB + CROSS,
    # airing
    "dry-tumble": SQ + TUMBLE,
    "dry-tumble-low": SQ + TUMBLE + dots([12], 12),
    "dry-tumble-high": SQ + TUMBLE + dots([10, 14], 12),
    "no-tumble": SQ + TUMBLE + CROSS,
    "dry-line": SQ + '<path d="M5 7c3 4 11 4 14 0"/>',
    "dry-flat": SQ + '<path d="M7 12h10"/>',
    "dry-drip": SQ + '<path d="M8 7v10M12 7v10M16 7v10" stroke-width="1.5"/>',
    "dry-shade": SQ + '<path d="M3 9l6-6M3 14l11-11" stroke-width="1.5"/>',
    # bleach
    "bleach": TRI,
    "bleach-non-chlorine": TRI + '<path d="M9 18l3.5-7M12.5 18l3.5-7" stroke-width="1.5"/>',
    "no-bleach": TRI + CROSS,
    # ironing
    "iron": IRON,
    "iron-low": IRON + dots([14], 14.8),
    "iron-medium": IRON + dots([12, 16], 14.8),
    "iron-high": IRON + dots([10, 14, 18], 14.8),
    "no-iron": IRON + CROSS,
    # dry cleaning
    "dry-clean": CIRCLE,
    "dry-clean-p": CIRCLE + '<path d="M10 16.5v-9h3a2.5 2.5 0 0 1 0 5h-3"/>',
    "dry-clean-f": CIRCLE + '<path d="M10 16.5v-9h5M10 12h4"/>',
    "no-dry-clean": CIRCLE + CROSS,
    # packing
    "fragile": '<path d="M7 3h10l-.6 6.4a4.4 4.4 0 0 1-8.8 0z"/><path d="M12 14v6"/><path d="M8 21h8"/>'
    '<path d="M12.5 3.5l-1.5 2.2 2 1.4-1.2 2"/>',
    "this-side-up": '<path d="M8 17V4"/><path d="m5 7 3-3 3 3"/><path d="M16 17V4"/><path d="m13 7 3-3 3 3"/>'
    '<path d="M4 21h16"/>',
    "keep-dry": '<path d="M3 13a9 9 0 0 1 18 0z"/><path d="M12 13v6a2 2 0 0 1-4 0"/><path d="M4 3v2"/>'
    '<path d="M8 1v2"/><path d="M16 1v2"/><path d="M20 3v2"/>',
    "do-not-stack": '<rect x="6" y="13" width="12" height="8" rx="1"/><rect x="6" y="3" width="12" height="7" rx="1"/>'
    '<path d="M3 3l18 18"/>',
    "handle-with-care": '<rect x="7.5" y="3" width="9" height="8" rx="1"/><path d="M3 9v3a9 8 0 0 0 18 0V9"/>'
    '<path d="M3 9l2.5 3M21 9l-2.5 3"/>',
    "keep-away-from-heat": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4'
    'M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/><path d="M3 21L21 3"/>',
    # attestation (simple geometric marks, free to reproduce)
    "ce": '<path d="M11 6.5a5.5 5.5 0 1 0 0 11"/><path d="M21 6.5a5.5 5.5 0 1 0 0 11M16 12h4.5"/>',
    "ukca": '<path d="M4 3v4a2.5 2.5 0 0 0 5 0V3"/><path d="M14 3v7M14 6.5l4-3.5M14 6.5l4 3.5"/>'
    '<path d="M9 14h-3a2 2 0 0 0-2 2v2a2 2 0 0 0 2 2h3"/><path d="M13.5 20l2.5-6 2.5 6M14.4 18h3.2"/>',
    "e-mark": '<path d="M6.5 12h11a5.5 5.5 0 1 0-1.6 3.9"/>',
}

old = set(p.stem for p in OUT.glob("*.svg"))
for name, body in ICONS.items():
    (OUT / f"{name}.svg").write_text(HEAD + body + "</svg>\n", encoding="utf-8")
print(len(ICONS), "pictograms; removed:", sorted(old - set(ICONS)))
