---
name: bobina
description: Print on a thermal roll printer with the bobina CLI - receipts, lists, notes, labels, QR codes, one label per row of a spreadsheet. Use when the user asks to print something on their receipt or label printer, to make labels from a CSV/Excel file, to preview a label, or when a bobina command fails.
---

# bobina

bobina prints Markdown on 58/80 mm thermal printers. Paper is real: look before printing, and print only what the
user asked for.

## Before the first print

1. `bobina printer list`: is a printer configured? If not, ask the user (`bobina printer scan`, then
   `bobina printer add NAME ADDRESS`). To try without hardware: `bobina printer add test --path out.bin`.
2. A new printer prints with a safe default. For better results, suggest once: `bobina calibrate tear` (a ruler:
   the user tears it and reads the mm) and `bobina calibrate feed` (three lines: touching or apart).

## Printing

- Look first, without paper: `bobina check FILE` (length, problems) or `bobina view FILE` (terminal preview).
- You have no terminal: always add `--yes` to `print` (otherwise E107, exit 7). Add it only after the user agreed to
  print this; for a long job (many labels, many cm) say the length from `check` first.
- Text without a file: `bobina print "# TITLE\n- [ ] milk\n- [ ] bread" --yes`.
- A document: Markdown plus `{.center}`, `{size=large}`, `{.invert}`; QR with a ```qr block. `bobina help format`.
- One label per row: `bobina print label.bob.md --data rows.csv --yes`; filters and copies: `--where shelf=A`,
  `--copies-from jars`, `--sheet Estoque` (xlsx), `--join catalog.json --on name`, `--set unit=kg`.
  `bobina help data` lists them. A `{{ name }}` that is not a column prints empty and is reported (M130, with the
  columns the data has): fix the document or the column, do not ignore it.
- Several labels on one strip, cut apart by hand: `--compact`; a printed guide line where to cut or tear:
  `--marks cut|tear|both`.
- Images of labels instead of paper: `bobina preview label.bob.md --data rows.csv -o 'labels/{column}.png'`.
- Same again: `bobina print --last --yes` (identical); `--again` re-renders (new date and counters).

## Reading results

- `bobina check FILE --json` (also `print` and `preview`) gives `{"stats": {...}, "problems": [...]}`, problems with `code`, `severity`,
  `message`, `suggestion`. Warnings never block: tell the user what they mean, with the suggestion.
- Exit codes: 0 ok, 1 usage, 2 document, 3 strict, 4 printer unreachable, 5 printer not ready (paper, cover),
  6 command language (another app switched the printer: `bobina mode esc`), 7 confirmation needed (add `--yes`),
  8 security (template sandbox), 9 a payment code was left out (`Q111`: the rest printed; fix the attribute
  and print again).
- `printed on NAME: ~N cm` means the job reached the printer. If the paper came out blank, the roll is in upside
  down (the side that darkens with a fingernail faces the head).

## Do not

- Print to test something: use `check`, `view`, `preview` or a file printer.
- Read or print personal data the user did not give you for this job.
- Reprint after an error without asking: E402 may have printed part of the job ("check the paper").

Docs: README.md, docs/CLI.md, docs/FORMAT.md, docs/guides/batch-printing.md (`llms.txt` indexes them).
