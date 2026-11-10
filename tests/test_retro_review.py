"""Code review of the P0/P1 commits, done afterwards (08/11): one test per confirmed finding."""

import pytest

from bobina import cli, history
from bobina.cli import args as cargs
from bobina.cli import common


def run(*argv):
    return cli.main(list(argv))


def test_long_one_line_text_prints_as_text(isolated):
    assert run("print", "--dry-run", "a" * 300) == cli.OK  # used to be E201 'File name too long'


@pytest.mark.parametrize("text", ["12/3.5", "R$10/2.5kg", "07/11/2026."])
def test_text_with_a_slash_and_a_dot_is_text(isolated, text):
    assert run("print", "--dry-run", text) == cli.OK


def test_a_mistyped_file_name_is_still_caught(isolated):
    assert run("print", "--dry-run", "lista.bob.md") == cli.USAGE  # E201 with did-you-mean


def test_history_never_keeps_then_text_or_url_secrets():
    argv = ["print", "a.md", "--then=Pix chave-aleatoria Joao", "https://h.example/i.png?token=SECRET", "--allow-net"]
    stored = history.redact(argv)
    assert "--then=text" in stored and "https://h.example/…" in stored
    assert not any("SECRET" in t or "Joao" in t for t in stored)
    secrets = history.scan(argv)[1]
    assert any("SECRET" in s for s in secrets) and "Pix chave-aleatoria Joao" in secrets


def test_a_dotted_header_without_a_join_gets_an_alias_and_keeps_its_name(isolated, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    (tmp_path / "p.csv").write_text("price.usd,Name\n10,x\n")
    (tmp_path / "p.bob.md").write_text("A{{ row['price.usd'] }} B{{ price_usd }}\n")
    assert run("print", "--dry-run", str(tmp_path / "p.bob.md"), "--data", str(tmp_path / "p.csv")) == cli.OK
    out = capsys.readouterr().out
    assert "A10 B10" in out


def test_an_alias_never_takes_the_name_of_a_source(isolated, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NO_COLOR", "1")
    (tmp_path / "items.csv").write_text("id,Stock\n1,5\n")
    (tmp_path / "stock.csv").write_text("id,qty\n1,40\n")
    (tmp_path / "s.bob.md").write_text("[{{ stock_src.qty }}]\n")
    assert run("print", "--dry-run", "s.bob.md", "--data", "items.csv", "--join", "stock.csv", "--on", "id") == 0
    captured = capsys.readouterr()
    assert "[40]" in captured.out and "M155" in captured.out + captured.err  # renamed, and it says why


def test_no_source_rename_without_named_sources(isolated, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "product.csv").write_text("product,x\nA,1\n")
    (tmp_path / "p.bob.md").write_text("{{ product }}\n")
    assert run("check", "p.bob.md", "--data", "product.csv") == cli.OK
    assert "M155" not in capsys.readouterr().err


def test_a_counters_value_that_is_not_a_mapping_is_a_document_error(isolated, tmp_path, capsys):
    doc = tmp_path / "c.bob.md"
    doc.write_text("---\ncounters: order\n---\n#{{ seq.order }}\n")
    assert run("check", str(doc), "--then", str(doc)) == cli.DOC
    assert "counters: must be a mapping" in capsys.readouterr().err


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-11-07 18:00", "2026-11-07T18:00"),
        ("  2026-11-07", "2026-11-07"),
        ("2026-11-07T18:00:05", "2026-11-07T18:00:05"),
    ],
)
def test_since_accepts_a_space_before_the_time(value, expected):
    from bobina.cli.history import _since

    assert _since(value) == expected


def test_help_works_with_join_options_around(capsys):
    with pytest.raises(SystemExit) as e:
        cargs.parse_args(cargs.make_parser(), ["print", "--on", "k", "--help"])
    assert e.value.code in (0, 1)
    assert common  # imported for the module under test
