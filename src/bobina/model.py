"""Neutral document model produced by the parser and consumed by the layout engine."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Attrs:
    classes: set[str] = field(default_factory=set)
    kv: dict[str, str] = field(default_factory=dict)

    def has(self, cls: str) -> bool:
        return cls in self.classes

    def merged(self, other: Attrs) -> Attrs:
        return Attrs(self.classes | other.classes, {**self.kv, **other.kv})


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    strike: bool = False
    underline: bool = False
    invert: bool = False
    mono: bool = False
    font: str | None = None
    size: str | None = None
    white: bool = False  # printed white on black by what holds it (a black chat bubble): as on an .invert line


@dataclass
class Block:
    line: int = 0
    attrs: Attrs = field(default_factory=Attrs)


@dataclass
class Heading(Block):
    level: int = 1
    runs: list[Run] = field(default_factory=list)


@dataclass
class Paragraph(Block):
    runs: list[Run] = field(default_factory=list)
    follows: bool = False  # the next lines of the paragraph above, after an inner line's {…}: no block gap


@dataclass
class Item:
    children: list[Block] = field(default_factory=list)
    task: bool | None = None  # None = not a task; False = open; True = done


@dataclass
class ListBlock(Block):
    ordered: bool = False
    start: int = 1
    items: list[Item] = field(default_factory=list)


@dataclass
class Quote(Block):
    children: list[Block] = field(default_factory=list)


@dataclass
class Div(Block):
    """A ::: block: a box (.box), columns side by side (.columns: each child is a column, a Div), or only a group of
    blocks (an unknown class: its content prints as it is)."""

    children: list[Block] = field(default_factory=list)
    fence: str = ""  # the line that opened it, as written (::: {.box title=MESA}): problems name it
    closed: bool = True  # False: no line of ::: closed it (M105), it runs to the end of what holds it


@dataclass
class Divider(Block):
    pass


@dataclass
class Fence(Block):
    kind: str = ""  # qr, raw, text, image, ... or a code language
    content: str = ""
    arg: str = ""  # the word after the kind: ```contact whatsapp -> "whatsapp"


@dataclass
class Image(Block):
    src: str = ""
    alt: str = ""


@dataclass
class Table(Block):
    header: list[list[Run]] = field(default_factory=list)
    rows: list[list[list[Run]]] = field(default_factory=list)
    aligns: list[str] = field(default_factory=list)
    attr_lines: dict[str, int] = field(default_factory=dict)  # ".compact"/"width=" -> the line it was written on
    row_lines: list[int] = field(default_factory=list)  # the source line of each row
    columns: list[Attrs] = field(default_factory=list)  # each column's settings, from the end of its title cell
    heads: list[Attrs] = field(default_factory=list)  # each title cell's own classes (.bold .invert .shade .right…)
    cells: list[list[Attrs]] = field(default_factory=list)  # each body cell's classes and span=, row by row
    head_row: Attrs = field(default_factory=Attrs)  # the {…} after the title row's closing pipe: its classes
    row_attrs: list[Attrs] = field(default_factory=list)  # the same for each body row


@dataclass
class Document:
    meta: dict = field(default_factory=dict)
    blocks: list[Block] = field(default_factory=list)
    base_dir: str = "."
    meta_lines: dict[str, int] = field(default_factory=dict)  # front matter key -> the line it was written on
