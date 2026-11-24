# White text on black

Ink spreads into thin white strokes: on the MTP-II (paper, 18/11) white letters of the printer font at 1x (24 dots
tall) closed up, even bold, and a hyphen, one dot tall, disappeared; at 2x they held. In an inverted box (24/11)
plain small white text printed thin and faded, bold held up. So white text on black smaller than the profile's
`raster.invert_bold_below_px` (48 dots) prints bold, and bobina says so (`F206`, a note): `.invert` lines and
words, `title-style=band` box titles, everything an `::: {.box .invert}` holds (its lines, lists, columns, tables),
a table's `style=header-invert` titles, its inverted rows and cells and the inverted words in them, black chat
bubbles. A word inverted inside an inverted line or box is black on paper: it stays as it is. Codes in an inverted
box keep their white tile, and images are not text: neither changes.

- The printer font drawn as an image (bands, boxes, tables, columns): bold, and a dot taller, so its 1-dot strokes
  are 2 dots both ways. Native inverted words (`GS B`) get the printer's bold, `ESC E`.
- A raster font: its bold face (white raster text under 20 px still gives `F204`).
- Text already bold stays bold, without the note; `size=2x` (48 dots) and up keeps its weight.
- ⚠ not tested on paper: a job that uses it gets `P301` until a strip passes
  ([docs/printers/strips/inverted-bold.bob.md](../printers/strips/inverted-bold.bob.md)).

The preview shows the bold, as it prints. A printer whose paper holds thin white text can turn it off in its
profile: `raster.invert_bold_below_px = 0` (a copy of the profile in `~/.config/bobina/profiles/`).
