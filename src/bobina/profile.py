"""Printer profiles: what a printer can do, measured, as data (TOML)."""

from __future__ import annotations

import functools
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from . import paths

BUILTIN = "mtp-ii-58"


@dataclass
class Profile:
    id: str
    name: str
    width_dots: int
    dpi: int
    data: dict = field(repr=False)
    _pages: tuple | None = field(default=None, repr=False, compare=False)

    # -- convenience accessors ------------------------------------------------
    def tracking_gap(self, tracking: int, sw: int) -> int:
        """Dots after each character for ESC SP n at width sw. The spec doubles it with the width; a printer that
        was measured not to lists those widths in native.tracking_unscaled_at (MTP-II: 2x, paper 09/11). Widths
        nobody measured follow the spec: lines then wrap early rather than run off the paper."""
        widths = self.get("native.tracking_unscaled_at")
        if not isinstance(widths, list):
            widths = [widths]  # tracking_unscaled_at = 2: one width
        measured = [w for w in widths if isinstance(w, int) and not isinstance(w, bool)]  # "2" or true: not a width
        return tracking if sw in measured else tracking * sw

    def code39_wide(self) -> int:
        """Modules of a wide Code39 element in the firmware's GS k output (python-barcode draws 3)."""
        return int(self.get("barcode.code39_wide", 3))

    def get(self, dotted: str, default=None):
        cur = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    @property
    def cell(self) -> tuple[int, int]:
        w, h = self.get("native.cell", [12, 24])
        return int(w), int(h)

    @property
    def columns(self) -> int:
        return self.width_dots // self.cell[0]

    def native_glyph(self, ch: str) -> bool:
        if self.get("encoding") == "codepage":  # what one of the printer's code pages has (ESC t)
            return plain_ascii(ch) or code_page_for(ch, self.codepages()) is not None
        cp = ord(ch)
        return any(lo <= cp <= hi for lo, hi in self.get("native.glyph_ranges", []))

    def codepages(self) -> tuple:
        """((python codec, ESC t number), …) in order of preference (profile [codepages]); kept until the table
        itself changes (engine.apply_overrides replaces it)."""
        table = self.get("codepages") or {}
        if self._pages is None or self._pages[0] is not table:
            self._pages = (table, tuple((str(k), int(v)) for k, v in table.items()))
        return self._pages[1]

    def mm_to_dots(self, mm: float) -> int:
        return round(mm * self.dpi / 25.4)


def plain_ascii(ch: str) -> bool:
    """Printable ASCII: sent as it is, never through a code page (one test for the encoder, the layout and P301)."""
    return 0x20 <= ord(ch) < 0x7F


@functools.lru_cache(maxsize=4096)
def code_page_for(ch: str, pages: tuple) -> tuple | None:
    """The first (codec, number) of pages that has ch in ONE byte, or None (a multi-byte codec never counts)."""
    for codec, n in pages:
        try:
            if len(ch.encode(codec)) == 1:
                return codec, n
        except (UnicodeEncodeError, LookupError):
            continue
    return None


def _builtin_dir():
    return resources.files("bobina") / "profiles"


def available() -> dict[str, str]:
    """id -> source ('built-in' or a path)."""
    out = {}
    for f in _builtin_dir().iterdir():
        if f.name.endswith(".toml"):
            out[f.name[:-5]] = "built-in"
    user = paths.config_dir() / "profiles"
    if user.is_dir():
        for f in user.glob("*.toml"):
            out[f.stem] = str(f)
    return out


def load(name: str | None = None) -> Profile:
    name = name or BUILTIN
    p = Path(name)
    if p.suffix == ".toml" and p.exists():
        raw = p.read_bytes()
    else:
        user = paths.config_dir() / "profiles" / f"{name}.toml"
        if user.exists():
            raw = user.read_bytes()
        else:
            f = _builtin_dir() / f"{name}.toml"
            if not f.is_file():
                raise KeyError(f"unknown profile '{name}' (see: bobina profile list)")
            raw = f.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    return Profile(
        id=data["id"],
        name=data.get("name", data["id"]),
        width_dots=int(data["width_dots"]),
        dpi=int(data.get("dpi", 203)),
        data=data,
    )
