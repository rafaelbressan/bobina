"""Built-in knowledge: profiles, templates, counters, fonts."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .. import engine
from .. import profile as profiles
from .common import OK, USAGE, Fail, print_json


def cmd_profile(args):
    if args.action == "list":
        import tomllib

        rows = {}
        for k, v in profiles.available().items():
            try:
                rows[k] = {"source": v, "measured": profiles.load(k).get("measured", True) is not False}
            except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as e:  # a broken user profile still lists
                rows[k] = {"source": v, "measured": None, "error": str(e)}
        if args.json:
            print_json(rows, indent=2)
            return OK
        for k, r in rows.items():
            kind = {True: "measured", False: "not measured (imported)", None: f"unreadable: {r.get('error')}"}
            print(f"{k:28s} {kind[r['measured']]:24s} {r['source']}")
        return OK
    p = profiles.load(args.name or args.profile)
    if args.json:
        print_json(p.data, indent=2, default=str)
        return OK
    cell = f"{p.cell[0]}x{p.cell[1]}"
    print(f"{p.id}: {p.name}\n  {p.width_dots} dots, {p.dpi} dpi, {p.columns} columns (native font {cell})")
    print(f"  evidence: {p.get('evidence', '')}")
    from .. import features

    untested = features.of_profile(p)
    if untested:
        names = ", ".join(features.FEATURES[f]["title"] for f in untested)
        print(f"  {features.MARK}: {names} (docs/TESTED.md)")
    if p.get("measured") is False:
        print(f"  source: {p.get('source', '?')}; not measured on paper: bobina calibrate tear, bobina calibrate feed")
    print(
        f"  qr: module {p.get('qr.default_module')} ecc {p.get('qr.default_ecc')} · images: "
        f"{p.get('image.dither')} gamma {p.get('image.gamma')} · preview calibrated: {p.get('preview.calibrated')}"
    )
    return OK


def template_names() -> list[str]:
    from importlib import resources

    d = resources.files("bobina") / "templates"
    return sorted(f.name[:-7] for f in d.iterdir() if f.name.endswith(".bob.md"))


def template_meta(name: str) -> dict:
    from ..templating import split_front_matter

    try:
        meta, _, _ = split_front_matter(engine.load_template(name, os.getcwd()))
    except ValueError as e:
        raise Fail(USAGE, str(e), problem="E207") from None
    return meta


def starter(name: str) -> str:
    """A document that fills template NAME, every field with a # required / # optional comment."""
    return starter_from_fields(name, engine.template_fields(template_meta(name)))


def starter_from_fields(name: str, fields: dict) -> str:
    """The starter of template NAME from its fields (bobina template show NAME --json): bobina mcp builds it from
    that JSON."""
    out = ["---", f"template: {name}"]
    for k, spec in fields.items():
        val = "[]" if spec.get("type") == "table" or k in ("items", "lines") else '""'
        note = "required" if spec.get("required") else "optional"
        hint = spec.get("example") or spec.get("help") or (f"default: {spec['default']}" if "default" in spec else "")
        out.append(f"{k}: {val}".ljust(24) + f"# {note}" + (f" — {hint}" if hint else ""))
    out.append("---")
    return "\n".join(out) + "\n"


def cmd_template(args):
    if args.action == "list":
        names = template_names()
        if args.json:
            print_json(names)
            return OK
        width = max(len(n) for n in names)
        for n in names:
            f = engine.template_fields(template_meta(n))
            req = [k for k, v in f.items() if v.get("required")]
            print(f"{n:{width}s}  fields: {', '.join(f)}  (required: {', '.join(req) or '-'})")
        return OK
    if not args.name:
        raise Fail(USAGE, f"usage: bobina template {args.action} NAME", problem="E101")
    if args.action == "show":
        f = engine.template_fields(template_meta(args.name))
        if args.json:
            print_json(f, indent=2, ensure_ascii=False)
            return OK
        print(f"{'FIELD':12s}{'REQUIRED':10s}{'TYPE':8s}DEFAULT / EXAMPLE / HELP")
        for k, v in f.items():
            info = v.get("default") or v.get("example") or v.get("help") or ""
            print(f"{k:12s}{'yes' if v.get('required') else 'no':10s}{v.get('type', 'text'):8s}{info}")
        print(f"\nstart one: bobina template new {args.name} my-{args.name}.bob.md")
        return OK
    if args.action == "new":
        text = starter(args.name)
        if args.file:
            p = Path(args.file)
            if p.exists():
                raise Fail(USAGE, f"{p} exists", problem="E208")
            p.write_text(text)
            print(f"wrote {p}: fill the fields, then: bobina print {p}")
        else:
            print(text, end="")
        return OK
    return USAGE


def cmd_seq(args):

    from .. import fileio, paths

    path = paths.state_dir() / "counters.json"
    if args.action == "list":
        st = fileio.read_json(path, {})
        if args.json:
            print_json(st)
        elif not st:
            print("no counters yet: a counter starts at the first confirmed print that uses {{ seq.NAME }},"
                  " or with bobina seq set NAME N")  # fmt: skip
        for k, v in st.items():
            print(f"{k:16s} next value {v}")
        return OK
    if not args.name:
        raise Fail(
            USAGE, f"usage: bobina seq {args.action} NAME" + (" VALUE" if args.action == "set" else ""), problem="E101"
        )
    if args.action == "set" and args.value is None:
        raise Fail(USAGE, "usage: bobina seq set NAME VALUE", problem="E101")

    def change(st):
        if args.action == "set":
            st[args.name] = int(args.value)
        else:
            st.pop(args.name, None)

    fileio.locked_update(path, change)
    st = fileio.read_json(path, {})
    print(
        f"{args.name}: "
        + (f"next value {st[args.name]}" if args.name in st else "reset (starts from its start: value)")
    )
    return OK


FONTS = [
    ("native", "recommended", "1x", "fastest; 32 columns; no italic"),
    ("Terminus", "recommended", "12px", "bitmap; best at small sizes"),
    ("Atkinson Hyperlegible", "recommended", "14px", "body text (bold ok)"),
    ("IBM Plex Mono", "ok", "16px", "tables, code (bold 16, regular 20)"),
    ("Barlow Condensed", "ok", "20px", "narrow"),
    ("Spleen 12x24", "preview", "24px", "emulates the printer font in previews"),
    ("Z003", "poor <28px", "28px", "script; titles only (system font)"),
]


def font_test_doc(family: str) -> str:
    sizes = [12, 14, 16, 20, 24, 28, 32]
    out = [
        f'---\nfonts: {{test: "{family}"}}\nallow: [F201, F202]\n---',
        "# FONT TEST {.center}",
        f"{family} {{.center}}",
        "",
    ]
    for px in sizes:
        out.append(f"{px}px: Ação Pão 0O1lI {{font=test size={px}px}}")
        out.append("")
        out.append(f"{px}px bold: **Ação Pão 0O1lI** {{font=test size={px}px}}")
        out.append("")
    out.append(f'Mark the smallest legible size: bobina fonts mark "{family}" PX {{.center}}')
    out.append("")
    out.append("--- {.cut}")
    return "\n".join(out) + "\n"


def cmd_fonts(args):
    from .. import rasterfont

    if args.action == "test":
        if not args.family:
            raise Fail(USAGE, 'usage: bobina fonts test "FAMILY"', problem="E101")
        if rasterfont.resolve(args.family) is None:
            raise Fail(USAGE, f'font "{args.family}" not found (bundled or installed)', problem="E207")
        args.target = font_test_doc(args.family)
        args.last = args.again = False
        args.output = None
        from .documents import cmd_print  # lazy: documents imports this module

        return cmd_print(args)
    if args.action == "mark":
        if not args.family or not args.px:
            raise Fail(USAGE, 'usage: bobina fonts mark "FAMILY" MIN_PX [--note TEXT]', problem="E101")
        rasterfont.mark(args.family, int(args.px), args.note or "")
        print(f"{args.family}: minimum {args.px}px saved; check and print will nudge below it")
        return OK
    user = rasterfont.user_registry()
    rows = list(FONTS) + [
        (v.get("family", k), "marked", f"{v['min_px']}px", v.get("note", "your test")) for k, v in user.items()
    ]
    if args.json:
        print_json([dict(zip(("font", "status", "min", "notes"), f, strict=True)) for f in rows], indent=2)
        return OK
    print(f"{'FONT':24s}{'STATUS':14s}{'MIN':7s}NOTES")
    for f in rows:
        print(f"{f[0]:24s}{f[1]:14s}{f[2]:7s}{f[3]}")
    print('\nuntested fonts: bobina measures the stem (≥ 2 dots); test one: bobina fonts test "FAMILY"')
    print("evidence: docs/printers/mtp-ii-58.md (tests F1, F2, R5)")
    return OK


def cmd_library(args):
    """Saved labels printed by name: bobina print @NAME."""
    from .. import library
    from .common import _read_target

    try:
        if args.action == "list":
            items = library.entries()
            if args.json:
                print_json(items, indent=2, ensure_ascii=False)
                return OK
            if not items:
                print("no saved labels yet. Save one: bobina library add NAME FILE")
                return OK
            for name, e in items.items():
                source, base = library.get(name)
                try:
                    missing = [k for k, _ in engine.fields_to_ask(source, base)]
                except Exception:  # noqa: BLE001
                    missing = []
                ask = f"  fields: {', '.join(missing)} (--set or --ask)" if missing else ""
                print(f"@{name:16s} {e.get('note', '')}{ask}")
            return OK
        if not args.name:
            raise Fail(
                USAGE,
                f"usage: bobina library {args.action} NAME" + (" FILE" if args.action == "add" else ""),
                problem="E101",
            )
        if args.action == "add":
            if not args.source:
                raise Fail(USAGE, 'usage: bobina library add NAME FILE|"TEXT"', problem="E101")
            library.check_name(args.name)
            ns = argparse.Namespace(**{**vars(args), "target": args.source})
            source, base, origin = _read_target(ns)
            p = library.add(args.name, source, base, origin, note=args.note or "", force=args.force)
            print(f"saved @{args.name} ({p}). Print it: bobina print @{args.name}")
            return OK
        if args.action == "show":
            source, base = library.get(args.name)
            e = library.entries().get(args.name, {})
            print(f"@{args.name}  from {e.get('origin', '?')}  (images relative to {base})")
            if e.get("note"):
                print(f"note: {e['note']}")
            print("-" * 32)
            print(source, end="" if source.endswith("\n") else "\n")
            return OK
        if args.action == "rm":
            library.remove(args.name)
            print(f"removed @{args.name}")
            return OK
    except library.LibraryError as e:
        raise Fail(USAGE, str(e), problem="E206") from None
    return USAGE
