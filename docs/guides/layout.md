# Layout: boxes

A **box** draws a frame around blocks. It opens with a line of three colons (`:::`) and its settings in braces,
and closes with a line of colons only. Inside, write any Markdown: text, lists, headings, QR codes, images,
tables, other boxes, [columns](layout-columns.md) (blocks side by side, `:::: {.columns}`).

```markdown
::: {.box title="TABLE"}
# 109 {.center size=huge}
:::
```

- A line of three or more colons with `{…}` after it opens a block; `::: box` (one word) is `::: {.box}`.
- A line of colons only always closes the innermost open block. When blocks are inside each other, give the outer
  one more colons (`::::`) so the file reads well: they change nothing.
- Names and values are lowercase. A value needs quotes only when it has a space: `title=TABLE`,
  `title="TABLE 4"`.
- On GitHub and Obsidian the `:::` lines show as text; the content still reads.

## Settings

`::: {.box}` draws a 2-dot frame with one letter of room inside.

| Setting | What it does |
|---|---|
| `title="…"` | a title; without it, only the frame |
| `title-style=border` | the title cuts the top line, centred (the default) |
| `title-style=inside` | the title is the first line inside, bold |
| `title-style=band` | the title in white on a black band across the top |
| `.dashed` `.dotted` `.double` | the frame's line (`.solid` is the default) |
| `thickness=3` | a thicker line, in dots (at least 2: `B101`) |
| `width=half` | a narrower box: `full` (the default), `half`, `third`, `50%`, `30mm`, `16ch` (letters) |
| `.center` `.right` | where a narrower box goes (on the left by default) |
| `.shade` | a light grey background, kept off the letters |
| `.invert` | all black, frame and room too; what it holds prints white, its images inverted (**⚠ not tested on paper**) |

A long title wraps into more lines with `band` and `inside`; on the border it is cut with "…" (`L109`).

## Recipes

A table plate, the number as big as the printer font goes (`huge`, 8 mm):

```markdown
::: {.box title="TABLE"}
# 109 {.center size=huge}
:::
```

The waiters who served, on a band:

```markdown
::: {.box title="SERVED BY" title-style=band}
- Ana
- Bruno
:::
```

An order slip, dashed, the title inside:

```markdown
::: {.box .dashed title="Order 42" title-style=inside}
2x Coffee
1x Cheese bread
:::
```

A box in a box (four colons outside, so the file reads well):

```markdown
:::: {.box title="ORDER"}
Table 4 · 2 people

::: {.box .shade width=half .center}
PAID
:::
::::
```

## On paper

- A box is never wider than its room (the paper, or what a quote or a list item leaves; `width=half` is half of
  it) and always keeps 4 letters inside: a frame too thick for it is drawn thinner (`M101`). Its frame and room take one letter on each side, so a full box holds 30
  letters on 58 mm paper (32 without it) and 46 on 80 mm (48), on the same grid as the text around it.
- The whole box prints as one image: the frame shares its lines with the text, so the text inside is drawn in the
  printer font's look (the same dots). A QR code inside is sized as an image, to fit the room.
- `bobina view FILE` shows the box in the terminal: `┌─ TABLE ─┐`, the text inside, `└───┘` (`.invert`: `┏━┓`).
- In an `.invert` box, `.invert` on an image swaps it back (a screenshot's white logo on black stays so); on text it
  does nothing (`M101`). Thin or small raster text closes up white on black (`F204`). A code stays black on
  white in a white margin, so it scans (`Q114`).
- Tested on paper (MTP-II, 18/11): a border title and a band, a dashed frame, the grey, as the preview. Text on
  `.shade`: prefer bold, thin strokes fade on the grey (the top bar of a "T").

## When something is wrong

bobina prints anyway and says what to fix (`bobina check FILE` shows the same list without printing):

| Code | When | Example message |
|---|---|---|
| `M101` | an unknown name or value | `title-style=strip` → border, inside or band |
| `M101` | a value with spaces and no quotes | `title=TABLE 4: a value with spaces goes in quotes` |
| `M101` | a line of colons with nothing open | `a line of ::: with no ::: block open: ignored` |
| `M105` | a block that is never closed | `::: {.box} at line 1 is never closed: the heading 109 and the box at line 4 are inside it` → add a line of `:::` where it should end |
| `L109` | a title longer than the border holds | `title "…" is longer than the border holds (26 letters): cut with …` |
| `B101` | a line thinner than 2 dots | `box thickness 1 prints broken` |
