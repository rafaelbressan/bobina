"""bobina config list | get KEY | set KEY VALUE | unset KEY | edit: every setting of config.toml from the command
line (the table: bobina.config_keys). Printers have their own: bobina printer set/show."""

from __future__ import annotations

import tomllib

from .. import config, config_keys, fileio, locales
from ..config_keys import KEYS, SCHEMA, KeyError_, entry, shown
from . import common
from .common import CONFIRM, OK, USAGE, Fail, ask, err, open_editor, print_json, render_problems


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


def _load() -> dict:
    """config.load(); a file that does not read stops with where it breaks (bobina config edit fixes it)."""
    try:
        return config.load()
    except fileio.StateError as e:
        raise Fail(USAGE, f"{e}\n→ bobina config edit", problem="E209") from None


def _key(name: str | None) -> config_keys.Key:
    if not name:
        raise Fail(USAGE, "which setting? bobina config get KEY (all of them: bobina config list)", problem="E101")
    try:
        return config_keys.find(name)
    except KeyError_ as e:
        raise Fail(USAGE, str(e), problem=e.code) from None


def _write(fn, *a) -> None:
    try:
        fn(*a)
    except (OSError, fileio.StateError) as e:
        raise Fail(
            USAGE, f"cannot write {config.path()}: {getattr(e, 'strerror', None) or e}", problem="E209"
        ) from None


def cmd_config(args):
    action = args.action or "list"
    if action != "list" and getattr(args, "all", False):
        err(f"note: --all does nothing with bobina config {action}: it is for bobina config list")
    if action == "list":
        return config_list(args)
    if action == "edit":
        return config_edit(args)
    if action == "unset" and args.key and config_keys.group(args.key):
        return config_unset_group(args, args.key)
    key = _key(args.key)
    if action == "get":
        if args.value:
            raise Fail(USAGE, f"bobina config get {key.name} takes no value; to change it: bobina config set "
                       f"{key.name} {' '.join(args.value)}", problem="E101")  # fmt: skip
        return _locale(args, saved=False) if key.name == "locale" else config_get(args, key)
    if key.owner:
        raise Fail(USAGE, f"{key.name} is set with: {key.owner}", problem="E101")
    if action == "set":
        if not args.value:
            raise Fail(USAGE, f"bobina config set {key.name} VALUE: {key.accepts()}"
                       + (f" (e.g. {key.example})" if key.example else ""), problem="E101")  # fmt: skip
        try:
            value = config_keys.parse(key, args.value)
        except KeyError_ as e:
            raise Fail(USAGE, str(e), problem=e.code) from None
        if args.dry_run:
            print(f"{key.name} = {shown(value)} would be saved (dry run: nothing written)")
            return OK
        _write(config.set_value, key.name, value)
        if key.name == "locale":
            return _locale(args, saved=True)
        return config_get(args, key, said=f"{key.name} = {shown(value)} saved in config.toml")
    if action == "unset":
        if args.value:
            raise Fail(USAGE, f"bobina config unset {key.name} takes no value", problem="E101")
        cfg = _load()  # a file that does not read: E209, never a traceback
        if args.dry_run:
            present, value = config_keys.lookup(cfg, key.name)
            print(f"{key.name} = {shown(value)} would be removed (dry run: nothing written)" if present else
                  f"{key.name} is not set: nothing to remove")  # fmt: skip
            return OK
        try:
            removed = config.unset_value(key.name)
        except (OSError, fileio.StateError) as e:
            raise Fail(USAGE, f"{getattr(e, 'strerror', None) or e}", problem="E209") from None
        said = f"{key.name}: back to the default ({key.default_shown()})" if removed else (
            f"{key.name} was not set: it is the default ({key.default_shown()})")  # fmt: skip
        return config_get(args, key, said=said)
    return USAGE


def _problems(messages: list[str], notes: list[str] = ()) -> list[dict]:
    from ..nudges import Nudge

    return [Nudge("E304", m, None, "bobina config get KEY says what it accepts").as_dict() for m in messages] + [
        Nudge("E304", m, None, "kept as written: check the code (bobina help CODE)", severity="note").as_dict()
        for m in notes
    ]


def config_unset_group(args, group: str) -> int:
    """bobina config unset problems: every GROUP.key back to its default in one go, saying what was removed and the
    command that sets it back exactly as it was."""
    import shlex

    if args.value:
        raise Fail(USAGE, f"bobina config unset {group} takes no value", problem="E101")
    cfg = _load()
    removed = {}
    for key in config_keys.group(group):
        present, value = config_keys.lookup(cfg, key.name)
        if present:
            removed[key.name] = value
    restore = " && ".join(
        f"bobina config set {name} {shlex.quote(config_keys.typed(KEYS[name], v))}" for name, v in removed.items()
    )
    what = " and ".join(f"{n} {config_keys.typed(KEYS[n], v)}" for n, v in removed.items())
    if removed and args.dry_run:
        print(f"{what} would be removed (dry run: nothing written)")
        return OK
    if removed and not args.yes:  # a whole group: asked first, as bobina history clear does
        tty = common.open_tty()
        if tty is None:
            raise Fail(CONFIRM, f"confirmation required: no terminal attached. Re-run with --yes to remove {what} "
                       "(nothing changed)", problem="E107")  # fmt: skip
        with tty:
            if ask(tty, f" remove {what}? [y/n] ") not in ("y", "yes"):
                err("nothing removed")
                return CONFIRM
    done = []
    for name in removed:
        try:
            config.unset_value(name)
        except (OSError, fileio.StateError) as e:
            back = " && ".join(f"bobina config set {n} {shlex.quote(config_keys.typed(KEYS[n], removed[n]))}"
                               for n in done)  # fmt: skip
            again = f"\n→ {', '.join(done)} already removed; to restore them: {back}" if done else ""
            raise Fail(USAGE, f"{getattr(e, 'strerror', None) or e}{again}", problem="E209") from None
        done.append(name)
    if args.json:
        print_json({"schema": SCHEMA, "key": group, "removed": removed, "restore": restore,
                    "path": str(config.path()), "problems": []}, indent=2, ensure_ascii=False)  # fmt: skip
        return OK
    if not removed:
        print(f"nothing to remove: every {group} setting is already the default")
        return OK
    print(f"{what} removed: back to the defaults")
    print(f"to restore them: {restore}")
    return OK


def config_get(args, key, said: str = "") -> int:
    cfg = _load()
    e = entry(key, cfg)
    if args.json:
        problems = _problems([e["problem"]] if e["problem"] else [], e["notes"])
        print_json({"schema": SCHEMA, **e, "path": str(config.path()), "problems": problems}, indent=2,
                   ensure_ascii=False, default=str)  # fmt: skip
        return OK
    if said:
        print(said)
    else:
        where = "config.toml" if e["source"] == "config" else "default"
        value = shown(e["value"]) if e["source"] == "config" else key.default_shown()
        print(f"{key.name} = {value} ({where})")
    print(f"  {key.about}")
    print(
        f"  accepts: {key.accepts()}" + (f" · e.g. bobina config set {key.name} {key.example}" if key.example else "")
    )
    if e["source"] == "config":
        print(f"  default: {key.default_shown()} (bobina config unset {key.name})")
    if e["problem"] and not args.quiet:
        err(f"note: config.toml: {e['problem']}; the default is used")
    for n in e["notes"] if not args.quiet else ():
        err(f"note: {n}: kept as written, it silences or stops nothing until bobina has that code")
    return OK


def config_list(args) -> int:
    cfg = _load()
    show_all = getattr(args, "all", False)
    keys = [k for k in KEYS.values() if k.name != "printers" and (show_all or not k.advanced)]
    rows = [entry(k, cfg) for k in keys]
    printers = cfg.get("printers") if isinstance(cfg.get("printers"), dict) else {}
    shown_keys = {r["key"] for r in rows}  # their problems are on their own line
    others = [m for w, m in config_keys.problems(cfg) if w not in shown_keys]  # unknown keys, printers, [chat.*]
    if args.json:
        print_json({"schema": SCHEMA, "path": str(config.path()), "keys": rows, "printers": printers,
                    "problems": _problems([r["problem"] for r in rows if r["problem"]] + others,
                                          [n for r in rows for n in r["notes"]])},
                   indent=2, ensure_ascii=False, default=str)  # fmt: skip
        return OK
    width = max(len(r["key"]) for r in rows)
    print(f"{config.path()}" + ("" if config.path().exists() else " (not created yet: every value is the default)"))
    for r in rows:
        if r["source"] == "config":
            value, where = shown(r["value"]), ""
        else:
            value, where = r["default_shown"], " (default)"
        flag = "  ← " + (r["problem"] or "; ".join(r["notes"])) if r["problem"] or r["notes"] else ""
        print(f"  {r['key']:<{width}}  {value}{where}{flag}")
    for line in others:
        print(f"  ! {line}")
    if printers:
        print("printers (change: bobina printer set NAME KEY VALUE · all of one: bobina printer show NAME):")
        default = cfg.get("default_printer")
        for name, pr in printers.items():
            pr = pr if isinstance(pr, dict) else {}
            where = pr.get("address") or pr.get("path") or pr.get("command") or ""
            star = "*" if name == default else " "
            print(f"  {star} {name}  {pr.get('transport', 'bluetooth')} {where}  [{pr.get('profile', 'mtp-ii-58')}]")
    hidden = sum(1 for k in KEYS.values() if k.advanced and k.name != "printers")
    print(
        "change: bobina config set KEY VALUE · back to the default: bobina config unset KEY · about one: bobina "
        "config get KEY" + ("" if show_all else f" · {hidden} more: --all") + " · the file: bobina config edit"
    )
    return OK


def config_edit(args) -> int:
    """Opens config.toml in the editor (as bobina edit chooses it), then says what it cannot use."""
    p = config.path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        fileio.atomic_write(p, config.EXAMPLE)
    try:
        cfg = config.load()
    except fileio.StateError:  # the file is broken: that is why it is being edited
        cfg = {}
    code = open_editor(p, getattr(args, "editor", None), cfg)
    if code:
        err(f"note: the editor exited with {code}")
    text = p.read_text(encoding="utf-8")
    try:
        cfg = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise Fail(USAGE, f"{p} is not valid TOML now ({e}): every command stops on it until it is fixed\n"
                   "→ bobina config edit", problem="E209") from None  # fmt: skip
    found = config_keys.problems(cfg)
    if not found:
        print(f"{p}: every setting is fine")
        return OK
    from ..nudges import Nudge

    shown_ = []
    for where, msg in found:
        line = config_keys.line_of(text, where)
        shown_.append(Nudge("E304", msg, line, "bobina config get KEY says what it accepts"))
    for line in render_problems(shown_, f"{p}: bobina uses the default for these"):
        err(line)
    return OK


def _locale(args, saved: bool) -> int:
    """get/set locale: the locale a print would use, where it comes from, and how a date prints with it."""
    found = locales.Machine().peek()  # the same answer a print would act on; nothing written
    loc = locales.parse(found.value) or locales.parse(locales.FALLBACK)
    shown_ = locales.printable(loc)
    notes = []
    if shown_ != loc:
        notes.append(
            locales.script_note(loc, shown_, found.detail if found.source == "config" else f"from {found.detail}")
        )
        if saved:
            locales.first_time(f"{locales.SCRIPT} {found.value}")  # said here: the next print does not repeat it
    from ..nudges import Nudge

    problems = [Nudge(c, m, None, h) for c, m, h in notes]
    st = {"schema": SCHEMA, "key": "locale", "value": found.value, "source": found.source,
          "prints_as": locales.tag(shown_), "time_zone": found.zone, "path": str(config.path()),
          "example": _examples(shown_)}  # fmt: skip
    if args.json:
        print_json({**st, "problems": [n.as_dict() for n in problems]}, indent=2, ensure_ascii=False)
        return OK
    ex = " · ".join(st["example"].values())
    if saved:
        print(f"locale {found.value} saved in {st['path']}: {ex}")
    elif found.source == "config":
        print(f"locale {found.value} (config.toml): {ex}")
        print("documents with locale: keep theirs · change it: bobina config set locale TAG")
    elif found.source in ("time zone", "environment"):
        print(f"locale not set: the first print, check or preview saves {found.value} (from {found.detail}): {ex}")
        print(f"set it now: bobina config set locale {found.value}")
    else:
        zone = f"no country in the time zone {found.zone}" if found.zone else "no time zone"
        why = f"locale = {found.bad!r} in config.toml is not a locale bobina knows" if found.bad else zone
        print(f"{why}: documents without locale: print in English (en): {ex}")
        print("set yours: bobina config set locale TAG (pt-BR, en-GB, fr-CA …)")
    if problems and not args.quiet:
        for line in render_problems(problems, ""):
            err(line)
    return OK
