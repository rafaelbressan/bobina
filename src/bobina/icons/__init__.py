"""Bundled icons, as 1-bit bitmaps ready for the printer: src/bobina/icons/<set>/<name>-<px>.png, made once from
the SVGs next to them by tools/gen_icons.py (no SVG renderer at run time). Generic symbols only, never a company's
logo. Licenses: icons/licenses/ (Lucide: ISC)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent
SET = "lucide"


def names(icon_set: str = SET) -> list[str]:
    return sorted(p.stem for p in (ROOT / icon_set).glob("*.svg"))


@cache
def load(name: str, px: int = 24, icon_set: str = SET) -> Image.Image:
    """The icon as a mode "1" image (black = ink). KeyError when there is no such icon at that size."""
    p = ROOT / icon_set / f"{name}-{px}.png"
    if not p.is_file():
        sizes = sorted(int(q.stem.rsplit("-", 1)[1]) for q in (ROOT / icon_set).glob(f"{name}-*.png"))
        raise KeyError(f"no icon {name!r} at {px} px" + (f" (sizes: {sizes})" if sizes else f": {names(icon_set)}"))
    with Image.open(p) as im:
        return im.convert("1")
