# bobina

Print Markdown on thermal roll printers — receipts, lists, labels, QR codes, payment codes (Pix, UPI, SEPA…), photos —
with calibrated defaults, a preview you can trust, and **nudges instead of blocks**.

```bash
bobina print "# MARKET\n- [ ] milk\n- [ ] bread"
bobina print list.bob.md
bobina template new receipt sale.bob.md && bobina print sale.bob.md
```

Every command that prints shows a **confirmation screen** first (the dry run): a terminal preview
on the real 32-column grid, paper length, counters it will use, and nudges with the evidence
behind them. `p` prints; `--yes` skips it. **Without a terminal (scripts, agents, ssh) add `--yes`**:
otherwise nobody can answer and the print stops with `E107` (exit 7). `-n` shows the screen and prints nothing.
Agents: start at [llms.txt](llms.txt) (or [llms-full.txt](llms-full.txt), everything in one file); a ready skill
is in [skills/bobina/SKILL.md](skills/bobina/SKILL.md).

```
┌─ preview · mtp-ii-58 · 58 mm ──┐
│                                │
│M A R K E T                     │
│                                │
│☐  milk                         │
│☐  bread                        │
└────────────────────────────────┘
 ~3.1 cm of paper · 1 native rows, 2 raster · 2.9 KB
 [p] print   [s] save as…   [q] quit
```

## Why

Cheap 58/80 mm printers are good enough for a lot — if something takes care of their limits.
bobina was calibrated on a minimum-quality printer (Goldensky MTP-II): every default comes from
a printed and photographed test, so what works there works on better printers. You can ask for
anything; bobina only warns, and tells you why (`warning[Q101] … (evidence: N6)`).

- **One engine** for check, preview and print: the PNG preview is the exact dot pattern sent.
- **Native when the printer does it well, raster when it does not** — per line, decided by the
  printer profile (glyphs the font lacks, italic, inverted bands, drawn checkboxes).
- **Readable documents**: plain Markdown plus Pandoc-style attributes. See [docs/FORMAT.md](docs/FORMAT.md).
- **Safe data**: values from CSV or `--set` are printed literally and can never inject Markdown,
  template code or printer commands; templates run in a sandbox.

## Install

```bash
uv tool install bobina        # or: pipx install bobina   (from a checkout: ./install.sh)
bobina printer scan           # find the Bluetooth address
bobina printer add mtp AA:BB:CC:DD:EE:FF
bobina status                 # paper, cover, errors
```

Printer on another machine? `bobina printer add tower --command "ssh tower bobina send --yes -"`.
No printer at hand? `bobina printer add test --path out.bin` appends every job's bytes to `out.bin` (a file
printer: `status` and `paper` need Bluetooth; `bobina printer list` shows where each printer goes).

## The format in one screen

````markdown
---
locale: pt-BR
counters:
  ticket: { start: 1, format: "A-{:03}" }
fonts:
  body: native                 # the printer's own font (fast)
  hand: Z003                   # any alias you like
---
# TICKET {{ seq.ticket }} {.invert .center}

{{ now | date("full") }}        <!-- quinta-feira, 5 de novembro de 2026 -->

- [ ] open task
- [x] done task (struck)

| Item | Qty | Price |
|---|--:|--:|
| Bread | 6 | {{ 4.8 | currency("BRL") }} |

```qr
https://example.com
```

```pay {scheme=pix to="you@example.com" name="Shop" city="Rio" amount=10.00}
```

Signed, [Ana]{font=hand size=32px}

--- {.cut}
````

`bobina help format` has the rest: sizes (`small`…`huge`, physical mm), dividers, barcodes,
Data Matrix, PDF417, images (dither and gamma), rotation, upside-down text, templates and data.

## One label per row

A document with `{{ blanks }}` plus a table (CSV, TSV, JSON, Excel) prints one label per row; the
columns fill the blanks. Step by step: [docs/guides/batch-printing.md](docs/guides/batch-printing.md);
in the terminal: `bobina help data`.

```bash
bobina check jar-label.bob.md --data pantry.csv                 # paper length and problems, nothing printed
bobina print jar-label.bob.md --data pantry.csv --where shelf=A --copies-from jars --yes
bobina print tag.bob.md --data stock.xlsx --sheet Estoque --yes  # a sheet other than the first
bobina print shelf-tag.bob.md --data a=prices.xlsx --join b=catalog.json --on name --yes
bobina print note.bob.md --set produto=Feijão --set validade=2027-01-31 --yes   # one value, no table
bobina preview jar-label.bob.md --data pantry.csv -o 'labels/{product}.png'    # one PNG per label
```

A `{{ name }}` that is not a column prints empty and is reported (`M130`, with the columns the data has).

## Commands

| Command | Does |
|---|---|
| `print [FILE \| "TEXT" \| -]` | render → confirm → print. `--data rows.csv` (above), `--set KEY=VALUE`, `--copies N` (identical), `--repeat N` (new counter values each), `-o job.bin` (save, do not print) |
| `print --last` / `--again` | reprint the last job: identical bytes / re-rendered (new `now` and counters); with `-o FILE` save instead |
| `check FILE` | problems, paper length, native/raster rows, nothing printed (`--data`, `--json` → `{"stats", "problems"}`, `--strict`) |
| `preview FILE \| "TEXT"` | exact PNG (`-o out.png`); `--data rows.csv -o 'dir/{column}.png'` one per label; `--realistic` simulates ink spread |
| `view FILE` | preview in the terminal |
| `edit [FILE] [--template NAME]` | write in your editor, confirm, print |
| `template list \| show \| new` | receipt, label, todo, card, note, and a shop gallery: [guides/templates.md](docs/guides/templates.md) |
| `seq list \| set \| reset` | persistent counters (`{{ seq.NAME }}`); `seq set ticket 100`: the next print uses 100 |
| `printer scan \| add \| list \| use \| remove` | printers live in `~/.config/bobina/config.toml` |
| `status`, `mode [esc\|tspl\|cpcl]` | printer state; command language |
| `calibrate compare PHOTO FILE` | how close the preview is to the paper |
| `calibrate tear` / `calibrate feed` | where the tear bar is; whether feeds after images need the safe mode |
| `paper [new 15m \| used 3m]` | paper left on the roll (the printer only reports "out") |
| `profile list \| show`, `fonts list`, `send FILE.bin` | profiles, tested fonts, raw bytes |

`bob` is the same binary. Short aliases exist for typing (`bobina help aliases`); docs always use
full names. Exit codes: 0 ok · 1 usage · 2 document · 3 strict nudges · 4 unreachable · 5 printer
not ready · 6 language · 7 confirmation needed/declined · 8 security · 9 a payment code left out (Q111).

## Repository

| Path | What |
|---|---|
| `src/bobina/` | the package (engine, layout, ESC/POS, preview, CLI) and built-in profiles, templates, fonts |
| `docs/` | [`FORMAT.md`](docs/FORMAT.md) (the `.bob.md` spec), [`CLI.md`](docs/CLI.md) (commands, options, problems, exit codes), [`SECURITY.md`](docs/SECURITY.md) (threat model), [`guides/batch-printing.md`](docs/guides/batch-printing.md), [`TESTED.md`](docs/TESTED.md) (what was and was not tested on paper) |
| `examples/` | documents and data used by the guides (`examples/batch/`) |
| `spec/conformance/` | test tickets with expected bitmaps — a `bob/1` implementation renders them identically |
| `tests/` | unit, security and golden tests (no printer needed) |
| `docs/printers/` | measured capabilities of each profiled printer (`mtp-ii-58.md`) |
| `contrib/` | Bluetooth boot service for Linux (`install.sh` sets it up) |
| `tools/` | maintenance scripts: public export and personal-data scan |

## Status

Pre-release (v0.x). MIT licensed (bundled fonts keep their own licenses: `src/bobina/fonts/LICENSES.md`). Baseline profile: `mtp-ii-58` (measured); 32 more imported from escpos-printer-db, not measured on paper (`bobina profile list`; calibrate before trusting them). Realistic preview is an estimate until
the profile is calibrated from photos (`preview.calibrated = false`).

## Hardware notes (MTP-II)

| Symptom | Likely cause |
|---|---|
| `printer unreachable` | printer off or asleep: press POWER until the yellow LED is steady |
| Blank output | roll upside down (the side that darkens with a fingernail faces the head) |
| Turns off when printing | battery: charge it; first use: remove the film on the battery contacts |
| Prints garbage | another app sent a different command language (TSPL/CPCL) as text; the MTP-II itself only speaks ESC/POS |
| Self-test | printer off → hold FEED, press POWER, release at the beep |
| The last line stops at the tear bar, or a `--marks tear` line is off | `bobina calibrate tear` (a ruler: tear it and read the mm), then `bobina calibrate feed` (does the printer obey a paper feed right after an image?) |
