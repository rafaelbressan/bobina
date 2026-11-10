"""Paper odometer: how much of the roll is left.

The MTP-II reports only "paper out" (no near-end sensor answers), but bobina knows the exact length
of every print. Tell it the roll length (or its diameter) when you load a roll; every confirmed print
adds its length. Prints made by other apps or the self-test are not counted: correct with `paper used`."""

from __future__ import annotations

import math
import re
import time

from . import fileio, paths

UNIT = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|m)?\s*$")


def parse_length(s: str, default_unit: str = "m") -> float:
    """'15m', '1500cm', '40mm', '15' (meters) -> millimetres."""
    m = UNIT.match(str(s))
    if not m:
        raise ValueError(f"length '{s}': use 15m, 1500cm or 40mm")
    v = float(m.group(1).replace(",", "."))
    return v * {"mm": 1, "cm": 10, "m": 1000}[m.group(2) or default_unit]


def from_diameter(outer_mm: float, core_mm: float = 12.0, thickness_mm: float = 0.06) -> float:
    """Roll length from its outer diameter: area of the paper ring / thickness."""
    return math.pi * (outer_mm**2 - core_mm**2) / (4 * thickness_mm)


def _path():
    return paths.state_dir() / "paper.json"


def _load() -> dict:
    return fileio.read_json(_path(), {})  # damaged: an error, never "no roll" (that would drop every printer's roll)


def get(printer: str) -> dict | None:
    return _load().get(printer)


def new_roll(printer: str, roll_mm: float, note: str = ""):
    def put(d):
        d[printer] = {
            "roll_mm": round(roll_mm, 1),
            "used_mm": 0.0,
            "prints": 0,
            "loaded": time.strftime("%Y-%m-%d %H:%M"),
            "note": note,
        }

    fileio.locked_update(_path(), put)


def add(printer: str, mm: float, set_to: bool = False, count: bool = True):
    """Count paper. set_to replaces the total; count=False adds without counting a bobina print."""

    def count_it(d):
        r = d.get(printer)
        if not r:
            return
        r["used_mm"] = round((mm if set_to else r.get("used_mm", 0.0) + mm), 1)
        if not set_to and count:
            r["prints"] = r.get("prints", 0) + 1
            r["printed_mm"] = round(r.get("printed_mm", 0.0) + mm, 1)

    if _path().exists():
        fileio.locked_update(_path(), count_it)


def remaining(printer: str) -> float | None:
    r = get(printer)
    return None if not r else r["roll_mm"] - r.get("used_mm", 0.0)


def check(printer: str, job_mm: float, nudges) -> str:
    """Summary line for the confirmation screen; adds P101/P102 nudges. The odometer only advises: a damaged
    paper.json is shown here and does not stop the print (it is never overwritten either)."""
    try:
        r = get(printer)
    except fileio.StateError as e:
        return f" paper: not counted ({e})"
    if not r:
        return " paper: roll length unknown (bobina paper new 15m, or --diameter 40mm)"
    left = r["roll_mm"] - r.get("used_mm", 0.0)
    after = left - job_mm
    pct = max(0.0, after / r["roll_mm"] * 100)
    if job_mm > left:
        nudges.add(
            "P102",
            f"this print needs {job_mm / 10:.0f} cm but only ~{max(left, 0) / 10:.0f} cm are left on the roll",
            None,
            "load a new roll first (bobina paper new LENGTH)",
        )
    elif after < max(1000.0, r["roll_mm"] * 0.1):
        nudges.add(
            "P101",
            f"roll almost over: ~{after / 1000:.1f} m left after this print ({pct:.0f}%)",
            None,
            "have a new roll at hand",
        )
    return f" paper: ~{max(after, 0) / 1000:.1f} m left after this print ({pct:.0f}% of {r['roll_mm'] / 1000:.1f} m)"
