# Installing bobina

bobina needs Python 3.11 or newer. Pick one way:

| You have | Run |
|---|---|
| Linux or macOS, nothing set up | `curl -LsSf https://raw.githubusercontent.com/rafaelbressan/bobina/main/get.sh \| sh` |
| uv | `uv tool install bobina` |
| Debian 12+, Ubuntu 24.04+ | `sudo apt install pipx && pipx ensurepath && pipx install bobina` |
| Homebrew (macOS) | `brew install rafaelbressan/tap/bobina` |
| Windows | `uv tool install bobina` or `pipx install bobina` (printer driver: `drivers/windows/`) |
| A checkout, to change bobina | `./install.sh` (editable install, plus the Bluetooth service on Linux) |

Then `bobina printer scan`, `bobina printer add NAME ADDRESS` and `bobina status`.

## Bluetooth needs the system Python

bobina talks to Bluetooth printers through RFCOMM sockets (`socket.AF_BLUETOOTH`), which only Linux has and
only a Python built with the BlueZ headers provides. Debian's and Ubuntu's `python3` have them; the Pythons that uv
downloads and Homebrew's do not (checked on uv 0.13 and Homebrew 7). Without them a Bluetooth printer fails with
"this Python has no Bluetooth sockets"; file (`--path`) and command (`--command`, e.g. ssh to the host with
the printer) printers work everywhere.

- `get.sh` picks a system Python 3.11+ with Bluetooth sockets on Linux, and says so when there is none.
- By hand: `uv tool install --python /usr/bin/python3 bobina`. pipx from apt already uses the system Python.
- Ubuntu 22.04 has Python 3.10: `sudo apt install python3.11`, then `pipx install --python python3.11 bobina`.
- Pairing and the boot service need BlueZ: `sudo apt install bluez`.

## get.sh

`get.sh` installs uv with its official installer when it is missing, then runs `uv tool install bobina`.
Running it again upgrades. Options go after `sh -s --`:

```bash
curl -LsSf https://raw.githubusercontent.com/rafaelbressan/bobina/main/get.sh | sh -s -- --bluetooth-service
```

| Option | What |
|---|---|
| `--bluetooth-service` | Linux: the systemd user service `bt-printer.service`: Bluetooth on and the printer paired at boot. Its files come from the git tag of the installed version, into `~/.local/share/bobina/` |
| `--extras pdf,svg,xlsx` | optional parts: PDF pages, SVG images, `.xlsx` data |
| `--version 0.2.0` | that version instead of the latest (`0.2.0rc1` for a pre-release) |
| `--python PATH` | the Python to install with |

Uninstall: `uv tool uninstall bobina`; the service: `systemctl --user disable bt-printer.service`, then delete
`~/.config/systemd/user/bt-printer.service` and `~/.local/share/bobina/`.

## Debian and Ubuntu: why no .deb

pipx from apt installs bobina on Debian's own Python (Bluetooth works) and upgrades with `pipx upgrade bobina`.
A .deb would have to bundle a virtualenv built for each distribution's Python (Debian 12 has 3.11, Ubuntu 24.04
3.12), or Debian packages of every dependency (some, like `ppf-datamatrix`, are not in Debian), plus an apt
repository so that upgrades reach anyone. That is a build to keep per release for what one apt line already does.

## Homebrew

The formula installs the runtime dependencies, not the extras (`pdf`, `svg`, `xlsx`): for those, use `get.sh
--extras` or `uv tool install 'bobina[pdf,svg,xlsx]'`. With Homebrew's Python, Bluetooth printers do not work (see above): on Linux prefer `get.sh`.
How the tap is published and bumped: `contrib/homebrew/README.md`.
