"""Job history (audit log): one JSON line per `bobina print` in ~/.local/state/bobina/history.jsonl.

Private by default: the text of labels is not kept (a sha256 of each document says whether it changed), values of
--set/--set-all are hidden (they may be a Pix key or a phone number) and inline text targets become "text".
Config: history = false turns it off; history_max (default 5000 jobs) bounds the file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from . import config, fileio, paths

SCHEMA = "bobina.history/1"
VALUE_FLAGS = ("--set", "--set-all")


def path() -> Path:
    return paths.state_dir() / "history.jsonl"


def enabled() -> bool:
    return config.load().get("history", True) is not False


KEEP_VALUE = {  # options whose value is a file name, a number or a setting, never personal data
    "--data", "--join", "--on", "--sheet", "--rows", "--copies", "--repeat", "--copies-from", "--page", "--profile",
    "--printer", "-o", "--output", "--problems", "--allow", "--allow-all", "--editor", "--limit",
}  # fmt: skip
MASK_VALUE = {"--set": "=", "--set-all": "=", "--where": "!=~"}  # keep the key/column, hide the value


def scan(argv: list[str]) -> tuple[list[str], set[str]]:
    """One pass over what a person typed -> (argv as stored, values to mask in stored messages).
    Stored: inline text (any target that is not an existing file, @name or URL) becomes "text"; --set/--set-all/
    --where keep only the key; option values are kept only for the options in KEEP_VALUE. Masked: the values of
    those options, typed text, and the path and query of URLs. Abbreviated options are refused by the parser, so
    they cannot slip through here."""
    out: list[str] = []
    secrets: set[str] = set()
    k = 0
    while k < len(argv):
        tok = argv[k]
        flag, eq, inline = tok.partition("=") if tok.startswith("--") else (tok, "", "")
        if flag in MASK_VALUE:
            value = inline if eq else (argv[k + 1] if k + 1 < len(argv) else "")
            masked = _mask(value, MASK_VALUE[flag])
            out += [f"{flag}={masked}"] if eq else [flag, masked]
            m = re.match(r"[^=!~]*(?:!=|~=|=)(.*)", value, re.S)
            if m and m.group(1):
                secrets.add(m.group(1))
            k += 1 if eq else 2
            continue
        if tok.startswith("-"):
            if eq and flag in TARGET_VALUE:  # --then=TEXT is a target: kept only when it names a file
                out.append(f"{flag}={_target(inline)}")
            elif eq and flag not in KEEP_VALUE:
                out.append(f"{flag}=***")  # a value of an option not known to be safe
            else:
                out.append(tok)
            if eq and inline and flag not in KEEP_VALUE and not (flag in TARGET_VALUE and _is_target_name(inline)):
                secrets.add(inline)
            if not eq and flag in KEEP_VALUE and k + 1 < len(argv):
                out.append(argv[k + 1])
                k += 1
            k += 1
            continue
        out.append(_target(tok))
        if re.match(r"https?://", tok):
            rest = re.sub(r"^https?://[^/?#\s]+", "", tok)
            if len(rest) >= 3:
                secrets.add(rest)  # path and query of a URL: masked in stored messages
        elif not _is_target_name(tok):
            secrets.add(tok)
        k += 1
    return out, secrets


def redact(argv: list[str]) -> list[str]:
    """argv as stored in the history (see scan)."""
    return scan(argv)[0]


TARGET_VALUE = {"--then"}


def _target(tok: str) -> str:
    """A target as stored: commands, files and @names as typed; a URL as scheme://host/… (paths and query
    strings can carry tokens); anything else is typed text and becomes "text"."""
    m = re.match(r"(https?://[^/?#\s]+)", tok)
    if m:
        return m.group(1) + ("/…" if len(tok) > len(m.group(1)) else "")
    return tok if _is_target_name(tok) else "text"


def _mask(value: str, seps: str) -> str:
    m = re.match(r"([^=!~]*)(!=|~=|=)", value) if seps != "=" else re.match(r"([^=]*)(=)", value)
    return f"{m.group(1)}{m.group(2)}***" if m else "***"


def _is_target_name(tok: str) -> bool:
    """Commands, existing files, @library names and URLs (scheme + host only) are kept."""
    if tok in {"print", "check", "preview", "view", "p", "c", "v"} or tok.startswith("@"):
        return True
    if re.match(r"https?://", tok):
        return True  # stored as scheme://host/… by _target
    return _is_file(tok)


def _is_file(tok: str) -> bool:
    try:
        return len(tok) < 1024 and Path(tok).expanduser().is_file()
    except OSError:
        return False


def new_id(now: float) -> str:
    return datetime.fromtimestamp(now).strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex()


class Recorder:
    """Collects one job and appends it when the command ends (printed, cancelled, failed, saved, dry run)."""

    def __init__(self, argv: list[str]):
        self.start = time.time()
        self.argv, self.secrets = scan(argv)  # values typed on the command line, masked in stored messages
        self.res = None
        self.outcome = ""
        self.printer = ""
        self.saved_to = ""
        self.counters: dict | None = None  # the seq values of the job
        self.summary: dict | None = None  # --last: what the stored job was (there is no render to read)
        self.problems: list = []  # --last: the problems stored with that job (Nudge), or a failure's

    def outcome_for(self, outcome: str) -> str:
        """The word recorded for a job: failures as they are, else what the job did (saved, dry run…)."""
        return outcome if outcome in ("failed", "cancelled", "interrupted") else (self.outcome or outcome)

    def finish(self, outcome: str, exit_code: int, problems: list | None = None) -> dict | None:
        """Appends the job. Never raises: a broken history must not turn a finished print into a crash (the
        user would print again and get a duplicate label)."""
        try:
            return self._finish(outcome, exit_code, problems)
        except Exception as e:  # noqa: BLE001 - see the docstring
            import sys

            print(f"note: job not recorded in the history ({e.__class__.__name__}: {e})", file=sys.stderr)
            return None

    def _finish(self, outcome: str, exit_code: int, problems: list | None) -> dict | None:
        if not enabled():
            return None
        res = self.res
        rec = {
            "schema": SCHEMA,
            "id": new_id(self.start),
            "time": datetime.fromtimestamp(self.start).isoformat(timespec="seconds"),
            "command": "print",
            "argv": self.argv,
            "outcome": self.outcome_for(outcome),
            "exit": exit_code,
            "duration_s": round(time.time() - self.start, 2),
            "printer": self.printer,
            "saved_to": self.saved_to,
        }
        if res is not None:
            labels = getattr(res, "labels", None) or [res]
            joins = getattr(res, "joins", [])
            rec |= {
                "profile": res.profile.id,
                "labels": len(labels),
                "length_mm": round(res.length_mm, 1),
                "cuts": joins.count("cut"),
                "tears": joins.count("tear"),
                "parts": _parts(res),
                "counters": self.counters if self.counters is not None else res.stats().get("counters", {}),
                "bytes_sha256": hashlib.sha256(res.data).hexdigest(),
            }
            problems = problems if problems is not None else res.visible_nudges()
        elif self.summary:
            rec |= self.summary
        # messages can quote data (barcode contents, keys, --set values): stored with those values masked
        secrets = set(self.secrets)
        for r in getattr(res, "results", None) or ([res] if res is not None else []):
            secrets.update(getattr(getattr(r, "rendered", None), "data", None) or [])
        rec["problems"] = [_problem(p, secrets) for p in (problems or [])]
        try:
            keep = int(config.load().get("history_max", 5000))
        except (TypeError, ValueError):
            keep = 5000
        p = path()
        line = (json.dumps(rec, ensure_ascii=False, default=str) + "\n").encode("utf-8")
        with fileio.locked(p):  # append and trim of two jobs never interleave
            with p.open("ab") as f:
                f.write(line)
            _trim(p, keep)
        return rec


def _problem(p, secrets: set[str]) -> dict:
    d = p.as_dict()
    out = {k: d.get(k) for k in ("code", "severity", "line", "part", "file") if d.get(k) is not None}
    out["message"] = mask(d.get("message", ""), secrets)
    return out


LONG_DIGITS = re.compile(r"\d[\d .()/-]{5,}\d")  # phones, document numbers, Pix keys
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def mask(text: str, secrets: set[str]) -> str:
    """Hides data inside a message: every value given to the job (longest first), long digit runs, e-mails."""
    for s in sorted((s for s in secrets if len(s) >= 3), key=len, reverse=True):
        text = text.replace(s, "***")
    return EMAIL.sub("***", LONG_DIGITS.sub("***", text))


def _parts(res) -> list[dict]:
    seen, out = set(), []
    for m in getattr(res, "label_meta", []) or []:
        key = (m["part"], m["file"])
        if key not in seen:
            seen.add(key)
            out.append({"part": m["part"], "file": m["file"]})
    return out


def _trim(p: Path, keep: int) -> None:
    """Keeps the last `keep` jobs; rewrites atomically, only when 10% over. Called under the history lock."""
    if keep <= 0:
        return
    lines = p.read_bytes().splitlines()
    if len(lines) <= keep + max(10, keep // 10):
        return
    fileio.atomic_write(p, b"\n".join(lines[-keep:]) + b"\n")


def load() -> list[dict]:
    """Every readable job; damaged lines are skipped (counted in history.skipped)."""
    global skipped
    try:
        lines = path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out, skipped = [], 0
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            r = None
        if isinstance(r, dict) and "id" in r and "time" in r:
            out.append(r)
        elif line.strip():
            skipped += 1
    return out


skipped = 0


def select(rows: list[dict], *, since: str | None = None, outcome: str | None = None, printer: str | None = None):
    if since:
        rows = [r for r in rows if r.get("time", "") >= since]
    if outcome:
        rows = [r for r in rows if r.get("outcome", "").startswith(outcome)]
    if printer:
        rows = [r for r in rows if r.get("printer") == printer]
    return rows


def stats(rows: list[dict]) -> dict:
    from collections import Counter

    by_outcome = Counter(r.get("outcome", "?") for r in rows)
    printed = [r for r in rows if r.get("outcome") == "printed"]
    weeks = Counter()
    for r in printed:
        d = datetime.fromisoformat(r["time"])
        weeks[f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"] += r.get("length_mm", 0) / 10
    codes = Counter(p["code"] for r in rows for p in r.get("problems", []))
    durations = [r.get("duration_s", 0) for r in printed]
    return {
        "jobs": len(rows),
        "by_outcome": dict(by_outcome),
        "printed_labels": sum(r.get("labels", 0) for r in printed),
        "paper_cm": round(sum(r.get("length_mm", 0) for r in printed) / 10, 1),
        "paper_cm_by_week": {k: round(v, 1) for k, v in sorted(weeks.items())},
        "top_problems": codes.most_common(10),
        "avg_print_s": round(sum(durations) / len(durations), 2) if durations else 0,
    }
