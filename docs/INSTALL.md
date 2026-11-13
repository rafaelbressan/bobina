# Installing bobina

bobina needs Python 3.11 or newer. Pick one way:

| You have | Run |
|---|---|
| Linux or macOS, nothing set up | `curl -LsSf https://raw.githubusercontent.com/rafaelbressan/bobina/main/get.sh \| sh` |
| uv | `uv tool install bobina` |
| Debian 12+, Ubuntu 24.04+ | the .deb (below), or `sudo apt install pipx && pipx ensurepath && pipx install bobina` |
| Homebrew (macOS) | `brew tap rafaelbressan/bobina https://github.com/rafaelbressan/bobina && brew install rafaelbressan/bobina/bobina` |
| Windows | `uv tool install bobina` or `pipx install bobina` (printer driver: `drivers/windows/`) |
| A checkout, to change bobina | `./install.sh` (editable install, plus the Bluetooth service on Linux) |

Then `bobina init` (printer, profile, locale, roll, a test strip).

## Upgrading

`bobina update` shows the upgrade command of whatever installed bobina (uv, pipx, pip, Homebrew) and asks before
running it; for the .deb and git installs it says the steps. `--check` exits 10 when a release is newer. Once a
day a command at a terminal ends with `bobina 0.1.4 is available (you have 0.1.3): uv tool upgrade bobina`, never
for agents, scripts or pipes (`bobina config set update_check off`).

## Bluetooth needs the system Python

bobina talks to Bluetooth printers through RFCOMM sockets (`socket.AF_BLUETOOTH`), which only Linux has and
only a Python built with the BlueZ headers provides. Debian's and Ubuntu's `python3` have them; the Pythons that uv
downloads and Homebrew's do not (checked on uv 0.13 and Homebrew 7). Without them a Bluetooth printer fails with
"was built without Bluetooth sockets", which says how to reinstall; file (`--path`) and command (`--command`, e.g. ssh to the host with
the printer) printers work everywhere.

- The .deb and pipx from apt use the system Python; `get.sh` picks one with Bluetooth sockets, or says there is none.
- By hand: `uv tool install --reinstall --python /usr/bin/python3 bobina` (also moves an install off uv's Python).
- Ubuntu 22.04 has Python 3.10: `sudo apt install python3.11`, then `pipx install --python python3.11 bobina`.
- Pairing and the boot service need BlueZ: `sudo apt install bluez`.

## get.sh

`get.sh` installs uv with its official installer when it is missing, then runs `uv tool install bobina`.
Running it again upgrades and keeps the extras installed before. Options go after `sh -s --`:

```bash
curl -LsSf https://raw.githubusercontent.com/rafaelbressan/bobina/main/get.sh | sh -s -- --bluetooth-service
```

| Option | What |
|---|---|
| `--bluetooth-service` | Linux: the systemd user service `bt-printer.service`: Bluetooth on and the printer paired at boot. Its files come from the git tag of the installed version, into `~/.local/share/bobina/` |
| `--extras pdf,svg,xlsx,mcp` | optional parts: PDF pages, SVG images, `.xlsx` data, `bobina mcp` (the server for agents) |
| `--version 0.2.0` | that version instead of the latest (`0.2.0rc1` for a pre-release) |
| `--python PATH` | the Python to install with |

Uninstall: `uv tool uninstall bobina`; the service: `systemctl --user disable bt-printer.service`, then delete
`~/.config/systemd/user/bt-printer.service` and `~/.local/share/bobina/`.

## Debian and Ubuntu: the .deb

Each [release](https://github.com/rafaelbressan/bobina/releases) has `bobina_X.Y.Z_amd64.deb` and `_arm64.deb`
(64-bit Raspberry Pi OS too): `sudo apt install ./bobina_X.Y.Z_arm64.deb`. It runs on the system `python3` (3.11
to 3.14) with its own copies of the dependencies, not Debian's. No apt repository (`bobina update` says the next
.deb) and no extras: for them, pipx from apt (above).

## Homebrew

This repository is the tap; install with the full name (Homebrew 7 trusts a tap only then). No extras (`pdf`,
`svg`, `xlsx`, `mcp`): for them, `get.sh --extras`. No Bluetooth sockets (above): on Linux prefer `get.sh` or the
.deb.
