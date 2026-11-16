# Tables: styles, fonts and receipts

A table in a `.bob.md` is a plain Markdown table. What bobina adds goes in braces `{…}` on the line right under the
table (with or without a blank line): everything for the whole table in **one** `{…}`. Names and values are
lowercase.

```markdown
| Item | Qty | Price |
|---|--:|--:|
| Espresso | 2 | 9,00 |
| Bagel | 1 | 39,00 |
{style=receipt .compact}
```

## Columns

- The second line sets each column's alignment, as in any Markdown: `---` left, `--:` right, `:-:` centre.
- Each column is as wide as its text, with **one column of space** between two columns. The table fills the paper
  (the first column takes what is left); `.compact` keeps it narrow, `.center` or `.right` places it.
- The printer font has 32 columns on 58 mm paper and 48 on 80 mm, the spaces included: 4 columns on 58 mm leave
  29 for text. A cell wraps at its spaces; a word longer than its column is cut (`L101`).
- In a cell: `**bold**`, `*italic*`, `~~strike~~`, `[word]{.underline}`, `[word]{.invert}`. `font=` and `size=`
  on a word in a cell do nothing (`M101`): give them to the whole table.

## Tables without a title row

Markdown needs a title row. Leave its cells empty and bobina prints no title and no rule: label on the left, value
on the right, the way receipts print totals.

```markdown
| | |
|---|--:|
| SUBTOTAL | 157,50 |
| **TOTAL** | **176,40** |
```

## Ready-made styles

One word on the line under the table: `{style=receipt}`.

| Style | Looks like | Prints as |
|---|---|---|
| `plain` | the default: bold titles, a solid rule under them | text |
| `receipt` | dashed rules above and below the titles, titles not bold | text and rules |
| `lines` | as `plain`, and a dotted line between rows | text and rules |
| `grid` | a full grid: the lines between columns go in their column of space, the border takes 1 column | image |
| `header-invert` | white titles on a black band, no rule | the titles as an image |
| `zebra` | every other row on light grey dots | the grey rows as images; ⚠ not tested on paper (`P301`) |

A table without titles gets no title band or rule in any style. Text prints faster and sharper than an image.

## Smaller letters: `font=` and `size=`

`{font=Terminus size=16px}` draws the table as an image in that font (bundled: Terminus, Spleen, IBM Plex Mono,
Atkinson Hyperlegible, Barlow Condensed, DejaVu Sans; sizes as in [FORMAT §5](../FORMAT.md#5-sizes-)). A column is
as wide as the font's `0`, so the counts below hold for monospace fonts; a proportional font lines its columns up
by the dot. Columns on one line, the spaces between columns included:

| Font | 58 mm (384 dots) | 80 mm (576 dots) |
|---|---|---|
| printer font | 32 | 48 |
| Terminus 12px (its tested minimum) | 64 | 96 |
| Terminus 14px | 54 | 82 |
| Terminus 16px | 48 | 72 |
| Terminus 20px | 38 | 57 |
| IBM Plex Mono 16px | 40 | 60 |
| Spleen 24px (the printer font's look) | 31 | 47 |

`size=` alone uses Terminus (`2x`, `3x`: the printer font's look, drawn). Spleen is cut for 24px: smaller, use
Terminus. A font below its tested minimum gives `F201`, one not found `F203`; `header-invert` titles under 20px
give `F204`.

## Turned tables

A table whose columns cannot keep 6 characters each prints **turned** along the paper, the titles on the right
(`orientation=auto`, the default; note `L106`). `orientation=vertical` always turns it (`width=half` places it),
`orientation=horizontal` never does. A turned table keeps its style and font.

## When something is wrong

bobina prints anyway and says what to fix (`bobina check FILE` shows the same list without printing):

| Code | When | Example message |
|---|---|---|
| `M101` | an unknown style; it prints `plain` | `style=recibo: unknown style; plain, receipt, lines, grid, header-invert, zebra` |
| `M101` | a value in capitals; it prints `plain` | `style=RECEIPT: values are lowercase` |
| `M101` | something a table does not take | `leading= does nothing on a table` |
| `L101` | a word longer than its column was cut | `word 'DESCRICAO…' split at 8 columns in a table` |
| `L106` | the table was turned | `a table of 9 columns does not fit across the paper: it prints VERTICALLY…` |

## A shop receipt, whole

```markdown
## Café Example {.center}

| Qty | Item | Price |
|--:|---|--:|
| 2 | Espresso | 18,00 |
| 1 | Bagel | 39,00 |
| 1 | Lemon pie | 28,00 |
{style=receipt}

| | |
|---|--:|
| SUBTOTAL | 85,00 |
| SERVICE 10% | 8,50 |
| **TOTAL** | **93,50** |
```

Seven columns on 58 mm, the way supermarkets print: give the item table `{style=receipt font=Terminus size=16px}`.
