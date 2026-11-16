"""bobina help table: where each {…} of a table goes and what it takes, on one screen (--json for programs). The long
form is docs/guides/tables.md, table-cells.md and receipts.md; tests/test_table_help.py keeps this in step with the
parser (names), the layout (styles, columns per line) and the catalog (codes)."""

from __future__ import annotations

import textwrap

GUIDES = ("docs/guides/tables.md", "docs/guides/table-cells.md", "docs/guides/receipts.md")

PLACES = (  # (where the {…} goes, its reach, an example)
    ("the line under the table", "the table", "{style=receipt font=Terminus size=16px}"),
    ("the end of a title cell", "its column", '| Price {width=8ch prefix="R$ "} |'),
    ("the end of a body cell", "that cell", "| 9,00 {.bold} |  | | Off {span=all} |"),
    ("after a row's last pipe", "that row", "| TOTAL | 93,50 | {.bold}"),
)

STYLES = {  # every style of layout.TABLE_STYLES (a test checks): how it looks
    "plain": "bold titles, a solid rule under them (the default)",
    "receipt": "dashed rules above and below the titles, titles not bold",
    "lines": "as plain, and a dotted line between rows",
    "grid": "a full grid, drawn as an image (its border takes 1 column)",
    "header-invert": "white titles on a black band",
    "zebra": "every other row on light grey dots (not tested on paper: P301)",
}

TABLE_ALSO = (
    ".compact: narrow, not the paper's width; .center .right: where a narrow table goes; "
    "orientation=auto|vertical|horizontal: auto turns a table that cannot fit (L106)"
)

COLUMNS_PER_LINE = (  # (font, columns on 58 mm, on 80 mm), the 1-column spaces between columns included; a test
    ("printer font", 32, 48),  # measures each with bobina check (L108)
    ("Terminus 12px", 64, 96),
    ("Terminus 16px", 48, 72),
    ("Terminus 20px", 38, 57),
    ("IBM Plex Mono 16px", 40, 60),
    ("Spleen 24px", 31, 47),
)

COLUMN = {
    "width=": "auto (the default: the auto columns share what is left, and the widest text column, left-aligned "
    "with letters, takes the rest of the paper), 7ch (columns of the table's font), "
    "20mm, 30% (of the text room), 96 (dots). A column with a width wraps its text inside it and cuts a longer "
    "word at its edge, without a warning",
    "prefix=": '"R$ " before every body value: never in the title row, never in an empty cell',
    "suffix=": '" kg" after every body value. The width counts both; a --data or --set value stays as it is',
}

CELL_CLASSES = (".bold", ".italic", ".underline", ".strike", ".invert", ".shade", ".left", ".center", ".right")
ROW_CLASSES = tuple(c for c in CELL_CLASSES if c != ".strike")

SPAN = (
    "span=all (to the end of the row) or span=N (this cell and the next N-1), in a body cell. It starts where "
    "it is written: write one empty cell for each column before it; the cells after it need not be written"
)

NO_TITLE = 'Leave the title cells empty (| | |): no title row, no rule. Settings still go there: | | {prefix="R$ "} |'

EXAMPLE = """\
| Qty | Item | Price {width=8ch} |
|--:|---|--:|
| 2 | Espresso | 18,00 |
| 1 | Bagel | 39,00 |
| | Birthday: no charge {span=all} |
{style=receipt}

| | {prefix="R$ "} |
|---|--:|
| SUBTOTAL | 57,00 |
| SERVICE 10% | 5,70 |
| TOTAL | 62,70 | {.bold}"""

PROBLEMS = {  # the codes a table can give, and when (each one is in nudges.CATALOG: a test checks)
    "M101": "a name or value a table does not take, in capitals or in the wrong place: it says the right one and "
    "the table still prints (plain style, auto width, the cell in its own column)",
    "L101": "a word longer than an auto column was cut",
    "L106": "the table was turned along the paper to fit",
    "L107": "the widths add up to more than the paper: scaled down",
    "L108": "the width each column got (bobina check only)",
    "M104": "a {…} after the title row: GitHub and Obsidian show the table as text",
    "F204": "white-on-black titles or cells in a font under 20px",
    "P301": "light grey (zebra, .shade) is not tested on paper yet",
}


def help_text() -> str:
    out = ["bobina help table — tables in a .bob.md (long form: docs/guides/tables.md,",
           "table-cells.md and receipts.md)", "",
           "A table is a Markdown table; bobina's settings go in {…}, and where a {…} goes",
           "is its reach. One {…} per place, all of that reach in it. Names and values are",
           "lowercase.", ""]  # fmt: skip
    out += [f"  {where:26s}{reach:12s}{example}" for where, reach, example in PLACES]
    out += ["", "TABLE  style=" + "|".join(STYLES)]
    out += [f"  {name:15s}{looks}" for name, looks in STYLES.items()]
    out += _wrap(TABLE_ALSO, "  ")
    out += ["  font=Terminus size=16px: drawn in that font. Columns per line (spaces too):",
            f"    {'':20s}58 mm  80 mm"]  # fmt: skip
    out += [f"    {font:20s}{a:5d}  {b:5d}" for font, a, b in COLUMNS_PER_LINE]
    out += ["", "COLUMN  at the end of its title cell"]
    for key, what in COLUMN.items():
        out += _wrap(what, f"  {key:9s}", 11)
    out += ["", "CELL  " + " ".join(CELL_CLASSES)]
    out += _wrap(SPAN, "  ")
    out += ["", "ROW  " + " ".join(ROW_CLASSES), "", "NO TITLE ROW"]
    out += _wrap(NO_TITLE, "  ")
    out += ["", "EXAMPLE"] + [f"  {line}" if line else "" for line in EXAMPLE.split("\n")]
    out += ["", "PROBLEMS  bobina check FILE lists them; bobina help CODE says what to do"]
    for code, when in PROBLEMS.items():
        out += _wrap(when, f"  {code} ", 7)
    return "\n".join(out)


def help_json() -> dict:
    return {
        "places": [{"where": w, "reach": r, "example": e} for w, r, e in PLACES],
        "styles": STYLES,
        "table": TABLE_ALSO,
        "columns_per_line": [{"font": f, "58mm": a, "80mm": b} for f, a, b in COLUMNS_PER_LINE],
        "column": COLUMN,
        "cell": {"classes": list(CELL_CLASSES), "span": SPAN},
        "row": {"classes": list(ROW_CLASSES)},
        "no_title": NO_TITLE,
        "example": EXAMPLE,
        "problems": PROBLEMS,
        "guides": list(GUIDES),
    }


def _wrap(text: str, first: str, indent: int = 2) -> list[str]:
    """`text` wrapped for an 80-column terminal, `first` in front of its first line."""
    return textwrap.wrap(text, 79, initial_indent=first, subsequent_indent=" " * indent)
