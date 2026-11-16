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


def test_a_check_runs_as_the_eval_runs_it(box):
    script = ROOT / "evals" / "checks" / "table_checks.py"
    r = subprocess.run([sys.executable, str(script), "clean", "etiqueta.bob.md"], capture_output=True, text=True)
    assert r.returncode == 1 and "M101" in r.stderr
