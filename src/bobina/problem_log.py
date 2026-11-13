"""--log FILE (or log_file in config.toml): the problems of each run appended to a JSONL file, for logging and audit
systems. One object per problem (schema bobina.log/1). Messages are masked as the history masks them (values typed
on the command line, data printed in the job, long digit runs and e-mails). Each recorded job writes its problems
as soon as it is recorded (a long bobina chat logs every answer, not only at the end); what is left is written when
the command ends. Writing the log never fails the command: a note says why it could not be written. Without a
target nothing is collected."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

SCHEMA = "bobina.log/1"
FIELDS = ("code", "severity", "message", "line", "source", "part", "file")

_state: dict = {"target": None, "command": "", "said": False}
_seen: dict[tuple, dict] = {}  # problems reported since the last write, in order (deduplicated)
_secrets: set[str] = set()


def start(argv: list[str], command: str, target: str | None) -> None:
    """A new run. target: the log file (None: nothing is collected, nothing costs anything)."""
    _seen.clear()
    _secrets.clear()
    _state.update(target=target or None, command=command, said=False)
    if target:
        from . import history

        _secrets.update(history.scan(argv)[1])


def active() -> bool:
    return bool(_state["target"])


def add(items, res=None) -> None:
    """Problems as they are reported (screen, warnings, errors). res: the job, whose printed data is masked."""
    if not active():
        return
    if res is not None:
        from . import history

        _secrets.update(history.data_secrets(res))
    for n in items or []:
        d = n.as_dict() if hasattr(n, "as_dict") else dict(n)
        key = (d.get("code"), d.get("line"), d.get("message"), d.get("source"))
        if key not in _seen:
            _seen[key] = {k: d.get(k) for k in FIELDS if d.get(k) not in (None, "")}


def entries(exit_code: int | None, job: str | None) -> list[dict]:
    from . import history

    when = datetime.now().isoformat(timespec="seconds")
    out = []
    for p in _seen.values():
        row = {"schema": SCHEMA, "time": when, "job": job, "command": _state["command"], "exit": exit_code}
        row |= {k: v for k, v in p.items() if k != "message"}
        row["message"] = history.mask(p.get("message", ""), _secrets)
        out.append(row)
    return out


def job_done(job: str, exit_code: int | None) -> None:
    """A job was recorded in the history: its problems are written now, with its id."""
    write(exit_code, job)


def write(exit_code: int | None, job: str | None) -> None:
    """Appends the problems collected so far and forgets them. A failure is said once, as a note."""
    if not active() or not _seen:
        return
    rows = entries(exit_code, job)
    _seen.clear()
    why = _append(_state["target"], rows)
    if why and not _state["said"]:
        _state["said"] = True
        print(f"note: the problems of this run were not logged to {_state['target']} ({why})", file=sys.stderr)


def _append(target: str, rows: list[dict]) -> str:
    """'' when written; else why not. One write in append mode: two runs logging at once never mix their lines,
    and no lock file is left beside the log."""
    import os

    data = "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows).encode("utf-8")
    try:
        p = Path(target).expanduser()
        fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view) :]
        finally:
            os.close(fd)
    except (OSError, RuntimeError) as e:  # RuntimeError: ~user that names no user
        return getattr(e, "strerror", None) or str(e)
    return ""
