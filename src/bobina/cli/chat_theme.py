"""The screen colours of bobina chat: presets, the terminal's background, and colours of one's own in config.toml.

Which: --screen-colors, else chat_screen_colors in config.toml, else the terminal's background when it says it
(COLORFGBG), else dark. Then [chat.screen_colors] in config.toml overrides parts of it. Colours off (NO_COLOR,
--no-color, TERM=dumb: view.colors_off) win over everything: no colour words, but bold, italic, underline and dim
stay."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

ELEMENTS = ("you", "you-text", "ai", "ai-text", "dim", "frame", "status", "warning", "error")
PRESETS: dict[str, dict[str, str]] = {
    "dark": {"you": "#00afaf", "you-text": "#87d7d7", "ai": "#d787ff", "ai-text": "", "dim": "#808080",
             "frame": "#5f87af", "status": "#808080", "warning": "#d7af5f", "error": "#ff5f5f"},
    "light": {"you": "#00787a", "you-text": "#005f5f", "ai": "#8700af", "ai-text": "", "dim": "#6c6c6c",
              "frame": "#5f5f87", "status": "#585858", "warning": "#875f00", "error": "#af0000"},
    "contrast": {"you": "#00ffff", "you-text": "#afffff", "ai": "#ff87ff", "ai-text": "#ffffff", "dim": "#e4e4e4",
                 "frame": "#ffffff", "status": "#ffffff", "warning": "#ffff00", "error": "#ff5f5f"},
    "mono": {name: "" for name in ELEMENTS},
}  # fmt: skip
THEMES = tuple(PRESETS)
ABOUT = {  # what each looks like, in one line (the one source for the lists, --help, completion and the docs)
    "dark": "light text on a dark terminal",
    "light": "dark text on a light terminal",
    "mono": "no colours; bold and dim only",
    "contrast": "bright, high-contrast colours",
}
WORDS = {"black": "dark", "night": "dark", "white": "light", "bright": "light", "day": "light",
         "high-contrast": "contrast", "hc": "contrast", "high": "contrast", "none": "mono", "plain": "mono",
         "monochrome": "mono", "no-color": "mono", "nocolor": "mono", "bw": "mono", "escuro": "dark",
         "claro": "light"}  # fmt: skip
ATTRS = {"bold", "italic", "underline", "dim", "reverse", "nobold", "noitalic", "nounderline", "strike"}


def normalise(text: str) -> str:
    """How an option value is compared (one rule for --theme, /theme and the other chat options)."""
    return text.strip().lower().replace("_", "-")


def name_of(text: str) -> str | None:
    """A theme name from what was typed (synonyms too), or None."""
    k = normalise(text)
    return k if k in PRESETS else WORDS.get(k)


def attributes(value: str) -> str:
    """Only the attribute words of a style ("bold #ff8700" -> "bold"): what stays when colours are off."""
    return " ".join(w for w in value.split() if w.lower() in ATTRS)


@dataclass
class Theme:
    name: str
    colors: dict[str, str]  # element -> prompt_toolkit style ("#00afaf", "bold ansired")
    off: str = ""  # why there are no colours ("NO_COLOR is set", "--no-color", "TERM=dumb"); "" when there are
    notes: list[str] = field(default_factory=list)

    @property
    def color(self) -> bool:
        return not self.off and self.name != "mono"

    def styles(self) -> dict[str, str]:
        """The screen's style classes from the elements (no colour words when colours are off)."""
        c = self.colors if self.color else {k: attributes(v) for k, v in self.colors.items()}
        dim = c["dim"] or "dim"

        def bold(v):
            return f"bold {v}".strip()

        return {
            "frame": c["frame"], "title": "bold", "you": bold(c["you"]), "you-text": c["you-text"],
            "ai": bold(c["ai"]), "ai-text": c["ai-text"], "dim": dim, "counter": dim, "status": c["status"] or "dim",
            "note": c["warning"] or "bold", "over": bold(c["error"]), "bottom-toolbar": "noreverse",
        }  # fmt: skip


def background(env=None) -> str | None:
    """dark or light from COLORFGBG ("15;0": white on black), which many terminals set; None when unknown. A
    256-colour background counts by its brightness (231 and the light greys are light)."""
    env = os.environ if env is None else env
    parts = env.get("COLORFGBG", "").split(";")
    try:
        bg = int(parts[-1])
    except ValueError:
        return None
    if bg < 16:
        return "light" if bg in (7, 9, 10, 11, 12, 13, 14, 15) else "dark"
    if bg <= 231:  # the 6x6x6 cube
        levels = (0, 95, 135, 175, 215, 255)
        n = bg - 16
        r, g, b = levels[n // 36], levels[n // 6 % 6], levels[n % 6]
    elif bg <= 255:  # the greys
        r = g = b = 8 + 10 * (bg - 232)
    else:
        return None
    return "light" if 0.299 * r + 0.587 * g + 0.114 * b > 140 else "dark"


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


def build(name: str, own: dict | None = None, off: str = "") -> Theme:
    """A preset with one's own colours over it ([chat.screen_colors]); a wrong element or colour is a note, and the
    preset's colour stays. off: why colours are off ("" when they are on)."""
    colors, notes = dict(PRESETS[name]), []
    for element, value in (own or {}).items():
        if element not in ELEMENTS:
            notes.append(f"[chat.screen_colors] {element}: not a part of the chat screen ({', '.join(ELEMENTS)})")
        elif not isinstance(value, str) or not valid(value):
            notes.append(f"[chat.screen_colors] {element} = {value!r}: not a colour (#00afaf, #0af, ansired, red);"
                         f" the one of {name} is used")  # fmt: skip
        else:
            colors[element] = value
    return Theme(name, colors, off=off, notes=notes)


OLD_KEY = "chat_theme"  # read too, with a note: the name before chat_screen_colors


def pick(option: str | None, cfg: dict, env=None, off: str | None = None) -> Theme:
    """--screen-colors (already a valid name), else chat_screen_colors (or the older chat_theme), else the
    terminal's background, else dark; then [chat.screen_colors] (or the older [chat.colors]) over it. off: why
    colours are off (default: view.colors_off of env)."""
    from ..view import colors_off

    env = os.environ if env is None else env
    off = colors_off(env=env) if off is None else off
    notes = []
    name = option
    key = "chat_screen_colors" if cfg.get("chat_screen_colors") is not None else OLD_KEY
    if key == OLD_KEY and cfg.get(OLD_KEY) is not None:
        notes.append(f"{OLD_KEY} in config.toml is now called chat_screen_colors (it was read; rename it)")
    if not name and cfg.get(key) is not None:
        name = name_of(str(cfg[key]))
        if not name:
            notes.append(f"{key} = {cfg[key]!r} in config.toml: not one of {', '.join(THEMES)}; the terminal's (or"
                         " dark) is used")  # fmt: skip
    name = name or background(env) or "dark"
    chat = cfg.get("chat") if isinstance(cfg.get("chat"), dict) else {}
    own: dict = {}
    for table in ("colors", "screen_colors"):  # the newer name wins where both say the same element
        value = chat.get(table)
        if value is None:
            continue
        if table == "colors":
            notes.append("[chat.colors] in config.toml is now called [chat.screen_colors] (it was read; rename it)")
        if isinstance(value, dict):
            own.update(value)
        else:
            notes.append(f'[chat.{table}] in config.toml must be a table: you = "#00afaf"')
    theme = build(name, own, off)
    theme.notes[:0] = notes
    return theme
