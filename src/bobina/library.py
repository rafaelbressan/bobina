"""Saved labels: ready documents printed by name (`bobina print @NAME`), like the label app's fast printing.

An entry is a snapshot of the document (`~/.config/bobina/library/NAME.bob.md`) plus where it came from, so
relative images keep resolving from the original folder. Names are plain words: no paths, no traversal.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import fileio, paths

NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


class LibraryError(ValueError):
    code = "E206"


def folder() -> Path:
    return paths.config_dir() / "library"


def _index_path() -> Path:
    return folder() / "index.json"


def _index() -> dict:
    try:
        return fileio.read_json(_index_path(), {})
    except fileio.StateError as e:
        raise LibraryError(f"{e}; the saved labels are still in {folder()}") from None


def check_name(name: str) -> str:
    if not NAME_RE.fullmatch(name or "") or name.endswith(".bob.md"):
        raise LibraryError(f"'{name}': a library name is letters, digits, '.', '_' or '-' (max 64)")
    return name


def entries() -> dict[str, dict]:
    idx = _index()
    return {n: e for n, e in sorted(idx.items()) if (folder() / f"{n}.bob.md").is_file()}


def add(name: str, source: str, base_dir: str, origin: str, note: str = "", force: bool = False) -> Path:
    check_name(name)
    p = folder() / f"{name}.bob.md"
    entry = {"base": base_dir, "origin": origin, "note": note, "added": datetime.now().isoformat(timespec="seconds")}

    def put(idx):  # under the index lock: two adds at once keep both entries
        if p.exists() and not force:
            raise LibraryError(f"'{name}' is already in the library (use --force to replace it)")
        fileio.atomic_write(p, source)
        idx[name] = entry

    _update(put)
    return p


def _update(fn):
    try:
        return fileio.locked_update(_index_path(), fn)
    except fileio.StateError as e:
        raise LibraryError(f"{e}; the saved labels are still in {folder()}") from None


def get(name: str) -> tuple[str, str]:
    """-> (source, base_dir)."""
    check_name(name)
    p = folder() / f"{name}.bob.md"
    if not p.is_file():
        known = ", ".join(entries()) or "none yet"
        raise LibraryError(f"no saved label '{name}' (saved: {known}; add one with: bobina library add {name} FILE)")
    base = _index().get(name, {}).get("base") or str(folder())
    if not Path(base).is_dir():
        base = str(folder())
    return p.read_text(encoding="utf-8"), base


def remove(name: str) -> None:
    check_name(name)
    p = folder() / f"{name}.bob.md"
    if not p.is_file():
        raise LibraryError(f"no saved label '{name}'")

    def drop(idx):
        p.unlink(missing_ok=True)
        idx.pop(name, None)

    _update(drop)
