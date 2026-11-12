"""The colours of the chat screen: presets, the terminal's background, and colours of one's own in config.toml.

Which theme: --theme, else chat_theme in config.toml, else the terminal's background when it says it (COLORFGBG),
else dark. Then [chat.colors] in config.toml overrides elements of it (you, ai, dim, frame, status, warning, error).
NO_COLOR wins over everything: no colours (bold and dim stay)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

ELEMENTS = ("you", "ai", "dim", "frame", "status", "warning", "error")
PRESETS: dict[str, dict[str, str]] = {
    "dark": {"you": "#00afaf", "ai": "#d787ff", "dim": "#808080", "frame": "#5f87af", "status": "#808080",
             "warning": "#d7af5f", "error": "#ff5f5f"},
    "light": {"you": "#00787a", "ai": "#8700af", "dim": "#6c6c6c", "frame": "#5f5f87", "status": "#585858",
              "warning": "#875f00", "error": "#af0000"},
    "contrast": {"you": "#00ffff", "ai": "#ff87ff", "dim": "#e4e4e4", "frame": "#ffffff", "status": "#ffffff",
                 "warning": "#ffff00", "error": "#ff5f5f"},
    "mono": {name: "" for name in ELEMENTS},
}  # fmt: skip
THEMES = tuple(PRESETS)
WORDS = {"black": "dark", "night": "dark", "white": "light", "bright": "light", "day": "light",
         "high-contrast": "contrast", "hc": "contrast", "high": "contrast", "none": "mono", "plain": "mono",
         "monochrome": "mono", "no-color": "mono", "nocolor": "mono", "bw": "mono", "escuro": "dark",
         "claro": "light"}  # fmt: skip
ATTRS = {"bold", "italic", "underline", "dim", "reverse", "nobold", "noitalic"}


@dataclass
class Theme:
    name: str
    colors: dict[str, str]  # element -> prompt_toolkit style ("#00afaf", "bold ansired")
    color: bool = True  # False: no colours at all (mono, NO_COLOR); bold and dim stay
    notes: list[str] = field(default_factory=list)

    def styles(self) -> dict[str, str]:
        """The screen's style classes from the elements."""
        c = self.colors if self.color else {k: "" for k in ELEMENTS}
        dim = c["dim"] or "dim"
        return {
            "frame": c["frame"], "title": "bold", "you": f"bold {c['you']}".strip(), "you-text": c["you"],
            "ai": f"bold {c['ai']}".strip(), "dim": dim, "counter": dim, "status": c["status"] or "dim",
            "note": c["warning"] or "bold", "over": f"bold {c['error']}".strip(), "bottom-toolbar": "noreverse",
        }  # fmt: skip


def name_of(text: str) -> str | None:
    """A theme name from what was typed (synonyms too), or None."""
    k = text.strip().lower().replace("_", "-")
    return k if k in PRESETS else WORDS.get(k)


def background(env=None) -> str | None:
    """dark or light from COLORFGBG ("15;0": white on black), which many terminals set; None when unknown."""
    env = os.environ if env is None else env
    parts = env.get("COLORFGBG", "").split(";")
    try:
        bg = int(parts[-1])
    except ValueError:
        return None
    return "light" if bg in (7, 9, 10, 11, 12, 13, 14, 15) else "dark"


def valid(value: str) -> bool:
    """A colour prompt_toolkit understands (#rgb, #rrggbb, ansired, red…), with bold, italic, underline or dim."""
    from prompt_toolkit.styles.style import parse_color

    words = value.split()
    if not words:
        return False
    for w in words:
        if w.lower() in ATTRS:
            continue
        try:
            parse_color(w)
        except ValueError:
            return False
    return True


def build(name: str, own: dict | None = None, env=None) -> Theme:
    """A preset with one's own colours over it ([chat.colors]); a wrong element or colour is a note, and the
    preset's colour stays."""
    env = os.environ if env is None else env
    colors, notes = dict(PRESETS[name]), []
    for element, value in (own or {}).items():
        if element not in ELEMENTS:
            notes.append(f"[chat.colors] {element}: not an element of the chat screen ({', '.join(ELEMENTS)})")
        elif not isinstance(value, str) or not valid(value):
            notes.append(f"[chat.colors] {element} = {value!r}: not a colour (#00afaf, #0af, ansired, red);"
                         f" the {name} theme's is used")  # fmt: skip
        else:
            colors[element] = value
    no_color = bool(env.get("NO_COLOR")) or env.get("TERM") == "dumb"
    return Theme(name, colors, color=name != "mono" and not no_color, notes=notes)


def pick(option: str | None, cfg: dict, env=None) -> Theme:
    """--theme (already a valid name), else chat_theme, else the terminal's background, else dark."""
    env = os.environ if env is None else env
    notes = []
    name = option
    if not name and cfg.get("chat_theme") is not None:
        name = name_of(str(cfg["chat_theme"]))
        if not name:
            notes.append(f"chat_theme = {cfg['chat_theme']!r} in config.toml: not a theme ({', '.join(THEMES)});"
                         " the terminal's (or dark) is used")  # fmt: skip
    name = name or background(env) or "dark"
    own = ((cfg.get("chat") or {}).get("colors")) if isinstance(cfg.get("chat"), dict) else None
    if own is not None and not isinstance(own, dict):
        notes.append('[chat.colors] in config.toml must be a table: you = "#00afaf"')
        own = None
    theme = build(name, own, env)
    theme.notes[:0] = notes
    return theme
