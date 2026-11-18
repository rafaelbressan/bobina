# Layout: columns

**Columns** put blocks side by side. `:::: {.columns}` holds them, and **every column opens with
`::: {.column}`** and closes with a line of colons only. Inside a column write any Markdown: text, lists,
headings, QR codes, images, tables, [boxes](layout.md), even more columns.

````markdown
:::: {.columns valign=middle}
::: {.column width=40%}
```qr
https://example.com/receipt/276712
```
:::
::: {.column}
CUSTOMER NOT IDENTIFIED
Receipt 276712 · Series 4
15/11/2026 11:33
:::
::::
````

- A line of colons only always closes the innermost open block. Give the columns four colons (`::::`) and each
  column three, and **always close the columns with as many colons as opened them** (`::::`). To open the next
  column write `::: {.column}` again: a bare `:::` there closes the columns (`M101` says so).
- Any `::: {…}` right inside the columns is a column too (`::: {}`); a `::: {.box}` there is a column drawn as a box.
  Text outside every column prints as a column of its own (`M101`).
- Names and values are lowercase; a value needs quotes only when it has a space.

## Settings

| Where | Setting | What it does |
|---|---|---|
| a column | `width=40%` | a share of the text room (the line less the gaps between columns): `40%` and `60%` fill it |
| a column | `width=12ch` `width=30mm` | letters; millimetres as the letters that fit in them |
| a column | `width=auto` | the default: the columns without a width share what is left |
| both | `valign=top` | where shorter content sits: `top` (the default), `middle` (or `center`), `bottom`; on the columns for all of them, on a column for that one |
| the columns | `gap=1ch` | letters between columns (1 by default; `gap=0`) |
| the columns | `wrap=nowrap` | the default: one row; the content squeezes into the columns |
| the columns | `wrap=wrap` | a column that does not fit starts a new row, under the others (`L110`) |
| the columns | `wrap=wrap-reverse` | the same, the new row above |
| the columns | `orientation=vertical` | along the roll, a label read sideways ([turned columns](#turned-columns)) |

## How much fits

Across the paper there are 32 letters of the printer font on 58 mm and 48 on 80 mm; columns take whole letters.
Two columns on 58 mm with one letter between them share 31: 16 and 15 (the first gets the odd letter).

With `wrap=nowrap` nothing moves: text wraps inside its column, QR codes and images shrink to fit it. A QR code
squeezed below the size a phone reads still prints, with `Q101` (it may not scan).

With `wrap=wrap` a column **does not fit** when the widths ask for more letters than the line has, or when its
content needs more than it gets: its longest word, a QR code at the smallest size that scans, a table's narrowest
columns, an image's width in mm. It starts a new row at its own width. The same file can stand side by side on
80 mm and move on 58 mm:

```markdown
:::: {.columns wrap=wrap}
::: {.column width=20ch}
Rua Exemplo, 190 · Botafogo
:::
::: {.column width=20ch}
Mon to Sat 7am–10pm
:::
::::
```

20 + 1 + 20 = 41 letters: on 58 mm the hours print under the address (`L110`); on 80 mm, beside it.

## Turned columns

`orientation=vertical` lays the columns out along the roll: a label `length=` long (72 mm by default, or `auto`)
and as tall as the paper is wide, printed turned like a [turned table](tables.md#turned-tables), its top on the
right. The widths share the length; content too tall for the label goes on in another label, never cut
(`L110`, `L112`). Example, settings and rules: [layout-columns-turned.md](layout-columns-turned.md).

## On paper

- A row of columns prints as one image, the text in it in the printer font's look. Tested on paper (MTP-II,
  18/11): a QR beside two lines at its middle, as the preview; the QR scanned.
- Columns are never wider than their room: the paper, or what a quote, a list item or a box leaves.
- `bobina view FILE` draws the columns side by side, where they are on the paper.

## When something is wrong

bobina prints anyway and says what to fix (`bobina check FILE` shows the list without printing):

| Code | When | Example message |
|---|---|---|
| `M101` | fewer colons closed the columns | `this ::: closes the :::: {.columns} of line 1` → `to close the columns write ::::; to open another column write ::: {.column}` |
| `M101` | text outside every column | `the text is inside :::: {.columns} but outside any column` |
| `M101` | widths too wide, `wrap=nowrap` | `the columns' widths ask for 41 of the 32 letters: each narrowed to 16 + 15` |
| `L110` | `wrap=wrap` moved a column | `column 2 does not fit beside column 1 (the widths ask for 41 of the 32 letters)` |
| `Q101` | a squeezed QR code | `QR module 2 in raster mode: it may not scan` |
| `L111` | no letter left for them (deep in boxes, quotes, lists) | `no room for columns here: what they hold prints one under the other` |
