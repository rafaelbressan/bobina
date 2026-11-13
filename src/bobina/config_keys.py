"""Every setting of config.toml in one table: what `bobina config list/get/set/unset/edit` and `bobina printer
set/show` offer, how a value is checked, and what a print does with a value it cannot read (nudges, not blocks:
said once, and the default is used). tests/test_config_keys.py fails when the code reads a key this table lacks."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

ON, OFF = ("on", "true", "yes", "1"), ("off", "false", "no", "0")


@dataclass(frozen=True)
class Key:
    name: str
    kind: str  # bool | int | number | text | choice | profile | locale | length | folders | table
    default: object  # None: no fixed value; `default_text` says what happens without one
    about: str
    choices: object = ()  # a tuple, or a function () -> tuple (profiles, chat styles…)
    default_text: str = ""
    example: str = ""
    advanced: bool = False  # only in `bobina config list --all`
    minimum: float | None = None
    unit: str = ""
    owner: str = ""  # the command that writes it (bobina config set refuses it and names this one)
    bare_unit: str = ""  # length: the unit of a bare number, as its reader takes it (paper_roll 15 = 15 m)

    def accepted(self) -> tuple[str, ...]:
        c = self.choices() if callable(self.choices) else self.choices
        return tuple(c)

    def default_shown(self) -> str:
        if self.default_text:
            return self.default_text
        return shown(self.default)

    def accepts(self) -> str:
        """What a value can be, in words (errors, get, list)."""
        if self.kind == "bool":
            return "on or off"
        if self.kind == "choice":
            return ", ".join(self.accepted())
        if self.kind == "profile":
            return ", ".join(self.accepted()) + ", or the path of a profile .toml"
        if self.kind == "int":
            return "a whole number" + (f" ({self.minimum:g} or more)" if self.minimum is not None else "")
        if self.kind == "number":
            more = f" ({self.minimum:g} or more)" if self.minimum is not None else ""
            return f"a number{' of ' + self.unit if self.unit else ''}{more}"
        if self.kind == "locale":
            return "a BCP 47 tag (pt-BR, en-US, fr-CA)"
        if self.kind == "length":
            bare = f"; a bare number is {self.bare_unit}" if self.bare_unit else ""
            return f"a length with its unit (15m, 10cm, 4in){bare}"
        if self.kind == "folders":
            return "one or more folders"
        if self.kind == "table":
            return "a table: bobina config edit"
        if self.kind == "codes":
            return "problem codes, comma-separated (L102,F301; none: an empty list)"
        return "text"


def shown(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, list):
        return ", ".join(map(str, v)) or "none"
    if isinstance(v, float) and v.is_integer():
        return f"{v:g}"
    return str(v)


def _profiles() -> tuple:
    from . import profile

    return tuple(sorted(profile.available()))


def _styles() -> tuple:
    from .chat import STYLES

    return STYLES


def _layouts() -> tuple:
    from .chat import LAYOUTS

    return LAYOUTS


def _themes() -> tuple:
    from .cli.chat_theme import THEMES

    return THEMES


def _ais() -> tuple:
    from .ai import ORDER

    return ORDER


def _formats() -> tuple:
    from .cli.common import PROBLEM_FORMATS

    return PROBLEM_FORMATS


def _marks() -> tuple:
    from .cli.common import MARKS

    return MARKS


KEYS: dict[str, Key] = {
    k.name: k
    for k in (
        Key("locale", "locale", None, "dates, numbers and money of documents without locale:",
            default_text="from the time zone, saved by the first print", example="pt-BR"),
        Key("step", "bool", True, "a print of several labels stops after each one so you can tear it off",
            example="off"),
        Key("marks", "choice", "none", "a fine dashed line where a label ends: cut, tear or both", _marks,
            example="both"),
        Key("profile", "profile", None, "the printer profile of printers that do not name one", _profiles,
            default_text="mtp-ii-58", example="mtp-ii-58"),
        Key("editor", "text", None, "the editor of bobina edit and bobina config edit",
            default_text="$VISUAL, $EDITOR, else nano", example="code --wait"),
        Key("paper_roll", "length", None, "the length of a new roll (bobina paper new without a length)",
            default_text="none: bobina paper new asks the length", example="15m", bare_unit="m"),
        Key("keep_last", "bool", True, "keep the last print for print --last and --again"),
        Key("history", "bool", True, "record each print in bobina history"),
        Key("history_max", "int", 5000, "jobs kept in the history", minimum=1, example="2000", advanced=True),
        Key("log_file", "text", None, "append the problems of every run to this file as JSON lines (as --log FILE;"
            " a relative path is beside config.toml)", default_text="none", example="~/bobina-problems.jsonl"),
        Key("font_downloads", "bool", True, "download the font of another script on first use", example="off"),
        Key("update_check", "bool", True, "once a day, say at the end of a command when a newer bobina exists",
            example="off"),
        Key("image_dirs", "folders", [], "folders --sandbox may read images from, besides the document's",
            example="~/Pictures/labels"),
        Key("default_printer", "text", None, "the printer used without --printer",
            default_text="the only printer, if there is one", owner="bobina printer use NAME"),
        Key("ai", "choice", None, "the AI of bobina chat", _ais, default_text="the first one found",
            owner="bobina ai use NAME"),
        Key("ai_model", "text", None, "that AI's model", default_text="its own default",
            owner="bobina ai use NAME --model MODEL"),
        Key("chat_name", "text", "you", "your name over your messages in bobina chat", example="Ana"),
        Key("chat_limit", "length", "10cm", "paper per chat answer at most (1.5cm to 1m)", example="15cm",
            bare_unit="cm"),
        Key("chat_questions", "bool", False, "bobina chat prints your messages too", example="on"),
        Key("chat_layout", "choice", "strip", "bobina chat: one strip, or one ticket per answer", _layouts,
            example="tickets"),
        Key("chat_paper_style", "choice", "labels-underline", "how chat answers look on paper", _styles,
            example="bubbles"),
        Key("chat_screen_colors", "choice", None, "the colours of the chat screen", _themes,
            default_text="the terminal's, else dark", example="light"),
        Key("chat_question_limit", "int", None, "characters of a printed question", minimum=1,
            default_text="what fits on one line", advanced=True),
        Key("chat", "table", None, "[chat.screen_colors]: your own colours (you = \"#00afaf\")",
            default_text="none", advanced=True),
        Key("printers", "table", None, "the printers", default_text="none", owner="bobina printer add / set"),
        # the problem policy ([problems] in config.toml): command line > environment > document > config > default
        Key("problems.allow", "codes", [], "problems never shown (as --allow on every command); errors still stop",
            example="L102,F301"),
        Key("problems.error", "codes", [], "problems that stop the job (as --strict, for these codes only)",
            example="M130,M131"),
        Key("problems.strict", "bool", False, "every warning stops the job (as --strict; --no-strict for one run)",
            example="on"),
        Key("problems.format", "choice", "pretty", "how problems are written (as --problems; BOBINA_PROBLEMS wins)",
            _formats, example="plain"),
    )
}  # fmt: skip
TABLES = {"problems"}  # tables whose keys are in KEYS as TABLE.key


def lookup(cfg: dict, name: str) -> tuple[bool, object]:
    """(is it set, its value) for a key, also a TABLE.key one ([problems] allow = … or problems.allow = …)."""
    table, dot, leaf = name.partition(".")
    if not dot:
        return (name in cfg), cfg.get(name)
    sub = cfg.get(table)
    if isinstance(sub, dict) and leaf in sub:
        return True, sub[leaf]
    return False, None


def group(name: str) -> list[Key]:
    """The keys of a dotted group (problems -> problems.allow, problems.error …); [] when NAME is not one."""
    return [k for k in KEYS.values() if k.name.startswith(name + ".")] if "." not in name else []


def typed(key: Key, value) -> str:
    """A value as it is typed after bobina config set (the restore command of unset GROUP)."""
    if key.kind == "codes":
        found = codes(value) if isinstance(value, (list, str)) else [str(value)]
        return ",".join(found) if found else "none"
    if key.kind == "folders" and isinstance(value, list):
        return " ".join(value)
    return shown(value)


CODE = re.compile(r"[A-Z]\d{3}")


def codes(v) -> list[str]:
    """A list of problem codes from a list or a comma-separated text ("none" or "" is an empty list)."""
    items = [part for x in (v if isinstance(v, list) else [v]) for part in re.split(r"[,\s]+", str(x))]
    out = [x.strip().upper() for x in items if x.strip()]
    return [] if out == ["NONE"] else out


def unknown_codes(values: list[str]) -> list[str]:
    """Codes bobina does not have, each with the closest one: notes, never a block (a later bobina may add it)."""
    from .nudges import CATALOG

    out = []
    for c in values:
        if c not in CATALOG:
            near = difflib.get_close_matches(c, list(CATALOG), n=1, cutoff=0.5)
            out.append(f"{c} is not a bobina problem code" + (f" (did you mean {near[0]}?)" if near else ""))
    return out


PRINTER_KEYS: dict[str, Key] = {
    k.name: k
    for k in (
        Key("transport", "choice", "bluetooth", "how bytes reach it", ("bluetooth", "file", "command")),
        Key("address", "text", None, "Bluetooth address", example="AA:BB:CC:DD:EE:FF"),
        Key("channel", "int", 1, "Bluetooth RFCOMM channel", minimum=1),
        Key("path", "text", None, "a device or file the bytes are written to", example="/dev/usb/lp0"),
        Key("command", "text", None, "a command the bytes are piped to", example="ssh tower bobina send --yes -"),
        Key("profile", "profile", "mtp-ii-58", "its printer profile", _profiles),
        Key("tear_mm", "number", None, "where the tear bar is (bobina calibrate tear)", minimum=0, unit="mm",
            default_text="the profile's"),
        Key("tear_margin_mm", "number", 6.0, "paper past the tear bar after the last line, once tear_mm is "
            "measured", minimum=0, unit="mm"),
        Key("busy_timeout", "number", 300.0, "seconds to wait while another bobina job uses it", minimum=0,
            unit="seconds"),
        Key("timeout", "number", 120.0, "seconds a file or command printer may take", minimum=0, unit="seconds"),
        Key("blank_rows_after_raster", "bool", True, "feeds after images as white rows (bobina calibrate feed)",
            advanced=True),
        Key("idle_before_tail", "bool", True, "wait until idle before the end of a job (bobina calibrate feed)",
            advanced=True),
    )
}  # fmt: skip


class KeyError_(ValueError):
    """A key or value bobina cannot use: the message names what is accepted; code E101 (key) or E304 (value)."""

    def __init__(self, message: str, code: str = "E304"):
        super().__init__(message)
        self.code = code


def find(name: str, table: dict[str, Key] | None = None, what: str = "setting", every: str = "") -> Key:
    """The key called NAME, or KeyError_ with the closest one and where all of them are listed (every)."""
    table = KEYS if table is None else table
    if name in table:
        return table[name]
    near = difflib.get_close_matches(name.replace("-", "_").lower(), list(table), n=1, cutoff=0.6)
    hint = f": did you mean {near[0]}?" if near else ""
    raise KeyError_(f"no {what} called '{name}'{hint} (all of them: {every or 'bobina config list --all'})", "E101")


def parse(key: Key, raw: str | list[str]):
    """A value typed on the command line -> the value to store. Raises KeyError_ with what is accepted."""
    values = raw if isinstance(raw, list) else [raw]
    if key.kind == "codes":  # L102,F301 or L102 F301
        return check(key, codes(values))
    if key.kind == "folders":
        return check(key, [str(v) for v in values])
    if len(values) != 1:
        raise KeyError_(f"{key.name} takes one value; quote it if it has spaces: '{' '.join(values)}'")
    v = str(values[0])
    return check(key, v, typed=True)


def check(key: Key, v, typed: bool = False):
    """The value as bobina uses it, or KeyError_. typed: v is the text the person typed (on, 5, 10cm)."""
    if key.kind == "table":
        if typed or not isinstance(v, dict):
            raise KeyError_(f"{key.name} is a table: change it with bobina config edit")
        return v
    if key.kind == "codes":
        if not isinstance(v, (list, str)):
            raise KeyError_(f"{key.name} = {v!r}: {key.accepts()}")
        found = codes(v)
        bad = [c for c in found if not CODE.fullmatch(c)]
        if bad:
            raise KeyError_(f"{key.name}: '{bad[0]}' is not a problem code (a letter and three digits: L102)")
        return found
    if key.kind == "bool":
        if isinstance(v, bool):
            return v
        w = str(v).strip().lower()
        if w in ON + OFF:
            return w in ON
        raise KeyError_(f"{key.name} = {v!r}: use on or off")
    if key.kind in ("int", "number"):
        try:
            n = int(str(v)) if key.kind == "int" else float(str(v).replace(",", "."))
        except ValueError:
            raise KeyError_(f"{key.name} = {v!r}: {key.accepts()}") from None
        if isinstance(v, bool) or (key.minimum is not None and n < key.minimum):
            raise KeyError_(f"{key.name} = {v!r}: {key.accepts()}")
        return n
    if key.kind == "profile" and isinstance(v, str) and v.endswith(".toml"):
        from pathlib import Path

        if Path(v).expanduser().is_file():  # profile.load takes a path too
            return v
        raise KeyError_(f"{key.name} = {v!r}: no such file")
    if key.kind in ("choice", "profile"):
        accepted = key.accepted()
        w = str(v).strip()
        if w in accepted:
            return w
        near = difflib.get_close_matches(w.lower(), list(accepted), n=1, cutoff=0.5)
        hint = f" (did you mean {near[0]}?)" if near else ""
        raise KeyError_(f"{key.name} = {v!r}: use {', '.join(accepted)}{hint}")
    if key.kind == "locale":
        from . import locales

        loc = locales.parse(str(v))
        if loc is None:
            near = locales.closest(str(v))
            raise KeyError_(f"'{v}' is not a locale bobina knows" + (f" (did you mean {near}?)" if near else "")
                            + f": {key.accepts()}")  # fmt: skip
        return locales.tag(loc)
    if key.kind == "length":
        from . import paper

        try:
            mm = paper.parse_length(str(v), key.bare_unit or None)
        except ValueError as e:
            raise KeyError_(f"{key.name} = {v!r}: {e}") from None
        if key.name == "chat_limit" and not 15 <= mm <= 1000:  # chat caps more with a note; less is refused
            raise KeyError_(f"{key.name} = {v!r}: from 1.5cm to 1m")
        return str(v).strip()
    if key.kind == "folders":  # as --sandbox reads it (common.sandbox_dirs): a list of folder names
        if isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v):
            return v
        raise KeyError_(f'{key.name} = {v!r}: a list of folders, image_dirs = ["~/Pictures"]')
    if not isinstance(v, str) or (typed and not v.strip()):
        raise KeyError_(f"{key.name} = {v!r}: {key.accepts()}")
    return v


_SAID: set[tuple[str, str]] = set()  # (key, value) said this run: once per value (cleared by cli.main)


def read(cfg: dict, name: str, say=None):
    """The value of a top-level key as a print uses it: a value bobina cannot read is said once (note) and the
    default is used, so a typo in config.toml never stops a print."""
    key = KEYS[name]
    fallback = key.default
    present, value = lookup(cfg, name)
    if not present:
        return fallback
    try:
        return check(key, value)
    except KeyError_ as e:
        said = (name, repr(value))
        if said not in _SAID:
            _SAID.add(said)
            used = shown(fallback) if fallback is not None else key.default_shown()
            (say or _err)(f"note: config.toml: {e}; {used} is used (bobina config set {name} VALUE)")
        return fallback


def _err(msg: str) -> None:
    import sys

    print(msg, file=sys.stderr)


def problems(cfg: dict) -> list[tuple[str, str]]:
    """Every key of a config bobina cannot use -> [(where, message)]: unknown keys (with did-you-mean) and values
    that do not check, top level and per printer (bobina config edit says them after the editor closes)."""
    out = []
    for name, v in cfg.items():
        if name not in KEYS and name not in TABLES:
            near = difflib.get_close_matches(name, list(KEYS), n=1, cutoff=0.6)
            out.append((name, f"{name}: not a bobina setting" + (f" (did you mean {near[0]}?)" if near else "")))
            continue
        if name == "printers":
            if not isinstance(v, dict):
                out.append((name, "printers: a table of printers, [printers.NAME]"))
                continue
            for pname, pr in v.items():
                if not isinstance(pr, dict):
                    out.append((f"printers.{pname}", f"[printers.{pname}]: a table"))
                    continue
                for k, pv in pr.items():
                    where = f"printers.{pname}.{k}"
                    if k not in PRINTER_KEYS:
                        near = difflib.get_close_matches(k, list(PRINTER_KEYS), n=1, cutoff=0.6)
                        out.append((where, f"{where}: not a printer setting"
                                    + (f" (did you mean {near[0]}?)" if near else "")))  # fmt: skip
                        continue
                    try:
                        check(PRINTER_KEYS[k], pv)
                    except KeyError_ as e:
                        out.append((where, f"[printers.{pname}] {e}"))
            continue
        if name in TABLES:
            if not isinstance(v, dict):
                out.append((name, f"{name}: a table, [{name}]"))
                continue
            for k, sv in v.items():
                where = f"{name}.{k}"
                if where not in KEYS:
                    near = difflib.get_close_matches(where, [n for n in KEYS if n.startswith(name + ".")], n=1,
                                                     cutoff=0.6)  # fmt: skip
                    out.append((where, f"{where}: not a bobina setting" + (f" (did you mean {near[0]}?)" if near
                                                                         else "")))  # fmt: skip
                    continue
                try:
                    check(KEYS[where], sv)
                except KeyError_ as e:
                    out.append((where, str(e)))
            continue
        if name == "chat":
            extra = [k for k in (v if isinstance(v, dict) else {}) if k != "screen_colors"]
            for k in extra:
                out.append((f"chat.{k}", f"[chat.{k}]: not a bobina setting (did you mean [chat.screen_colors]?)"))
            continue
        try:
            check(KEYS[name], v)
        except KeyError_ as e:
            out.append((name, str(e)))
    return out


def line_of(text: str, where: str) -> int | None:
    """The line of config.toml that sets `where` (key, or printers.NAME.key), for messages."""
    parts = where.split(".")
    table, key = (".".join(parts[:-1]), parts[-1]) if len(parts) > 1 else ("", parts[0])
    current = ""
    for i, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*\[\s*([^\]]+?)\s*\]", line)
        if m:
            current = m.group(1).strip()
            if not table and current == key:
                return i
            continue
        if current == table and re.match(rf"^\s*\"?{re.escape(key)}\"?\s*=", line):
            return i
    return None


SCHEMA = "bobina.config/1"


def entry(key: Key, table: dict) -> dict:
    """One setting as bobina config list/get and bobina printer show write it (--json rows, bobina.config/1)."""
    set_, value = lookup(table, key.name)
    value = value if set_ else key.default
    bad, notes = "", []
    if set_:
        try:
            checked = check(key, value)
        except KeyError_ as e:
            bad = str(e)
        else:
            if key.kind == "codes":
                value, notes = checked, unknown_codes(checked)
    return {
        "key": key.name,
        "value": value,
        "source": "config" if set_ else "default",
        "default": key.default,
        "default_shown": key.default_shown(),
        "accepts": key.accepts(),
        "choices": list(key.accepted()),
        "about": key.about,
        "example": key.example,
        "advanced": key.advanced,
        "set_by": key.owner or "bobina config set",
        "problem": bad,
        "notes": notes,  # what is set but may not do what is meant (an unknown problem code): never a block
    }
