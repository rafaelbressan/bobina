# The `.bob.md` format — `bob/1` (draft v0.4)

Status: **draft**. Becomes `bob/1` once frozen. Every feature below is marked
**✓ implemented** (covered by tests) or **◇ planned** (part of the format, not implemented yet;
using it gives the note `M103` or `M102`, never an error).

A `.bob.md` file describes a print for a thermal roll printer. It is valid Markdown (GitHub and Obsidian
read it) and maps predictably onto narrow, low-resolution printers.

## 0. Principles

- **Plain Markdown first.** Any Markdown file is a valid `.bob.md`.
- **Readable over terse.** Names are full English words (`invert`, `align=center`), lowercase, never codes.
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
locale: pt-BR                  # BCP 47 (`lang:` too): dates, numbers, money; default: the machine's (§7.1)
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
| `**bold**` `*italic*` `~~strike~~` `` `mono` `` | inline styles (table cells too); italic and strike are drawn as raster on printers without them |
| `- item`, `1. item`, nested lists | bullet `•`, right-aligned numbers; nested items and continuation lines align under the item text |
| `- [ ] todo`, `- [x] done` | drawn checkboxes; done items struck through. `tasks.done: check` = box only, `plain` = `[ ]`/`[x]` in the printer font (fastest) |
| `\| a \| b \|` tables | printer-font grid, bold titles and a rule (empty titles: none); one `{…}` under it: `style=plain\|receipt\|lines\|grid\|header-invert\|zebra`, `font=Terminus size=16px` (~48 columns on 58 mm), `.compact`, `orientation=`; `chart=line\|bar\|area\|sparkline` and `data=FILE`: [charts](guides/charts.md); a column's `{width=9ch prefix="R$ "}` ends its title cell: [guides/tables.md](guides/tables.md); a cell's or row's `{.invert}`, `span=all`: [table-cells](guides/table-cells.md); [receipts](guides/receipts.md); `bobina help table` |
| `---` | divider (§3) |
| `> quote` | `│ ` prefix |
| `::: {.box}` … `:::`, `:::: {.columns}` | a frame ([layout](guides/layout.md)); blocks side by side ([layout-columns](guides/layout-columns.md), `bobina help layout`); along the roll: `orientation=vertical` |
| `![alt](photo.jpg){…}` | image (§6.5) |
| `:fragile:`, `:wash-30:` … | an **icon**, 2 columns (`{size=3x}`: big); names and meanings: [guides/icons.md](guides/icons.md). Never from code or data; unknown: `M161` |
| `<!-- comment -->` | ignored |
| `\*`, `\#` … | CommonMark escapes: printed literally |
| `****TOTAL****` | printed with its asterisks (`M106`) |

## 3. Attributes `{…}` ✓

Pandoc syntax: `.class`, `key=value`, `key="quoted value"`. They go:
- at the end of a heading or paragraph line: `# SALE {.invert .center}`; in a paragraph, its line and those above back to the previous `{…}`
- on a span: `Total: [R$ 42,00]{.bold size=large}` (only the span grows; the line prints as an image)
- on a line of their own: it applies to the **block above** (tables, images, objects): a table followed by `{.compact}` (blank line or not)
- on a divider: `--- {.dashed thickness=2}`

`Table 4 {.center}` / `Waiter: Ana {.right}` / `Thanks`: centred, right, left.

| Class | Effect |
|---|---|
| `.left` `.center` `.right` `.justify` | alignment (justify spreads spaces on the character grid, or pixels in raster) |
| `.bold` `.italic` `.underline` `.strike` | style for the whole block or span |
| `.invert` | on a block: a **continuous** white-on-black band (raster); on a span: inverted words (native); on a box: all black. |
| `.flip` | upside down (native `ESC {`, rows sent in reverse order; raster when a row is not native) |
| `.mono` | monospace (the printer font already is) |
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
| `tracking=` | extra space after each character, in dots (≤ 32). Printer font: `ESC SP n`, ×2 at 2× width (not on the MTP-II: `native.tracking_unscaled_at`) | ✓ |
| `indent=` | left indent: `indent=4` columns, or `indent=3mm` / `24px`; wrapped lines stay aligned | ✓ |

Unknown classes or keys and those a block does not take (`leading=` on a table…) give `M101` and are ignored.

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
downloads its pinned Noto font (38 KB for Thai, up to 8.3 MB for CJK), says so first (license, size; `F304`) and
keeps it for offline use. No network, or `bobina config set font_downloads off`: boxes and `F305` (`bobina fonts get
thai`). Han follows `lang:` (ja, ko, zh-TW), else nearby kana or hangul, else Simplified Chinese. These lines, and
Arabic or Hebrew ones, are drawn whole, never letter by letter.

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

The info string carries the type and attributes: ` ```qr {width=half .right} `. Every object (image, code, `pay`,
`contact`) is centred unless `.left`/`.right`; `width=full|half|third|50%|30mm|200` sizes it (codes: the largest
integer module); `caption="…"` follows it unless `caption-align=left|center|right`.

### 6.1 QR code ✓

````markdown
```qr {ecc=M}
https://example.com
```
````

`module=` dots per module (profile default 4; minimum 3 native, 4 raster → `Q101`), `ecc=L|M|Q|H` (`L` → `Q102`),
`width=` (native: module ≤ 16), `render=raster`, `caption="Menu"`. Content that fits no QR → `Q109`, nothing printed.
An image keeps its 2-module quiet zone on the paper (`Q103`: a smaller module). The MTP-II's own QR always
has 5-dot modules (version 3–7): `width=` prints an image that wide; `module=` or more data, an image with `Q113`.

### 6.2 Barcodes ✓

````markdown
```barcode {type=code128}
ABC-123
```
````

`type=code128` (default) `ean13 ean8 upca code39 code93 codabar itf` — native on the printer, with an exact
preview. `module=` (minimum 2), `height=` dots (default 80), `text=below|above|both|none`, `width=` (module ≤ 6). `orientation=auto|horizontal|vertical`:
`auto` turns a barcode wider than the paper into a **vertical** one along the paper, so it is never cut (`Q110`); vertical barcodes are raster with module ≥ 4 along the paper and a
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
under the code with the scheme and the amount (`Pix · R$ 10,00`), or the name. The QR attributes (`width=`,
`module=`, `ecc=`) work too. Attributes
take `{{ }}`, so a receipt per row carries its own amount. Without `amount=` (or with 0) the code is open: the payer
types it.

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
the command exits with 9 (`--allow Q111` for 0). A scheme nobody has scanned with its
real app gives the note `P302`; scan a print before customers use it (docs/TESTED.md). Each scheme's fields, official names and limits: `bobina help pay SCHEME` (`--json` too) and
[pay.md](pay.md). A value over a limit is an error (`Q111` says how much to cut), never cut.
An amount that reads two ways (`amount=1.890`) is `Q111` too: write `1890`, `1.890,00` or `1.89`.
The same value in `| paymoney`, or in `| currency` without a locale (§7.1), is printed as typed with `M202`.

### 6.4 Data Matrix and PDF417 ✓

````markdown
```datamatrix {width=third}
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
  rendered at the target width (extras `bobina[svg]`, `bobina[pdf]`; missing → `I105`); they print as
  line art unless `.dither` or `dither=`.
- `https://` URLs only when the command line has `--allow-net` (`I103` otherwise); public hosts only,
  no redirects, ≤ 10 MB (`I106`); every fetch is reported (`I104`). A document cannot enable the network.
- `width=` (default: the paper width), `dither=floyd-steinberg|atkinson|bayer|threshold`,
  `gamma=` (defaults: front matter `image:`, then the profile).
- A drawing prints black and white, a photo dithered (`I109` says which);
  `.dither`, `.threshold` or `threshold=60%` choose.
- In order: `crop=x,y,w,h` (viewer pixels or `%`; SVG/PDF: `%`; `I111`), `.invert`, `rotate=` any
  angle, `mirror=x|y|xy` (`.mirror`: x), fitted whole (`I110`), `mask=circle|ellipse|rounded`
  (`radius=3mm|12|10%`): paper outside.
- `caption="…"`/`caption=alt`: a line under. Above 40 megapixels or unreadable: `I101`, the rest prints.

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

### 6.8 Contact codes (`contact`) ✓

````markdown
```contact whatsapp
+55 11 90000-0000
```
````

The network after `contact`; the value in the body: a phone with its country code, a user name or the app's link.
It prints a QR of the network's public link and a caption. `vcard` and `mecard` take `key: value` lines. A value
that makes no link is `Q112` (code left out, exit 9); every network gives `P303` until scanned with its app.
Networks and values: `bobina help contact` and [contact.md](contact.md).

### 6.9 Planned objects ◇

Shapes.

## 7. Variables (Jinja) ✓

The body is a **Jinja** template, evaluated once in a **sandbox**: `if`, `for`, `set x = …`, `with` and `{{ }}` only
(others: `M311`), no files, no network. Comments are `<# … #>` (so `{#id}` stays a
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
| `smallcaps` | `{{ "Arroz" \| smallcaps }}` → Aʀʀᴏᴢ (an image line, `F301`) |

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

Previews, `check` and `--dry-run` only show the next values. A print reserves its numbers when it is built, so two
prints never share one; a job not printed gives them back unless a later print took some after them, and a number
is never printed twice ([guides/counters.md](guides/counters.md)). The CLI adds `--repeat N` (N
renders, new values each) and `--copies N` (identical copies); `bobina seq` lists and resets them, and
`bobina seq set NAME N` starts one at N.

### 7.4 Data is literal

**The author is trusted; data is not.** Values from `--data` (CSV), `--set` and any future server input:
- are inserted as **literal text** after Markdown parsing: `# PROMO` prints a hash, `{.invert}` prints braces,
  `:fragile:` prints the word;
- are never evaluated as templates;
- can never produce a `raw` block (`M314` for variables inside `raw`), choose an image path (`M312`), or carry
  control characters (removed from all text and barcode data before encoding).

`| markdown`: the author's values (front matter, literals) get all but `raw` (`M121`); others get
text markup only, after parsing (no `{…}`; images `M122`; code blocks, `:::`, link definitions `M123`). Template violations are **errors**: files (`M310`), unsafe attributes and `.format()` (`M311`), more than 2000 loop
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
- Using one (`template: NAME`), its lookup, the built-ins, `template show`/`new`:
  [guides/templates.md](guides/templates.md).
- `--ask` (on `print`, `check`, `preview`) asks the fields still missing on the terminal, in the order the
  template declares them, showing `help`, `example` and the default;
  `type: table` fields take one row per line (`item; qty; price`, empty line to finish). A document without
  `fields:` gets its undeclared `{{ variables }}` asked. Answers are data, exactly like `--set` (literal,
  never Markdown or template code); fields already set by the front matter, `--set` or `--data` columns are
  not asked; a required field left empty prints with `M131`. No terminal → usage error.

## 9. Rendering contract

- bobina decides every line break; the printer never wraps.
- Per line, native when the profile says the printer does it well, raster otherwise — a raster line looks like the
  native ones (the printer font is emulated); `render=` forces it.
- A print starts with the profile's top margin, separates blocks by `block_gap_dots`, and
  ends with enough feed for the last line to clear the tear bar with room to spare (profile `feed_after_dots`,
  or the printer's measured `tear_mm` + 6 mm; `tear_margin_mm` in the printer's config.toml changes the 6 mm).
- Errors stop a print only for parsing (`DOC`) and security (`M31x`); everything else is a nudge.

## 10. Conformance

`spec/conformance/` holds tickets — the printed test series rewritten as `.bob.md` — with their expected bitmaps
for profile `mtp-ii-58` (`BOBINA_NOW=2026-11-05T09:49:00`). An implementation conforms to `bob/1` when it renders
every ticket to the same bitmap. Printing one and running `bobina calibrate compare PHOTO TICKET` measures how close
a printer's paper is to the preview.

## Appendix A — nudge codes

Categories: **B** drawing · **C** charts · **F** fonts · **Q** codes · **L** layout · **I** images · **P** printer · **M** markup and
templates. `bobina help nudges` prints the same list; `allow: [CODE]` or `--allow CODE` silences one.

Errors (`E…`) stop the job: nothing prints. Exit codes are in `docs/CLI.md`.

`E101` command line usage · `E102` one document only · `E103` a job option given twice, differently · `E104`
--then / --compact misuse · `E105` --last / --again misuse, or nothing printed yet · `E106` only one part reads stdin
· `E107` a terminal is needed (confirmation or --ask) · `E201` file not found or unreadable · `E202` file type not a
target · `E203` image, PDF page or range not usable · `E204` network target needs --allow-net · `E205` nothing to
print · `E206` saved label (library) problem · `E207` unknown template, profile, font or help topic · `E208` output
file problem · `E209` a state file damaged or busy · `E301` data file unreadable or unsupported · `E302` no data rows
(or none match --rows/--where) · `E303` unknown column or sheet · `E304` invalid value (--rows, --copies-from, --set,
length) · `E305` job too large (1000 labels, 100 copies) · `E401` no printer configured, or unknown · `E402` printer
unreachable · `E403` printer not ready (paper, cover) · `E405` printer busy (another job) · `E406` `bobina init` found
no printer · `E501` document error · `E601` no AI found, or unknown · `E602` the AI did not answer · `E701` could not
check for a new bobina

Nudges:

| Code | Severity | Meaning |
|---|---|---|
| `B101` | warning | stroke thinner than 2 dots prints broken |
| `B102` | note | free rotation angles look jagged |
| `C101` | note | what a chart drew (`check` only) |
| `C102` | note | chart points averaged to fit |
| `C103` | warning | a chart value is not a number: row left out |
| `C104` | note | chart dates out of order: drawn as written |
| `C105` | note | chart labels fewer or smaller, to fit |
| `C106` | warning | `chart=` with nothing to draw: a table |
| `C107` | note | repeated chart labels combined |
| `C108` | warning | a title names no column of the `data=` file |
| `C109` | warning | `data=` file not read |
| `C110` | note | label-only chart rows at its ends left out |
| `F201` | warning | font below its tested minimum size |
| `F202` | warning | untested font with strokes thinner than 2 dots |
| `F203` | warning | font not found, a bundled font was used |
| `F204` | warning | inverted raster text too thin or small |
| `F205` | warning | font size out of range (6 to 400 px), clamped |
| `F301` | note | glyph not in the printer font: line printed as an image |
| `F302` | warning | glyph missing in every available font |
| `F303` | note | size not supported natively, nearest native size used |
| `F304` | note | font for another script downloaded (once; used offline from then on) |
| `F305` | warning | font for this script not downloaded: letters print as boxes |
| `F306` | note | no font for the locale's script: English words, its formats |
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
| `Q111` | warning | payment code not built: an attribute is missing or invalid (left out, exit 9) |
| `Q112` | warning | contact code not built: the network or its value is wrong (left out, exit 9) |
| `Q113` | note | native QR with fixed modules: this QR printed as an image |
| `Q114` | note | code in an inverted box: black on white |
| `Q115` | warning | … its margin short, or reversed |
| `L101` | warning | word longer than the line was split |
| `L102` | note | long print |
| `L103` | warning | preformatted line longer than the paper was wrapped |
| `L104` | warning | rotated block wider than the paper was cropped |
| `L105` | warning | nothing printable: every block was skipped |
| `L106` | note | table turned vertical |
| `L107` | warning | table columns narrowed to fit the paper |
| `L108` | note | the width each table column got (`check` only) |
| `L109` | warning | box title cut (…) |
| `L110` | note | a column that did not fit moved to a new row |
| `L111` | warning | no room for a box or columns: printed without them |
| `L112` | note | turned label too tall: more labels, or a picture shrunk |
| `L113` | note | `rotate=90` on columns: `orientation=vertical` meant? |
| `L114` | warning | turned label: a block cut across its lines |
| `I101` | warning | image not found, unreadable or in an unsupported format |
| `I102` | note | image downscaled to the paper width |
| `I103` | warning | network image skipped (`--allow-net` if trusted) |
| `I104` | note | image fetched from the network |
| `I105` | warning | PDF/SVG support not installed |
| `I106` | warning | network source refused (private address, redirect, type, size) |
| `I107` | warning | a path with a space: write `![](<a b.png>)` |
| `I108` | warning | image outside its folder and `image_dirs` (`--sandbox`, MCP) |
| `I109` | note | an image read as a drawing (black and white) or a photo (dithered) |
| `I110` | note | a slanted image prints smaller, to fit its corners |
| `I111` | warning | `crop=` past the image's edges |
| `P101` | warning | the paper roll is almost over (estimate) |
| `P102` | warning | the print is longer than the paper left on the roll (estimate) |
| `P103` | warning | the roll is narrower than this printer's paper (recorded anyway) |
| `P104` | note | roll length not set: no paper estimate |
| `P105` | note | `--compact`: labels print at once, without stops |
| `P106` | note | `--step` without a terminal: labels print at once |
| `P201` | warning | raw bytes bypass every check and are not previewed |
| `P301` | note | this job uses a feature not tested on paper yet |
| `P302` | note | a payment code nobody has scanned with its app yet |
| `P303` | note | a contact code nobody has scanned with its app yet |
| `P401` | note | no Bluetooth or USB search here (says why) |
| `P402` | note | the name does not settle the profile: one was taken |
| `P403` | warning | a USB printer this user cannot write to |
| `P404` | warning | config.toml names a profile bobina does not know |
| `M101` | warning | unknown attribute |
| `M102` | note | unknown block type, printed as preformatted text |
| `M103` | note | attribute not implemented yet (ignored) |
| `M104` | note | a `{…}` after a table's title row: GitHub shows the table as text |
| `M105` | warning | a `:::` block is never closed |
| `M106` | note | 4+ asterisks printed as written (`literal_asterisks: false`: bold) |
| `M107` | note | `***text***` is bold italic |
| `M120` | note | field rendered as Markdown |
| `M121` | warning | raw block removed from a variable |
| `M122` | warning | image removed (not the author's value) |
| `M123` | warning | code block, `:::` or link definition removed (not the author's value) |
| `M124` | warning | reserved characters removed |
| `M130` | warning | undefined variable printed as empty |
| `M131` | warning | required template field is empty |
| `M140` | warning | counter passed its stop value |
| `M150` | warning | `--join`: rows of the main source without a match (joined fields empty) |
| `M151` | warning | `--join`: the joined source repeats a key (the first row is used) |
| `M152` | warning | `--join`: a column in two sources; `{{ col }}` is the main one's |
| `M153` | warning | data values lost: a row with more fields than the header, or values under an empty header |
| `M154` | warning | the data header repeats a column name (the last one is used) |
| `M155` | note | a data source was renamed because a column has its name |
| `M156` | note | an option has no effect here |
| `M157` | warning | `--set` replaces a data column of the same name in every row |
| `M158` | note | data columns renamed to names usable in `{{ }}`: `Product Name` → `product_name` |
| `M159` | warning | two data columns would get the same usable name; the first keeps it |
| `M160` | note | Excel formula cells without a saved value print empty |
| `M161` | warning | no icon with that `:name:` (printed as written) |
| `M201` | warning | date pattern looks like Moment.js |
| `M202` | warning | a value is not a number, or a date moved out of the calendar (printed as it is) |
| `M203` | note | this machine's locale, from its time zone, saved in config.toml (said once) |
| `M204` | note | no locale for this machine: dates, numbers and money in English |
| `M205` | warning | the document's `locale:` is unknown (the machine's is used) |
| `M310` | error | templates cannot read files |
| `M311` | error | unsafe template operation |
| `M312` | error | a variable cannot choose a file path |
| `M313` | error | template limit exceeded |
| `M314` | error | variables cannot be used inside raw blocks |
| `M315` | error | template path outside the allowed folders |
