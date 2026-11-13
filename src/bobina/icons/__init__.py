"""Bundled icons, as 1-bit bitmaps ready for the printer: src/bobina/icons/<set>/<name>-<px>.png, made once from
the SVGs next to them by tools/gen_icons.py (no SVG renderer at run time). Generic symbols only, never a company's
logo. Sets: lucide (ISC, icons/licenses/) and pictograms (care symbols, packing and attestation marks drawn for
bobina). catalog.py groups them by category with what each one means.

In a document, `:fragile:` is an icon: the parser turns a known name into one character of a Private Use Area
(char_for), which the layout treats as a two-column cell and the emulator and raster fonts draw (load)."""

from __future__ import annotations

import difflib
import re
from functools import cache
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent
SET = "lucide"
SETS = ("pictograms", "lucide")  # a name in both: the first wins
SIZES = (24, 48, 72, 96, 120, 144, 168, 192)  # 1x to 8x of a 24-dot printer cell (tools/gen_icons.py draws them)

# Names people write for an icon (English): -> the icon's own name
ALIASES = {
    "this-way-up": "this-side-up", "up": "this-side-up", "dry": "keep-dry", "no-stack": "do-not-stack",
    "care": "handle-with-care", "heat": "keep-away-from-heat", "warning": "triangle-alert", "alert": "triangle-alert",
    "home": "house", "trash": "trash-2", "bin": "trash-2", "cross": "x", "ok": "check", "love": "heart",
    "cold": "snowflake", "frozen": "snowflake", "freeze": "snowflake", "hot": "flame", "fire": "flame",
    "water": "droplet", "drop": "droplet", "temperature": "thermometer", "email": "mail", "pin": "map-pin",
    "location": "map-pin", "time": "clock", "date": "calendar", "cart": "shopping-cart", "cut": "scissors",
    "like": "thumbs-up", "gluten": "wheat", "dairy": "milk", "nuts": "nut", "glass": "glass-water",
    "person": "user-round", "user": "user-round", "box": "package", "parcel": "package", "delivery": "truck",
    "price": "tag", "sale": "tag", "rain": "umbrella", "medicine": "pill", "food": "utensils",
    "recyclable": "recycle", "mobius": "recycle", "hand-wash": "wash-hand", "do-not-wash": "no-wash",
    "tumble-dry": "dry-tumble", "tumble-dry-low": "dry-tumble-low", "tumble-dry-high": "dry-tumble-high",
    "do-not-tumble": "no-tumble", "do-not-tumble-dry": "no-tumble", "do-not-bleach": "no-bleach",
    "non-chlorine-bleach": "bleach-non-chlorine", "do-not-iron": "no-iron", "do-not-dry-clean": "no-dry-clean",
    "line-dry": "dry-line", "flat-dry": "dry-flat", "drip-dry": "dry-drip", "fridge": "refrigerator",
}  # fmt: skip

# :fragile: -> an icon; :fragile::keep-dry: is two. A run of shortcodes is not next to a letter, digit, colon or slash
# (10:30:00, a:b:c, https://x.com/:id: stay text). ONE is a single shortcode inside a run.
RUN = re.compile(r"(?<![\w:/])((?::[A-Za-z][A-Za-z0-9_+-]*:)+)(?![\w:/])")
ONE = re.compile(r":([A-Za-z][A-Za-z0-9_+-]*):")

PUA = 0x10F000  # Supplementary Private Use Area-B: not used by symbol fonts (Nerd Fonts use area A)


def names(icon_set: str | None = None) -> list[str]:
    """The icons of one set, or of every set (documents)."""
    sets = (icon_set,) if icon_set else SETS
    return sorted({p.stem for s in sets for p in (ROOT / s).glob("*.svg")})


@cache
def _table() -> tuple[str, ...]:
    return tuple(names())


def canonical(name: str) -> str | None:
    """A name written in a document (any case, _ or -) -> the icon's name, or None."""
    n = name.strip().lower().replace("_", "-")
    n = ALIASES.get(n, n)
    return n if n in _table() else None


def char_for(name: str) -> str:
    return chr(PUA + _table().index(name))


def name_of(ch: str) -> str | None:
    i = ord(ch) - PUA
    t = _table()
    return t[i] if 0 <= i < len(t) else None


def is_icon(ch: str) -> bool:
    return len(ch) == 1 and name_of(ch) is not None


def strip(s: str) -> str:
    """s without icon characters (data values: a value is never an icon)."""
    return "".join(ch for ch in s if not is_icon(ch)) if any(is_icon(ch) for ch in s) else s


def closest(name: str, n: int = 3) -> list[str]:
    words = list(_table()) + list(ALIASES)
    return difflib.get_close_matches(name.lower().replace("_", "-"), words, n=n, cutoff=0.6)


def _set_of(name: str) -> str:
    return next((s for s in SETS if (ROOT / s / f"{name}.svg").is_file()), SET)


@cache
def load(name: str, px: int = 24, icon_set: str | None = None) -> Image.Image:
    """The icon as a mode "1" image (black = ink), px x px. A size that was not made from the SVG is resized from
    the nearest one that was. KeyError when there is no such icon."""
    folder = ROOT / (icon_set or _set_of(name))
    p = folder / f"{name}-{px}.png"
    if p.is_file():
        with Image.open(p) as im:
            return im.convert("1")
    sizes = sorted(int(q.stem.rsplit("-", 1)[1]) for q in folder.glob(f"{name}-*.png"))
    if not sizes:
        raise KeyError(f"no icon {name!r}: {', '.join(names())}")
    src = min(sizes, key=lambda s: (abs(s - px), -s))
    with Image.open(folder / f"{name}-{src}.png") as im:
        big = im.convert("L").resize((px, px), Image.LANCZOS)
    return big.point(lambda v: 0 if v < 160 else 255).convert("1", dither=Image.NONE)


def shown(ch: str) -> str:
    """What a terminal shows for an icon cell (it cannot draw the icon)."""
    return "◆" if is_icon(ch) else ch


def help_text() -> str:
    """bobina help icons: every name by category with what it means, then the other names people write."""
    import textwrap

    from .catalog import CATEGORIES, TRADEMARK

    lines = [
        "Icons: write :name: in any text (:fragile: Glass). Alone on a line with {size=3x .center}: a big mark.",
        "Not in code, not from --data or --set values (printed as written). \\:name: keeps the colons.",
        "With pictures and uses: docs/guides/icons.md",
    ]
    for _key, title, about, items in CATEGORIES:
        lines += ["", f"{title} ({about})"]
        lines += [f"  :{n}:".ljust(26) + meaning for n, meaning in items]
    also = "Also: " + ", ".join(f":{a}: = :{n}:" for a, n in sorted(ALIASES.items()))
    lines += ["", *textwrap.wrap(also, 100, break_on_hyphens=False, break_long_words=False)]
    return "\n".join([*lines, "", *textwrap.wrap(TRADEMARK, 100)])
