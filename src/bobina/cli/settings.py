"""bobina config: see and change a setting of config.toml (today: locale)."""

from __future__ import annotations

from .. import config, locales
from .common import OK, USAGE, Fail, err, print_json, render_problems


def _examples(loc) -> dict:
    """A date, a number and an amount in the country's currency, as documents without locale: will print them."""
    from babel import dates as bdates
    from babel import numbers as bnumbers

    from ..templating import current_time, resolve_tz

    country = locales.country_of_locale(loc)
    currencies = bnumbers.get_territory_currencies(country) if country else []
    return {
        "date": bdates.format_date(current_time(resolve_tz({})), "short", locale=loc),
        "number": bnumbers.format_decimal(1234.5, locale=loc),
        "money": bnumbers.format_currency(1234.5, currencies[0] if currencies else "USD", locale=loc),
    }


def _state() -> dict:
    """What documents without locale: use on this machine now, and where it comes from (nothing is written)."""
    saved = config.load().get("locale")
    zone = locales.system_zone()
    if saved and locales.parse(saved):
        value, source = locales.tag(locales.parse(saved)), "config"
    elif saved:
        value, source = None, "default"  # an unknown tag in config.toml: English, as M204 says
    else:
        value, source = locales.infer(zone, locales.system_language()[0]), "time zone"
        source = source if value else "default"
    loc = locales.parse(value) or locales.parse(locales.FALLBACK)
    shown = locales.printable(loc)
    return {"schema": "bobina.config/1", "key": "locale", "value": value, "source": source,
            "prints_as": locales.tag(shown), "time_zone": zone, "path": str(config.path()),
            "example": _examples(shown), "_loc": loc, "_saved": saved}  # fmt: skip


def cmd_config(args):
    notes = []
    if args.value is not None:
        loc = locales.parse(args.value)
        if loc is None:
            hint = "→ a BCP 47 tag: pt-BR, en-US, fr-CA, en-IN"
            raise Fail(USAGE, f"'{args.value}' is not a locale bobina knows\n{hint}", problem="E304")
        try:
            config.set_value("locale", locales.tag(loc))
        except OSError as e:
            raise Fail(USAGE, f"cannot write {config.path()}: {e.strerror or e}", problem="E209") from None
    st = _state()
    loc, saved = st.pop("_loc"), st.pop("_saved")
    if st["prints_as"] != locales.tag(loc):
        notes.append(locales.script_note(loc, locales.parse(st["prints_as"]), "config.toml"))
        if args.value is not None:
            locales.first_time(f"F304 {locales.tag(loc)}")  # said here: the next print does not repeat it
    from ..nudges import Nudge

    problems = [Nudge(c, m, None, h) for c, m, h in notes]
    if args.json:
        print_json({**st, "problems": [n.as_dict() for n in problems]}, indent=2, ensure_ascii=False)
        return OK
    ex = " · ".join(st["example"].values())
    if args.value is not None:
        print(f"locale {st['value']} saved in {st['path']}: {ex}")
    elif st["source"] == "config":
        print(f"locale {st['value']} (config.toml): {ex}")
        print("documents with locale: keep theirs · change it: bobina config locale TAG")
    elif st["source"] == "time zone":
        print(f"locale not set: the first print, check or preview saves {st['value']} (from the time zone"
              f" {st['time_zone']}): {ex}")  # fmt: skip
        print(f"set it now: bobina config locale {st['value']}")
    else:
        zone = f"no country in the time zone {st['time_zone']}" if st["time_zone"] else "no time zone"
        why = f"locale = {saved!r} in config.toml is not a locale bobina knows" if saved else zone
        print(f"{why}: documents without locale: print in English (en): {ex}")
        print("set yours: bobina config locale TAG (pt-BR, en-GB, fr-CA …)")
    if problems and not args.quiet:
        for line in render_problems(problems, ""):
            err(line)
    return OK
