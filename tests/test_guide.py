"""docs/guides/batch-printing.md: every file it names exists in examples/batch, and every command in its code
blocks runs there (print as --dry-run, previews into a temporary folder)."""

import re
import shlex
from pathlib import Path

import pytest

from bobina.cli import main

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (ROOT / "docs" / "guides" / "batch-printing.md").read_text(encoding="utf-8")
EX = ROOT / "examples" / "batch"
PLACEHOLDERS = {"other.bob.md", "file.xlsx"}  # names the guide uses for the reader's own files


def commands():
    out = []
    for block in re.findall(r"```sh\n(.*?)```", GUIDE, re.S):
        for line in block.replace("\\\n", " ").splitlines():  # join "\" line continuations
            if line.strip().startswith("bobina "):
                out.append(line.strip())
    return out


def test_every_file_the_guide_names_exists():
    named = set(re.findall(r"[\w-]+\.(?:bob\.md|xlsx|csv|tsv|txt|jsonl?|png|pdf)\b", GUIDE))
    named = {n for n in named if not n.endswith(".jsonl")}  # history files etc. are not examples
    missing = sorted(n for n in named - PLACEHOLDERS if not (EX / n).exists())
    assert not missing, f"the guide names files that examples/batch does not have: {missing}"


@pytest.mark.parametrize("line", commands())
def test_every_guide_command_runs(line, isolated, monkeypatch):
    monkeypatch.chdir(EX)
    argv = shlex.split(line, comments=True)[1:]  # a shell comment ends the command; a quoted "#1" does not
    for k, a in enumerate(argv):  # every output goes to a temporary folder, never into examples/
        if a in ("-o", "--output") and k + 1 < len(argv):
            argv[k + 1] = str(isolated / Path(argv[k + 1]).name)
        elif a.startswith(("-o=", "--output=")):
            flag, _, v = a.partition("=")
            argv[k] = f"{flag}={isolated / Path(v).name}"
    if argv[0] == "print":
        argv.append("--dry-run")
    assert main(argv) == 0, line


def test_the_guide_has_commands():
    assert len(commands()) >= 5
