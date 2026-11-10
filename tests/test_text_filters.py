"""Text case filters: the same output whatever case or accents the source used. Data stays data."""

import pytest

from bobina.engine import build
from bobina.rows import TextRow
from bobina.templating import Tainted


def text(expr, value, locale="pt-BR"):
    r = build(f"---\nlocale: {locale}\n---\n{{{{ x | {expr} }}}}", fields={"x": Tainted(value)})
    return " ".join("".join(c.ch for c in row.cells).strip() for row in r.rows if isinstance(row, TextRow))


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("upper", "ARROZ DA FAZENDA SÃO JOÃO"),
        ("lower", "arroz da fazenda são joão"),
        ("capitalize", "Arroz da fazenda são joão"),
        ("titlecase", "Arroz da Fazenda São João"),
        ("deaccent", "arroz DA fazenda Sao Joao"),
        ("camel", "arrozDaFazendaSaoJoao"),
        ("pascal", "ArrozDaFazendaSaoJoao"),
        ("snake", "arroz_da_fazenda_sao_joao"),
        ("kebab", "arroz-da-fazenda-sao-joao"),
        ("slug", "arroz-da-fazenda-sao-joao"),
    ],
)
def test_case_filters(expr, expected):
    assert text(expr, "arroz DA fazenda São João") == expected


def test_titlecase_follows_the_document_language():
    assert text("titlecase", "bread OF the day", "en") == "Bread of the Day"
    assert text("titlecase", "pan DE la casa", "es") == "Pan de la Casa"


def test_smallcaps_keeps_capitals():
    assert text("smallcaps", "Arroz") == "Aʀʀᴏᴢ"


def test_filter_output_from_data_is_still_literal():
    assert text("upper", "**x** {{ 7*7 }}") == "**X** {{ 7*7 }}"
