"""~/.config/bobina/config.toml — printers, default profile, editor. Addresses live here, never in code."""

from __future__ import annotations

import tomllib

from . import fileio, paths

EXAMPLE = """# bobina configuration
# default_printer = "mtp"
# editor = "cursor --wait"
#
# [printers.mtp]
# transport = "bluetooth"          # bluetooth | file | command
# address = "AA:BB:CC:DD:EE:FF"    # bluetooth MAC
# channel = 1
# profile = "mtp-ii-58"
#
# [printers.tower]                 # print from another machine through ssh
# transport = "command"
# command = "ssh tower bobina send --yes -"
# profile = "mtp-ii-58"
"""


def path():
    return paths.config_dir() / "config.toml"


def load() -> dict:
    p = path()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise fileio.StateError(f"cannot read {p}: {e.strerror or e}") from e
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise fileio.StateError(f"{p} is not valid TOML ({e})") from e


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def save(cfg: dict):
    lines = ["# bobina configuration (written by bobina; comments are not preserved)"]
    for k, v in cfg.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_toml_value(v)}")
    for name, pr in (cfg.get("printers") or {}).items():
        lines.append("")
        lines.append(f"[printers.{name}]")
        for k, v in pr.items():
            lines.append(f"{k} = {_toml_value(v)}")
    fileio.atomic_write(path(), "\n".join(lines) + "\n")  # a reader never sees half a config


def printer(cfg: dict, name: str | None) -> tuple[str | None, dict | None]:
    printers = cfg.get("printers") or {}
    name = name or cfg.get("default_printer")
    if name and name in printers:
        return name, printers[name]
    if name and ":" in name:  # a bare MAC address
        return name, {"transport": "bluetooth", "address": name, "channel": 1}
    if not name and len(printers) == 1:
        n = next(iter(printers))
        return n, printers[n]
    return name, None
