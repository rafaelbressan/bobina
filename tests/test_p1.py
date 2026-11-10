"""P1 fixes of the 07/11 review: empty parts, mistyped file names, crashes on odd inputs, limits."""

import pytest

from bobina import cli, sources
from bobina.cli import args as cargs
from bobina.cli import common


@pytest.fixture
def kit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.bob.md").write_text("A\n")
    (tmp_path / "foto.png").write_bytes(b"")
    return tmp_path


def fail(*argv):
    a = cargs.parse_args(cargs.make_parser(), ["print", *argv])
    with pytest.raises(common.Fail) as e:
        common.load_job(a)
    return e.value


def test_every_part_needs_a_document(kit, monkeypatch):
    monkeypatch.setattr(common, "stdin_has_data", lambda: False)
    assert fail("--dry-run", "--then", "a.bob.md").problem == "E104"
    assert "after a --then" in str(fail("a.bob.md", "--then", "--dry-run", "--then", "a.bob.md"))


def test_a_mistyped_file_name_is_not_printed_as_text(kit):
    e = fail("fotoo.png")
    assert e.problem == "E201" and "did you mean foto.png" in str(e)
    for name in ("logo.pdf", "imgs/x.jpg", "dados.csv"):
        assert fail(name).problem == "E201"
    assert cli.main(["print", "hello world", "-o", str(kit / "o.bin")]) == cli.OK  # text is still text


def test_odd_inputs_are_coded_problems_not_tracebacks(kit):
    (kit / "d.csv").write_text("item,n\nx,inf\n")
    assert fail("a.bob.md", "--data", "d.csv", "--copies-from", "n").problem == "E304"
    (kit / "d.csv").write_text("item,n\nx,2.9\n")
    assert fail("a.bob.md", "--data", "d.csv", "--copies-from", "n").problem == "E304"
    (kit / "z.csv").write_text("item,n\nx,0\n")
    assert fail("a.bob.md", "--data", "z.csv", "--copies-from", "n").problem == "E304"
    with pytest.raises(sources.ImageError, match="not valid base64"):
        sources.load("data:image/png;base64,@@@", str(kit))
    (kit / "pasta").mkdir()
    with pytest.raises(sources.ImageError, match="folder"):
        sources.load("pasta", str(kit))


def test_the_label_limit_counts_copies(kit):
    assert fail("a.bob.md", "--repeat", "600", "--copies", "2").problem == "E305"
    assert "1200 labels" in str(fail("a.bob.md", "--repeat", "600", "--copies", "2"))


def test_strict_quiet_problems_are_consistent(kit, capsys):
    import json

    (kit / "f.bob.md").write_text("F\n\n![](missing.png)\n")
    (kit / "g.bob.md").write_text("G\n\n![](missing.png)\n")
    assert cli.main(["preview", "f.bob.md", "--strict", "-o", "p.png"]) == cli.STRICT
    assert not (kit / "p.png").exists()
    capsys.readouterr()
    assert cli.main(["check", "f.bob.md", "-q", "--strict"]) == cli.STRICT
    assert "I101" in capsys.readouterr().err  # -q never hides why it stopped
    assert cli.main(["print", "f.bob.md", "--dry-run", "--problems", "jsonl"]) == cli.OK
    assert json.loads(capsys.readouterr().err.strip().splitlines()[-1])["code"] == "I101"
    assert cli.main(["check", "f.bob.md", "--then", "g.bob.md", "--problems", "jsonl"]) == cli.OK
    rows = [json.loads(x) for x in capsys.readouterr().err.splitlines()]
    assert [r["file"] for r in rows if r["code"] == "I101"] == ["f.bob.md", "g.bob.md"]


def test_part_errors_keep_the_hint_apart(kit, capsys):
    import json

    assert cli.main(["print", "a.bob.md", "--then", "https://example.com/x.png", "-o", "x.bin",
                     "--problems", "jsonl"]) == cli.USAGE  # fmt: skip
    row = json.loads(capsys.readouterr().err.splitlines()[0])
    assert row["code"] == "E204" and row["suggestion"] and "\n" not in row["message"]


def test_edit_again_rebuilds_the_same_job(kit, monkeypatch):
    from bobina.cli import documents

    (kit / "l.bob.md").write_text("{{ nome }} {{ item }}\n")
    (kit / "d.csv").write_text("item\nx\ny\n")
    monkeypatch.setattr(documents.editor, "open_file", lambda *a, **k: None)
    monkeypatch.setattr(common, "ask_fields", lambda a, s, b: {"nome": "Rafa"})
    seen = {}

    def confirm(args, res, title, rebuild=None, *a, **k):
        seen["before"] = (res.joins, res.labels[0].fields.get("nome"))
        res2 = rebuild()
        seen["after"] = (res2.joins, res2.labels[0].fields.get("nome"))
        return False, res2

    monkeypatch.setattr(documents, "confirm_loop", confirm)
    assert cli.main(["print", "l.bob.md", "--data", "d.csv", "--compact", "--ask"]) == cli.CONFIRM
    assert seen["before"] == seen["after"] == (["cut"], "Rafa")
    assert not documents.editable("@pote") and not documents.editable("foto.png")
