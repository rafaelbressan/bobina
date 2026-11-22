#!/usr/bin/env python3
"""Checks of the table and chart tasks in evals/agent-eval.yaml, graded from what the real bobina says and shows:
`bobina check --json` (problems, the width each column got: L108, what a chart drew: C101) and `bobina view` (the strip as text; a drawn rule is a
line of braille dots; a table in a raster font is a map of the paper when it fits the paper's printer-font columns,
else on its own grid in a wider frame, every cell whole; only a raster paragraph wider than the frame is cut with
"…", so text is matched whole or cut). The document is read only for what never prints (a value typed in a cell
versus a column's prefix). Standard library only: it runs with the sandbox's python3 and its `bobina`.

    table_checks.py CHECK FILE      exit 0 when the check passes; otherwise it says why
    (the setup moves this file out of the agent's folder, next to state/: $BOBINA_STATE_DIR/../table_checks.py)
"""

from __future__ import annotations

import ast
import contextlib
import functools
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BRAILLE = re.compile(r"^[⠀-⣿]+$")
SHIM_REAL = re.compile(r"^REAL, TRACE = (.+)$", re.M)  # cli-agent-eval's shim: REAL, TRACE = '/…/bobina', '/…'
FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
SEPARATOR = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


class CheckFailed(Exception):
    """One check did not pass; its message says why. Only that check fails, never the grader."""


def fail(why: str):
    raise CheckFailed(why)


@functools.cache
def executable() -> str:
    """The real bobina, not cli-agent-eval's shim in front of it: the shim logs every call into the agent's trace,
    and a check is not the agent's call. The shim names the real program in its REAL line (sandbox.py SHIM)."""
    found = shutil.which("bobina")
    if not found:
        fail("no bobina on PATH")
    m = SHIM_REAL.search(Path(found).read_bytes()[:8192].decode("utf-8", "replace"))
    return ast.literal_eval(m.group(1))[0] if m else found


@functools.cache
def bobina(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([executable(), *args], capture_output=True, text=True)


def problems(path: str) -> list[dict]:
    r = bobina("check", path, "--json")
    try:
        return json.loads(r.stdout)["problems"]
    except (ValueError, KeyError):
        fail(f"bobina check {path} --json gave no JSON (exit {r.returncode}): {r.stderr.strip()[-300:]}")


def view(path: str) -> list[str]:
    """The lines inside the first view box, each as wide as the frame: the paper's printer-font columns, or more
    for a table in a smaller font (its own grid, every cell whole; the paper's text keeps the paper's columns)."""
    out, inside = [], False
    for ln in bobina("view", path).stdout.splitlines():
        if ln.startswith("┌"):
            inside = True
        elif ln.startswith("└"):
            break
        elif inside and ln.startswith("│") and "⟶" not in ln:  # the tear line ends the strip
            out.append(ln[1 : ln.rindex("│")])
    if not out:
        fail(f"bobina view {path} showed nothing")
    return out


def is_rule(line: str) -> bool:
    return bool(BRAILLE.match(line.strip()))


def receipt_rule(path: str) -> set[str]:
    """How bobina view shows the dashed rule of style=receipt (its braille letters) for this document's printer
    (its front matter: profile, locale…), asked of bobina itself: a solid rule, a divider (--- {.dashed}) or another
    style's line shows other letters. The reference goes in a temporary folder, or next to the document when the
    system's cannot be written."""
    head = FRONT_MATTER.match(Path(path).read_text(encoding="utf-8"))
    return _receipt_rule(head.group(0) if head else "", str(Path(path).resolve().parent))


@functools.cache
def _receipt_rule(front: str, folder: str) -> frozenset[str]:
    for where in (None, folder):
        with contextlib.suppress(OSError), tempfile.TemporaryDirectory(dir=where) as tmp:
            doc = Path(tmp) / "reference.bob.md"
            doc.write_text(front + "| A |\n|---|\n| b |\n{style=receipt}\n", encoding="utf-8")
            lines = view(str(doc))
            i = find(lines, "A")
            if i < 1 or not is_rule(lines[i - 1]):
                fail(f"bobina view shows no receipt rule to compare with: {lines}")
            return frozenset(lines[i - 1].strip())
    fail("no folder for the reference receipt table (neither the system's temporary one nor the document's)")


def is_receipt_rule(line: str, path: str) -> bool:
    return is_rule(line) and set(line.strip()) <= receipt_rule(path)


def widths(path: str, ncol: int) -> list[tuple[str, int]] | None:
    """(title, width) of each column of the first table with `ncol` columns, from bobina check's L108 note."""
    for p in problems(path):
        if p["code"] == "L108":
            said = p["message"].split(": ", 1)[1].rsplit(" (", 1)[0].split(" · ")
            if len(said) == ncol:
                return [(t.rsplit(" ", 1)[0], int(t.rsplit(" ", 1)[1])) for t in said]
    return None


def body_rows(path: str) -> list[str]:
    """The body rows of every table in the document as written (no title row, no separator row). A separator is
    only the line right after a table's title row: a body row of dashes (| - | - |) stays a body row."""
    lines, rows, i = Path(path).read_text(encoding="utf-8").splitlines(), [], 0
    while i < len(lines):
        if "|" in lines[i] and i + 1 < len(lines) and SEPARATOR.match(lines[i + 1]):
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
        else:
            i += 1
    return rows


def shown(text: str) -> str:
    """A regex for `text` as the view shows it: whole, or cut with "…" after at least its first letter (a raster
    paragraph wider than the frame; a table's cells are never cut)."""
    cut = (re.escape(text[:k]) + "…" for k in range(len(text) - 1, 0, -1))
    return "(?:" + "|".join([re.escape(text), *cut]) + ")"


def find(lines: list[str], *words: str) -> int:
    """The index of the first line with every word in it (whole or cut with "…"), else -1."""
    pats = [re.compile(shown(w)) for w in words]
    return next((i for i, ln in enumerate(lines) if all(p.search(ln) for p in pats)), -1)


# --- the checks -------------------------------------------------------------------------------------------------


def clean(path):
    bad = [f"{p['code']} {p['message']}" for p in problems(path) if p["severity"] in ("warning", "error")]
    if bad:
        fail("bobina check: " + "; ".join(bad))


def totals_without_title(path):
    lines = [ln for ln in view(path) if ln.strip()]
    if len(lines) != 3 or any(is_rule(ln) for ln in lines):
        fail(f"expected only the three totals lines, saw: {lines}")


def totals_name_left_value_right(path):
    lines = view(path)
    for name, value in (("Subtotal", "157,50"), ("Gorjeta sugerida", "18,90"), ("Total", "176,40")):
        i = find(lines, name, value)
        line = lines[i] if i >= 0 else ""
        if not (re.match(shown(name), line) and re.search(shown(value) + "$", line)):
            fail(f"{name} on the left and {value} against the right margin: got {line!r}")


def rules_around_titles(path, *titles):
    lines = view(path)
    i = find(lines, *titles)
    if i < 0:
        fail(f"no title line with {titles}")
    above = i > 0 and is_receipt_rule(lines[i - 1], path)
    if not (above and i + 1 < len(lines) and is_receipt_rule(lines[i + 1], path)):
        fail(f"no receipt's dashed line both above and below the titles: {lines[max(0, i - 1) : i + 2]}")


def bar_titles_ruled(path):
    rules_around_titles(path, "QTDE", "DESCRIÇÃO", "VALOR")


def bar_items(path):
    lines = view(path)
    for item, value in (("Bagel ovos", "39,00"), ("Chá gelado", "18,00"), ("Brownie", "22,00")):
        if find(lines, item, value) < 0:
            fail(f"no line with {item} and {value}")


MARKET = (  # item, code, description, quantity, unit, unit price, total
    ("001", "1431", "CEBOLA KG", "1.105", "kg", "12,90", "14,25"),
    ("003", "7369", "BANANA PRATA ORG", "1.635", "kg", "9,99", "16,33"),
    ("008", "7896016500213", "LENTILHA GRANFINO", "1", "un", "11,98", "11,98"),
)


def market_one_line_per_item(path):
    """Each item's figures fit their columns (the widths bobina check says), so they print on the item's first
    line: item, quantity, unit, unit price and total; the code and the description may wrap."""
    w = widths(path, 7)
    if not w:
        fail("bobina check gave no widths for a 7-column table (turned, or not 7 columns?)")
    for col in (0, 3, 4, 5, 6):
        need = max(len(item[col]) for item in MARKET)
        if w[col][1] < need:
            fail(f"column {w[col][0]!r} is {w[col][1]} wide: its values ({need}) wrap onto a second line")


def market_smaller_letters(path):
    w = widths(path, 7)
    said = [p["message"] for p in problems(path) if p["code"] == "L108"]
    if not w or not any(re.search(r" in .+ \d+px columns:", m) for m in said if len(m.split(" · ")) == 7):
        fail(f"the 7-column table is not drawn in a smaller font (bobina check: {said})")


def market_code_narrow(path):
    w = widths(path, 7)
    if not w:
        fail("bobina check gave no widths for a 7-column table")
    (_, code), (_, desc) = w[1], w[2]
    if not (code <= 8 and desc >= 10 and desc > code):
        fail(f"code column {code} (want ≤ 8), description {desc} (want ≥ 10 and wider): {w}")


def market_discount_under_description(path):
    """The discount comes right after item 003, starts where the description does and runs on past the
    description's column: the whole 'Desconto no item 3 - 3,27' on one line (a table's cells are never cut)."""
    lines = view(path)
    item = find(lines, "BANANA")
    if item < 0:
        fail("no item 003 (no line with BANANA)")
    d = next((i for i, ln in enumerate(lines) if "Desconto" in ln), -1)
    if d < 0 or "Desconto no item 3 - 3,27" not in lines[d]:
        fail(f"'Desconto no item 3 - 3,27' is not on one line (squeezed into one column?): {lines[d : d + 2]}")
    nxt = find(lines, "LENTILHA")
    if not item < d < (nxt if nxt >= 0 else len(lines)):
        fail("the discount line is not right after item 003")
    at, desc = lines[d].index("Desconto"), lines[item].index("BANANA")
    if at != desc:
        fail(f"the discount starts at column {at}, the description at {desc}")


PRICES = (("Arroz", "24,90", "21,90"), ("Feij", "8,49", "7,99"), ("Caf", "18,90", "16,50"))


def prices_prefixed(path, rows=PRICES):
    lines = view(path)
    for name, *values in rows:
        i = find(lines, name)
        if i < 0 or not all(re.search(shown(f"R$ {v}"), lines[i]) for v in values):
            fail(f"{name}: expected {', '.join('R$ ' + v for v in values)} on its line: {lines[i] if i >= 0 else ''!r}")


def prices_not_before_names(path):
    lines = view(path)
    title = find(lines, "Produto")
    if title >= 0 and "R$" in lines[title]:
        fail(f"R$ in the title row: {lines[title]!r}")
    if any(re.search(r"R\$\s*(Arroz|Feij|Caf|Produto)", ln) for ln in lines):
        fail("R$ printed before a product name")


def prices_not_typed(path):
    typed = [r for r in body_rows(path) if "R$" in r]
    if typed:
        fail(f"R$ typed in the cells, not set for the columns: {typed}")


def fix_prices(path):
    prices_prefixed(path, (("Arroz", "24,90", "21,90"), ("Feij", "8,49", "7,99")))
    prices_not_before_names(path)


def fix_receipt_look(path):
    rules_around_titles(path, "Produto", "Preço", "Promo")


def fix_discount_wider(path):
    """The discount's text runs on past its own column, into the TOTAL column (a line of its own counts too)."""
    lines = view(path)
    for words in (("BANANA PRATA", "16,33"), ("CASTANHA CAJU", "34,97")):
        if find(lines, *words) < 0:
            fail(f"{words[0]} is gone")
    total_at = re.search(shown("16,33"), lines[find(lines, "BANANA PRATA", "16,33")]).start()
    d = find(lines, "Desconto")
    if d < 0 or len(lines[d].rstrip()) <= total_at:
        fail(f"the discount line stays in its column (it ends before column {total_at}): {lines[d : d + 2]}")


def drawn(path: str, kind: str) -> str:
    """What bobina check says it drew (C101) for the first chart of that kind; fails when there is none."""
    said = [p["message"] for p in problems(path) if p["code"] == "C101" and p["message"].startswith(f"chart={kind}:")]
    if not said:
        fail(f"no chart={kind} drawn (bobina check says no C101 for one)")
    return said[0]


def supply_line(path):
    said = drawn(path, "line")
    if not all(w in said for w in ("8 points", "by date", "values read: 0, 800, 3500, 52000, 120000, 300000")):
        fail(f"a line of the 8 supply values spaced by date expected: {said}")


def supply_three_values_along_the_axis(path):
    said = drawn(path, "line")
    ticks = re.search(r"y ticks (.*?) \((turned along the axis|upright)\)", said)
    if not ticks or len(ticks.group(1).split(", ")) != 3 or ticks.group(2) != "turned along the axis":
        fail(f"three Y values written along the axis expected: {said}")


def supply_about_3cm(path):
    m = re.search(r"; (\d+)x(\d+) dots", drawn(path, "line"))
    if not m or not 216 <= int(m.group(2)) <= 264:  # 3 cm is 240 dots at 203 dpi
        fail(f"a chart about 3 cm tall expected: {m.group(0) if m else 'no size'}")


def bakery_bars(path):
    said = drawn(path, "bar")
    if not all(w in said for w in ("7 points", "2 series", "values read: 1240.5, 980, 1105.25, 1320, 1890.75, 2430")):
        fail(f"bars of the 7 days' sales read as reais, and a second series (the goal), expected: {said}")


def file_bars(path):
    said = drawn(path, "bar")
    if not all(w in said for w in ("1 series (valor)", "5 points", "values read: 530.5, 590, 500.75, 750, 660")):
        fail(f"bars of valor per data from vendas.csv (5 days, summed) expected: {said}")
    if [r for r in body_rows(path) if re.search(r"320|410|380|450|520", r)]:
        fail("the values were typed into the document: they should come from vendas.csv")


def file_half_centred_grid(path):
    said = drawn(path, "bar")
    if not re.search(r"; 1[89]\dx\d+ dots, centred", said) or "a grid" not in said:
        fail(f"half the paper wide, centred, with dotted lines at the values expected: {said}")


CHECKS = {f.__name__.replace("_", "-"): f for f in (
    clean, totals_without_title, totals_name_left_value_right, bar_titles_ruled, bar_items,
    market_one_line_per_item, market_smaller_letters, market_code_narrow, market_discount_under_description,
    prices_prefixed, prices_not_before_names, prices_not_typed, fix_prices, fix_receipt_look, fix_discount_wider,
    supply_line, supply_three_values_along_the_axis, supply_about_3cm, bakery_bars, file_bars, file_half_centred_grid,
)}  # fmt: skip


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in CHECKS:
        sys.exit(f"usage: table_checks.py CHECK FILE; checks: {', '.join(CHECKS)}")
    try:
        CHECKS[sys.argv[1]](sys.argv[2])
    except CheckFailed as e:
        sys.exit(str(e))
