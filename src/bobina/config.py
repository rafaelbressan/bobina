"""~/.config/bobina/config.toml — printers, default profile, editor, locale. Addresses live here, never in code."""

from __future__ import annotations

import re
import tomllib

from . import fileio, paths

EXAMPLE = """# bobina configuration
# locale = "pt-BR"                 # documents without locale: (bobina config locale TAG)
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


TABLE = re.compile(r"^\s*\[\[?[^\[\]]+\]\]?\s*(#.*)?$")  # [printers.mtp], [[x]]


def set_value(key: str, value) -> None:
    """Sets one top-level KEY in config.toml and keeps the rest of the file as it is: comments, tables, the order
    (save() rewrites the whole file). Under the file's lock; a file that would no longer read is never written."""
    p = path()
    with fileio.locked(p):
        try:
            text = p.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = ""
        except OSError as e:
            raise fileio.StateError(f"cannot read {p}: {e.strerror or e}") from e
        lines = text.splitlines()
        first_table = next((i for i, line in enumerate(lines) if TABLE.match(line)), len(lines))
        line = f"{key} = {_toml_value(value)}"
        same = re.compile(rf"^\s*{re.escape(key)}\s*=")
        hit = next((i for i in range(first_table) if same.match(lines[i])), None)
        if hit is not None:
            lines[hit] = line
        else:
            i = first_table
            while i > 0 and not lines[i - 1].strip():  # before the blank lines that open the first table
                i -= 1
            lines.insert(i, line)
        new = "\n".join(lines) + "\n"
        try:
            ok = tomllib.loads(new).get(key) == value
        except tomllib.TOMLDecodeError:
            ok = False
        if not ok:
            raise fileio.StateError(f"{p}: could not set {key} without changing the rest; set {line} by hand")
        fileio.atomic_write(p, new)


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
