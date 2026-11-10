# Homebrew formula

`bobina.rb` is the formula of the tap `rafaelbressan/tap` (the repository `rafaelbressan/homebrew-tap`), for
`brew install rafaelbressan/tap/bobina`. It installs bobina into a virtualenv on Homebrew's `python@3.14`. Pillow
comes from Homebrew's `pillow` formula (a bottle: no image libraries to build); every other runtime dependency is a
`resource` built from its sdist. The extras (`pdf`, `svg`, `xlsx`) are not included. Homebrew's Python has no
Bluetooth sockets: with brew, file and command printers work, Bluetooth ones do not (docs/INSTALL.md).

## Publish the tap (once)

1. `brew tap-new rafaelbressan/tap` creates the tap locally, with GitHub workflows for `brew test-bot`.
2. `cp contrib/homebrew/bobina.rb "$(brew --repository rafaelbressan/tap)/Formula/"`, commit it there, then
   `gh repo create rafaelbressan/homebrew-tap --public --source "$(brew --repository rafaelbressan/tap)" --push`.
3. Check it as a user would: `brew install rafaelbressan/tap/bobina && brew test bobina`.
4. Automatic bumps: a fine-grained personal access token with access to `rafaelbressan/homebrew-tap` only,
   permission *Contents: read and write*, saved in this repository as the secret `HOMEBREW_TAP_TOKEN`
   (`gh secret set HOMEBREW_TAP_TOKEN --repo rafaelbressan/bobina`).

## Bumps: automatic on a release

The `homebrew` job of `.github/workflows/release.yml` runs on each release tag that is not a pre-release, once the
PyPI install test passed, on macOS. It takes this file, points `url` and `sha256` at the new sdist on PyPI,
regenerates the resources, builds from source, runs `brew test` and `brew audit --strict`, and only then pushes
to the tap. Without the secret it does nothing (a notice in the run). Automated, because a by-hand bump is the
same commands and easy to forget; safe, because any failure stops before the push and the GitHub release does not
wait for it. When it fails, bump by hand:

```bash
cd "$(brew --repository rafaelbressan/tap)"
# url and sha256 of the new sdist: https://pypi.org/project/bobina/#files
brew update-python-resources --ignore-main-package-cooldown --exclude-packages pillow rafaelbressan/tap/bobina
brew install --build-from-source rafaelbressan/tap/bobina && brew test rafaelbressan/tap/bobina
git commit -am "bobina X.Y.Z" && git push
```

- Homebrew 7 resolves only packages uploaded more than a day ago (a supply-chain cooldown);
  `--ignore-main-package-cooldown` lifts it for bobina itself, not for its dependencies.
- Homebrew 7 loads formulae from third-party taps only once trusted. `brew install rafaelbressan/tap/bobina`
  (the full name) trusts it; `brew update-python-resources` does not: run `brew trust --tap rafaelbressan/tap`.
- Keep `depends_on "python@3.X"` on a Python the `pillow` formula is built for (`brew info pillow`), or
  `import PIL` fails and `brew test` says so.
- Changing the formula (dependencies, test): edit it here; the job takes everything but `url`, `sha256` and the
  resources from this file. A new runtime dependency in pyproject.toml fails `tests/test_install_files.py` until
  the resources here are regenerated.
