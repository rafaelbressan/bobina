"""--problems pretty|plain|json|jsonl: the same problems for people, grep and logs (schema bobina.problem/1)."""

import json

import pytest

from bobina import cli


@pytest.fixture
def kit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOBINA_PROBLEMS", raising=False)
    (tmp_path / "a.bob.md").write_text("A\n")
    (tmp_path / "f.bob.md").write_text("F\n\n![](missing.png)\n")
    return tmp_path


JOB = ["print", "a.bob.md", "--then", "nope.bob.md", "--then", "f.bob.md", "-o", "x.bin"]


def test_jsonl_one_object_per_problem(kit, capsys):
    assert cli.main([*JOB, "--problems", "jsonl"]) == cli.USAGE
    rows = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [(r["code"], r["severity"], r["part"], r["file"]) for r in rows] == [
        ("E201", "error", 2, "nope.bob.md"),
        ("I101", "warning", 3, "f.bob.md"),
    ]
    assert all(r["schema"] == "bobina.problem/1" and r["outcome"] == "nothing printed" for r in rows)
    assert rows[1]["line"] == 3 and rows[1]["suggestion"]


def test_json_one_document(kit, capsys):
    cli.main([*JOB, "--problems", "json"])
    doc = json.loads(capsys.readouterr().err)
    assert doc["outcome"] == "nothing printed" and len(doc["problems"]) == 2


def test_plain_has_no_icons_or_header(kit, capsys):
    cli.main([*JOB, "--problems", "plain"])
    lines = capsys.readouterr().err.splitlines()
    assert lines[0].startswith("error E201 part 2 (nope.bob.md): file not found")
    assert lines[1].startswith("warning I101 part 3 (f.bob.md) line 3:") and " -- " in lines[1]


def test_usage_errors_and_the_environment(kit, capsys, monkeypatch):
    monkeypatch.setenv("BOBINA_PROBLEMS", "jsonl")
    with pytest.raises(SystemExit):
        cli.main(["print", "--nope"])
    row = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert row["code"] == "E101"
    assert cli.main(["check", "f.bob.md"]) == cli.OK
    row = json.loads(capsys.readouterr().err.strip())
    assert row["code"] == "I101" and row["outcome"] == ""  # check: nothing was meant to print


def test_pretty_is_the_default(kit, capsys):
    cli.main(JOB)
    err = capsys.readouterr().err
    assert err.startswith("1 error, 1 warning — nothing printed") and "✗ error   [E201]" in err


def test_check_json_lists_problems_like_problems_json(capsys):
    from bobina import cli

    assert cli.main(["check", "Olá {{ nome }}", "--json"]) == cli.OK
    import json

    doc = json.loads(capsys.readouterr().out)
    assert [p["code"] for p in doc["problems"]] == ["M130"]
    assert doc["problems"][0]["schema"] == "bobina.problem/1"
    assert "length_mm" in doc["stats"]
