"""bobina help CODE, docs/problems/CODE.md and help --json: every problem code says what to do."""

import importlib.util
import json
from pathlib import Path

from bobina import cli
from bobina.nudges import CATALOG
from bobina.problem_help import FIX, explain

ROOT = Path(__file__).resolve().parents[1]


def test_every_code_says_what_to_do():
    assert not set(CATALOG) - set(FIX), sorted(set(CATALOG) - set(FIX))
    assert not set(FIX) - set(CATALOG), sorted(set(FIX) - set(CATALOG))
    assert all(len(FIX[c]) > 15 for c in CATALOG)


def test_help_code_in_the_terminal_and_as_json(capsys):
    assert cli.main(["help", "e302"]) == cli.OK
    out = capsys.readouterr().out
    assert "E302" in out and "what to do" in out and "nothing prints" in out
    assert cli.main(["help", "M130", "--json"]) == cli.OK
    assert json.loads(capsys.readouterr().out) == explain("M130")


def test_help_json_describes_commands_options_and_problems(capsys):
    assert cli.main(["help", "--json"]) == cli.OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "bobina.help/1"
    flags = {f for o in doc["commands"]["print"]["options"] for f in o["flags"]}
    assert {"--yes", "--data", "--marks", "--last"} <= flags
    assert [p["code"] for p in doc["problems"]] == list(CATALOG)


def test_the_problem_pages_are_current():
    spec = importlib.util.spec_from_file_location("gen", ROOT / "tools" / "gen_problem_docs.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    for code in CATALOG:
        page = ROOT / "docs" / "problems" / f"{code}.md"
        assert page.read_text(encoding="utf-8") == gen.page(code), f"run: python tools/gen_problem_docs.py ({code})"


def test_the_problem_index_is_current_and_no_page_is_stale():
    spec = importlib.util.spec_from_file_location("gen", ROOT / "tools" / "gen_problem_docs.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    folder = ROOT / "docs" / "problems"
    assert (folder / "README.md").read_text(encoding="utf-8") == gen.index()
    assert {p.stem for p in folder.glob("*.md")} - {"README"} == set(CATALOG)


def test_every_topic_answers_json_with_its_shape(capsys):
    expect = {"format": "text", "data": "text", "aliases": "text", "nudges": "problems", "problems": "problems",
              "print": "options", "commands": "commands", "e107": "fix"}  # fmt: skip
    for topic, key in expect.items():
        assert cli.main(["help", topic, "--json"]) == cli.OK
        doc = json.loads(capsys.readouterr().out)
        assert key in doc, topic
        assert doc.get("schema") == "bobina.help/1" or "code" in doc, topic
