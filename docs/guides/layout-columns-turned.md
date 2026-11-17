# Layout: turned columns

`:::: {.columns orientation=vertical}` lays the [columns](layout-columns.md) out **along the roll**: a label read
sideways, the paper's width as its height. A shelf label, the name on the left and a big price on the right:

````markdown
:::: {.columns orientation=vertical valign=middle}
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

It prints turned the way a [turned table](tables.md#turned-tables) does, clockwise: the label's top on the right
of the paper, its first column printed first. Read it with that edge up.

## Length and height

| Setting | What it does |
|---|---|
| `length=72mm` | the default: the label's length along the roll (`7.2cm`, `576` dots); at most 300 mm |
| `length=auto` | as long as the columns' content needs: text on as few lines as it can, an image as big as fits the height |

- The label's height is the paper's printable width: 48 mm (384 dots, 16 lines of text) on 58 mm paper, 72 mm on
  80 mm.
- Widths share the length as they share the line of standing columns: a 72 mm label has 47 letters, so `60%` and
  `40%` get 28 and 18 of the 46 left by the gap. `12ch`, `30mm` and `auto` work as they do standing.
- `valign=` places each column across the height, as read: `top` is the paper's right edge, `bottom` its left.

## Content taller than the label

Nothing is cut:

- `wrap=wrap`: a column that does not fit (the widths, or its content taller than the label) starts a new label,
  printed after this one; `wrap=wrap-reverse`, before it (`L110`).
- Otherwise what does not fit goes on in another label printed after it, each column at its place, cut between
  lines and blocks; a single block taller than the label (a big image) is drawn smaller to fit it (`L112`).

## Good to know

- Only columns outside quotes and lists turn (`M101`); there they stand.
- `rotate=90` on columns turns the picture of them standing across the paper; bobina suggests
  `orientation=vertical` (`L112`).
- `bobina view FILE` shows the label standing, as read, under `↻ columns printed turned, top on the right`.
- ⚠ Not tested on paper yet.
