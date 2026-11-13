# Goldensky MTP-II (58 mm) — measured capabilities

Profile: `mtp-ii-58` (`src/bobina/profiles/mtp-ii-58.toml`). Firmware MTP-II-6114, ESC/POS mode,
384 dots (48 mm printable), 203 dpi, Bluetooth classic (SPP/RFCOMM channel 1).

Every row comes from a printed, photographed and phone-scanned test ticket (series N = native,
F = fonts, R = raster, B = transport). This is bobina's baseline "minimum quality" printer: what works
here should work on better printers. The conformance tickets in `spec/conformance/` reproduce the series.

Legend: ✅ native works · ⚠️ native with caveats · 🖼️ do it in raster · ❌ not supported.
bobina picks native when ✅ and falls back to raster otherwise; problems are nudges, never blocks.

## Text and sizes

| Feature | Native | Notes | Decision |
|---|---|---|---|
| Font A 12×24 (32 columns) | ✅ | default | native |
| Font B / `ESC M 1–4` / `ESC ! 01` | ❌ | `ESC M 1` prints **nothing**; others ignored | never send `ESC M 1` |
| `GS !` 1×1 … 4×4 (incl. 1×2, 2×1) | ✅ | `ESC ! 30` also gives 2×2 | native |
| `GS !` 6×6, 8×8 | ⚠️ | jagged (enlarged bitmap) | huge titles → 🖼️ |
| Accents (UTF-8 directly) | ✅ | no `ESC t` needed | native |
| Chinese / Japanese | ✅ / ⚠️ | Korean no | — |

## Styles

| Feature | Native | Notes | Decision |
|---|---|---|---|
| Bold `ESC E` / double strike `ESC G` | ✅ | identical | native |
| Underline `ESC - 1/2` | ✅ / ⚠️ | spaces not underlined; 2-dot ≈ 1-dot | native |
| Inverted `GS B` | ⚠️ | spaces stay white (per-word blocks) | continuous band → 🖼️ |
| Upside down `ESC {` | ✅ | line order is not reversed (bobina reverses it) | native |
| 90° rotation `ESC V` | ✅ | rotates each character | nice vertical text → 🖼️ |
| Italic `ESC 4` | ❌ | — | 🖼️ |

## Spacing and layout

| Feature | Native | Notes | Decision |
|---|---|---|---|
| Line spacing `ESC 3 n` | ✅/⚠️ | 0 and ≥ 30 fine; **n below the font height gives a large gap** | set n = height + 6 |
| Character spacing `ESC SP n` | ✅ | stays n dots at 2×, 3× and 4× width: never scaled as the spec says (paper, 09/11 and 13/11) | native; profile `native.tracking_unscaled_at = [2, 3, 4]` |
| Alignment `ESC a` | ✅ | | native |
| Left margin `GS L` | ✅ | | native |
| Print width `GS W` | ❌ | ignored | host computes |
| Tabs `ESC D` + HT | ❌ | ignored | use `ESC $` or monospace |
| Absolute position `ESC $` | ✅ | | native tables possible |
| Automatic line wrap | ⚠️ | splits words | **host word wrap** |

## Symbols in the internal font

| Feature | Native | Decision |
|---|---|---|
| `• · …`, currencies, `° ± § ¶ « » ¿ ¡`, `² ³ µ` | ✅ | native |
| Fractions `½ ¼ ¾` | ⚠️ tiny | ok |
| Arrows, `✓ ✗ ★ ♥`, checkboxes `☐☑☒`, emoji | ❌ | 🖼️ (that line only) |
| Box drawing `┌─┐│` | ⚠️ gaps at corners | simple dividers ok |
| Blocks `█▓▒░` | ✅ | native |

## Codes (reference: a phone scanner app)

| Feature | Native | Notes | Decision |
|---|---|---|---|
| UPC-A, EAN-13, EAN-8 | ✅ | firmware computes the check digit | native |
| UPC-E | ❌ | did not print (retest with 8 digits) | — |
| CODE39 | ✅ | firmware **appends a mod-43 check char** (not in the human-readable text); wide bars are **2** modules, not 3 (258 dots for ABC-123 at module 2, paper 09/11) | native; profile `barcode.code39_wide = 2` |
| CODABAR, CODE93, CODE128 | ✅ | module ≥ 2 | native |
| ITF | ⚠️ | detected but not read | nudge |
| Module 1 | ❌ | too thin | **minimum 2** |
| QR (module 3–16, ECC M/H) | ✅ | read | default **module 4, ECC M**; `size=full` = largest integer module |
| QR ECC L | ⚠️ | read with difficulty | only on request |
| PDF417 (`GS ( k` cn 48) | ❌ | prints the bytes as text | 🖼️ raster works |
| Data Matrix | — | raster module 4+ read | 🖼️ |
| Pix (BR Code) as native QR | ✅ | read by banking apps (CPF, e-mail, phone keys) | native |
| **Vertical barcode** (raster, bars across the paper) | — | modules 2 and 3 **did not scan**, **4 did**: the feed direction blurs (whole heated lines in a row close thin gaps) | module ≥ 4 + 10-module quiet zone |

## Raster drawing rules

| Rule | Value |
|---|---|
| Minimum stroke | **2 dots** (1 prints faint/broken) |
| Minimum gap between strokes | **2 dots** (1 merges) |
| Checkerboard / hatching | ≥ 2 dots (1 becomes blurry grey) |
| Minimum text | **12 px Terminus**, 14 px Atkinson Hyperlegible (8 px illegible, 10 px borderline) |
| Inverted text (white on black) | bold ≥ 20 px with ≥ 4 dots of margin |
| QR in raster | **module ≥ 4** (2 and 3 did not read); native reads at 3 |
| Raster band height (`GS v 0`) | **16 rows** (13/11: with 64 rows a light line appears at a random height, a different one on the same image, where the Bluetooth link starves the printer; with 16 none) |
| Rich typography, lists, drawn checkboxes, grids, bars, fills | ✅ |

Recommended raster fonts: Atkinson Hyperlegible 16–20 (bold ok), Terminus / Spleen 12–16 for small
text, IBM Plex Mono 20 (bold 16), Barlow Condensed 20 (narrow), script fonts 28+.

## Photos

Default **Floyd–Steinberg, gamma 1.8**; `dither=atkinson` uses gamma 1.5 (more contrast). Bayer shows
a grid; threshold is for line art. The dot-gain curve and the warm-up effect are still to be measured
(the realistic preview is an estimate until then).

## Paper, transport and status

- **Tear bar ≈ 5 mm after the head** (`bobina calibrate tear`, ruler read on 05/11 and again on 08/11): jobs end
  with 11 mm of feed (5 + 6 to spare).
- **Faded start**: always begin with `ESC J 24` (3 mm). A slight fade at the start of long raster
  jobs remains.
- **Transport**: 4 KB chunks with no pause — smaller chunks with pauses produced light horizontal
  stripes (the motor stops while waiting for data). Keep the link open until the job is processed:
  closing right after sending dropped the tail of long jobs (final feed and cut line).
  The kernel send buffer of the RFCOMM socket holds ~50 KB, so `sendall()` of a big raster returns at once and the
  bytes cross only as fast as the printer prints: bobina waits until the queue in the kernel is empty (while it keeps
  moving; 20 s without progress = the printer stopped), then asks `GS r 1`, and closes with `SO_LINGER`. A fixed
  wait lost the end of a 29 KB strip twice on 08/11 (the last 10 mm, then the final feed).
- **ESC J right after an image is ignored** (08/11): between two raster lines a 10 mm `ESC J 80` moved nothing
  and the lines touched, and a `--marks tear` line stopped 3 mm short whatever the feed after it (5 or 8 mm; the
  ruler says the tear bar is 5 mm away). Blank raster rows do move the paper, so `escpos.blank_rows_after_raster`
  sends every feed that follows an image as blank rows (48 bytes per dot row). A NUL byte before the ESC J did not
  help. A GS r 1 sent while it prints an image is dropped too: the end-of-job confirmation is asked every 0.5 s.
- **It drops commands that arrive while it prints a big image.** After a 29 KB (or even 7 KB) raster, the final
  `ESC J` and a `GS r 1` sent right behind it were ignored: no feed, never an answer, while a new connection got an
  answer at once. The same feed after an 8-row bar, or sent once the image had printed, worked (08/11, 5 tests).
  So a job that ends with an image sends its last commands only when `GS r 1` is answered again (asked every
  0.5 s; the requests made while it is busy vanish without side effects). A 19 mm image took ~1 s.
- **Windows**: `drivers/windows` (bobina's own Unidrv driver) prints correctly over **USB**; over the Bluetooth
  virtual COM port Windows loses bytes mid-job. Linux/bobina over Bluetooth is fine.
- **Status**: `DLE EOT 1–4` and `GS r 1` answer (online, error, paper). `GS I` does not. **No cover sensor**:
  an open cover reads as paper out (`16 32 12 72`; ready is `16 12 12 12`), and closing the cover without the
  paper end over the sensor makes the printer beep continuously until the paper is pulled out.
  No near-end paper sensor answers — bobina counts paper instead (`bobina paper`). No battery query.
- **Command language: ESC/POS only.** The vendor app's "command switching" sends
  `1F 1B 1F FC 01 02 03 xx` (55 = ESC/POS, 33 = TSPL, 44 = CPCL) over the same RFCOMM channel; this firmware
  accepts it and ignores it — even with the app's connect frame first and a power cycle, TSPL jobs print as
  text (tested 2026-11-06). The command
  is for other models of the same app family.
- **Density: no working command.** `ESC 7` has no effect (one parameter byte leaked as text); `GS ( K` fn 49 is
  not supported (parameters print as text); `DC2 # n` is parsed but changes nothing, and with n ≥ 0x1F it
  swallows the following bytes — never send it. Density is handled with gamma/dither on the host.

## Still to measure

UPC-E with 8 digits, the dot-gain curve.
