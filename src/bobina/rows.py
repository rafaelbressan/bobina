"""Print rows: the single intermediate between layout and output.

Both the ESC/POS encoder and the preview consume the same rows, so the preview shows exactly
what is sent ("what you check is what you print")."""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image


@dataclass
class Cell:
    ch: str
    bold: bool = False
    underline: bool = False
    invert: bool = False
    italic: bool = False
    strike: bool = False
    wide: bool = False  # occupies two columns (CJK, drawn checkbox)


@dataclass
class TextRow:
    cells: list[Cell]
    scale: tuple[int, int] = (1, 1)
    align: str = "left"
    line: int = 0
    native: bool = True  # False: printed as an image through the font emulator
    reason: str = ""  # why it is not native
    upside_down: bool = False  # ESC { 1 (the block's rows are sent in reverse order)
    tracking: int = 0  # extra dots after each character (ESC SP n; how it scales with the width: Profile.tracking_gap)
    gap: int | None = None  # dots between this line and the next (None: profile native.line_gap_dots)

    def columns(self) -> int:
        return sum(2 if c.wide else 1 for c in self.cells)


@dataclass
class BitmapRow:
    image: Image.Image  # mode "1", full paper width
    line: int = 0
    kind: str = "image"
    text_rows: list | None = None  # for text drawn as an image (inverted bands): shown as text in views


@dataclass
class QRRow:
    data: str
    module: int
    ecc: str
    align: str = "center"
    line: int = 0
    native: bool = True


@dataclass
class BarcodeRow:
    kind: str
    data: str
    module: int
    height: int
    text: str = "below"
    align: str = "center"
    line: int = 0


@dataclass
class FeedRow:
    dots: int
    mark: str = field(default="", compare=False)  # "tear": the feed to the tear bar (drawn ⟶ in terminal views);
    # "cut": the space between --compact labels when no cut line is printed (drawn ✂ in terminal views)
    tear_at: int | None = field(default=None, compare=False)  # --marks tear: the printed line, this many dots in


@dataclass
class RawRow:
    data: bytes
    line: int = 0


Row = TextRow | BitmapRow | QRRow | BarcodeRow | FeedRow | RawRow


@dataclass
class Job:
    rows: list = field(default_factory=list)
    width: int = 384
