#!/usr/bin/env python3
"""Checks of the table tasks in evals/agent-eval.yaml, graded from what the real bobina says and shows: `bobina check
--json` (problems, and the width each column got: L108) and `bobina view` (the strip as text, on the printer's
grid; a drawn rule is a line of braille dots). The document is read only for what never prints (a value typed in a
cell versus a column's prefix). Standard library only: it runs with the sandbox's python3 and its `bobina`.

    table_checks.py CHECK FILE      exit 0 when the check passes; otherwise it says why
    (the setup moves this file out of the agent's folder, next to state/: $BOBINA_STATE_DIR/../table_checks.py)
"""

from __future__ import annotations

import functools
import json
import re
import subprocess
import sys
from pathlib import Path

BRAILLE = re.compile(r"^[⠀-⣿]+$")


@functools.cache
def bobina(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bobina", *args], capture_output=True, text=True)


def problems(path: str) -> list[dict]:
    r = bobina("check", path, "--json")
    try:
        return json.loads(r.stdout)["problems"]
    except (ValueError, KeyError):
        sys.exit(f"bobina check {path} --json gave no JSON (exit {r.returncode}): {r.stderr.strip()[-300:]}")


def view(path: str) -> list[str]:
    """The lines inside the first view box, each as wide as the box (the paper)."""
    out, inside = [], False
    for ln in bobina("view", path).stdout.splitlines():
        if ln.startswith("┌"):
            inside = True
        elif ln.startswith("└"):
            break
        elif inside and ln.startswith("│") and "⟶" not in ln:  # the tear line ends the strip
            out.append(ln[1 : ln.rindex("│")])
    if not out:
        sys.exit(f"bobina view {path} showed nothing")
    return out


def is_rule(line: str) -> bool:
    return bool(BRAILLE.match(line.strip()))


def widths(path: str, ncol: int) -> list[tuple[str, int]] | None:
    """(title, width) of each column of the first table with `ncol` columns, from bobina check's L108 note."""
    for p in problems(path):
        if p["code"] == "L108":
            said = p["message"].split(": ", 1)[1].rsplit(" (", 1)[0].split(" · ")
            if len(said) == ncol:
                return [(t.rsplit(" ", 1)[0], int(t.rsplit(" ", 1)[1])) for t in said]
    return None


def body_rows(path: str) -> list[str]:
    """The body rows of every table in the document as written (no title row, no separator row)."""
    lines, rows = Path(path).read_text(encoding="utf-8").splitlines(), []
    for i, ln in enumerate(lines):
        if re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$", ln) and i > 0 and "|" in lines[i - 1]:
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(lines[j])
                j += 1
    return rows


def find(lines: list[str], *words: str) -> int:
    """The index of the first line with every word in it, else -1."""
    return next((i for i, ln in enumerate(lines) if all(w in ln for w in words)), -1)


def fail(why: str) -> None:
    sys.exit(why)


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
    for name, value in (("Subtotal", "157,50"), ("Gorjeta sugerida", "18,90"), ("Total", "176,40")):
        i = find(view(path), name, value)
        line = view(path)[i] if i >= 0 else ""
        if not (line.startswith(name) and line.endswith(value)):
            fail(f"{name} on the left and {value} against the right margin: got {line!r}")


def rules_around_titles(path, *titles):
    lines = view(path)
    i = find(lines, *titles)
    if i < 0:
        fail(f"no title line with {titles}")
    if not (i > 0 and is_rule(lines[i - 1]) and i + 1 < len(lines) and is_rule(lines[i + 1])):
        fail(f"no dashed line both above and below the titles: {lines[max(0, i - 1) : i + 2]}")


def bar_titles_ruled(path):
    rules_around_titles(path, "QTDE", "DESCRIÇÃO", "VALOR")


def bar_items(path):
    lines = view(path)
    for item, value in (("Bagel ovos", "39,00"), ("Chá gelado", "18,00"), ("Brownie", "22,00")):
        if find(lines, item, value) < 0:
            fail(f"no line with {item} and {value}")


MARKET = (("001", "14,25"), ("003", "16,33"), ("008", "11,98"))


def market_one_line_per_item(path):
    lines = view(path)
    for it, total in MARKET:
        i = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith(it)), -1)
        if i < 0 or total not in lines[i]:
            fail(f"item {it} and its total {total} are not on one line: {lines[i] if i >= 0 else 'no such line'!r}")


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
    lines = view(path)
    d = find(lines, "Desconto no item 3 - 3,27")
    if d < 0:
        fail("no line with the whole 'Desconto no item 3 - 3,27' (squeezed into one column?)")
    item = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("003")), -1)
    nxt = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("008")), len(lines))
    if not item < d < nxt:
        fail("the discount line is not right after item 003")
    starts = lines[item].index("BANANA") if "BANANA" in lines[item] else -1
    if lines[d].index("Desconto") != starts:
        fail(f"the discount starts at column {lines[d].index('Desconto')}, the description at {starts}")


PRICES = (("Arroz", "24,90", "21,90"), ("Feij", "8,49", "7,99"), ("Caf", "18,90", "16,50"))


def prices_prefixed(path, rows=PRICES):
    lines = view(path)
    for name, *values in rows:
        i = find(lines, name)
        if i < 0 or not all(f"R$ {v}" in lines[i] for v in values):
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
    total_at = lines[find(lines, "BANANA PRATA", "16,33")].index("16,33")
    d = find(lines, "Desconto")
    if d < 0 or len(lines[d].rstrip()) <= total_at:
        fail(f"the discount line stays in its column (it ends before column {total_at}): {lines[d : d + 2]}")


CHECKS = {f.__name__.replace("_", "-"): f for f in (
    clean, totals_without_title, totals_name_left_value_right, bar_titles_ruled, bar_items,
    market_one_line_per_item, market_smaller_letters, market_code_narrow, market_discount_under_description,
    prices_prefixed, prices_not_before_names, prices_not_typed, fix_prices, fix_receipt_look, fix_discount_wider,
)}  # fmt: skip


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in CHECKS:
        sys.exit(f"usage: table_checks.py CHECK FILE; checks: {', '.join(CHECKS)}")
    CHECKS[sys.argv[1]](sys.argv[2])
