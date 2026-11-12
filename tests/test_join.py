"""--data [NAME=]FILE --join [NAME=]FILE --on KEY: one label per main row, columns of the other sources added."""

import json

import openpyxl
import pytest

from bobina import cli, datasource
from bobina.cli import args as cargs
from bobina.cli import common
from bobina.rows import TextRow


@pytest.fixture
def ab(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["nome", "preco", "valor", "categoria"])
    for r in (["Arroz", 12.5, "1kg", "graos"], ["Cafe", 18.9, "250g", "bebida"], ["Sal", 3, "1kg", "tempero"]):
        ws.append(r)
    wb.save(tmp_path / "A.xlsx")
    (tmp_path / "B.json").write_text(
        json.dumps(
            [
                {"nome": "arroz", "categoria": "mercearia", "id": 101},
                {"nome": "Cafe", "categoria": "matinal", "id": 202},
                {"nome": "Cafe", "categoria": "outra", "id": 999},
            ]
        )
    )
    (tmp_path / "estoque.csv").write_text("id,qtd\n101,40\n202,7\n")
    (tmp_path / "e.bob.md").write_text(
        "{{ nome }} {{ preco }} | {{ a.categoria }} {{ b.categoria }} {{ id }} | {{ categoria }}\n"
    )
    return tmp_path


def run(*argv):
    a = cargs.parse_args(cargs.make_parser(), ["print", *argv])
    res, *_ = common.load_job(a)
    texts = [
        " ".join("".join(c.ch for c in row.cells).strip() for row in r.rows if isinstance(row, TextRow))
        for r in res.labels
    ]
    return texts, {n.code: n.message for n in res.visible_nudges()}


def test_the_a_b_example(ab):
    texts, nudges = run("e.bob.md", "--data", "a=A.xlsx", "--join", "b=B.json", "--on", "nome")
    assert texts == [
        "Arroz 12.5 | graos mercearia 101 | graos",  # key matched regardless of case
        "Cafe 18.9 | bebida matinal 202 | bebida",  # B repeats Cafe: the first row is used
        "Sal 3 | tempero   | tempero",  # no match: the B fields print empty
    ]
    assert "'Sal'" in nudges["M150"] and "Cafe" in nudges["M151"] and "'categoria'" in nudges["M152"]


def test_default_names_from_files_and_two_joins_with_where_and_copies(ab):
    (ab / "f.bob.md").write_text("{{ nome }} {{ B.id }} qtd {{ qtd }}\n")
    texts, _ = run(
        "f.bob.md", "--data", "A.xlsx", "--join", "B.json", "--on", "nome", "--join", "estoque.csv", "--on", "B.id=id",
        "--where", "qtd!=", "--copies-from", "qtd",
    )  # fmt: skip
    assert texts.count("Arroz 101 qtd 40") == 40 and texts.count("Cafe 202 qtd 7") == 7 and len(texts) == 47


def test_keys_with_different_names(ab):
    (ab / "C.csv").write_text("produto,cor\nSal,branco\n")
    (ab / "g.bob.md").write_text("{{ nome }} {{ cor }}\n")
    texts, _ = run("g.bob.md", "--data", "A.xlsx", "--join", "C.csv", "--on", "nome=produto", "--where", "nome=sal")
    assert texts == ["Sal branco"]


def test_join_values_are_literal(ab):
    (ab / "x.json").write_text(json.dumps([{"nome": "Sal", "nota": "**x** {{ 7*7 }}"}]))
    (ab / "h.bob.md").write_text("{{ nota }}\n")
    texts, _ = run("h.bob.md", "--data", "A.xlsx", "--join", "x.json", "--on", "nome", "--where", "nome=Sal")
    assert texts == ["**x** {{ 7*7 }}"]


@pytest.mark.parametrize(
    "argv, code",
    [
        (["--data", "A.xlsx", "--join", "B.json"], "E101"),  # --join without --on
        (["--join", "B.json", "--on", "nome"], "E101"),  # --join without --data
        (["--data", "A.xlsx", "--join", "B.json", "--on", "codigo"], "E303"),
        (["--data", "a=A.xlsx", "--join", "a=B.json", "--on", "nome"], "E304"),  # two sources named a
    ],
)
def test_join_errors(ab, argv, code):
    a = cargs.parse_args(cargs.make_parser(), ["print", "e.bob.md", *argv])
    with pytest.raises(common.Fail) as e:
        common.load_job(a)
    assert e.value.problem == code


def test_named_and_key_spec():
    assert datasource.named("b=x.json") == ("b", "x.json")
    assert datasource.named("2026 precos.xlsx") == ("d_2026_precos", "2026 precos.xlsx")
    assert datasource.key_spec("a.nome=b.produto", "a", "b") == ("nome", "produto")
    assert datasource.key_spec("b.id=id", "a", "c") == ("b.id", "id")
    assert cli  # imported for the exit codes in other tests


def test_empty_keys_never_match(ab):
    (ab / "m.csv").write_text("nome,qtd\nArroz,1\n,2\n")
    (ab / "o.csv").write_text("nome,cat\n,SECRETO\nArroz,grao\n")
    (ab / "k.bob.md").write_text("{{ nome }} {{ cat }}\n")
    texts, nudges = run("k.bob.md", "--data", "m.csv", "--join", "o.csv", "--on", "nome")
    assert texts == ["Arroz grao", ""] and "SECRETO" not in " ".join(texts)
    assert "(empty)" in nudges["M150"]


def test_json_columns_are_the_union_of_all_objects(ab):
    (ab / "cat.json").write_text(json.dumps([{"nome": "Sal"}, {"nome": "Arroz", "id": "101", "prateleira": "A"}]))
    (ab / "u.bob.md").write_text("{{ nome }} {{ id }}\n")
    texts, _ = run("u.bob.md", "--data", "A.xlsx", "--join", "cat.json", "--on", "nome", "--where", "prateleira=A")
    assert texts == ["Arroz 101"]


def test_a_source_named_like_a_column(ab):
    (ab / "produto.csv").write_text("produto,preco\nArroz,10\n")
    (ab / "preco2.csv").write_text("produto,cor\nArroz,branco\n")
    (ab / "p.bob.md").write_text("{{ produto }} {{ preco }} {{ cor }} {{ produto_src.preco }}\n")
    texts, nudges = run("p.bob.md", "--data", "produto.csv", "--join", "preco2.csv", "--on", "produto")
    assert texts == ["Arroz 10 branco 10"] and "produto_src" in nudges["M155"]
    a = cargs.parse_args(cargs.make_parser(), ["print", "p.bob.md", "--data", "produto=produto.csv"])
    with pytest.raises(common.Fail) as e:
        common.load_job(a)
    assert e.value.problem == "E304"


def test_dotted_column_without_join_stays_a_column(ab):
    (ab / "d.csv").write_text("price,price.usd\n10,2\n")
    (ab / "q.bob.md").write_text("{{ price }}\n")
    texts, _ = run("q.bob.md", "--data", "d.csv")
    assert texts == ["10"]


def test_lost_columns_are_reported(ab):
    (ab / "x.csv").write_text("nome,preco,nome\nMel, silvestre,10,x\n")
    (ab / "x.bob.md").write_text("{{ nome }}\n")
    _, nudges = run("x.bob.md", "--data", "x.csv")
    assert "M153" in nudges and "M154" in nudges


def _codes(*argv):
    a = cargs.parse_args(cargs.make_parser(), ["print", *argv])
    res, *_ = common.load_job(a)
    return [n.code for n in res.visible_nudges()]


def test_m152_only_when_the_bare_name_is_used(ab):
    (ab / "p.bob.md").write_text("{{ nome }} {{ a.categoria }} {{ b.categoria }}\n")
    assert "M152" not in _codes("p.bob.md", "--data", "a=A.xlsx", "--join", "b=B.json", "--on", "nome")
    assert "M152" in _codes("e.bob.md", "--data", "a=A.xlsx", "--join", "b=B.json", "--on", "nome")  # {{ categoria }}
    assert "M152" in _codes(  # --where with the bare name: ambiguous too
        "p.bob.md", "--data", "a=A.xlsx", "--join", "b=B.json", "--on", "nome", "--where", "categoria=graos"
    )


def test_where_on_an_ambiguous_column_suggests_the_prefix(ab):
    a = cargs.parse_args(
        cargs.make_parser(),
        [
            "print",
            "e.bob.md",
            "--data",
            "a=A.xlsx",
            "--join",
            "b=B.json",
            "--on",
            "nome",
            "--where",
            "categoria=matinal",
        ],
    )
    with pytest.raises(common.Fail) as e:
        common.load_job(a)
    assert e.value.problem == "E302" and "--where b.categoria=matinal" in str(e.value)


def test_m152_kept_when_the_alias_of_the_header_is_used(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "A.csv").write_text("nome,Categoria\nArroz,graos\n")
    (tmp_path / "B.csv").write_text("nome,Categoria\nArroz,mercearia\n")
    (tmp_path / "C.csv").write_text("nome,outra\nArroz,x\n")
    (tmp_path / "d.bob.md").write_text("{{ nome }} {{ categoria }}\n")
    assert "M152" in _codes("d.bob.md", "--data", "a=A.csv", "--join", "b=B.csv", "--on", "nome")
    a = cargs.parse_args(cargs.make_parser(), ["print", "d.bob.md", "--data", "a=A.csv", "--join", "c=C.csv",
                         "--on", "nome", "--join", "b=B.csv", "--on", "nome", "--where", "categoria=mercearia"])  # fmt: skip
    with pytest.raises(common.Fail) as e:
        common.load_job(a)
    assert "--where b.Categoria=mercearia" in str(e.value)  # the source that has it, not the first one


def test_on_before_its_join_is_a_usage_error(ab, capsys):
    with pytest.raises(SystemExit) as e:
        cargs.parse_args(cargs.make_parser(), ["print", "e.bob.md", "--data", "a=A.xlsx", "--on", "nome",
                                               "--join", "b=B.json"])  # fmt: skip
    assert e.value.code == 1 and "needs a --join before it" in capsys.readouterr().err


@pytest.mark.parametrize(
    "tail,words",
    [
        (["--join", "b=B.json", "--on", "nome", "--on", "id", "--join", "estoque.csv"], "already has --on nome"),
        (["--join", "b=B.json", "--join", "estoque.csv", "--on", "nome"], "has no --on"),
    ],
)
def test_each_join_takes_its_own_on_right_after_it(ab, capsys, tail, words):
    with pytest.raises(SystemExit):
        cargs.parse_args(cargs.make_parser(), ["print", "e.bob.md", "--data", "a=A.xlsx", *tail])
    assert words in capsys.readouterr().err


def test_a_header_with_a_space_is_reachable_under_its_source_name(tmp_path, capsys):
    """'Unit Price' in --data a=… and 'Item Code' in --join b=… are {{ a.unit_price }} and {{ b.item_code }}, as the
    bare {{ unit_price }} and {{ item_code }} are (they printed empty, with an M130 naming the wrong variable)."""
    (tmp_path / "p.csv").write_text("name,Unit Price\nRice,5\n")
    (tmp_path / "c.json").write_text('[{"name": "rice", "Item Code": "7"}]')
    out = tmp_path / "o.bin"
    doc = "{{ a.unit_price }}|{{ unit_price }}|{{ b.item_code }}|{{ item_code }}|{{ row['Unit Price'] }}"
    argv = ["--data", f"a={tmp_path / 'p.csv'}", "--join", f"b={tmp_path / 'c.json'}", "--on", "name"]
    assert cli.main(["print", doc, *argv, "-o", str(out)]) == cli.OK
    assert b"5|5|7|7|5" in out.read_bytes()
    e = capsys.readouterr().err
    assert "M130" not in e and "under a source's name too: a.unit_price" in e


def test_m130_names_the_source_of_a_missing_column(tmp_path, capsys):
    (tmp_path / "p.csv").write_text("name,Unit Price\nRice,5\n")
    assert cli.main(["check", "{{ a.nope }}", "--data", f"a={tmp_path / 'p.csv'}"]) == cli.OK
    assert "variable 'a.nope' is not defined" in capsys.readouterr().err


def test_m130_points_a_bare_name_to_the_source_that_has_it():
    from bobina.nudges import Nudges
    from bobina.templating import render

    n = Nudges()
    render("{{ unit_price }}", {}, n, fields={"a": {"unit_price": "5", "name": "Rice"}})
    (m130,) = [x for x in n if x.code == "M130"]
    assert m130.message == "variable 'unit_price' is not defined"
    assert m130.suggestion.startswith("write {{ a.unit_price }}")
