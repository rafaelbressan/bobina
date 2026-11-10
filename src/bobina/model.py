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
class Divider(Block):
    pass


@dataclass
class Fence(Block):
    kind: str = ""  # qr, raw, text, image, ... or a code language
    content: str = ""


@dataclass
class Image(Block):
    src: str = ""
    alt: str = ""


@dataclass
class Table(Block):
    header: list[list[Run]] = field(default_factory=list)
    rows: list[list[list[Run]]] = field(default_factory=list)
    aligns: list[str] = field(default_factory=list)


@dataclass
class Document:
    meta: dict = field(default_factory=dict)
    blocks: list[Block] = field(default_factory=list)
    base_dir: str = "."
