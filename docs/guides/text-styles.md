# Spans and white text

Two details of styling text ([FORMAT §3](../FORMAT.md)): what a span takes, and how bobina keeps
white text on black readable.

## A span: part of a line

`[words]{…}` styles part of a line. It takes `.bold` `.italic` `.underline` `.strike` `.invert` `.mono`, `font=`
and `size=`; anything else (`.center`, `.shade`, `foo=`) does nothing there and gives `M101`: a whole line's `{…}`
goes at its end.

```markdown
Total: [R$ 42,00]{.bold size=large}
[BRS]{size=2x} {.invert}
```

A line whose words all take one size prints natively at that size (the second line: a 2x band). Sizes mixed on a
line (`Um [BRS]{size=2x} dois`) print that line as an image in the printer font's look: one line as tall as its
tallest part, the words on one baseline. In a table cell a span's `size=` and `font=` do nothing (`M101`): they go
on the table's `{…}` line.

## White text on black is bold when small

Ink spreads into thin white strokes: on the MTP-II (paper, 18/11) white letters of the printer font at 1x (24 dots
tall) closed up, even bold, and a hyphen, one dot tall, disappeared; at 2x they held. So white text on black
smaller than the profile's `raster.invert_bold_below_px` (48 dots) prints bold, and bobina says so (`F206`, a note):
`.invert` lines and words, `title-style=band` box titles, a table's `style=header-invert` titles and its inverted
rows and cells.

- The printer font drawn as an image (bands, tables, box titles): bold, and a dot taller, so its 1-dot strokes are
  2 dots both ways. Native inverted words (`GS B`) get the printer's bold, `ESC E`.
- A raster font: its bold face (white raster text under 20 px still gives `F204`).
- Text already bold stays bold, without the note; `size=2x` (48 dots) and up keeps its weight.
- ⚠ not tested on paper: a job that uses it gets `P301` until a strip passes
  ([docs/printers/strips/inverted-bold.bob.md](../printers/strips/inverted-bold.bob.md)).

The preview shows the bold, as it prints. A printer whose paper holds thin white text can turn it off in its
profile: `raster.invert_bold_below_px = 0` (a copy of the profile in `~/.config/bobina/profiles/`).
