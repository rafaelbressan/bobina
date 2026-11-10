"""Product decisions of 07/11: required fields per data row, options that need --data,
--set over a data column, --data twice, usable names for any column header."""

import pytest

from bobina import cli
from bobina.cli import args as cargs
from bobina.cli import common
from bobina.rows import TextRow


@pytest.fixture
def kit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "br.csv").write_text("Product Name;Preço;Data de Validade\nArroz;10;2027-01\nFeijão;8;2027-02\n")
    (tmp_path / "gaps.csv").write_text("product_name;Preço\n;5\nSal;2\n")
    (tmp_path / "t.bob.md").write_text(
        '---\nfields:\n  product_name: {required: true}\n---\n{{ product_name }} {{ row["Preço"] }} {{ preco }}\n'
    )
    return tmp_path


def run(*argv):
    a = cargs.parse_args(cargs.make_parser(), ["print", *argv])
    res, *_ = common.load_job(a)
    texts = [
        " ".join("".join(c.ch for c in row.cells).strip() for row in r.rows if isinstance(row, TextRow))
        for r in res.labels
    ]
    return texts, [(n.code, n.message) for n in res.visible_nudges()]


def test_headers_get_usable_names_and_row_keeps_the_exact_ones(kit):
    texts, nudges = run("t.bob.md", "--data", "br.csv")
    assert texts == ["Arroz 10 10", "Feijão 8 8"]
    assert any(c == "M158" and "Product Name → product_name" in m for c, m in nudges)


def test_required_field_is_checked_per_data_row(kit):
    _, nudges = run("t.bob.md", "--data", "gaps.csv")
    assert ("M131", "data row 1: required field 'product_name' is empty") in nudges
    assert cli.main(["check", "t.bob.md", "--data", "gaps.csv", "--strict"]) == cli.STRICT


def test_set_wins_over_a_data_column_with_a_warning(kit):
    texts, nudges = run("t.bob.md", "--data", "br.csv", "--set", "product_name=Promo")
    assert texts[0].startswith("Promo") and any(c == "M157" for c, _ in nudges)


@pytest.mark.parametrize(
    "argv, msg",
    [
        (["--where", "a=b"], "--where needs --data"),
        (["--sheet", "X"], "--sheet needs --data"),
        (["--data", "br.csv", "--data", "gaps.csv"], "--data was given twice"),
        (["--copies", "0"], "1 or more"),
    ],
)
def test_option_rules(kit, argv, msg):
    a = cargs.parse_args(cargs.make_parser(), ["print", "t.bob.md", *argv])
    with pytest.raises(common.Fail, match=msg):
        common.load_job(a)


def test_options_without_effect_are_notes(kit):
    _, nudges = run("t.bob.md", "--data", "br.csv", "--sheet", "X", "--repeat", "2")
    assert [c for c, _ in nudges].count("M156") == 2


def test_undefined_attribute_or_index_is_a_warning_not_a_crash(kit):
    (kit / "u.bob.md").write_text('{{ c.id }} {{ x["y"] }}\n')
    _, nudges = run("u.bob.md")
    assert {m for c, m in nudges if c == "M130"} >= {"variable 'c' is not defined", "variable 'x' is not defined"}
