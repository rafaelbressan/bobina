"""The table tasks of evals/agent-eval.yaml stay gradable as bobina changes: each one's solution passes every check
of evals/checks/table_checks.py with this checkout's bobina, and the broken file of table-fix fails them."""

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / "evals" / "agent-eval.yaml").read_text(encoding="utf-8"))
TASKS = [t for t in SPEC["tasks"] if t["id"].startswith("table-")]
CHECK = re.compile(r'table_checks\.py" (\S+) (\S+)$')


def load_checks():
    spec = importlib.util.spec_from_file_location("table_checks", ROOT / "evals" / "checks" / "table_checks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A work folder where `bobina` is this checkout's, as the eval's shim makes it the installed one."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "bobina").write_text(f'#!/bin/sh\nexec "{sys.executable}" -m bobina "$@"\n')
    (bin_ / "bobina").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "src"))
    monkeypatch.setenv("BOBINA_NONINTERACTIVE", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    work = tmp_path / "work"
    work.mkdir()
    (work / "etiqueta.bob.md").write_bytes((ROOT / "evals" / "fixtures" / "etiqueta.bob.md").read_bytes())
    monkeypatch.chdir(work)
    return work


def checks_of(task) -> list[tuple[str, str]]:
    found = [CHECK.search(c["shell"]) for c in task["checks"]]
    assert all(found), f"{task['id']}: every check is a table_checks.py CHECK FILE"
    return [m.groups() for m in found]


def failures(checks, pairs) -> list[str]:
    out = []
    for name, path in pairs:
        try:
            checks.CHECKS[name](path)
        except SystemExit as e:
            out.append(f"{name}: {e.code}")
    return out


@pytest.mark.parametrize("task", TASKS, ids=[t["id"] for t in TASKS])
def test_the_solution_passes_every_check(task, box):
    for cmd in task["solution"]:
        subprocess.run(["bash", "-c", cmd], check=True, capture_output=True)
    checks = load_checks()  # fresh: its cache of bobina's answers belongs to one sandbox
    assert {name for name, _ in checks_of(task)} <= set(checks.CHECKS)
    assert not failures(checks, checks_of(task))


def test_the_broken_file_fails_the_fix_checks(box):
    task = next(t for t in TASKS if t["id"] == "table-fix")
    said = failures(load_checks(), checks_of(task))
    assert len(said) == len(task["checks"]), said


def said(check: str, text: str) -> list[str]:
    """What one check says of a document written into the work folder (empty: it passes)."""
    Path("doc.bob.md").write_text(text, encoding="utf-8")
    return failures(load_checks(), [(check, "doc.bob.md")])


def test_r_dollar_typed_in_cells_is_caught_with_short_separators(box):
    doc = "| Produto | Preço | Promo |\n|---|--:|--:|\n| Arroz 5 kg | R$ 24,90 | R$ 21,90 |\n"
    assert said("prices-not-typed", doc)
    assert said("prices-not-typed", doc.replace("|---|--:|--:|", "|:-|-:|:-:|"))


def test_totals_in_a_smaller_font_pass(box):
    doc = "| | |\n|---|--:|\n| Subtotal | 157,50 |\n| Gorjeta sugerida | 18,90 |\n| Total | 176,40 |\n"
    doc += "{font=Terminus size=16px}\n"
    for check in ("clean", "totals-without-title", "totals-name-left-value-right"):
        assert not said(check, doc), check


def test_a_dashed_divider_over_a_plain_table_is_not_the_receipt_look(box):
    doc = "--- {.dashed}\n\n| QTDE | DESCRIÇÃO | VALOR |\n|--:|---|--:|\n| 1 | Bagel ovos | 39,00 |\n"
    assert said("bar-titles-ruled", doc)
    assert not said("bar-titles-ruled", doc.replace("--- {.dashed}\n\n", "") + "{style=receipt}\n")


def test_no_item_003_is_said_plainly(box):
    doc = "| IT | DESCRIÇÃO |\n|---|---|\n| 001 | CEBOLA |\n| | Desconto no item 3 - 3,27 {span=all} |\n"
    assert said("market-discount-under-description", doc) == [
        "market-discount-under-description: no item 003 (no line starting with 003)"
    ]


def test_the_checks_call_the_real_bobina_not_the_eval_shim(box, tmp_path, monkeypatch):
    """cli-agent-eval puts a shim named bobina first on PATH that logs each call as the agent's; the checks read
    the real program from the shim's REAL line and leave the trace alone."""
    real = tmp_path / "bin" / "bobina"  # the box's bobina, this checkout's
    shim, trace = tmp_path / "shim" / "bobina", tmp_path / "trace.jsonl"
    shim.parent.mkdir()
    shim.write_text(f"#!/bin/sh\necho called >> {trace}\nexit 1\nREAL, TRACE = {str(real)!r}, {str(trace)!r}\n")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim.parent}{os.pathsep}{os.environ['PATH']}")
    checks = load_checks()
    assert checks.executable() == str(real)
    assert failures(checks, [("clean", "etiqueta.bob.md")])[0].startswith("clean: bobina check: M101")
    assert not trace.exists()


def test_a_check_runs_as_the_eval_runs_it(box):
    script = ROOT / "evals" / "checks" / "table_checks.py"
    r = subprocess.run([sys.executable, str(script), "clean", "etiqueta.bob.md"], capture_output=True, text=True)
    assert r.returncode == 1 and "M101" in r.stderr
