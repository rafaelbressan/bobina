# Notes for coding agents

bobina is a Python CLI (src/bobina) that prints Markdown on thermal roll printers. Read CONTRIBUTING.md first: it
has the rules that tests enforce.

## Every change

```bash
.venv/bin/pytest -q                                 # no printer needed
.venv/bin/ruff check src tests tools && .venv/bin/ruff format src tests tools
.venv/bin/python tools/leakscan.py                  # no personal data: runs in CI
```

- Rendering changes: `BOBINA_UPDATE_GOLDEN=1 pytest tests/test_golden.py`, then look at every changed PNG.
- Docs have a token budget per page (tests/test_token_budget.py): over it, split or cut the page.
- Docs that are generated, never edited by hand: `docs/diagrams/nudges-flow.md` and `docs/problems/`
  (`tools/gen_problem_docs.py`),
  `docs/pay.md` (`tools/gen_pay_docs.py`), `docs/guides/icons.md` and its pictures (`tools/gen_icon_docs.py`; icons:
  `tools/draw_pictograms.py`, `tools/gen_icons.py`), `llms-full.txt` (`tools/gen_llms_full.py`), imported printer
  profiles (`tools/import_profiles.py`).
- A new command or option: `COMMAND_KIND`, `ALSO_KNOWN`/`NO_SYNONYMS` in `src/bobina/cli/args.py` and a hint case
  in `tests/test_option_hints.py` (a test fails until done). A new problem code: `CATALOG` in `src/bobina/nudges.py`,
  what to do in `FIX` (`src/bobina/problem_help.py`), the table in `docs/FORMAT.md`, then `tools/gen_problem_docs.py`.

## Principles

- Nudges, not blocks: warn with a code, a suggestion and the evidence; refuse only for security.
- Printer facts come from paper: a profile value needs a printed test (docs/printers/). Imported profiles are
  `measured = false` and conservative.
- Full command names in docs and output; English in code and docs.
- Never print on a real printer from tests: use `-o`, `--dry-run`, `check`, `preview` or a file printer
  (`bobina printer add test --path out.bin`).

## Map

| Path | What |
|---|---|
| `src/bobina/engine.py`, `layout.py` | document → rows (native text, raster, codes, feeds) |
| `src/bobina/escpos.py`, `transport.py` | rows → bytes; Bluetooth, file and command transports |
| `src/bobina/cli/` | commands (`args.py` parser, `documents.py` print/check/preview, `device.py` printer/calibrate) |
| `src/bobina/profiles/` | printer profiles (TOML) and their sources |
| `evals/agent-eval.yaml` | agent tasks for cli-agent-eval (how well agents use this CLI) |
| `site/` | the website bobina.md: Astro, the docs of the latest release, agent-ready (`site/README.md`) |
