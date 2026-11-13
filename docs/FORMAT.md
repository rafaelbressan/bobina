# The `.bob.md` format — `bob/1` (draft v0.4)

Status: **draft**. Becomes `bob/1` once frozen. Every feature below is marked
**✓ implemented** (in bobina v0.1, covered by tests) or **◇ planned** (part of the format, not implemented yet;
using it gives the note `M103` or `M102`, never an error).

A `.bob.md` file describes a print for a thermal roll printer. It is valid Markdown — it reads well on GitHub
or Obsidian — and it maps predictably onto narrow, low-resolution printers.

## 0. Principles

- **Plain Markdown first.** Any Markdown file is a valid `.bob.md`.
- **Readable over terse.** Names are full English words (`invert`, `align=center`), never codes.
- **Reuse standards.** CommonMark + Pandoc-style attributes for markup, Jinja for variables, Unicode CLDR for
  dates and numbers, BCP 47 for languages, IANA for time zones.
- **The document says what, the printer profile says how.** Native command or raster, dots per millimetre and
  every limit come from the profile, so the same file prints on 58 mm and 80 mm, 203 and 300 dpi.
- **Nudges, not blocks.** Anything questionable prints with a warning that carries a suggestion and the test
  that justifies it. Only security violations stop a print (§9).
- **What you check is what you print.** The preview is the exact dot pattern sent to the printer.

File extension: **`.bob.md`** (canonical); `.bob` is accepted. Encoding: UTF-8.

## 1. Front matter (optional) ✓

```yaml
---
bob: 1                         # format version (informational for now)
profile: mtp-ii-58             # printer profile; the CLI or the printer config can override it
locale: pt-BR                  # BCP 47: month names, numbers and money, all in it (`lang:` too); default: the machine's (§7.1)
timezone: America/Sao_Paulo    # IANA; default: the system zone
align: left                    # default alignment: left | center | right | justify
size: normal                   # default text size (§5)
fonts:                         # font roles and aliases (§4)
  body: native
  title: native
  code: IBM Plex Mono
  hand: Z003
image: { dither: floyd-steinberg, gamma: 1.8 }   # photo defaults (§6.5)
tasks: { done: strike }        # strike (default) | check | plain (§2)
counters:                      # persistent sequences (§7.3)
  ticket: { start: 1, format: "A-{:03}" }
allow: [F301]                  # nudge codes accepted for this document (silenced)
template: receipt              # fill a template (§8); the other keys become its fields
labels: { pt: { total: Total } }   # override a template's fixed labels
---
```

Every key is optional. Any other key is a **variable** available to the body (`shop: Padaria` → `{{ shop }}`).

## 2. Markdown ✓

| Markdown | Result |
|---|---|
| `#`, `##`, `###` (and deeper, styled as `###`) | headings in the **printer font**: 2×2 bold, 1×2 bold, bold (profile `native.headings`); a raster font with `fonts.title` |
| paragraph | word-wrapped by bobina, never by the printer (the printer splits words) |
| a newline inside a paragraph | a **line break** (as in Obsidian), not a space |
| `**bold**` `*italic*` `~~strike~~` `` `mono` `` | inline styles; italic and strike are drawn as raster on printers without them |
| `- item`, `1. item`, nested lists | bullet `•`, right-aligned numbers; nested items and continuation lines align under the item text |
| `- [ ] todo`, `- [x] done` | drawn checkboxes; done items struck through. `tasks.done: check` = box only, `plain` = `[ ]`/`[x]` in the printer font (fastest) |
| `\| a \| b \|` tables | monospace grid, header bold with a rule under it, column alignment from `:--`/`--:`, **stretched to the paper width** (the first column absorbs the slack); `{.compact}` keeps it narrow |
| `---` | divider (§3) |
| `> quote` | `│ ` prefix |
| `![alt](photo.jpg){…}` | image (§6.5) |
| `:fragile:`, `:wash-30:` … | an **icon**, 2 columns (`{size=3x}`: big); names and meanings: [guides/icons.md](guides/icons.md). Never from code or data; unknown: `M161` |
| `<!-- comment -->` | ignored |
| `\*`, `\#` … | CommonMark escapes: the character is printed literally |

## 3. Attributes `{…}` ✓

Pandoc syntax: `.class`, `key=value`, `key="quoted value"`. They go:
- at the end of a heading or paragraph line: `# SALE {.invert .center}`
- on a span: `Total: [R$ 42,00]{.bold size=large}`
- on a line of their own: it applies to the **block above** (tables, images, objects): a table followed by `{.compact}`
- on a divider: `--- {.dashed thickness=2}`

| Class | Effect |
|---|---|
| `.left` `.center` `.right` `.justify` | alignment (justify spreads spaces on the character grid, or pixels in raster) |
| `.bold` `.italic` `.underline` `.strike` | style for the whole block or span |
| `.invert` | on a block: a **continuous** white-on-black band (raster); on a span: inverted words (native) |
| `.flip` | upside down (native `ESC {`, rows sent in reverse order; raster when a row is not native) |
| `.mono` | monospace (the printer font is already monospace) |
| `.compact` | tables: do not stretch |
| `.solid .dashed .dotted .double .wavy .cut` | divider style (`.cut` adds scissors: a place to tear) |

| Key | Effect | Status |
|---|---|---|
| `size=` | §5 | ✓ |
| `font=` | a role, alias or family name (§4) | ✓ |
| `align=` | same as the alignment classes | ✓ |
| `rotate=` | clockwise, like CSS: `90`, `180`, `270` exact; other angles allowed (nudge `B102`); always raster | ✓ |
| `render=raster\|native` | force how a block is printed (text blocks and QR codes) | ✓ |
| `thickness=` | divider stroke in dots (minimum 2, nudge `B101`) | ✓ |
| `leading=` | space between lines: `leading=18` dots, `18px` or `2mm`. Printer font: line height + N (`ESC 3`) | ✓ |
| `tracking=` | extra space after each character, in dots (≤ 32). Printer font: `ESC SP n`, doubled at 2× width on printers that follow the spec (not at 2× on the MTP-II: profile `native.tracking_unscaled_at`); line breaks use the real width | ✓ |
| `indent=` | left indent: `indent=4` columns, or `indent=3mm` / `24px`; wrapped lines stay aligned | ✓ |

Unknown classes or keys give `M101` and are ignored.

## 4. Fonts ✓

Three levels, from general to specific:

1. **Roles** in front matter — `body` (paragraphs, lists), `title` (headings), `code` (inline `code` in raster blocks).
2. **Aliases** — any other name in `fonts:` (`hand: Z003`), used with `{font=hand}` on a block or a span.
3. **Family names** — `{font="Atkinson Hyperlegible"}`.

`native` (the default for `body` and `title`) is the printer's internal font: fastest, sharpest, lightest on the
battery. Any other font makes that block raster. A native block with a raster span becomes raster too, drawn
with the printer-font look.

Fonts are looked up among the **bundled** fonts first (same result on every machine: Atkinson Hyperlegible,
IBM Plex Mono, Barlow Condensed, Terminus, Spleen, DejaVu Sans), then among installed fonts (fontconfig).
A font that cannot be found falls back to Atkinson Hyperlegible (`F203`).

Quality nudges, from the printed tests of the profile:
- below a font's **tested minimum** → `F201` with the minimum and the evidence;
- an **untested** font: bobina measures its stem at the requested size and warns below 2 dots (`F202`);
- inverted raster text thinner than bold 20 px → `F204`;
- a character the printer font lacks (emoji, arrows, `☐`) → that **line only** becomes raster (`F301`, a note);
  a character no font has → printed as a box (`F302`).

**Other scripts** (Thai, Indic, Khmer, Myanmar, Ethiopic, CJK): the first time a document needs one, bobina
downloads its Noto font (pinned URL, size and sha256; 38 KB for Thai, 4.5 to 8.3 MB for CJK), says so first (font,
OFL license, size, source; `F304`) and keeps it in `~/.local/share/bobina/fonts/` for offline use. No network, or
`bobina config set font_downloads off`: boxes and `F305` (`bobina fonts get thai`, a language or a document). Han
follows `lang:` (ja, ko, zh-TW), else nearby kana or hangul, else Simplified Chinese. These lines, and Arabic or
Hebrew ones, are drawn whole (joined, stacked, right to left), never letter by letter.

`bobina fonts test "FAMILY"` prints a size ladder; `bobina fonts mark "FAMILY" PX` records your minimum.

| Size at 203 dpi | Height | What works (tests F1, F2, R5) |
|---|---|---|
| < 12 px | < 1.5 mm | nothing legible |
| 12–13 px | ~1.5 mm | bitmap fonts made for it (Terminus, Spleen) |
| 14–19 px | ~2 mm | regular sans/mono with a large x-height (Atkinson) |
| ≥ 20 px | 2.5 mm | most fonts, serifs, thin weights, bold inverted text |
| ≥ 28 px | 3.5 mm | script and decorative fonts |

## 5. Sizes ✓

Named sizes are **physical**; the profile converts them with its `dpi`:

| Name | Height | 203 dpi | 300 dpi | Printer font (mtp-ii-58) |
|---|---|---|---|---|
| `small` | 1.5 mm | 12 px | 18 px | 1×1 |
| `normal` | 2.5 mm | 20 px | 30 px | 1×1 |
| `large` | 3.5 mm | 28 px | 41 px | 2×2 |
| `title` | 5 mm | 40 px | 59 px | 2×2 |
| `huge` | 8 mm | 64 px | 94 px | 3×3 |

Exact sizes: `size=20px` or `size=3mm` (raster fonts; the printer font uses the nearest multiplier, `F303`) and
printer multipliers `size=2x`, `size=1x2` (width × height; above 4× prints jagged).

## 6. Objects (fenced blocks)

The info string carries the object type and its attributes: ` ```qr {size=full .right} `.
Objects are centred unless aligned with `.left` / `.right`.

### 6.1 QR code ✓

````markdown
```qr {module=4 ecc=M}
https://example.com
```
````

`module=` dots per module (profile default 4; minimum 3 native, 4 raster → `Q101`), `ecc=L|M|Q|H` (`L` → `Q102`),
`size=full|half|third|30mm` — the largest **integer** module that fits (integer modules keep codes scannable;
native QR stops at 16), `render=raster`, `caption="Menu"` a centred line under the code. Content that does not fit
any QR → `Q109`, nothing printed.

### 6.2 Barcodes ✓

````markdown
```barcode {type=code128}
ABC-123
```
````

`type=code128` (default) `ean13 ean8 upca code39 code93 codabar itf` — native on the printer, with an exact
preview. `module=` (minimum 2), `height=` dots (default 80), `text=below|above|both|none`, `width=full`
(or `.justify`) stretches with the largest integer module (≤ 6). `orientation=auto|horizontal|vertical`:
`auto` turns a barcode wider than the paper into a **vertical** one along the paper, so it is never cut (`Q110`,
a warning, since you may not want it); vertical barcodes are raster with module ≥ 4 along the paper and a
10-module white margin (measured: 2 and 3 did not scan). CODE39 gets the firmware's mod-43 check character in the
bars (not in the text). 1–250 printable ASCII characters; types the profile does not support → `Q106`; weak types
(ITF) → `Q107`.

### 6.3 Payment codes (`pay`) ✓

````markdown
```pay {scheme=upi to="shop@okbank" name="Chai Point" amount=120 note="Order 42"}
```
````

One block for every payment scheme, with the same attributes: `to=` who receives, `name=`, `amount=` (`24.90` or
`24,90`, in the scheme's currency), `ref=` your reference, `note=` text for the payer; a few schemes take an extra
(`city=` Pix, `bic=` SEPA, `currency=` PayPal, `label=` other). `caption=auto|none|"text"`: `auto` prints a line
under the code with the scheme and the amount (`Pix · R$ 10,00`), or the name. The QR attributes (`size=`,
`module=`, `ecc=`) work too. Pix is one scheme like the others: `pay {scheme=pix to=… name=… city=…}` (the old
```` ```pix ```` block is gone: it prints as text with `M102` and the way to write it). Attributes take `{{ }}`, so
a receipt per row carries its own amount. Without `amount=` (or with 0) the code is open: the payer types it.

| Scheme | `to=` | Tested in the app |
|---|---|---|
| `pix` (Brazil, BR Code with CRC16) | Pix key: CPF/CNPJ (check digits verified), e-mail, +55 phone, random key | ✅ banking apps, 05/11 (CPF, e-mail, phone keys) |
| `upi` (India, `upi://pay`; `name=` required) | UPI ID (`shop@okbank`) | ⚠ not tested in a payment app |
| `epc` (SEPA / GiroCode, EPC069-12 v002; `name=` required) | IBAN (check digits verified) | ⚠ not tested in a payment app |
| `promptpay` (Thailand, EMVCo) | phone, 13-digit tax ID or e-wallet ID | ⚠ not tested in a payment app |
| `paynow` (Singapore, SGQR; `name=` required) | UEN or mobile (+65…) | ⚠ not tested in a payment app |
| `bitcoin` (BIP21) | address | ✅ a bitcoin wallet, 09/11 |
| `lightning` | BOLT11 invoice, LNURL or lightning address | ⚠ not tested in a payment app |
| `paypal` `revolut` `wise` `picpay` `mercadopago` | user name or the app's link | ✅ each app, 09/11 |
| `cashapp` `venmo` | `$cashtag` or user name | ⚠ not tested in a payment app |
| `other` (WeChat Pay, Alipay, DuitNow, Yape, QRIS…) | — the payload read from the app's own QR, in the block body | ⚠ reprinted unchecked |

A missing or invalid attribute (an IBAN with a wrong check digit, a UPI ID without `@`, more decimals than the
currency has) gives `Q111` with a working example, and the code is not printed: the rest of the document is, and
the command exits with 9 so a script or agent knows (`--allow Q111` for 0). A scheme nobody has scanned with its
real app gives the note `P302`; scan a print before customers use it (docs/TESTED.md). No brand logos (they need
a licence). What each field means in each scheme, its official name and its limit: `bobina help pay SCHEME`
(`--json` too) and [pay.md](pay.md). A value over a limit is an error (`Q111` says how much to cut), never cut.
An amount that reads two ways (`amount=1.890`: R$ 1.890,00 or R$ 1,89?) is `Q111` too: write `1890`, `1.890,00` or `1.89`.
The same value in `| paymoney`, or in `| currency` without a locale (§7.1), is printed as typed with `M202`.

### 6.4 Data Matrix and PDF417 ✓

````markdown
```datamatrix {size=third}
batch 42
```

```pdf417 {module=2 columns=4}
long text
```
````

Raster (the printer has no native Data Matrix; its native PDF417 does not work). Data Matrix: `module=` (≥ 4),
`size=`. PDF417: `module=`, `ratio=`, `columns=`.

### 6.5 Images ✓

`![alt](photo.jpg){width=50% dither=atkinson gamma=1.5 .left}` or a fence ` ```image {…} ` with the path inside.

- Path relative to the document; `data:image/…;base64,…` embeds the image (≤ 10 MB).
- Formats: PNG, JPEG, GIF (first frame), WebP, BMP, TIFF; **SVG** and **PDF pages** (`page=N`, default 1) are
  rendered straight at the target width (extras `bobina[svg]`, `bobina[pdf]`; missing → `I105`). Vector sources
  default to `dither=threshold` (crisp line art); set `dither=` for photos inside a PDF.
- `https://` URLs only when the command line has `--allow-net` (`I103` otherwise); public hosts only,
  no redirects, ≤ 10 MB (`I106`); every fetch is reported (`I104`). A document cannot enable the network.
- `width=` dots or `%` (default: the paper width), `dither=floyd-steinberg|atkinson|bayer|threshold`,
  `gamma=` (defaults from front matter `image:`, then the profile — tuned on printed ramps).
- Images above 40 megapixels are refused (`I101`), unreadable ones give `I101` and the rest prints.

### 6.6 Text ✓

` ```text ` (or no type) prints the lines as they are, in the printer font, wrapping only lines wider than the paper
(`L103`). `rotate=90` turns the block. Any other language name (` ```python `) prints the same way with `M102`.

### 6.7 Raw bytes ✓

````markdown
```raw
1b 40   # hex bytes sent as-is; comments after #
```
````

The escape hatch: no checks, no preview (`P201`). Never accepted from variables (§7.4).

### 6.8 Planned objects ◇

` ```table {columns="auto,4ch,8ch" header=invert} ` (tables with explicit widths and styles), ` ```pay {scheme=…} `
(UPI, SEPA/EPC, PromptPay, PayNow, profile links) and shapes.

## 7. Variables (Jinja) ✓

The body is a **Jinja** template (the subset implemented by minijinja, so other languages can implement `bob/1`),
evaluated once in a **sandbox**: no files, no network, no imports. Comments are `<# … #>` (so `{#id}` stays a
Pandoc attribute).

Available: front-matter variables, template fields, `now` and `today` (time zone aware), `seq` (§7.3), `range`,
`namespace`, `label` (§8), and Jinja's built-in filters plus:

| Filter | Example (`locale: pt-BR`) |
|---|---|
| `date(style\|pattern)` | `{{ now \| date("full") }}` → quinta-feira, 5 de novembro de 2026 |
| `time`, `datetime` | `{{ now \| datetime("short") }}` → 05/11/2026 09:49 |
| `add(days=, hours=, minutes=, weeks=, months=, years=)` | `{{ now \| add(days=7) \| date("dd/MM") }}` → 12/11 |
| `currency(code)` | `{{ 1234.5 \| currency("BRL") }}` → R$ 1.234,50 |
| `number(decimals)`, `percent` | `{{ 1234.5 \| number }}` → 1.234,5 |
| `int`, `float` | `{{ "3 dias" \| int }}` → 3 |
| `letters` | `{{ 28 \| letters }}` → AB |
| `markdown` | interprets a value as Markdown (§7.4) |
| `upper`, `lower`, `capitalize`, `title`, `trim`, `truncate(n)`, `replace(a, b)` | Jinja's own: `{{ "arroz" \| upper }}` → ARROZ |
| `titlecase` | by the document language: `{{ "arroz DA fazenda" \| titlecase }}` → Arroz da Fazenda (`en`: Bread of the Day) |
| `deaccent` | `{{ "São João" \| deaccent }}` → Sao Joao |
| `camel`, `pascal`, `snake`, `kebab`, `slug` | `{{ "Arroz da Fazenda" \| snake }}` → arroz_da_fazenda (accents removed) |
| `smallcaps` | `{{ "Arroz" \| smallcaps }}` → Aʀʀᴏᴢ (Unicode small capitals: printed as an image line, `F301`; accented letters stay lowercase) |

Number filters read what a person types: `24.90`, `24,90`, `R$ 1.890,00`, `3 dias`. A value that is not a number
or is ambiguous (`1234.567`, `3 5`) gives `M202`: `currency`/`number`/`percent` print it as typed, `int`/`float`
give their default (0) and `add` counts it as 0, never a silent R$ 0,00. `percent` reads `10%` as 0.10.

Every filter keeps data as data: `{{ value | upper }}` from `--data`/`--set` is still printed literally and still
cannot become an image path (`M312`), and neither can a value joined into a path (`'img/' ~ value`).

### 7.1 Dates and languages

One locale for dates, numbers and money (`US$ 24,90`, `09/11/2026` in `pt-BR`): the document's `locale:`, else
`locale` in config.toml (`bobina config set locale TAG`), saved on first use from the time zone (`America/Sao_Paulo`:
`pt-BR`; `LANG`'s language if official there) or else a non-English `LANG`, said once (`M203`); else English
(`M204`). Only the document's `locale:` reads a typed `1.890` as a price (else `M202`); unknown: `M205`. No font
for the script (downloads off): English words, its country's formats (`en-TH`, `F306`).

Styles `short`, `medium`, `long`, `full` follow the document `locale` (the same line prints "Thursday, November 5,
2026" in `en-US`). Patterns use CLDR syntax (`dd/MM/yyyy HH:mm`); a pattern containing `%` is strftime, with month
and day names still localized. Moment.js tokens are not supported: `YYYY` and `DD` give `M201`.

### 7.2 Undefined variables

Printed as empty with `M130`.

### 7.3 Counters

A counter is an integer kept between prints; its appearance is formatting.

```yaml
counters:
  ticket: { start: 1, step: 1, format: "A-{:03}" }   # A-001, A-002 …  (one {:spec}, Python format)
  senha:  { format: "Senha {:d}" }                   # Senha 1, Senha 2 …  (the text goes in the format)
  box:    { start: 1, stop: 26, style: letters }     # A … Z, then M140 (wrap: true restarts)
  code:   { start: 255, style: hex }                 # FF, 100 …
```

| Write | Meaning |
|---|---|
| `{{ seq.ticket }}` | **one** value for the whole print (the same in the title and in the QR) |
| `{% for n in seq.ticket.take(10) %}` | ten new values in one print |
| `{% for n in range(1, 11) %}` | a local loop, not persisted |

Previews, `check` and `--dry-run` only show the next values; they take nothing. A print **reserves** its values when
it is built, so the confirmation screen shows the numbers that will be printed and two prints at the same time never
get the same number. If the job is then not printed (you quit, the printer is unreachable, the build fails), the
values go back, unless another print took numbers after them: then they stay skipped. A number is never printed
twice; a cancelled job may leave a gap (a job that stopped halfway also keeps its numbers; one you stop between
labels keeps those of the labels that printed). The CLI adds
`--repeat N` (N renders, new values each) and `--copies N` (identical copies); `bobina seq` lists and resets them,
and `bobina seq set NAME N` starts one at N, even before its first print.

### 7.4 Data is literal

**The author is trusted; data is not.** Values from `--data` (CSV), `--set` and any future server input:
- are inserted as **literal text** after Markdown parsing: `# PROMO` prints a hash, `{.invert}` prints braces,
  `:fragile:` prints the word;
- are never evaluated as templates;
- can never produce a `raw` block (`M314` for variables inside `raw`), choose an image path (`M312`), or carry
  control characters (removed from all text and barcode data before encoding).

`{{ value | markdown }}` opts one value in: its `raw` blocks are removed (`M121`), and for data values images too
(`M122`). Template violations are **errors**: files (`M310`), unsafe attributes (`M311`), more than 2000 loop
iterations or 2 MB of output (`M313`), template paths outside the document folder and
`~/.config/bobina/templates` (`M315`). See `docs/SECURITY.md`.

## 8. Templates ✓

A template is a `.bob.md` whose front matter declares its fields:

```yaml
---
fields:
  shop:  { required: true, example: "Padaria do Zé" }
  items: { required: true, type: table, columns: [item, qty, price] }
  pix:   { help: "Pix key: adds a Pix QR for the total" }
  date:  { default: "{{ now | datetime('short') }}" }
labels:
  en: { total: TOTAL, thanks: "Thank you!" }
  pt: { total: TOTAL, thanks: "Obrigado!" }
---
```

- `required: true` → empty gives `M131` (a warning in the confirmation screen); a `default:` may be an expression.
- `was: [old_name]` → a document that still uses a renamed field gets `M101` naming the new one.
- `labels` are picked by the document language (`{{ label.total }}`) and overridable with `labels:` in the document.
- Using one: `template: receipt` in front matter, the other keys are the fields. Lookup: a `.bob.md` path inside the
  document folder, `~/.config/bobina/templates/NAME.bob.md`, then the built-ins: `receipt` (items, total, optional
  Pix), `label`, `todo`, `card`, `note` and a gallery of shop tags (`bobina template list`; recipes in
  [guides/templates.md](guides/templates.md)).
- `--ask` (on `print`, `check`, `preview`) asks the fields still missing on the terminal, in the order the
  template declares them, showing `help`, `example` and the default (`[automatic]` for expressions);
  `type: table` fields take one row per line (`item; qty; price`, empty line to finish). A document without
  `fields:` gets its undeclared `{{ variables }}` asked. Answers are data, exactly like `--set` (literal,
  never Markdown or template code); fields already set by the front matter, `--set` or `--data` columns are
  not asked; a required field left empty prints with `M131`. No terminal → usage error.
- `bobina template show NAME` lists the fields; `bobina template new NAME FILE` writes a starter with every field
  marked `# required` / `# optional`.

## 9. Rendering contract

- bobina decides every line break; the printer never wraps.
- Per line, native when the profile says the printer does it well, raster otherwise — a raster line looks like the
  native ones (the printer font is emulated); `render=` forces it.
- A print starts with the profile's top margin (fixes the faded start), separates blocks by `block_gap_dots`, and
  ends with enough feed for the last line to clear the tear bar with room to spare (profile `feed_after_dots`,
  or the printer's measured `tear_mm` + 6 mm; `tear_margin_mm` in the printer's config.toml changes the 6 mm).
- Errors stop a print only for parsing (`DOC`) and security (`M31x`); everything else is a nudge.

## 10. Conformance

`spec/conformance/` holds tickets — the printed test series rewritten as `.bob.md` — with their expected bitmaps
for profile `mtp-ii-58` (`BOBINA_NOW=2026-11-05T09:49:00`). An implementation conforms to `bob/1` when it renders
every ticket to the same bitmap. Printing one and running `bobina calibrate compare PHOTO TICKET` measures how close
a printer's paper is to the preview.

## Appendix A — nudge codes

Categories: **B** drawing · **F** fonts · **Q** codes · **L** layout · **I** images · **P** printer · **M** markup and
templates. `bobina help nudges` prints the same list; `allow: [CODE]` or `--allow CODE` silences one.


Errors (`E…`) stop the job: nothing prints. Exit codes are in `docs/CLI.md`.

| Code | Severity | Meaning |
|---|---|---|
| `E101` | error | command line usage |
| `E102` | error | this command takes one document |
| `E103` | error | a job option was given twice with different values |
| `E104` | error | --then / --compact misuse |
| `E105` | error | --last / --again misuse, or nothing printed yet |
| `E106` | error | only one part can read stdin |
| `E107` | error | a terminal is needed (confirmation or --ask) |
| `E201` | error | file not found or unreadable |
| `E202` | error | file type not supported as a target |
| `E203` | error | image, PDF page or page range not usable |
| `E204` | error | network target needs --allow-net |
| `E205` | error | nothing to print |
| `E206` | error | saved label (library) problem |
| `E207` | error | unknown template, profile, font or help topic |
| `E208` | error | output file problem (exists, format) |
| `E209` | error | a bobina state file is damaged or busy (counters, paper, library, config) |
| `E301` | error | data file unreadable or in an unsupported format |
| `E302` | error | no data rows (or none match --rows/--where) |
| `E303` | error | unknown column or sheet |
| `E304` | error | invalid value (--rows, --copies-from, --set, length) |
| `E305` | error | job too large (1000 labels, 100 copies) |
| `E401` | error | no printer configured or unknown printer |
| `E402` | error | printer unreachable |
| `E403` | error | printer not ready (paper, cover, error) |
| `E405` | error | printer busy: another bobina job kept it too long |
| `E406` | error | `bobina init` found no printer to set up |
| `E501` | error | document error |
| `E601` | error | no AI found, or an unknown AI name |
| `E602` | error | the AI did not answer |

Nudges:

| Code | Severity | Meaning |
|---|---|---|
| `B101` | warning | stroke thinner than 2 dots prints broken |
| `B102` | note | free rotation angles look jagged |
| `F201` | warning | font below its tested minimum size |
| `F202` | warning | untested font with strokes thinner than 2 dots |
| `F203` | warning | font not found, a bundled font was used |
| `F204` | warning | inverted raster text too thin or small |
| `F205` | warning | font size out of range (6 to 400 px), clamped |
| `F301` | note | glyph not in the printer font: line printed as an image |
| `F302` | warning | glyph missing in every available font |
| `F303` | note | size not supported natively, nearest native size used |
| `F304` | note | font for another script downloaded (once; used offline from then on) |
| `F305` | warning | font for this script not downloaded (off, or no network): letters print as boxes |
| `F306` | note | no font for the locale's script (none, or downloads off): English words, its formats |
| `Q101` | warning | QR module too small to scan reliably |
| `Q102` | warning | QR error correction L reads with difficulty |
| `Q103` | warning | QR wider than the paper |
| `Q104` | warning | barcode wider than the paper |
| `Q105` | note | barcode preview is approximate (no encoder for this type) |
| `Q106` | warning | barcode type not supported by this printer |
| `Q107` | warning | barcode type prints but phones struggle to read it |
| `Q108` | warning | barcode module too thin to scan |
| `Q109` | warning | invalid barcode content |
| `Q110` | warning | barcode turned vertical to fit the paper |
| `Q111` | warning | payment code not built: an attribute is missing or invalid (the code is left out, the rest prints, exit 9) |
| `L101` | warning | word longer than the line was split |
| `L102` | note | long print |
| `L103` | warning | preformatted line longer than the paper was wrapped |
| `L104` | warning | rotated block wider than the paper was cropped |
| `L105` | warning | nothing printable: every block was skipped |
| `I101` | warning | image not found, unreadable or in an unsupported format (the hint lists the formats) |
| `I102` | note | image downscaled to the paper width |
| `I103` | warning | network image skipped: fetching shows the server when you print, and a shared document could reach your local network; add `--allow-net` if you trust it |
| `I104` | note | image fetched from the network (the server sees the print) |
| `I105` | warning | PDF/SVG support not installed |
| `I106` | warning | network source refused (private address, redirect, type, size) |
| `I107` | warning | `![](a b.png)` is not an image (path with a space): write `![](<a b.png>)` |
| `I108` | warning | image outside its folder and `image_dirs` (`--sandbox`, MCP) |
| `P101` | warning | the paper roll is almost over (estimate) |
| `P102` | warning | the print is longer than the paper left on the roll (estimate) |
| `P103` | warning | the roll is not as wide as this printer's paper (`paper new --width`; recorded anyway) |
| `P104` | note | roll length not set: no paper estimate |
| `P105` | note | `--compact`: labels print at once, without stops |
| `P106` | note | `--step` without a terminal: labels print at once |
| `P201` | warning | raw bytes bypass every check and are not previewed |
| `P301` | note | this job uses a feature not tested on paper yet |
| `P302` | note | a payment code nobody has scanned with its app yet |
| `P401` | note | no Bluetooth or USB search here (says why) |
| `P402` | note | the name does not settle the profile: one was taken |
| `P403` | warning | a USB printer this user cannot write to |
| `P404` | warning | config.toml names a profile bobina does not know |
| `M101` | warning | unknown attribute |
| `M102` | note | unknown block type, printed as preformatted text |
| `M103` | note | attribute not implemented yet (ignored) |
| `M120` | note | field rendered as Markdown |
| `M121` | warning | raw block removed from a variable |
| `M122` | warning | image removed from a --data/--set value |
| `M130` | warning | undefined variable printed as empty |
| `M131` | warning | required template field is empty |
| `M140` | warning | counter passed its stop value |
| `M150` | warning | `--join`: rows of the main source without a match (their joined fields print empty) |
| `M151` | warning | `--join`: the joined source repeats a key (the first row is used) |
| `M152` | warning | `--join`: a column exists in two sources; `{{ col }}` uses the main one, `{{ b.col }}` the other |
| `M153` | warning | data values lost: a row with more fields than the header, or values under an empty header |
| `M154` | warning | the data header repeats a column name (the last one is used) |
| `M155` | note | a data source was renamed because a column has its name (`produto.csv` with a `produto` column → `produto_src`) |
| `M156` | note | an option has no effect here (`--sheet` on a CSV, `--repeat` with `--data`) |
| `M157` | warning | `--set` replaces a data column of the same name in every row (decided: what you type wins) |
| `M158` | note | data columns renamed to names usable in `{{ }}`: `Product Name` → `product_name`, `Preço` → `preco`; `{{ row['Product Name'] }}` keeps the exact name |
| `M159` | warning | two data columns would get the same usable name; the first keeps it |
| `M160` | note | Excel formula cells without a saved value print empty |
| `M161` | warning | no icon with that `:name:` (printed as written) |
| `M201` | warning | date pattern looks like Moment.js |
| `M202` | warning | a value is not a number, or a date moved out of the calendar (printed as it is) |
| `M203` | note | this machine's locale, from its time zone, saved in config.toml (said once) |
| `M204` | note | no locale for this machine: dates, numbers and money in English |
| `M205` | warning | the document's locale: is not a locale bobina knows (the machine's is used) |
| `M310` | error | templates cannot read files |
| `M311` | error | unsafe template operation |
| `M312` | error | a variable cannot choose a file path |
| `M313` | error | template limit exceeded |
| `M314` | error | variables cannot be used inside raw blocks |
| `M315` | error | template path outside the allowed folders |

## Appendix B — changes

- **v0.4** (2026-11-06): consolidated; every feature marked implemented or planned; `render=` on text blocks;
  `tracking=`, `indent=` and `leading=` in both the printer font and raster fonts; `M103` reserved for planned
  attributes; code sizes, vertical barcodes, Data Matrix, PDF417, Pix details; nudge table.
- **v0.3** (2026-11-05): implementation notes (line breaks, comments, attribute lines, tables, tasks, rotation).
- **v0.2** (2026-11-05): fonts, sizes, Jinja + CLDR, counters, data-literal safety, templates.
- **v0.1** (2026-11-04): first draft.
