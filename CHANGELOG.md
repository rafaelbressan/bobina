# Changelog

## Unreleased

- The chat screen's colours: `--theme dark|light|mono|contrast` (`chat_theme`; by default the terminal's background
  when `COLORFGBG` says it, else dark), `/theme NAME` in the chat, and colours of one's own per element in
  `[chat.colors]` (a wrong one is a note and the theme's stays). `NO_COLOR` and `--no-color` win. When bobina
  rewrites config.toml it keeps every table, array of tables, date and multi-line string (before, only
  `[printers.*]` and plain values), and a config it cannot write back the same is left as it is, with a problem.
- `bobina init`: the first run in one command. It finds the printer (a Bluetooth scan, USB printers on Linux with
  their model), or takes a test file printer or one on another machine (ssh); suggests the profile from the name
  the printer gives itself ("looks like a Goldensky MTP-II, 58 mm paper: right?"); shows the locale with a date and
  an amount; records the roll as `paper new` does; and offers one test strip that carries the calibration (the
  feed test when the profile was not measured, the tear ruler at the end), then asks what the paper shows. Run it
  again to change one part; the rest stays.
- `bobina init --yes` (and `BOBINA_NONINTERACTIVE`) asks nothing and prints nothing: the first printer in a fixed
  order (USB, a known model, a printer-like name, never a headset; `--printer ADDRESS` chooses), its profile, the
  locale; it says that the roll length is missing (`P104`, with the `bobina paper new` command). `--json` writes
  `bobina.init/1`. New problems: `E406` (no printer found), `P401` (no Bluetooth stack, or no USB search here:
  said, never waited for), `P402` (the name does not settle the profile: no match, or it fits two paper widths),
  `P403` (a USB printer this user cannot write to, never taken by `--yes`), `P404` (an unknown profile in config.toml).
- `bobina chat`: talk to an AI; its answers print on the roll ([docs/chat.md](docs/chat.md)). On a terminal, a chat
  screen that stays open: a welcome block, an input box with a status line under the last message (the printer,
  the layout, auto or manual, the paper of the chat, the roll left or `roll ?`), your messages on the right, a
  spinner (Esc stops the answer), slash commands with completion; each answer prints right away (`/manual`: only
  on `/print`, `p`; `/again` prints another copy; `/say TEXT` sends text as it is). With a question
  (`bobina chat "QUESTION"`, or on stdin): asks once, writes the answer and exits; it prints only with `--yes`;
  `--json` (`bobina.chat/1`). prompt_toolkit (pure Python) is a new dependency.
- Short is a guardrail: every turn the AI is told the paper width, the limit per answer (`--limit`, `chat_limit`;
  10 cm, with its unit, 1.5 cm to 1 m), the paper used so far and the roll left; a longer answer is rewritten once,
  then cut with "…" (said in the terminal). A note at each metre of paper. The ticket's problems and the roll
  check (P101/P102) are said before printing.
- Layouts (`--layout`, `chat_layout`, `/strip`, `/tickets`): one strip, or one ticket per answer fed to the tear
  bar. Styles (`--style`, `chat_style`; default `labels-underline`): your name (`--name`, `chat_name`; "you") and ✦ with
  the AI's name over each message, with short marks by each speaker (`labels-underline`, `labels-dashes`,
  `labels-hook`), a small mark between exchanges (`labels-dots`), or a bubble (`labels-outline`, `labels-filled`);
  earlier looks too (`labels-ruled`, `labels-exchange`, `bubbles`, `boxes`, `plain`…). `--questions` (`chat_questions`) prints your messages too, on the right, about 3 lines at most: a longer
  one is not sent, never cut. Icons are bundled as 1-bit bitmaps (Lucide, ISC; `tools/gen_icons.py`,
  `bobina.icons`), the start of a reusable icon set.
- `bobina ai list | use NAME [--model MODEL]`: the AIs this machine has, best first: Claude Code, Codex and Gemini
  CLI with their own login and no tools, a local Ollama, then `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` (their HTTP
  APIs, with no SDK: every AI works with a plain install). The choice is saved in config.toml; the first chat
  takes the best one. No AI: `E601` says what to install or set; no answer: `E602`.
- Fixed: `>` quotes wrap inside their bar `│ `, nested quotes and quotes in a list item too: before, each line was
  wrapped to the full paper width and the bar pushed its end past the edge. Every line of a quote has the bar in
  the same column: a heading (2x, its bar drawn in), text in a raster font, right to left text (the bar on the
  right), an inverted band (a white bar); centred text is centred after the bar.
- Fixed: a printer that cannot be reached says which printer and why (`E402`): a printer through a command, its
  exit code and the last lines it wrote on stderr (3 at most, without colours), with what to try. Through ssh,
  exit 255 is ssh's own failure, read from what it said (not let in, unknown host key, unknown name, refused, no
  answer); 127 a program missing over there; anything else points to `ssh HOST bobina status` (the remote bobina
  as written). Suggestions to try a command by hand give it an empty job (`printf '' | …`). Before: `command
  failed (1):` and nothing else. Bluetooth printers, devices and files say what to check too (by the error), and a
  device that fails half way keeps "part of the job may have printed".

## 0.1.2 — 2026-11-11

- One locale per job, never mixed: a document's `locale:`, else the machine's (`locale` in config.toml), else
  English. A label without `locale:` on a machine in Brazil with `LANG=en_US` now prints "USE BY 09/11/2026" and
  "R$ 24,90", not "11/9/26" next to "R$ 24,90"; a USD price there is "US$ 24,90".
- The machine's locale is inferred on the first print, check, preview or `printer add` that needs it: the time
  zone's country, with the `LANG` language when it is official there, else the country's first (`America/Sao_Paulo`
  → pt-BR, `America/Toronto` + `fr_CA` → fr-CA, `Asia/Kolkata` + `en` → en-IN). It is saved in config.toml (the
  rest of the file kept as it was) and said once (`M203`); it stays when the laptop travels.
- `bobina config locale [TAG]` shows it (with a date, a number and an amount as they will print) or saves it;
  `--json` (schema `bobina.config/1`).
- No country in the time zone (`Etc/UTC`, containers): the `LC_ALL`, `LC_TIME` or `LANG` locale when it is not
  English (saved and said like the time zone's), else English, said once (`M204`).
- A typed amount that reads two ways (`1.890`) is read as a price only in a document that says its `locale:`;
  with the machine's locale it is printed as typed with `M202`, and payments refuse it in any locale. An unknown
  `locale:` in a document is `M205`, with the closest tag bobina knows.
- `printer add`, `use`, `remove` and `calibrate` change config.toml under its lock, on the file as it is then.
- A locale whose script needs a font prints in its language with that font (downloaded on first use, `F304`);
  with downloads off and the font not here, or no font known, it prints English words with its country's formats
  (th-TH → en-TH, `F306`, which says `bobina fonts get th`). config.toml keeps the person's locale (th-TH).
- Removed: money written as the currency's country does (R$ 24,90 in an otherwise English document).
- Rolls as they are described around the world. `bobina paper new` takes feet (`50ft`, `50'`) and `--width` (`57mm`,
  `2 1/4in`): a roll that is not as wide as the printer's paper (80 mm on a 58 mm printer) is recorded with the
  warning `P103`. A package code (`57x30`) is refused with its question: 30 metres (as sold in Brazil) or a 30 mm
  diameter (European catalogues)? The MCP tool paper_new takes the same length, or the roll's `diameter` (and
  `core`), and `width`; with a package code it tells the agent to ask the user that question.
- Thai, Devanagari and the other Indic scripts, Khmer, Myanmar, Ethiopic, Chinese, Japanese and Korean print as
  letters, not boxes: the first time a document needs one, bobina downloads its Noto font (38 KB for Thai, 4.5
  to 8.3 MB for CJK), says so before it starts (font, license, size, source; `F304` in the problems) and keeps it
  for offline use. Every file is pinned (URL, size, sha256). Without network, or with `font_downloads = false`,
  the line prints with boxes and `F305` says how to get the font: `bobina fonts get thai` (or `hi`, or a
  document); `bobina fonts scripts` lists them. Lines in these scripts and in Arabic or Hebrew are drawn whole
  (joined, stacked, right to left; Chinese and Thai wrap between letters), no longer letter by letter.

## 0.1.1 — 2026-11-10

- `bobina mcp`: a Model Context Protocol server (stdio) for agents, with the extra `bobina[mcp]`. Its tools
  (check, preview, print, template_list, template_show, help, status, paper, paper_new) run the CLI and return its
  JSON, problem codes and exit code. print is a dry run unless the call says `confirm: true`, after the user agreed;
  paper_new records a roll only with the length the user gave; a call stuck for 5 minutes is stopped and says so.
- Install without a checkout: `curl -LsSf https://raw.githubusercontent.com/rafaelbressan/bobina/main/get.sh | sh`
  (installs uv when missing; the Bluetooth boot service on request). A .deb for Debian and Ubuntu (amd64, arm64)
  on each GitHub release, on the system Python with its dependencies inside. A Homebrew formula in this repository
  (`brew tap rafaelbressan/bobina https://github.com/rafaelbressan/bobina`), bumped by the release workflow.
  docs/INSTALL.md has every way, apt's pipx included.
- uv's and Homebrew's Pythons have no Bluetooth sockets: `get.sh` and `./install.sh` use a system Python that has
  them, and the error says so.

## 0.1.0 — 2026-11-10

First version, calibrated on a Goldensky MTP-II (58 mm).

- Printer profiles: 32 more, generated from escpos-printer-db (CC BY 4.0) by `tools/import_profiles.py`: model facts
  only, `measured = false`, conservative (ASCII native text, raster barcodes, safe mode) until `bobina calibrate tear`
  and `bobina calibrate feed`; `bobina profile list` says which are measured. Sources: `src/bobina/profiles/SOURCES.md`.
- `--marks none|cut|tear|both`: a fine dashed line where one label or order ends (none by default).
- Payment codes: the ```` ```pay ```` block, one set of fields (`to`, `name`, `amount`, `ref`, `note`) for 15 schemes
  (Pix, UPI, SEPA/EPC, PromptPay, PayNow, bitcoin, lightning, PayPal, Cash App, Venmo, Revolut, Wise, PicPay,
  Mercado Pago, and `other` for a pasted payload). Pix is `pay {scheme=pix}`; template `pay-sign`. `bobina help pay SCHEME` (and
  docs/pay.md) says what each field means in that scheme, its official name and its limit. A value over a limit
  is `Q111`, never cut. Only Pix was scanned with real apps; the others carry the note `P302`.
- Any ```` ```qr ```` takes `caption=`: `auto` under a payment code ("Pix · R$ 10,00"), `none`, or your own text.
- Money without a `locale:` is written as the currency's country does (R$ 24,90, ₹120.00), not as the system
  LANG would (R$24.90 on an en_US machine). A document that declares `locale:` keeps its own.
- Exit code 9: the job went out without its payment code (`Q111`); the rest printed. `--allow Q111` gives 0.
- `print --json` and `preview --json` write the outcome, the figures and the problems (schemas `bobina.print/1`,
  `bobina.preview/1`); before, `print --json` hid the warnings. `paper` and `calibrate tear|feed` answer in JSON
  too; `view`, `edit`, `send` and `mode` say that `--json` does nothing there.
- `bobina help CODE` (what a problem means and what to do, docs/problems/), `bobina help --json` (commands,
  options, topics, problems and exit codes for programs), `llms.txt`, `llms-full.txt` and an agent skill
  (`skills/bobina`).
- Templates for shops: `clothing-tag`, `jewelry-tag`, `shelf-price`, `sale-price`, `food-label`, `shipping-label`
  (docs/guides/templates.md); prices typed as people type them (`24,90`, `R$ 1.890,00`), `M202` when a value is
  not a number. Notes `P301` (a feature not tested on paper yet) and `P302` (a payment code not tested in its app).
- Safe by default for printers nobody measured: feeds after images as white raster rows, idle wait before the end
  of an image job; `bobina calibrate feed` turns it off for printers that do not need it.

- Speed and memory: each QR is encoded once (cache), a batch decodes a logo once (per-file cache keyed by size and
  modification time), big JPEGs are decoded reduced (6000x4000 target: 250 MB -> 72 MB); `--pages` writes the PDF
  page by page at 1:1 (copies share one image); image export draws each label once.
- Long jobs: previews drawn page by page and split above ~2.5 m (1000 labels: 422 MB -> 88 MB); a print keeps only
  the shown labels' preview for `--last` (425 MB -> 68 MB); 1-bit PNGs. Bounded waits: download deadline and DNS
  timeout, device-file and bluetoothctl timeouts, stdin size caps, `BOBINA_NONINTERACTIVE=1`.
- Concurrency: a print reserves its seq numbers when it is built (given back when it is not printed and nobody took
  later ones), one job per printer at a time (`busy_timeout`, `E405`), and every state file (counters, paper,
  history, library, config, last job, exports) is written atomically under a lock; a damaged one is `E209`.
- `.bob.md`: Markdown + Pandoc attributes, fenced objects (QR, barcodes, payment codes, Data Matrix, PDF417, images,
  raw bytes), Jinja variables in a sandbox, CLDR dates/numbers per locale, persistent counters, templates.
- Engine: one set of print rows feeds the exact preview and the ESC/POS bytes; native when the printer does it
  well, raster per line when it does not; host word wrap; printer-font emulation for previews.
- CLI: `print` with a confirmation screen (`--yes` to skip), `check`, `preview` (`--realistic`), `view`, `edit`,
  `template`, `seq`, `printer`, `status`, `mode`, `paper` (roll odometer), `calibrate compare|tear|feed`, `fonts`.
- Spacing attributes: `tracking=` (letter spacing), `indent=` (columns or mm/px), `leading=` (line spacing), in the
  printer font (`ESC SP`, `ESC 3`) and in raster fonts.
- Text filters: `titlecase` (by language), `deaccent`, `camel`, `pascal`, `snake`, `kebab`, `slug`, `smallcaps`; also
  in export names (`{item|slug}`). Security: filters, string methods and joins keep data marked (no image path
  from data through `| lower` or `'img/' ~ value`).
- `bobina history` (list, show, stats, clear): every print job recorded privately (schema `bobina.history/1`).
- `--problems pretty|plain|json|jsonl` (or `BOBINA_PROBLEMS`): every error and warning, also usage errors, in a
  stable schema (`bobina.problem/1`) for scripts and logs.
- Export: `-o` with `{n}`, `{i}`, `{file}`, `{part}`, `{column}` saves one file per label (printer bytes from
  `print`, images from `preview`); `preview --pages -o x.pdf` makes one page per label.
- Several data sources: `--data a=FILE --join b=FILE --on KEY` (left join; bare column names when unambiguous,
  `{{ b.col }}` to choose; warnings for unmatched/duplicate keys and shared columns).
- Every problem has a code: errors `E1xx`–`E5xx` join the nudge catalog; one format for all of them.
- One strip: several files and `--then` parts in one job (one preview, confirmation and paper count);
  `--compact`/`--no-compact` per part and `--compact-all`; ✂ cut lines inside compact parts and between two
  compact parts, the tear feed elsewhere; counters continue across parts.
- Data for batches: `--data` reads CSV, TSV/TXT (delimiter detected, cp1252 fallback), Excel `.xlsx`
  (`--sheet`, `bobina[xlsx]`) and JSON; `--rows`, `--where`, `--copies-from` (copies per row).
- Saved labels: `bobina library add|list|show|rm` and `bobina print @NAME` (with `--set`/`--ask`).
- `--ask`: the missing template fields (or a document's undeclared `{{ variables }}`) are asked on the
  terminal, with help, examples, defaults and table rows; answers are literal data like `--set`.
- Images: SVG and PDF pages rendered at the paper width (`bobina[svg]`, `bobina[pdf]`); `bobina print`
  takes a photo, SVG, PDF (`--page N-M`) or https image directly; https images only with `--allow-net`,
  public hosts only (see `docs/SECURITY.md`).
- Codes fill the paper: `size=full|half` for QR/Data Matrix, stretched barcodes, long barcodes turned vertical.
- Safety: data from CSV/`--set` is literal (no Markdown, template or printer-command injection), template paths
  confined, sandbox limits; see `docs/SECURITY.md`.
- Profile `mtp-ii-58` with measured limits (`docs/printers/mtp-ii-58.md`) and conformance tickets
  (`spec/conformance/`).
