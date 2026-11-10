"""The built-in templates: each renders its own examples without a problem, and the values a person types
(prices with a comma, days that are not a number) never print a wrong value in silence."""

import pytest

from bobina.cli.library import template_meta, template_names
from bobina.engine import build, template_fields


def _doc(template, /, **values):
    lines = "".join(f'{k}: "{v}"\n' for k, v in values.items())
    return f"---\ntemplate: {template}\nlocale: pt-BR\n{lines}---\n"


def _text(res):
    return "".join(c.ch for r in res.rows for c in getattr(r, "cells", []))


def _warnings(res):
    return [n.code for n in res.visible_nudges() if n.severity in ("warning", "error")]


def _examples(name):
    fields = template_fields(template_meta(name))
    return {k: str(v["example"]) for k, v in fields.items() if "example" in v}


@pytest.mark.parametrize("name", template_names())
def test_a_template_renders_its_examples_cleanly(name):
    values, fields = _examples(name), template_fields(template_meta(name))
    if missing := [k for k, f in fields.items() if f.get("required") and k not in values]:
        pytest.skip(f"no one-line example for {missing} (a list or table): see spec/conformance")
    res = build(_doc(name, **values))
    assert not _warnings(res), _warnings(res)
    assert res.length_mm > 15


def test_the_food_label_use_by_date_is_today_plus_days():
    assert "08/11/2026" in _text(build(_doc("food-label", product="x", days="")))  # 05/11 + the default 3


def test_zero_days_is_today_not_the_default():
    res = build(_doc("food-label", product="x", days=0))
    assert _text(res).count("05/11/2026") == 2 and not _warnings(res)


def test_days_with_a_unit_count():
    assert "08/11/2026" in _text(build(_doc("food-label", product="x", days="3 dias")))


@pytest.mark.parametrize("days", ["uma semana", "9999999"])
def test_days_that_cannot_be_used_warn(days):
    assert "M202" in _warnings(build(_doc("food-label", product="x", days=days)))


@pytest.mark.parametrize("price", ["149,90", "149.90", "R$ 149,90"])
def test_a_price_with_comma_or_symbol_prints_right(price):
    res = build(_doc("clothing-tag", brand="b", piece="p", garment_size="M", price=price))
    assert "R$ 149,90" in _text(res).replace("\xa0", " ") and not _warnings(res)


def test_a_price_that_is_not_a_number_prints_as_typed_with_a_warning():
    res = build(_doc("shelf-price", product="p", price="consulte"))
    assert "consulte" in _text(res) and "R$ 0" not in _text(res)
    assert "M202" in _warnings(res)


def test_thousands_follow_the_locale():
    res = build(_doc("jewelry-tag", piece="p", code="c", price="1.890,00"))
    assert "R$ 1.890,00" in _text(res).replace("\xa0", " ")


@pytest.mark.parametrize(
    "typed, decimal, number",
    [
        ("24.90", ",", 24.9),
        ("149,90", ".", 149.9),
        ("R$ 1.890,00", ",", 1890.0),
        ("1,890.00", ",", 1890.0),
        ("1.890", ",", 1890),
        ("1.890", ".", 1.89),
        ("0.500", ",", 0.5),  # only zeros before: a decimal, never 500
        ("1 890", ",", 1890),
        ("3 dias", ".", 3),
        ("12345678901234567890", ".", 12345678901234567890),  # exact, not through a float
    ],
)
def test_parse_number_reads_what_people_type(typed, decimal, number):
    from bobina.templating import parse_number

    assert parse_number(typed, decimal) == number


@pytest.mark.parametrize("typed", ["3 5", "9,90 2 un", "1,5,3", "1.2345.678", "1234.567", "abc", True, "1" * 40])
def test_parse_number_refuses_what_it_would_have_to_guess(typed):
    from bobina.templating import parse_number

    assert parse_number(typed, ",") is None


def test_percent_reads_a_percent_sign():
    res = build('---\nlocale: en\nd: "10%"\n---\n{{ d | percent }} {{ 0.1 | percent }}\n')
    assert _text(res).split() == ["10%", "10%"]


def test_receipt_quantities_and_prices_as_people_type_them():
    doc = '---\ntemplate: receipt\nlocale: pt-BR\nshop: s\nitems:\n  - [Queijo, "0,5", "R$ 40,00"]\n---\n'
    res = build(doc)
    assert "R$ 20,00" in _text(res).replace("\xa0", " ") and "M202" not in _warnings(res)
