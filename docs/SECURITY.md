# Security model

Status: threat model and defenses for v0.x; red teams in `tests/test_security*.py`.

## What bobina is

A local CLI. It reads a document, renders it, and — after a confirmation — sends bytes to a printer.
`bobina mcp` runs every document in `--sandbox`; a print server is planned (below).

## Trust boundaries

| Principal | Trust | Examples |
|---|---|---|
| The person at the terminal | trusted | flags, `~/.config/bobina/config.toml`, `--editor`, printer `command` |
| Document author | trusted for layout and the images it names, **not** for templates outside its folder | a `.bob.md` you wrote, or one somebody shared |
| Data | **untrusted** | `--data` CSV cells, `--set` values, future server/chat input |
| Template from elsewhere | like a document | built-ins, `~/.config/bobina/templates/`, the document folder |

## Assets

Local files (photos, notes, keys), the printer's configuration (command language, settings reachable
with vendor commands), paper and battery, counters, and the history of the last print.

## Defenses

| Threat | Defense | Test |
|---|---|---|
| Data changes structure (`# PROMO`, `{.invert}`, `**x**`, `:fragile:`) | every `{{ }}` is a placeholder, substituted as literal text after parsing (icon characters in a value are dropped) | `test_templating.py`, `test_icons.py` |
| Data evaluated as template (`{{ seq.x.take(500) }}`) | values are never re-evaluated | `test_data_is_never_evaluated_as_template` |
| Data emits printer commands | no `raw` from data (`M314`, `RAW_FENCE` in `| markdown`); C0/C1 controls stripped from all text and barcode data | `test_no_path_lets_data_emit_raw_bytes`, `test_control_characters_never_reach_the_printer` |
| Data chooses a file to print/preview | image paths with data are refused (`M312`); `| markdown` on data removes images and image fences (`M122`) | `test_data_cannot_*` |
| Shared document pulls files via `template:` | template paths must be inside the document folder or `~/.config/bobina/templates` (`M315`) | `test_template_path_outside_document_folder_is_refused` |
| Template escapes the sandbox | Jinja `ImmutableSandboxedEnvironment`, no loader (`include`/`import` → `M310`), unsafe attributes → `M311`, globals cleared except `now`, `today`, `seq`, `range`, `namespace`, `label` | `test_sandbox_blocks` |
| Paper/CPU exhaustion | 2000 loop steps, 10 000 macro calls, 10 s, values and output ≤ 2 MB (`M313`), 1000 renders / 100 copies per batch, nudge above 30 cm, **confirmation before every print** | `test_sandbox_blocks`, `test_security_limits.py` |
| Spreadsheets (`--data .xlsx`) | formulas never evaluated (cached values only), file ≤ 20 MB, unpacked ≤ 200 MB (zip bomb), first 10 000 rows read; `.xls`/`.ods` refused; every value literal | `test_xlsx_values_sheet_and_no_formulas` |
| Image bombs | `Image.MAX_IMAGE_PIXELS = 40M`; base64 images and downloads ≤ 10 MB; PDF/SVG renders ≤ 8000 dots tall | `test_decompression_bomb_is_refused` |
| Image parsers as attack surface | Pillow limited to PNG/JPEG/GIF/BMP/WebP/TIFF (no EPS → no Ghostscript); PDF: one page rendered; SVG: `DOCTYPE`/`ENTITY` refused | `test_eps_is_not_opened`, `test_svg_with_entities_is_refused` |
| Shared document reads any image | `--sandbox` (MCP: always): only its folder and `image_dirs`, after symlinks (`I108`) | `test_sandbox` |
| SVG reads local files | every `href`/`url()` that is not `#fragment` or inline PNG/JPEG/GIF/WebP is removed before rendering (resvg would load absolute paths) | `test_svg_external_references_are_removed` |
| Document makes requests (tracking, SSRF into localhost/LAN/tailnet) | network images off unless the **command line** says `--allow-net` (`I103`); https only; every resolved address must be public (no loopback, private, link-local, CGNAT/tailnet, multicast; IPv4 in IPv6 checked) and the connection goes to the checked address (no rebinding); no redirects; image/PDF content types only; 10 MB / 10 s; each fetch is reported (`I104`) | `test_network_is_off_by_default`, `test_private_addresses_are_refused` |
| Malformed codes | barcode 1–250 printable ASCII; QR overflow; Pix key ≤ 77 chars, numeric amount, TLV ≤ 99 → nudge `Q109`, no crash | `test_oversized_or_invalid_codes_*` |
| Counter format strings | only one `{:spec}` allowed (`FMT_RE`), no attribute access | — |
| Font lookups | `fc-match` without a shell; the result must match the requested family | — |
| Fonts for other scripts (Thai, CJK…) | a document can make bobina download one, once: only the files pinned in `scriptfonts.py` (https at a fixed notofonts / Google Fonts commit, exact size and sha256, no redirects, 12 MB), written atomically. Reveals to GitHub that some text needs that script; `font_downloads = false` turns it off (`F305`, boxes) | `test_scriptfonts.py` |

Raw blocks written by the **author** are allowed by design (escape hatch): they always raise `P201`
in the confirmation screen and are never previewed. A shared document with a `raw` block can switch
the printer's command language on models that support it (`bobina mode esc` restores it; the MTP-II ignores it).

## Privacy

- The last print (source, bytes, preview) is kept in `~/.local/state/bobina/last/` for `print --last`.
  It can contain personal data (Pix keys, names). `bobina config set keep_last off` disables it.
- Drafts live in `~/.local/state/bobina/drafts/`.

## Requirements before a print server or chat bot exists

A server turns "document author" into "anyone who can reach it", and returns previews to them:

1. Treat every submitted document as **data**, not author: no local paths at all (images only as
   uploads or `data:` URIs), no `template:` paths, no `raw`, no `fonts:` outside the bundled set.
2. Previews returned to a client must come only from submitted content (no file reads) —
   otherwise the preview is an exfiltration channel.
3. Authentication on the tailnet, per-client paper/rate limits, and an audit log.
4. Keep `--yes` server-side only after an explicit human confirmation step (e.g. a chat button).

## Open

- Full multi-agent audit with the skill (`standard` profile): needs an OS-level sandbox; waits for a go.
- Red team round 2 when the server exists (requirements above).
