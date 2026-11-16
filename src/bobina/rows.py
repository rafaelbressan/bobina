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


def columns(cells: list[Cell]) -> int:
    """The columns these cells take on the character grid (a wide character takes 2)."""
    return sum(2 if c.wide else 1 for c in cells)


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
        return columns(self.cells)


@dataclass
class Boxed:
    """What the terminal views need to draw a ::: box: its frame on the paper's columns and the rows inside it."""

    rows: list  # the content, laid out at the box's inner width (a band title comes first, as its own row)
    inner: int  # dots: the width the content was laid out at
    left: int  # columns from the paper's edge to the frame (quote bars and list indents included in `lead`)
    cols: int  # columns the box takes, its frame included
    title: str = ""  # a title on the border, as printed (cut with … when it did not fit)
    style: str = "solid"  # solid, dashed, dotted, double: the frame's line
    lead: str = ""  # what the view shows before the box: the bars of the quotes it is in
    turned: float = 0  # degrees it was turned (rotate=, .flip): the view shows it standing, under a mark


@dataclass
class BitmapRow:
    image: Image.Image  # mode "1", full paper width
    line: int = 0
    kind: str = "image"
    text_rows: list | None = None  # for text drawn as an image (inverted bands): shown as text in views
    untested: tuple[str, ...] = ()  # features not tested on paper it draws (features.py, "zebra"): note P301
    wide_view: bool = False  # a table in a smaller font whose text rows need more columns than the paper: the
    # terminal views widen their frame to hold them (view.width)
    box: Boxed | None = None  # a ::: box: the views draw its frame and its content (view.box_lines)


@dataclass
class QRRow:
    data: str
    module: int
    ecc: str
    align: str = "center"
    line: int = 0
    native: bool = True
    version: int = 0  # the version the printer draws (a firmware that takes the module as minimum version, profile
    # qr.native_module_param); 0: the smallest one the content fits
    param: int = 0  # the module parameter sent (GS ( k fn 167) when it is not the module in dots; 0: module)


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
