"""Where bobina keeps config, state and downloaded data (XDG on Linux; overridable for tests)."""

from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    if v := os.environ.get("BOBINA_CONFIG_DIR"):
        return Path(v)
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "bobina"


def state_dir() -> Path:
    if v := os.environ.get("BOBINA_STATE_DIR"):
        return Path(v)
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "bobina"


def data_dir() -> Path:
    """Files bobina downloads and keeps (fonts for other scripts): BOBINA_DATA_DIR, else XDG_DATA_HOME/bobina."""
    if v := os.environ.get("BOBINA_DATA_DIR"):
        return Path(v)
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "bobina"


def fonts_dir() -> Path:
    return Path(__file__).parent / "fonts"
