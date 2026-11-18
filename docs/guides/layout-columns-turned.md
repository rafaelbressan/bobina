# Layout: turned columns

`:::: {.columns orientation=vertical}` lays the [columns](layout-columns.md) out **along the roll**: a label read
sideways, the paper's width as its height. A shelf label, the name on the left and a big price on the right:

````markdown
:::: {.columns orientation=vertical length=100mm valign=middle}
::: {.column width=60%}
## Café Torrado e Moído

500 g · Extraforte

```barcode {type=ean13}
789123456789
```
:::
::: {.column width=40%}
R$ 18,90 {size=3x}
:::
::::
````

It prints turned like a [turned table](tables.md#turned-tables), clockwise: its top on the right of the
paper, its first column first. Read it with that edge up.

## Length and height

| Setting | What it does |
|---|---|
| `length=72mm` | the default: the label's length along the roll (`7.2cm`, `575` dots); at most 300 mm |
| `length=auto` | as long as the columns' content needs: text on as few lines as it can, an image as big as fits the height |

- The label's height is the paper's printable width: 48 mm (384 dots) on 58 mm paper, 72 mm on 80 mm.
- Widths share the length as standing ones share the line: a 72 mm label has 47 letters, so `60%` and
  `40%` get 28 and 18 of the 46 left by the gap. `12ch`, `30mm` and `auto` work as they do standing.
- `valign=` places each column across the height, as read: `top` is the paper's right edge, `bottom` its left.

## Content taller than the label

Nothing is lost:

- `wrap=wrap`: a column that does not fit (the widths, or its content taller than the label) starts a new label,
  printed after this one; `wrap=wrap-reverse`, before it (`L110`).
- Otherwise what does not fit goes on in the next label, each column at its place, cut between lines and blocks
  (`L112`). A dashed line between 3 mm of white parts two labels.
- A single block taller than the label: a QR code or Data Matrix gets the largest whole module that fits (`Q101`
  when it may not scan), in a box too; a barcode shorter bars. Only a picture is drawn smaller: text and codes go
  on in the next label, cut at a blank line near the edge, never through a code (`L112`), else across its lines
  (`L114`, a warning); a code taller than the label is cut and will not scan (`Q101`, `Q108`).
- A barcode's bars run along the paper once turned: like a [vertical one](../FORMAT.md#62-barcodes-), module 4
  and 10 modules of white each side (an EAN-13: 58 mm of column), else `Q108`.

## Good to know

- In a quote or list they stand (`M101`).
- `rotate=90` on standing columns turns their picture; bobina suggests `orientation=vertical` (`L113`). On
  turned columns `rotate=` and `.flip` are ignored (`M101`).
- `bobina view FILE` shows it as read, under a `↻`.
- Tested on paper (MTP-II, 18/11): the label above; its EAN-13 scans.
