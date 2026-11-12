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


ESCAPES = {"\\": "\\\\", '"': '\\"', "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _toml_string(s: str) -> str:
    """A TOML basic string: quotes, backslashes, newlines and every control character escaped."""
    out = []
    for ch in s:
        if ch in ESCAPES:
            out.append(ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _toml_value(v) -> str:
    """One value as TOML. A value TOML cannot hold is a ValueError (the file is then not rewritten)."""
    import datetime as dt
    import math

    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return "nan"
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        return repr(v)
    if isinstance(v, str):
        return _toml_string(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):  # inside an array: an inline table
        return "{" + ", ".join(f"{_key(k)} = {_toml_value(x)}" for k, x in v.items()) + "}"
    raise ValueError(f"a {type(v).__name__} value cannot be written as TOML")


def _key(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else _toml_string(k)


def _is_tables(v) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(x, dict) for x in v)


def _table(lines: list[str], name: str, table: dict, array: bool = False) -> None:
    """[name] (or [[name]]) with its values, then its own tables and arrays of tables: every table is kept."""
    values = {k: v for k, v in table.items() if not isinstance(v, dict) and not _is_tables(v)}
    nested = any(isinstance(v, dict) or _is_tables(v) for v in table.values())
    if array or values or not nested:
        lines += ["", f"[[{name}]]" if array else f"[{name}]"]
        lines += [f"{_key(k)} = {_toml_value(v)}" for k, v in values.items()]
    for k, v in table.items():
        if isinstance(v, dict):
            _table(lines, f"{name}.{_key(k)}", v)
        elif _is_tables(v):
            for item in v:
                _table(lines, f"{name}.{_key(k)}", item, array=True)


def dumps(cfg: dict) -> str:
    """The config as TOML. It must read back as the same config, or this is a ValueError: a rewrite never
    leaves a file that does not load, nor one that says something else."""
    lines = ["# bobina configuration (written by bobina; comments are not preserved)"]
    for k, v in cfg.items():
        if not isinstance(v, dict) and not _is_tables(v):
            lines.append(f"{_key(k)} = {_toml_value(v)}")
    for k, v in cfg.items():
        if isinstance(v, dict):
            _table(lines, _key(k), v)
        elif _is_tables(v):
            for item in v:
                _table(lines, _key(k), item, array=True)
    text = "\n".join(lines) + "\n"
    try:
        same = tomllib.loads(text) == cfg
    except tomllib.TOMLDecodeError:
        same = False
    if not same:
        raise ValueError("the config would not read back the same")
    return text


def _write(cfg: dict) -> None:
    try:
        text = dumps(cfg)
    except ValueError as e:
        raise fileio.StateError(f"{path()} was not rewritten: {e}; change it by hand") from None
    fileio.atomic_write(path(), text)  # a reader never sees half a config


def save(cfg: dict) -> None:
    """Writes CFG as the whole config, under the file's lock. To change a config read earlier, use update():
    a save of an old copy drops what another bobina saved meanwhile (the locale of a first print)."""
    with fileio.locked(path()):
        _write(cfg)


def update(change):
    """change(cfg) on the config as it is now, read and written under the file's lock (printer add, calibrate…):
    two commands at the same time keep both changes. Returns what change returned."""
    with fileio.locked(path()):
        cfg = load()
        out = change(cfg)
        _write(cfg)
        return out


TABLE = re.compile(r"^\s*\[\[?[^\[\]]+\]\]?\s*(#.*)?$")  # [printers.mtp], [[x]]
KEY = re.compile(r"^\s*[A-Za-z0-9_\-\"'.]+\s*=")  # a key = value line


def _places(lines: list[str], first_table: int) -> list[tuple[int, bool]]:
    """Where a new top-level key may go, best first, and whether a blank line must follow it: after the last
    top-level key (and the lines that continue its value), else before the comment block that opens the first
    table (never between it and its header)."""
    keys = [i for i in range(first_table) if KEY.match(lines[i])]
    out = []
    if keys:
        i = keys[-1] + 1
        while (
            i < first_table and lines[i].strip() and not lines[i].lstrip().startswith("#") and not KEY.match(lines[i])
        ):
            i += 1  # the rest of a value written over several lines
        out.append((i, False))
    if first_table == len(lines):  # no table: at the end
        return [*out, (len(lines), False)]
    i = first_table
    while i > 0 and lines[i - 1].lstrip().startswith("#"):
        i -= 1
    while i > 0 and not lines[i - 1].strip():
        i -= 1
    return [*out, (i, bool(lines[i].strip())), (first_table, True)]


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
            candidates = [[*lines[:hit], line, *lines[hit + 1 :]]]
        else:
            gap = [""]
            candidates = [[*lines[:i], line, *(gap if blank else []), *lines[i:]]
                          for i, blank in _places(lines, first_table)]  # fmt: skip
        for new_lines in candidates:
            new = "\n".join(new_lines) + "\n"
            try:
                if tomllib.loads(new).get(key) == value:
                    fileio.atomic_write(p, new)
                    return
            except tomllib.TOMLDecodeError:
                continue
        raise fileio.StateError(f"{p}: could not set {key} without changing the rest; set {line} by hand")


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
