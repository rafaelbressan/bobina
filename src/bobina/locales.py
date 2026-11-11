"""The locale of a print, one for dates, numbers and money (never mixed): the document's locale:, else the machine's
(locale in config.toml, inferred from the time zone on the first run that needs it and saved), else English.

The engine alone (tests, library use) knows no machine: a document without locale: is English there. The CLI passes
a Machine, which reads config.toml, infers and saves, and says once what it chose (M203, M204, F306).

Only the document's own locale: settles a typed amount that reads two ways (1.890): the machine's was not chosen
for that document, so | currency prints it as typed with M202 (payments refuse it in any locale)."""

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
SAID = "said.json"  # in the state folder: the notes already given once (M204, F306 of the config's locale)
SCRIPT = "F306"  # no font for the locale's script yet


@dataclass
class Choice:
    locale: Locale  # what dates, numbers and money are written in
    explicit: bool  # the document's own locale: (it settles 1.890); the machine's and English do not
    origin: str = "default"  # document | config | default
    notes: list = field(default_factory=list)  # (code, message, suggestion) for the job's problems


def tag(loc: Locale) -> str:
    """pt_BR -> pt-BR (BCP 47, as documents and config.toml write it)."""
    return str(loc).replace("_", "-")


# ---------------------------------------------------------------- reading tags


def parse(value) -> Locale | None:
    """A locale from a tag as people write it (pt-BR, pt_BR.UTF-8, fr, en-TH), or None. A language with a country
    English with a country CLDR does not pair it with (en-TH, en-BR) is English words with the country's formats
    (what printable() falls back to). Other unknown pairs (pt-BT, a typo of pt-BR) are None: never guessed."""
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
    m = re.fullmatch(r"(en)_([A-Za-z]{2})", s, re.I)
    return mixed("en", m.group(2).upper()) if m else None


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
    return (SCRIPT, f"bobina cannot draw {lang} yet ({tag(loc)}, {where}): dates and numbers print as {tag(shown)}, "
            f"English words with {formats}", f"or choose another locale: {CHANGE}")  # fmt: skip


CHANGE = "bobina config locale TAG"


# ---------------------------------------------------------------- the machine


def system_zone() -> str | None:
    """This machine's time zone (IANA name): TZ, else the link /etc/localtime, else /etc/timezone; None when there is
    none (a container without zone data). Read once per process for each TZ value."""
    return _zone(os.environ.get("TZ", ""), LOCALTIME, TIMEZONE_FILE)


def _valid_zone(name: str) -> str | None:
    from zoneinfo import ZoneInfo

    name = (name or "").strip().lstrip(":")
    if not name or name.startswith("/"):
        return None
    try:
        ZoneInfo(name)
        return name
    except Exception:  # noqa: BLE001 - not a zone name (POSIX rules like <-03>3, a typo)
        return None


@lru_cache(maxsize=8)
def _zone(tz: str, localtime: str, timezone_file: str) -> str | None:
    if found := _valid_zone(tz):
        return found
    try:
        link = os.path.realpath(localtime)  # .../zoneinfo/America/Sao_Paulo
        if "zoneinfo/" in link and (found := _valid_zone(link.split("zoneinfo/", 1)[1])):
            return found
    except OSError:
        pass
    try:
        return _valid_zone(Path(timezone_file).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def country_of(zone: str | None) -> str | None:
    """America/Sao_Paulo -> BR; Etc/UTC and unknown zones -> None."""
    from babel.core import get_global

    if not zone:
        return None
    zone = get_global("zone_aliases").get(zone, zone)  # Asia/Calcutta -> Asia/Kolkata
    country = get_global("zone_territories").get(zone)
    return country if country and country.isalpha() and country != "ZZ" else None


LANG_VARS = ("LC_ALL", "LC_TIME", "LANG")  # the first one set wins, as for every program


def system_locale() -> tuple[str, Locale | None]:
    """(VAR=value, its locale) of the first of LC_ALL, LC_TIME, LANG that is set; C and POSIX -> None."""
    for var in LANG_VARS:
        value = os.environ.get(var, "").strip()
        if value:
            return f"{var}={value}", parse(value)
    return "", None


def system_language() -> tuple[str | None, str | None]:
    """(language, tag) of the system locale: en_US.UTF-8 -> ("en", "en-US"); C and POSIX -> (None, None)."""
    _, loc = system_locale()
    return (loc.language, tag(loc)) if loc else (None, None)


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
    """True the first time KEY is asked about on this machine (state folder); True again when that cannot be kept.
    said.json is read first and written (under its lock) only for a new key."""
    from . import fileio, paths

    p = paths.state_dir() / SAID
    try:
        if key in fileio.read_json(p, {}):
            return False

        def mark(said: dict) -> bool:
            new = key not in said
            said[key] = True
            return new

        return fileio.locked_update(p, mark)
    except (OSError, fileio.StateError, fileio.LockTimeout):
        return True


@dataclass
class Found:
    """What documents without locale: use on this machine, and where it comes from (Machine.peek: nothing written)."""

    value: str | None  # a tag (pt-BR), or None: English
    source: str  # config | time zone | environment | default
    detail: str = ""  # the time zone America/Sao_Paulo · LANG=pt_BR.UTF-8; no country in the time zone Etc/UTC
    zone: str | None = None
    bad: str | None = None  # an unknown locale in config.toml (English is used)


class Machine:
    """The locale of documents without locale: on this machine, for one CLI job (made per job, so `bobina edit`
    sees a change on its next rebuild). peek() says what it is without writing; get() also saves an inferred one
    and gives the notes, once per job: a batch of 1000 labels or a job of three parts says them once."""

    def __init__(self):
        self._got: tuple[str | None, list] | None = None

    def peek(self) -> Found:
        from . import config

        zone = system_zone()
        saved = config.load().get("locale")
        if saved:
            loc = parse(saved)
            if loc is None:
                return Found(None, "default", "config.toml", zone, bad=str(saved))
            return Found(tag(loc), "config", "config.toml", zone)
        language, _ = system_language()
        if found := infer(zone, language):
            return Found(found, "time zone", f"the time zone {zone}", zone)
        var, loc = system_locale()
        if loc is not None and loc.language != FALLBACK:  # pt_BR.UTF-8 in a container without a zone
            where = f"no country in the time zone {zone}" if zone else "no time zone"
            return Found(tag(loc), "environment", f"{var}; {where}", zone)
        return Found(None, "default", "", zone)

    def get(self) -> tuple[str | None, list]:
        if self._got is not None:
            return self._got[0], []
        self._got = self._resolve()
        return self._got

    def _resolve(self) -> tuple[str | None, list]:
        f = self.peek()
        if f.bad is not None:
            msg = f"locale = {f.bad!r} in config.toml is not a locale bobina knows: dates, numbers and money in English"
            return None, [("M204", msg, f"set yours: {_example(near=closest(f.bad))}")]
        if f.value is None:
            where = f"no country in the time zone {f.zone}" if f.zone else "no time zone on this machine"
            msg = f"{where}, and LC_ALL, LC_TIME, LANG name no other language: dates, numbers and money in English (en)"
            return None, [("M204", msg, f"set yours: {_example()}")] if first_time("M204") else []
        loc = parse(f.value)
        shown = printable(loc)
        if f.source == "config":
            note = shown != loc and first_time(f"{SCRIPT} {f.value}")
            return f.value, [script_note(loc, shown, "config.toml")] if note else []
        problem = _save(f.value)
        if problem:
            note = ("M203", f"locale {f.value} (from {f.detail}); not saved: {problem}",
                    f"set it: bobina config locale {f.value}")  # fmt: skip
        else:
            note = ("M203", f"locale {f.value} (from {f.detail}), saved in config.toml",
                    f"change it: {_example(f.value)}")  # fmt: skip
        if shown == loc:
            return f.value, [note]
        first_time(f"{SCRIPT} {f.value}")  # said now, with the choice: not again on the next run
        return f.value, [note, script_note(loc, shown, f"from {f.detail}")]


def _example(chosen: str | None = None, near: str = "") -> str:
    """bobina config locale <a close tag, the system locale's when it differs, else an example>."""
    _, system = system_language()
    other = near or (system if system and system != chosen and system.lower() != FALLBACK else "")
    return f"bobina config locale {other or ('en-US' if chosen else 'pt-BR')}"


@lru_cache(maxsize=1)
def _known() -> dict[str, str]:
    """Every CLDR locale as a tag, by its lower-case form: pt-br -> pt-BR."""
    out = {}
    for ident in localedata.locale_identifiers():
        try:
            t = tag(Locale.parse(ident))
        except (UnknownLocaleError, ValueError):
            continue
        out[t.lower()] = t
    return out


def _distance(a: str, b: str) -> int:
    d = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, d[0] = d[0], i
        for j, cb in enumerate(b, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (ca != cb))
    return d[-1]


def closest(value) -> str:
    """The known tag nearest to a mistyped one, or "": pt-BT -> pt-BR (same language, nearest country, the
    language's main country first), portugues -> pt (by the language's English name), pt-br -> pt-BR."""
    import difflib

    s = str(value or "").strip().split(".")[0].replace("_", "-").lower()
    known = _known()
    if s in known:
        return known[s]
    lang, _, rest = s.partition("-")
    same = [t for t in known.values() if t.lower().startswith(lang + "-") and "-" not in t[len(lang) + 1 :]]
    if same and rest:
        main = country_of_locale(Locale.parse(lang)) or ""
        best = min(same, key=lambda t: (_distance(rest, t[len(lang) + 1 :].lower()), t[len(lang) + 1 :] != main))
        return best
    names = {name.lower(): code for code, name in Locale("en").languages.items() if code in known}
    near = difflib.get_close_matches(s, list(names), n=1, cutoff=0.75)
    if near:
        return known[names[near[0]]]
    near = difflib.get_close_matches(s, list(known), n=1, cutoff=0.6)
    return known[near[0]] if near else ""


def _save(value: str) -> str:
    """Saves locale = VALUE in config.toml (the rest of the file as it was); "" or why it could not."""
    from . import config, fileio

    try:
        config.set_value("locale", value)
    except (OSError, fileio.StateError, fileio.LockTimeout) as e:
        return str(getattr(e, "strerror", None) or e)
    return ""


def choose(meta: dict, machine: Machine | str | None = None) -> Choice:
    """The locale of a document: its locale: (or lang:), else the machine's, else English. An unknown locale: is
    said (M205) and the machine's is used."""
    notes: list = []
    key = "locale" if meta.get("locale") else "lang"
    written = meta.get(key)
    loc = parse(written)
    origin = "document"
    if loc is None:
        value, notes = machine.get() if isinstance(machine, Machine) else (machine, [])
        loc = parse(value)
        origin = "config" if loc is not None else "default"
        if written:
            used = f"{tag(loc)}, this machine's" if loc is not None else "English (en)"
            near = closest(written)
            hint = (f"did you mean {key}: {near}? " if near else "") + "a BCP 47 tag like pt-BR, en-US, fr-CA"
            notes = [*notes, ("M205", f"{key}: {str(written)!r} is not a locale bobina knows: printed in {used}", hint)]
    loc = loc or Locale.parse(FALLBACK)
    shown = printable(loc)
    if shown != loc and origin == "document":  # the machine's says it once, in Machine
        notes = [*notes, script_note(loc, shown, "the document's locale:")]
    return Choice(shown, origin == "document", origin, list(notes))
