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
- Releases are tags (`.github/workflows/release.yml`): each one is published to PyPI, installed on Linux, macOS and
  Windows, and becomes a GitHub release. `vX.Y.Z-rc.N` is a pre-release (only installed when asked for). The tag must match the version
  in `pyproject.toml` (`0.2.0rc1` for `v0.2.0-rc.1`), and CHANGELOG.md gets a `## 0.2.0` section first.

## Homebrew and the .deb

- **Homebrew**: this repository is the tap `rafaelbressan/bobina` (`Formula/bobina.rb`: Pillow from Homebrew's
  bottle, every other dependency a `resource`); users run `brew tap rafaelbressan/bobina
  https://github.com/rafaelbressan/bobina`, then `brew install rafaelbressan/bobina/bobina` (the full name:
  Homebrew 7 trusts a tap only then). On each release that is not a pre-release,
  `.github/workflows/release-commit.yml` points `url` and `sha256` at the new sdist, regenerates the resources,
  builds from source, runs `brew test` and `brew audit --strict`, and records the site's casts and tickets with the
  new version (`site/capture/capture.py`), both with read-only access; its `push` job then commits the formula and
  the captures to `main` in one commit with its own token (after the personal-data scan), which also publishes the
  site of the new release. When that fails, fix it and run it again: `gh workflow run release-commit.yml -f
  version=X.Y.Z`. Or bump by hand on a Mac, in the tap (a clone of this repository):

  ```bash
  cd "$(brew --repository rafaelbressan/bobina)" && git pull
  # url and sha256 of the new sdist (https://pypi.org/project/bobina/#files) into Formula/bobina.rb, then:
  brew trust --tap rafaelbressan/bobina
  brew update-python-resources --ignore-main-package-cooldown --exclude-packages pillow rafaelbressan/bobina/bobina
  brew install --build-from-source rafaelbressan/bobina/bobina && brew test rafaelbressan/bobina/bobina
  git commit -am "Formula/bobina.rb: bobina X.Y.Z" && git push
  ```

  Homebrew 7 resolves only packages uploaded more than a day ago (`--ignore-main-package-cooldown` lifts that for
  bobina itself) and loads third-party taps only once trusted. Keep `depends_on "python@3.X"` on a Python the
  `pillow` formula is built for (`brew info pillow`). A new runtime dependency fails `tests/test_install_files.py`
  until the resources are regenerated.
- **The .deb**: `.venv/bin/python tools/build_deb.py --arch amd64` (or `arm64`; needs dpkg-deb, downloads wheels,
  compiles nothing) writes `dist/bobina_X.Y.Z_amd64.deb` from a fresh wheel of the checkout (or `--wheel W`);
  `contrib/deb/test-in-container.sh debian:12 dist/...deb` installs it with apt in docker and runs it. A new
  Python version goes in `PYTHONS` (tools/build_deb.py); a dependency whose compiled code needs a system library,
  in `SYSTEM_LIBS`; the build stops and says so, as it does when a dependency's environment marker would choose
  otherwise for a target than for the Python running the build.

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
