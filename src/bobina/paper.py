"""Paper odometer: how much of the roll is left.

The MTP-II reports only "paper out" (no near-end sensor answers), but bobina knows the exact length
of every print. Tell it the roll length (or its diameter) when you load a roll; every confirmed print
adds its length. Prints made by other apps or the self-test are not counted: correct with `paper used`."""

from __future__ import annotations

import math
import re
import shlex
import time

from . import fileio, paths

MM = {"mm": 1, "cm": 10, "m": 1000, "metre": 1000, "metres": 1000, "meter": 1000, "meters": 1000,
      "ft": 304.8, "feet": 304.8, "foot": 304.8, "'": 304.8, "’": 304.8,
      "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4, "”": 25.4}  # fmt: skip
CANON = {"'": "ft", "’": "ft", "feet": "ft", "foot": "ft", '"': "in", "”": "in", "inch": "in", "inches": "in",
         "metre": "m", "metres": "m", "meter": "m", "meters": "m"}  # fmt: skip
NUMBER = r"\d+[\s-]+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?"  # 15, 1,5, 2 1/4, 2-1/4, 1/2
_UNIT = "|".join(re.escape(u) for u in sorted(MM, key=len, reverse=True))
UNIT = re.compile(rf"^\s*({NUMBER})\s*({_UNIT})?\s*$", re.I)
_PART = rf"({NUMBER})\s*({_UNIT})?"
CODE = re.compile(rf"^\s*{_PART}\s*[x×*]\s*{_PART}(?:\s*[x×*]\s*{_PART})?\s*$", re.I)  # 57x30, 2 1/4" x 50'
FIT_MM = 3  # 57 mm rolls are sold for 58 mm printers, 3 1/8" (79.4 mm) ones for 80 mm


def _number(s: str) -> float:
    s = s.replace("-", " ").strip()
    if "/" not in s:
        return float(s.replace(",", "."))
    whole, _, frac = s.rpartition(" ")
    num, den = frac.split("/")
    if int(den) == 0:
        raise ValueError(f"'{s}': a fraction over 0")
    return float(whole or 0) + int(num) / int(den)


def parse_length(s: str, default_unit: str | None = "m") -> float:
    """'15m', '1500cm', '40mm', '50ft', "50'", '2 1/4in', '15' (default_unit; None: a unit is required) -> mm.
    A package code (57x30) is refused with the question it raises: see code_advice."""
    m = UNIT.match(str(s))
    unit = (m.group(2) or default_unit or "").lower() if m else ""
    if not unit:
        advice = code_advice(str(s), cli=True)
        raise ValueError(advice or f"length '{s}': use 15m, 1500cm, 40mm or 50ft")
    return _number(m.group(1)) * MM[unit]


def parse_width(s: str) -> float:
    """The paper width of a roll: '57mm', '80', '2 1/4in', '3 1/8"' -> mm (a bare number is mm)."""
    mm = parse_length(s, "mm")
    if not 10 <= mm <= 300:
        raise ValueError(f"width '{s}': a roll is 10 to 300 mm wide (57mm, 80mm, 2 1/4in)")
    return mm


def fits(width_mm: float, paper_mm: float) -> bool:
    return abs(width_mm - paper_mm) <= FIT_MM


def code_advice(s: str, cli: bool = False) -> str | None:
    """What to do with a package code given as a length, or None. "57x30" is never guessed: in Brazil 30 is the
    length in metres, in European catalogues the roll's diameter in mm (57 x 40 x 12: diameter and core). With a
    unit on every number ("57mm x 30m", '2 1/4" x 50\''), the code is split as it says. cli: the commands to run;
    otherwise the arguments of the MCP tool paper_new."""
    m = CODE.match(str(s))
    if not m:
        return None
    nums = [n.strip() if n else "" for n in m.groups()[0::2]]
    units = [CANON.get(u.lower(), u.lower()) if u else "" for u in m.groups()[1::2]]
    w, d, core = nums
    inch = units[0] == "in" or "/" in w or _number(w) < 10

    def call(length="", diameter=""):
        core_ = f"{core}{units[2] or 'mm'}" if core and diameter else ""
        width = w + (units[0] or ("in" if inch else "mm"))
        if cli:
            what = length or f"--diameter {diameter}" + (f" --core {core_}" if core_ else "")
            return f"bobina paper new {shlex.quote(what) if length else what} --width {shlex.quote(width)}"
        given = [("length", length), ("diameter", diameter), ("core", core_), ("width", width)]
        return ", ".join(f'{k} "{v}"' for k, v in given if v)

    if all(u for n, u in zip(nums, units, strict=True) if n):  # every number has its unit: nothing to ask
        split = call(length=d + units[1]) if units[1] in ("cm", "m", "ft") else call(diameter=d + units[1])
        return f"'{s}' is a package code with its units: {'run' if cli else 'give its parts as'} {split}"
    if inch:  # the US: inches x feet (a diameter is not given that way)
        ask = "Is" if cli else "never guess it. Ask the user: is"
        return f"'{s}' is a package code: {ask} {d} the roll's length in feet? (then {call(length=d + 'ft')})"
    as_length, as_diameter = call(length=d + "m"), call(diameter=d + "mm")
    if cli:
        return f"'{s}' is a package code: is {d} the roll's length in metres ({as_length}) or its outer diameter" \
               f" in mm ({as_diameter})?"  # fmt: skip
    return f"'{s}' is a package code, not a length: never guess it. Ask the user one question: is {d} the roll's" \
           f" length in metres, as rolls are sold in Brazil (then {as_length}), or its outer diameter in mm, as in" \
           f" European catalogues (then {as_diameter})?"  # fmt: skip


def from_diameter(outer_mm: float, core_mm: float = 12.0, thickness_mm: float = 0.06) -> float:
    """Roll length from its outer diameter: area of the paper ring / thickness."""
    return math.pi * (outer_mm**2 - core_mm**2) / (4 * thickness_mm)


def _path():
    return paths.state_dir() / "paper.json"


def _load() -> dict:
    return fileio.read_json(_path(), {})  # damaged: an error, never "no roll" (that would drop every printer's roll)


def get(printer: str) -> dict | None:
    return _load().get(printer)


def new_roll(printer: str, roll_mm: float, note: str = "", width_mm: float | None = None):
    def put(d):
        d[printer] = {
            "roll_mm": round(roll_mm, 1),
            "used_mm": 0.0,
            "prints": 0,
            "loaded": time.strftime("%Y-%m-%d %H:%M"),
            "note": note,
            **({"width_mm": round(width_mm, 1)} if width_mm else {}),
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
