# Tables: styles, fonts and columns

A table in a `.bob.md` is a plain Markdown table. What bobina adds goes in braces `{…}`, one `{…}` for each reach:

- for the whole table, on the line right under it (with or without a blank line): `{style=receipt .compact}`;
- for one column, at the end of its title cell: `| Price {width=9ch prefix="R$ "} |`;
- for one cell, at the end of its text, and for one row, after its closing pipe; a cell over several columns
  (`span=all`): [table-cells.md](table-cells.md).

Everything with the same reach goes in the same `{…}`. Names and values are lowercase. Whole receipts to copy:
[receipts.md](receipts.md).

```markdown
| Item | Qty | Price |
|---|--:|--:|
| Espresso | 2 | 9,00 |
{style=receipt .compact}
```

## Columns

- The second line sets each column's alignment, as in any Markdown: `---` left, `--:` right, `:-:` centre.
- Each column is as wide as its text, **one column of space** between columns. The table fills the paper: the
  widest text column (left-aligned, with letters) takes the rest; `.compact` keeps it narrow (`.center`, `.right`).
- The printer font has 32 columns on 58 mm paper and 48 on 80 mm, the spaces included: 4 columns on 58 mm leave
  29 for text. A cell wraps at its spaces; a word longer than an `auto` column is cut (`L101`).
- In a cell: `**bold**`, `*italic*`, `~~strike~~`, `[word]{.invert}`; `font=` and `size=` go to the whole table.

## Tables without a title row

Markdown needs a title row. Leave its cells empty (`| | |`) and bobina prints no title and no rule: label on the
left, value on the right, the way receipts print totals ([receipts.md](receipts.md#totals)).

## Column widths, prefixes and suffixes

At the end of a column's title cell:

- `width=`: `7ch` (7 columns), `20mm`, `30%` (of the table's text room, the spaces between columns left out:
  `50%` + `50%` fill it), `96` (dots), or `auto`, the default: the columns without a width share what is left. A
  column you give a width keeps it: its text wraps inside it, and a word longer than it (a 13-digit code in `7ch`)
  is **cut at its edge without a warning**: you chose that width.
- `prefix="R$ "`, `suffix=" kg"`: printed before or after every value of the column, never in the title row nor in
  an empty cell. The column's width counts them. A value from `--data` or `--set` stays as it is.

```markdown
| Product | Price {width=8ch prefix="R$ "} | Sale {width=8ch prefix="R$ "} |
|---|--:|--:|
| Rice 5 kg | 24,90 | 21,90 |
| Ground coffee 500 g | 18,75 | |
```

Without a title row: `| | {prefix="R$ "} |` (still empty).
`bobina check FILE` says the width each column got (`L108`): `column widths: Product 14 · Price 8 · Sale 8 (+2 gaps =
32 of 32)`. Widths wider than the paper shrink in proportion, `auto` columns keeping 2 (`L107`). With `font=`, `7ch`
is 7 times that font's `0`.

## Ready-made styles

One word on the line under the table: `{style=receipt}`.

| Style | Looks like | Prints as |
|---|---|---|
| `plain` | the default: bold titles, a solid rule under them | text |
| `receipt` | dashed rules above and below the titles, titles not bold | text and rules |
| `lines` | as `plain`, and a dotted line between rows | text and rules |
| `grid` | a full grid, its lines in the spaces between columns; the border takes 1 column | image |
| `header-invert` | white titles on a black band, no rule | the titles as an image |
| `zebra` | every other row on light grey dots | the grey rows as images; ⚠ not tested on paper (`P301`) |

Without titles: no title band or rule, in any style.

## Smaller letters: `font=` and `size=`

`{font=Terminus size=16px}` draws the table as an image in that font (bundled: Terminus, Spleen, IBM Plex Mono,
Atkinson Hyperlegible, Barlow Condensed, DejaVu Sans; sizes as in [FORMAT §5](../FORMAT.md#5-sizes-)). A column is
as wide as the font's `0` (a proportional font lines up by the dot). Columns per line, spaces included:

| Font | 58 mm (384 dots) | 80 mm (576 dots) |
|---|---|---|
| printer font | 32 | 48 |
| Terminus 12px (its tested minimum) | 64 | 96 |
| Terminus 14px | 54 | 82 |
| Terminus 16px | 48 | 72 |
| Terminus 20px | 38 | 57 |
| IBM Plex Mono 16px | 40 | 60 |
| Spleen 24px (the printer font's look) | 31 | 47 |

`size=` alone uses Terminus (`2x`, `3x`: the printer font's look). Below a font's tested minimum: `F201`; not
found: `F203`; `header-invert` titles under 20px: `F204`.

## Turned tables

A table whose columns cannot keep 6 characters each prints **turned** along the paper, the titles on the right
(`orientation=auto`, the default; note `L106`). With column widths it stays standing while they can shrink to fit,
and turns when not even that fits. `orientation=vertical` always turns it (`width=half` places it; column widths
hold along the paper); `orientation=horizontal` never does, narrowing every column (`L107`). Never past the paper.

## When something is wrong

bobina prints anyway and says what to fix (`bobina check FILE`: the same list, nothing printed):

| Code | When | Example message |
|---|---|---|
| `M101` | an unknown style; it prints `plain` | `style=recibo: unknown style; plain, receipt, …` |
| `M101` | a value in capitals | `style=RECEIPT: values are lowercase` |
| `M101` | a width it cannot read; the column is `auto` | `width=abc` |
| `M101` | a column setting in a body cell | `prefix= works at the end of a title cell, for its column` |
| `M101` | something a table does not take | `leading= does nothing on a table` |
| `L101` | a word longer than a column without `width=` was cut | `word 'DESCRICAO…' split at 8 columns in a table` |
| `L106` | the table was turned | `a table of 9 columns … prints VERTICALLY…` |
| `L107` | the columns do not fit as given | `column widths add up to 61 columns, the paper has 48: scaled down` |
