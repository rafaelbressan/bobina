"""Regenerates docs/guides/icons.md (every icon by category: its picture, its :name: and what it means, then ready
examples) from src/bobina/icons/catalog.py, and its pictures in docs/guides/icons/ drawn by bobina itself: each
icon from the bundled bitmaps, each example rendered like a print preview. Run after changing an icon or the
catalog: python tools/gen_icon_docs.py (tests/test_icons.py fails until the page and pictures match). Never edit
the page by hand."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bobina import icons  # noqa: E402
from bobina.icons.catalog import CATEGORIES, PNG_DIR, PNG_PX, USES, docs_page  # noqa: E402

PAGE = ROOT / "docs" / "guides" / "icons.md"
PICTURES = PAGE.parent / PNG_DIR


def icon_png(name: str):
    return icons.load(name, PNG_PX)


def use_png(src: str):
    from bobina.engine import build

    im = build(src).image.convert("L")
    box = im.point(lambda v: 255 - v).getbbox()  # the printed part, without the paper around it
    return im.crop((0, max(0, box[1] - 8), im.width, min(im.height, box[3] + 8))) if box else im


def main() -> None:
    PICTURES.mkdir(parents=True, exist_ok=True)
    wanted = set()
    for _key, _title, _about, items in CATEGORIES:
        for name, _meaning in items:
            icon_png(name).save(PICTURES / f"{name}.png", optimize=True)
            wanted.add(f"{name}.png")
    for slug, _title, _why, src in USES:
        use_png(src).convert("1", dither=0).save(PICTURES / f"use-{slug}.png", optimize=True)
        wanted.add(f"use-{slug}.png")
    for old in PICTURES.glob("*.png"):
        if old.name not in wanted:
            old.unlink()
    PAGE.write_text(docs_page(), encoding="utf-8")
    print(f"wrote {PAGE.relative_to(ROOT)} and {len(wanted)} pictures")


if __name__ == "__main__":
    main()
