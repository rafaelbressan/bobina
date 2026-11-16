# Table cells, rows and spans

What one cell or one row of a table looks like, and a cell that takes several columns. The table itself (styles,
fonts, column widths): [tables.md](tables.md). Whole receipts: [receipts.md](receipts.md).

Each `{…}` goes in one place, and its place is its reach. Names and values are lowercase; everything with the same
reach goes in one `{…}`.

| Where | Reach | What |
|---|---|---|
| the line right under the table | the whole table | `style=` `font=` `size=` `.compact` `orientation=` |
| the end of a title cell | its column, and that title cell | `width=` `prefix=` `suffix=`; the cell classes below |
| the end of a body cell | that cell | the cell classes, `span=` |
| after the pipe that closes a row | that row | `.bold .italic .underline .invert .shade .left .center .right` |

## A cell

At the end of a cell's text: `.bold` `.italic` `.underline` `.strike`, `.invert` (white on one black box, the
whole cell), `.shade` (light grey dots behind the text; ⚠ not tested on paper, `P301`), and `.left` `.center`
`.right`, which align that cell only. A title cell keeps its column settings and takes these too.

```markdown
| Item | Qty | Price {.invert} |
|---|--:|--:|
| Espresso {.bold} | 2 | 9,00 |
| Lemon pie | 1 {.left} | 28,00 {.shade} |
```

## A cell over several columns: `span=`

`span=all` (to the end of the row) or `span=3` (this column and the next 2), at the end of a body cell:

- It starts in the cell where it is written: **write one empty cell per column before it**. The cells after it
  need not be written: a row may have fewer cells than the title.
- Its text wraps in the columns it covers and the spaces between them. It widens them only when a word does not
  fit, from the room left on the paper. It aligns as the column it starts in, or as its own class (`.center`).
- A number larger than the columns left goes to the end (`M101`). A covered cell with text stops it before that
  cell (`M101`): nothing disappears. A covered cell's own `{…}` does nothing (`M101`). `span=1` is a plain cell.
- In `style=grid` no line is drawn inside it; zebra and `.shade` cover all of it. A turned table does the same.

Starting in the 3rd column, under the description:

```markdown
| IT | CODE | DESCRIPTION | TOTAL |
|---|---|---|--:|
| 003 | 7369 | BANANA PRATA | 16,33 |
| | | Discount on item 3 - 3,27 {span=all} |
```

## A row

After the pipe that closes the row, with nothing after it, in a row written with its leading pipe (without the
outer pipes, a last `{…}` is a cell). GitHub and Obsidian ignore that extra cell, so the
table stays a table there. Every cell of the row takes the classes; a cell's own alignment wins, styles add up.
`.invert` and `.shade` make one band across the whole row, spaces between columns and spans included.

```markdown
| | TOTAL | 61,00 | {.invert .bold}
```

A cell that is only `{…}` before a closing pipe is a cell: `| a | {.shade} |` shades the second cell. An empty
`{}` or an `{#id}` alone stays text.

For the title row, `style=header-invert` or the classes at the end of each title cell print the same and stay a
table everywhere. `| Item | Price | {.invert}` over `|---|--:|` also prints, but GitHub and Obsidian then show
the table as text (note `M104`).

A `{…}` that comes from data (`--data`, `--set`) is printed as text.

## When something is wrong

| Code | When | Example message |
|---|---|---|
| `M101` | a span that is not a number from 1 or `all`; the cell keeps its column | `span=2.5: a whole number from 1, or all` |
| `M101` | a value in capitals | `span=ALL: values are lowercase: span=all` |
| `M101` | a span past the end of the row | `span=5: 2 columns from here to the end of the row` |
| `M101` | a covered cell with text | `span=all stops before '9,00': that cell has text` |
| `M101` | `span=` in a title cell (ignored) | `span=all in a title cell: a title spans nothing (ignored)` |
| `M101` | what a row does not take | `.strike after a table row does nothing` |
| `M104` | a `{…}` after the title row | `a {…} after the title row makes GitHub and Obsidian show the table as text` |
