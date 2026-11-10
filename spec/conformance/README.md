# bob/1 conformance tickets

Each `NAME.bob.md` here has an expected exact bitmap `NAME.png` for profile `mtp-ii-58`.
An implementation conforms to `bob/1` when it renders every ticket to the same bitmap.
They are the printed test series (docs/printers/mtp-ii-58.md) rewritten as documents, and they run in
`tests/test_golden.py` (`BOBINA_NOW=2026-11-05T09:49:00`, locale from front matter).

Printing one on paper and comparing (`bobina calibrate compare photo.jpg NAME.bob.md`) measures
how faithful the preview is for a printer.
