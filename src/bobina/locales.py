"""The locale of a print, one for dates, numbers and money (never mixed): the document's locale:, else the machine's
(locale in config.toml, inferred from the time zone on the first run that needs it and saved), else English.

The engine alone (tests, library use) knows no machine: a document without locale: is English there. The CLI passes
a Machine, which reads config.toml, infers and saves, and says once what it chose (M203, M204, F304)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from babel import Locale, UnknownLocaleError, localedata

LOCALTIME = "/etc/localtime"  # module values, so tests can point them elsewhere
TIMEZONE_FILE = "/etc/timezone"  # Debian and Ubuntu also name the zone here
FALLBACK = "en"  # no locale anywhere: English (en-US formats: 11/5/26, $1,234.50, R$1,234.50)
SAID = "said.json"  # in the state folder: the notes already given once (M204, F304 of the config's locale)


@dataclass
class Choice:
    locale: Locale  # what dates, numbers and money are written in
    explicit: bool  # the document's or the machine's (config, time zone); False: the English fallback
    origin: str = "default"  # document | config | default
    notes: list = field(default_factory=list)  # (code, message, suggestion) for the job's problems


def tag(loc: Locale) -> str:
    """pt_BR -> pt-BR (BCP 47, as documents and config.toml write it)."""
    return str(loc).replace("_", "-")


# ---------------------------------------------------------------- reading tags


def parse(value) -> Locale | None:
    """A locale from a tag as people write it (pt-BR, pt_BR.UTF-8, fr, en-TH), or None. A language with a country
    CLDR does not pair (en-TH, pt-JP) is that language's words with the country's formats."""
    return _parse(str(value or "").strip())  # a front matter value may be anything YAML reads


@lru_cache(maxsize=64)
def _parse(value: str) -> Locale | None:
    s = value.split(".")[0].split("@")[0].replace("-", "_")
    if s.upper() in ("", "C", "POSIX"):
        return None
    try:
        return Locale.parse(s)
    except (UnknownLocaleError, ValueError, TypeError):
        pass
    m = re.fullmatch(r"([A-Za-z]{2,3})_([A-Za-z]{2})", s)
    return mixed(m.group(1).lower(), m.group(2).upper()) if m else None


def country_formats(country: str) -> Locale | None:
    """The main locale of a country (TH -> th_TH, BR -> pt_BR), by CLDR's likely subtags."""
    try:
        return Locale.parse(f"und_{country}")
    except (UnknownLocaleError, ValueError):
        return None


def country_of_locale(loc: Locale) -> str | None:
    if loc.territory and loc.territory.isalpha():
        return loc.territory
    from babel.core import get_global

    likely = get_global("likely_subtags").get(loc.language, "")
    country = likely.split("_")[-1] if likely else ""
    return country if len(country) == 2 and country.isalpha() else None


# Formats a mixed locale takes from the country; the rest (month and day names, currency names) from the language.
FORMAT_KEYS = ("date_formats", "time_formats", "datetime_formats", "datetime_skeletons", "number_symbols",
               "decimal_formats", "currency_formats", "percent_formats", "scientific_formats",
               "currency_symbols")  # fmt: skip


class _Mixed(Locale):
    """The words of one locale with the formats of a country (en-TH: English month names, Thai date order). A
    format with a character bobina cannot draw (the Thai word in th-TH's full date) keeps the language's."""

    def __init__(self, words: Locale, country: str, formats: Locale):
        super().__init__(words.language, words.territory, words.script)
        self.territory, self.script = country, None
        data = dict(localedata.load(str(words)))
        for key in FORMAT_KEYS:
            data[key] = _pick(formats._data.get(key), words._data.get(key))
        self.__mixed = localedata.LocaleDataDict(data)

    @property
    def _data(self):
        return self.__mixed


def _pick(country, own):
    if isinstance(country, Mapping):
        out = {k: v for k, v in (own or {}).items()} if isinstance(own, Mapping) else {}
        for k in country:
            v = _pick(country[k], out.get(k))
            if v is not None:
                out[k] = v
        return out
    text = getattr(country, "pattern", country)
    return country if not isinstance(text, str) or can_draw(text) else own


@lru_cache(maxsize=64)
def mixed(language: str, country: str) -> Locale | None:
    if country not in Locale("en").territories:
        return None
    try:
        words = Locale.parse("en_001" if language == "en" else language)  # en_001: English without US formats
    except (UnknownLocaleError, ValueError):
        return None
    formats = country_formats(country)
    return _Mixed(words, country, formats) if formats else None


# ---------------------------------------------------------------- scripts bobina can draw


def can_draw(text: str) -> bool:
    """Every character has a glyph in the font bobina draws missing glyphs with (DejaVu Sans, bundled)."""
    from . import rasterfont

    ref = rasterfont.resolve("DejaVu Sans")
    have = rasterfont.cmap(ref.path) if ref else frozenset()
    return all(ord(c) in have for c in text if not c.isspace())


@lru_cache(maxsize=64)
def drawable(loc: Locale) -> bool:
    """bobina can write this locale's words: left to right, and every letter of its month and day names in the
    bundled fonts."""
    if loc.text_direction != "ltr":  # bobina lays text out left to right
        return False
    names = [*loc.months["format"]["wide"].values(), *loc.months["format"]["abbreviated"].values(),
             *loc.days["format"]["wide"].values(), *loc.days["format"]["abbreviated"].values()]  # fmt: skip
    return can_draw("".join(names))


def printable(loc: Locale) -> Locale:
    """The locale bobina prints with: loc, or English words with loc's country formats (th-TH -> en-TH) while
    bobina has no font for loc's script. The one place to change when fonts per script exist (downloaded on first
    use): then this returns loc, with that font."""
    if drawable(loc):
        return loc
    country = country_of_locale(loc)
    return (parse(f"en-{country}") if country else None) or Locale.parse(FALLBACK)


def script_note(loc: Locale, shown: Locale, where: str) -> tuple[str, str, str]:
    lang = loc.get_language_name("en") or loc.language
    country = Locale("en").territories.get(shown.territory or "", "")
    formats = f"the formats of {country}" if country else "English formats"
    return ("F304", f"bobina cannot draw {lang} yet ({tag(loc)}, {where}): dates and numbers print as {tag(shown)}, "
            f"English words with {formats}", f"or choose another locale: {CHANGE}")  # fmt: skip


CHANGE = "bobina config locale TAG"


# ---------------------------------------------------------------- the machine


def system_zone() -> str | None:
    """This machine's time zone (IANA name): TZ, the link /etc/localtime, /etc/timezone; None when there is none
    (a container without zone data)."""
    from zoneinfo import ZoneInfo

    names = [os.environ.get("TZ", "").strip().lstrip(":")]
    try:
        link = os.path.realpath(LOCALTIME)  # .../zoneinfo/America/Sao_Paulo
        names.append(link.split("zoneinfo/", 1)[1] if "zoneinfo/" in link else "")
    except OSError:
        pass
    try:
        names.append(Path(TIMEZONE_FILE).read_text(encoding="utf-8").strip())
    except (OSError, UnicodeDecodeError):
        pass
    for name in names:
        if not name or name.startswith("/"):
            continue
        try:
            ZoneInfo(name)
            return name
        except Exception:  # noqa: BLE001 - not a zone name (POSIX rules like <-03>3, a typo)
            continue
    return None


def country_of(zone: str | None) -> str | None:
    """America/Sao_Paulo -> BR; Etc/UTC and unknown zones -> None."""
    from babel.core import get_global

    if not zone:
        return None
    zone = get_global("zone_aliases").get(zone, zone)  # Asia/Calcutta -> Asia/Kolkata
    country = get_global("zone_territories").get(zone)
    return country if country and country.isalpha() and country != "ZZ" else None


def system_language() -> tuple[str | None, str | None]:
    """(language, tag) of LC_ALL, else LANG: en_US.UTF-8 -> ("en", "en-US"); C and POSIX -> (None, None)."""
    for var in ("LC_ALL", "LANG"):
        value = os.environ.get(var, "").strip()
        if value:
            loc = parse(value)
            return (loc.language, tag(loc)) if loc else (None, None)
    return None, None


def infer(zone: str | None, language: str | None) -> str | None:
    """The locale a machine in ZONE most likely wants: the zone's country, with LANGUAGE if it is official there,
    otherwise the country's first official language (Sao_Paulo + en -> pt-BR, Toronto + fr -> fr-CA)."""
    from babel.languages import get_official_languages

    country = country_of(zone)
    if not country:
        return None
    official = list(get_official_languages(country, de_facto=True))
    for lang in ([language] if language in official else []) + official:
        loc = parse(f"{lang}-{country}")
        if loc is not None:
            return tag(loc)
    return None


def first_time(key: str) -> bool:
    """True the first time KEY is asked about on this machine (state folder); True again when that cannot be kept."""
    from . import fileio, paths

    def mark(said: dict) -> bool:
        new = key not in said
        said[key] = True
        return new

    try:
        return fileio.locked_update(paths.state_dir() / SAID, mark)
    except (OSError, fileio.StateError, fileio.LockTimeout):
        return True


class Machine:
    """The locale of documents without locale: on this machine, for the CLI. get() resolves it once per command:
    config.toml, else inferred from the time zone and saved there, else English. Its notes come with the first
    get() only, so a batch of 1000 labels says it once."""

    def __init__(self):
        self._got: tuple[str | None, list] | None = None

    def get(self) -> tuple[str | None, list]:
        if self._got is not None:
            return self._got[0], []
        self._got = self._resolve()
        return self._got

    def _resolve(self) -> tuple[str | None, list]:
        from . import config

        saved = config.load().get("locale")
        if saved:
            loc = parse(saved)
            if loc is None:
                return None, [("M204", f"locale = {str(saved)!r} in config.toml is not a locale bobina knows: dates, "
                               "numbers and money in English (en)", f"set yours: {_example()}")]  # fmt: skip
            shown = printable(loc)
            note = shown != loc and first_time(f"F304 {tag(loc)}")
            return str(saved), [script_note(loc, shown, "config.toml")] if note else []
        zone = system_zone()
        language, _ = system_language()
        found = infer(zone, language)
        if found is None:
            where = f"no country in the time zone {zone}" if zone else "no time zone on this machine"
            msg = f"{where}: dates, numbers and money in English (en)"
            return None, [("M204", msg, f"set yours: {_example()}")] if first_time("M204") else []
        problem = _save(found)
        if problem:
            note = ("M203", f"locale {found} (from the time zone {zone}); not saved: {problem}",
                    f"set it: bobina config locale {found}")  # fmt: skip
        else:
            note = ("M203", f"locale {found} (from the time zone {zone}), saved in config.toml",
                    f"change it: {_example(found)}")  # fmt: skip
        loc = parse(found)
        shown = printable(loc)
        if shown == loc:
            return found, [note]
        first_time(f"F304 {tag(loc)}")  # said now, with the choice: not again on the next run
        return found, [note, script_note(loc, shown, "from the time zone")]


def _example(chosen: str | None = None) -> str:
    """bobina config locale <the LANG tag when it differs, else an example>."""
    _, system = system_language()
    other = system if system and system != chosen and system.lower() != FALLBACK else ("en-US" if chosen else "pt-BR")
    return f"bobina config locale {other}"


def _save(value: str) -> str:
    """Saves locale = VALUE in config.toml (the rest of the file as it was); "" or why it could not."""
    from . import config, fileio

    try:
        config.set_value("locale", value)
    except (OSError, fileio.StateError, fileio.LockTimeout) as e:
        return str(getattr(e, "strerror", None) or e)
    return ""


def choose(meta: dict, machine: Machine | str | None = None) -> Choice:
    """The locale of a document: its locale: (or lang:), else the machine's, else English."""
    notes: list = []
    loc = parse(meta.get("locale") or meta.get("lang"))
    origin = "document"
    if loc is None:
        value, notes = machine.get() if isinstance(machine, Machine) else (machine, [])
        loc = parse(value)
        origin = "config" if loc is not None else "default"
    loc = loc or Locale.parse(FALLBACK)
    shown = printable(loc)
    if shown != loc and origin == "document":  # the machine's says it once, in Machine
        notes = [*notes, script_note(loc, shown, "the document's locale:")]
    return Choice(shown, origin != "default", origin, list(notes))
