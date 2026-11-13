"""bobina history: what was printed, cancelled, saved or failed (like git log)."""

from __future__ import annotations

from .. import history
from .common import OK, USAGE, Fail, ask, open_tty, plural, print_json


def _files(r: dict) -> str:
    parts = r.get("parts") or []
    return ", ".join(p["file"] for p in parts) or " ".join(a for a in r.get("argv", [])[1:3])


def _line(r: dict) -> str:
    probs = r.get("problems", [])
    errs = sum(1 for p in probs if p.get("severity") == "error")
    warns = sum(1 for p in probs if p.get("severity") == "warning")
    mark = (f" ✗{errs}" if errs else "") + (f" !{warns}" if warns else "")
    n = f"{r['labels_printed']}/{r.get('labels', 0)}" if "labels_printed" in r else f"{r.get('labels', 0)}"
    size = f"{n:>3} lbl {r.get('length_mm', 0) / 10:5.1f} cm" if "labels" in r else " " * 16
    return f"{r['id']}  {r['time'][:16].replace('T', ' ')}  {r.get('outcome', '?')[:16]:16s} {size}  {_files(r)}{mark}"


def _long(r: dict) -> str:
    out = [
        f"job {r['id']}",
        f"  time      {r['time']}  ({r.get('duration_s', 0)} s)",
        f"  outcome   {r.get('outcome', '?')} (exit {r.get('exit')})",
    ]
    if r.get("printer"):
        out.append(f"  printer   {r['printer']}  profile {r.get('profile', '')}")
    if r.get("saved_to"):
        out.append(f"  saved to  {r['saved_to']}")
    if "labels" in r:
        joins = f"{r.get('cuts', 0)} ✂  {r.get('tears', 0)} tear feeds"
        n = f"{r['labels_printed']} of {r['labels']} printed" if "labels_printed" in r else f"{r['labels']}"
        out.append(f"  labels    {n}  ·  {r['length_mm'] / 10:.1f} cm  ·  {joins}")
    for p in r.get("parts", []):
        out.append(f"  part {p['part']}    {p['file']}")
    for name, vals in (r.get("counters") or {}).items():
        out.append(f"  seq.{name}  {', '.join(vals)}")
    out.append(f"  command   bobina {' '.join(r.get('argv', []))}")
    for p in r.get("problems", []):
        where = f" {p['source']}" if p.get("source") else ""
        out.append(f"  {p['severity']:<8}{p['code']}{where}: {p['message']}")
    if r.get("bytes_sha256"):
        out.append(f"  bytes     sha256 {r['bytes_sha256'][:16]}…")
    return "\n".join(out)


OUTCOMES = (
    "printed",
    "stopped",
    "reprinted",
    "cancelled",
    "failed",
    "saved",
    "dry run",
    "interrupted",
    "nothing printed",
)


def _outcome(word: str | None) -> str | None:
    if not word:
        return None
    w = word.replace("-", " ").replace("_", " ").lower()
    if w == "strict":
        w = "nothing printed"
    if not any(o.startswith(w) for o in OUTCOMES):
        raise Fail(USAGE, f"--outcome {word}: use one of {', '.join(OUTCOMES)}", problem="E101")
    return w


def _since(value: str | None) -> str | None:
    """2026-11-07, 2026-11-07T18:00, today, yesterday, or 3d / 2w (days/weeks ago)."""
    if not value:
        return None
    import re
    from datetime import date, datetime, timedelta

    v = value.strip().lower()
    if v in ("today", "hoje"):
        return date.today().isoformat()
    if v in ("yesterday", "ontem"):
        return (date.today() - timedelta(days=1)).isoformat()
    m = re.fullmatch(r"(\d+)\s*([dw])", v)
    if m:
        days = int(m.group(1)) * (7 if m.group(2) == "w" else 1)
        return (date.today() - timedelta(days=days)).isoformat()
    try:
        iso = v.upper().replace(" ", "T", 1)  # 2026-11-07 18:00 works like 2026-11-07T18:00
        d = datetime.fromisoformat(iso)
        if "T" not in iso:
            return d.date().isoformat()
        return d.isoformat(timespec="seconds" if iso.count(":") >= 2 else "minutes")
    except ValueError:
        raise Fail(
            USAGE, f"--since {value}: use a date (2026-11-07), today, yesterday or 3d/2w", problem="E101"
        ) from None


def cmd_history(args):
    rows = history.load()
    if args.action == "clear":
        if not rows:
            print("history is empty")
            return OK
        if not args.yes:
            tty = open_tty()
            if tty is None:
                raise Fail(USAGE, "clearing the history needs confirmation: add --yes", problem="E107")
            with tty:
                if ask(tty, f" delete {plural(len(rows), 'job')} from {history.path()}? [y/N] ") not in ("y", "yes"):
                    return OK
        from .. import fileio

        with fileio.locked(history.path()):
            history.path().unlink(missing_ok=True)
        print(f"history cleared ({plural(len(rows), 'job')})")
        return OK
    total = len(rows)
    rows = history.select(rows, since=_since(args.since), outcome=_outcome(args.outcome), printer=args.printer)
    if args.action == "show":
        if not args.id:
            raise Fail(USAGE, "usage: bobina history show ID (see: bobina history)", problem="E101")
        hits = [r for r in rows if r["id"].startswith(args.id) or args.id == "last"]
        if args.id == "last":
            hits = hits[-1:]
        if not hits:
            raise Fail(USAGE, f"no job '{args.id}' in the history", problem="E101")
        r = hits[-1]
        if args.json:
            print_json(r, indent=2, ensure_ascii=False)
        else:
            print(_long(r))
        return OK
    if args.action == "stats":
        st = history.stats(rows)
        if args.json:
            print_json(st, indent=2, ensure_ascii=False)
            return OK
        print(f"{st['jobs']} jobs · " + ", ".join(f"{k} {v}" for k, v in st["by_outcome"].items()))
        print(f"printed: {st['printed_labels']} labels, {st['paper_cm']} cm of paper, ", end="")
        print(f"{st['avg_print_s']} s per job on average")
        for week, cm in st["paper_cm_by_week"].items():
            print(f"  {week}  {cm:6.1f} cm  " + "█" * min(40, int(cm / 5)))
        if st["top_problems"]:
            print("most frequent problems: " + ", ".join(f"{c} ×{n}" for c, n in st["top_problems"]))
        return OK
    rows = rows[-args.limit :] if args.limit else rows
    if args.json:
        print_json(rows, indent=2, ensure_ascii=False)
        return OK
    if not rows:
        if total:
            print(f"no job matches (the history has {total})")
        else:
            print("no jobs yet" + ("" if history.enabled() else " (history is off: history = false in config.toml)"))
        return OK
    for r in reversed(rows):
        print(_long(r) + "\n" if args.long else _line(r))
    if history.skipped:
        print(f"note: {history.skipped} damaged line(s) in {history.path()} were skipped")
    return OK
