# Contributing

- `python -m pip install -e ".[dev]"`, then `pytest -q` and `ruff check src tests && ruff format src tests`.
  No printer is needed: tests compare exact bitmaps (`tests/golden/`, `spec/conformance/`).
- An intended rendering change regenerates the bitmaps with `BOBINA_UPDATE_GOLDEN=1 pytest tests/test_golden.py`;
  look at every changed PNG before committing.
- New printer? Copy `src/bobina/profiles/mtp-ii-58.toml`, print the conformance tickets, photograph them, and
  record what works in `docs/printers/<id>.md`. Defaults must come from printed evidence.
- Principles: nudges, not blocks (warn with a suggestion and the evidence, never refuse — except security);
  full command names in docs and output; English everywhere.
- Never commit personal data: `python tools/leakscan.py` runs in CI on every push and pull request.
  `tools/install-hooks.sh` installs the same scan as git hooks (staged files and commit messages).
- Releases are tags: `vX.Y.Z-rc.N` publishes to TestPyPI and installs on Linux, macOS and Windows; `vX.Y.Z`
  publishes to PyPI and makes the GitHub release (`.github/workflows/release.yml`). The tag must match the version
  in `pyproject.toml` (`0.2.0rc1` for `v0.2.0-rc.1`), and CHANGELOG.md gets a `## 0.2.0` section first.

## A new command or option

A test fails until each step is done, so nothing is forgotten when the CLI grows:

1. **Kind of command**: add it to `COMMAND_KIND` in `src/bobina/cli/args.py`: `prints` (it takes `--yes`,
   `--dry-run`, `--editor`) or `reads` (it never prints; those options are not listed in its help and, if given,
   only a note says they do nothing).
   Without it, building the parser raises an error that says this.
2. **Synonyms of each new long option**: what people type for it (English and Portuguese) in `ALSO_KNOWN`, or the
   option in `NO_SYNONYMS` when its own name is what people type. No word may be a synonym of two options.
3. **Hint cases**: at least one realistic mistyped option for each new command in `CASES`
   (`tests/test_option_hints.py`).
4. Typos of every option of every command (swapped neighbours, a dropped letter, `_` for `-`, upper case, one dash)
   are tested automatically; nothing to add.

## A new problem code

Add it to `CATALOG` (`src/bobina/nudges.py`), say what to do in `FIX` (`src/bobina/problem_help.py`) and add it to
the table in `docs/FORMAT.md`, then run `python tools/gen_problem_docs.py` (the flow diagram and docs/problems/).
`tests/test_docs.py` and `tests/test_problem_help.py` check them.
