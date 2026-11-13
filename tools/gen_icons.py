"""Rasterizes the bundled icons once: src/bobina/icons/<set>/<name>.svg -> <name>-<px>.png, 1-bit, for the printer
(no SVG renderer at run time). --fetch downloads the SVGs and the license of the pinned icon set first.

Usage: python tools/gen_icons.py [--fetch]    (needs resvg-py, a dev dependency)

Icons are generic symbols only (a person, sparkles, a robot…), never a company's logo: logos are trademarks.
Lucide strokes are 2 units wide on a 24 grid, so at 24 px they print 2 dots wide (B101: thinner breaks up)."""

from __future__ import annotations

import argparse
import io
import sys
import urllib.error
import urllib.request
from pathlib import Path

from bobina.icons import SIZES  # 1x to 8x of a 24-dot cell; a raster font picks the nearest

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "src" / "bobina" / "icons"
SETS = {  # set -> (source URL pattern, version, license file, icon names)
    "lucide": (
        "https://cdn.jsdelivr.net/npm/lucide-static@{version}/{path}",
        "1.61.0",
        "LICENSE",
        [
            # the chat
            "user-round", "sparkles", "bot", "message-circle",
            # documents (:name: in any .bob.md): generic symbols, food, storage, shop
            "check", "x", "heart", "star", "info", "triangle-alert", "ban", "bell", "bookmark", "tag", "gift",
            "clock", "calendar", "phone", "mail", "map-pin", "house", "truck", "package", "shopping-cart",
            "scissors", "key", "lock", "sun", "moon", "snowflake", "thermometer", "flame", "droplet", "umbrella",
            "leaf", "recycle", "trash-2", "zap", "wifi", "music", "coffee", "utensils", "cake", "pizza", "wine",
            "beer", "glass-water", "apple", "carrot", "fish", "egg", "milk", "wheat", "nut", "bean", "cookie",
            "ice-cream-cone", "baby", "dog", "cat", "pill", "bike", "car", "plane", "hand", "hand-heart", "smile",
            "thumbs-up",
            # home goods: kitchen, food, bathroom, office
            "cooking-pot", "soup", "salad", "sandwich", "croissant", "cherry", "grape", "banana", "citrus",
            "drumstick", "beef", "ham", "popcorn", "candy", "lollipop", "cup-soda", "refrigerator", "microwave",
            "washing-machine", "bath", "shower-head", "bed-double", "sofa", "lamp", "shirt", "spray-can",
            "toilet", "pen", "pencil", "paperclip", "file-text", "folder", "printer", "book", "briefcase",
            "calculator", "ruler", "highlighter",
        ],
    ),
    # drawn for bobina (same license as bobina): packaging marks, in Lucide's style (24 grid, 2-unit strokes).
    # Generic drawings of the meaning, never a copy of a standard's artwork.
    "pictograms": (None, None, None, None),  # every SVG in icons/pictograms
}  # fmt: skip


def fetch(name: str) -> None:
    url, version, license_file, names = SETS[name]
    folder = ICONS / name
    folder.mkdir(parents=True, exist_ok=True)
    for icon in names:
        try:
            with urllib.request.urlopen(url.format(version=version, path=f"icons/{icon}.svg"), timeout=30) as r:
                (folder / f"{icon}.svg").write_bytes(r.read())
        except urllib.error.HTTPError as e:  # a name this version does not have: say it, keep going
            print(f"skipped {icon}: {e.code}", file=sys.stderr)
    with urllib.request.urlopen(url.format(version=version, path=license_file), timeout=30) as r:
        (ICONS / "licenses" / f"{name.title()}-LICENSE.txt").write_bytes(r.read())
    print(f"fetched {len(names)} icons of {name} {version}")


def rasterize(svg: str, px: int):
    import resvg_py
    from PIL import Image

    svg = svg.replace('stroke="currentColor"', 'stroke="#000"').replace('fill="currentColor"', 'fill="#000"')
    png = resvg_py.svg_to_bytes(svg_string=svg, width=px * 4, height=px * 4, background="white")
    im = Image.open(io.BytesIO(bytes(png))).convert("L").resize((px, px), Image.LANCZOS)
    return im.point(lambda v: 0 if v < 140 else 255).convert("1", dither=Image.NONE)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch", action="store_true", help="download the SVGs and the license first")
    a = ap.parse_args()
    (ICONS / "licenses").mkdir(parents=True, exist_ok=True)
    n = 0
    for name, (url, _, _, names) in SETS.items():
        if a.fetch and url:
            fetch(name)
        for icon in names or sorted(p.stem for p in (ICONS / name).glob("*.svg")):
            if not (ICONS / name / f"{icon}.svg").is_file():
                continue  # skipped by --fetch
            svg = (ICONS / name / f"{icon}.svg").read_text(encoding="utf-8")
            for px in SIZES:
                rasterize(svg, px).save(ICONS / name / f"{icon}-{px}.png", optimize=True)
                n += 1
    print(f"wrote {n} PNGs in {ICONS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
