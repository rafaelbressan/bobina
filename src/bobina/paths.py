"""Where bobina keeps config and state (XDG on Linux; overridable for tests)."""

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


def fonts_dir() -> Path:
    return Path(__file__).parent / "fonts"
