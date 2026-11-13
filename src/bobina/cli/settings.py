"""bobina config: see and change a setting of config.toml (locale, step)."""

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


ON, OFF = ("on", "true", "yes", "1"), ("off", "false", "no", "0")


def config_step(args):
    """step: does a print of several labels stop after each one (on, the default) or print them at once (off)."""
    if args.value is not None:
        v = args.value.strip().lower()
        if v not in ON + OFF:
            raise Fail(USAGE, f"bobina config step {args.value}: use on or off", problem="E304")
        try:
            config.set_value("step", v in ON)
        except OSError as e:
            raise Fail(USAGE, f"cannot write {config.path()}: {e.strerror or e}", problem="E209") from None
    raw = config.load().get("step")
    source = "config" if raw is not None else "default"
    if raw is not None and not isinstance(raw, bool):
        raise Fail(USAGE, f"step = {raw!r} in config.toml: use bobina config step on|off", problem="E101")
    on = raw is not False
    st = {"schema": "bobina.config/1", "key": "step", "value": on, "source": source, "path": str(config.path())}
    if args.json:
        print_json({**st, "problems": []}, indent=2, ensure_ascii=False)
        return OK
    what = ("on: a print of several labels stops after each one so you can tear it off"
            if on else "off: the labels of a print come out at once")  # fmt: skip
    where = " (saved in config.toml)" if args.value is not None else " (config.toml)" if raw is not None else ""
    print(f"step {what}{where}")
    print("one print: --no-step (all at once) or --step N (stop every N) · always: bobina config step "
          + ("off" if on else "on"))  # fmt: skip
    return OK


def cmd_config(args):
    if args.key == "step":
        return config_step(args)
    if args.value is not None:
        loc = locales.parse(args.value)
        if loc is None:
            near = locales.closest(args.value)
            hint = (f"→ did you mean {near}? " if near else "→ ") + "a BCP 47 tag: pt-BR, en-US, fr-CA, en-IN"
            raise Fail(USAGE, f"'{args.value}' is not a locale bobina knows\n{hint}", problem="E304")
        try:
            config.set_value("locale", locales.tag(loc))
        except OSError as e:
            raise Fail(USAGE, f"cannot write {config.path()}: {e.strerror or e}", problem="E209") from None
    found = locales.Machine().peek()  # the same answer a print would act on; nothing written
    loc = locales.parse(found.value) or locales.parse(locales.FALLBACK)
    shown = locales.printable(loc)
    notes = []
    if shown != loc:
        notes.append(
            locales.script_note(loc, shown, found.detail if found.source == "config" else f"from {found.detail}")
        )
        if args.value is not None:
            locales.first_time(f"{locales.SCRIPT} {found.value}")  # said here: the next print does not repeat it
    from ..nudges import Nudge

    problems = [Nudge(c, m, None, h) for c, m, h in notes]
    st = {"schema": "bobina.config/1", "key": "locale", "value": found.value, "source": found.source,
          "prints_as": locales.tag(shown), "time_zone": found.zone, "path": str(config.path()),
          "example": _examples(shown)}  # fmt: skip
    if args.json:
        print_json({**st, "problems": [n.as_dict() for n in problems]}, indent=2, ensure_ascii=False)
        return OK
    ex = " · ".join(st["example"].values())
    if args.value is not None:
        print(f"locale {found.value} saved in {st['path']}: {ex}")
    elif found.source == "config":
        print(f"locale {found.value} (config.toml): {ex}")
        print("documents with locale: keep theirs · change it: bobina config locale TAG")
    elif found.source in ("time zone", "environment"):
        print(f"locale not set: the first print, check or preview saves {found.value} (from {found.detail}): {ex}")
        print(f"set it now: bobina config locale {found.value}")
    else:
        zone = f"no country in the time zone {found.zone}" if found.zone else "no time zone"
        why = f"locale = {found.bad!r} in config.toml is not a locale bobina knows" if found.bad else zone
        print(f"{why}: documents without locale: print in English (en): {ex}")
        print("set yours: bobina config locale TAG (pt-BR, en-GB, fr-CA …)")
    if problems and not args.quiet:
        for line in render_problems(problems, ""):
            err(line)
    return OK
