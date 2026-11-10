"""Variables, counters, dates and the data-is-literal safety rules (FORMAT.md §7)."""

import pytest

from bobina.engine import build
from bobina.model import Heading, Paragraph
from bobina.nudges import SecurityError
from bobina.templating import Tainted


def text_of(res):
    out = []
    for b in res.doc.blocks:
        if isinstance(b, (Paragraph, Heading)):
            out.append(res.rendered.resolve("".join(r.text for r in b.runs)))
    return out


def kinds(res):
    return [type(b).__name__ for b in res.doc.blocks]


# --- data is literal -------------------------------------------------------------


def test_markdown_in_data_is_literal():
    res = build("{{ d }}", fields={"d": Tainted("# PROMOÇÃO")})
    assert kinds(res) == ["Paragraph"]
    assert text_of(res) == ["# PROMOÇÃO"]


def test_bold_and_attributes_in_data_are_literal():
    res = build("{{ d }}", fields={"d": Tainted("**Leve 2** {.invert size=huge}")})
    p = res.doc.blocks[0]
    assert not any(r.bold for r in p.runs) and not p.attrs.classes
    assert text_of(res) == ["**Leve 2** {.invert size=huge}"]


def test_raw_block_in_data_is_text_not_bytes():
    evil = "```raw\n1f 1b 1f fc 01 02 03 33\n```"
    res = build("{{ d }}", fields={"d": Tainted(evil)})
    assert b"\x1f\x1b\x1f\xfc" not in res.data
    assert kinds(res) == ["Paragraph"]


def test_data_is_never_evaluated_as_template():
    res = build("{{ d }}", fields={"d": Tainted("{{ seq.ticket.take(500) }}")})
    assert text_of(res) == ["{{ seq.ticket.take(500) }}"]
    assert res.rendered.counters.reserved() == {}


def test_markdown_filter_opts_in_but_strips_raw():
    src = "{{ d | markdown }}"
    res = build(src, fields={"d": "**Leve 2**\n\n```raw\n1b 40\n```\n"})
    assert any(r.bold for r in res.doc.blocks[0].runs)
    assert not any(type(b).__name__ == "Fence" for b in res.doc.blocks)
    assert "M121" in {n.code for n in res.nudges}


def test_control_characters_never_reach_the_printer():
    res = build("{{ d }}", fields={"d": Tainted("a\x1b@b\x1dV\x00c")})
    assert b"a@bVc" in res.data
    assert b"\x1dV" not in res.data


# --- sandbox ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "src,code",
    [
        ('{% include "/etc/passwd" %}', "M310"),
        ("{% import 'x' as y %}", "M310"),
        ("{{ ''.__class__.__mro__[1].__subclasses__() }}", "M311"),
        ("{{ seq.__dict__ }}", "M311"),
        ("{% for i in range(100000) %}x{% endfor %}", "M313"),
        ("{% for a in range(60) %}{% for b in range(60) %}x{% endfor %}{% endfor %}", "M313"),
        ("{{ seq.t.take(5000) }}", "M313"),
    ],
)
def test_sandbox_blocks(src, code):
    with pytest.raises(SecurityError) as e:
        build(src)
    assert e.value.nudge.code == code


def test_image_path_from_data_is_refused(tmp_path):
    with pytest.raises(SecurityError) as e:
        build("![x]({{ p }})", fields={"p": Tainted("/home/user/.ssh/id_ed25519")})
    assert e.value.nudge.code == "M312"


def test_variables_inside_raw_blocks_are_refused():
    with pytest.raises(SecurityError) as e:
        build("```raw\n{{ x }}\n```", fields={"x": "1b 40"})
    assert e.value.nudge.code == "M314"


def test_pandoc_id_is_not_a_jinja_comment():
    res = build("# Title {#intro}\n\ntext")
    assert kinds(res) == ["Heading", "Paragraph"]


# --- counters --------------------------------------------------------------------

FM = '---\ncounters:\n  t: { start: 1, format: "A-{:03}" }\n  box: { start: 1, stop: 3, style: letters }\n---\n'


def test_counter_same_value_in_one_print():
    res = build(FM + "# {{ seq.t }}\n\n{{ seq.t }}")
    assert text_of(res) == ["A-001", "A-001"]


def test_counter_take_and_commit_persists():
    res = build(FM + "{% for n in seq.t.take(3) %}\n{{ n }}\n\n{% endfor %}")
    assert text_of(res) == ["A-001", "A-002", "A-003"]
    res.commit()
    res2 = build(FM + "{{ seq.t }}")
    assert text_of(res2) == ["A-004"]


def test_counter_not_consumed_without_commit():
    build(FM + "{{ seq.t }}")
    assert text_of(build(FM + "{{ seq.t }}")) == ["A-001"]


def test_counter_stop_nudges_and_letters():
    res = build(FM + "{% for n in seq.box.take(4) %}{{ n }} {% endfor %}")
    assert text_of(res) == ["A B C D"]
    assert "M140" in {n.code for n in res.nudges}


def test_local_range_is_not_persisted():
    res = build("{% for n in range(1, 4) %}{{ n }} {% endfor %}")
    assert text_of(res) == ["1 2 3"]


# --- dates, numbers, locale ------------------------------------------------------


@pytest.mark.parametrize(
    "loc,expected",
    [
        ("pt-BR", "quinta-feira, 5 de novembro de 2026"),
        ("en-US", "Thursday, November 5, 2026"),
        ("fr-FR", "jeudi 5 novembre 2026"),
    ],
)
def test_full_date_follows_locale(loc, expected):
    res = build(f"---\nlocale: {loc}\n---\n{{{{ now | date('full') }}}}")
    assert text_of(res) == [expected]


def test_patterns_strftime_and_add():
    src = "---\nlocale: pt-BR\n---\n{{ now | date('dd/MM HH:mm') }} {{ now | date('%d de %B') }} {{ now | add(days=7) | date('dd/MM') }}"
    assert text_of(build(src)) == ["05/11 09:49 05 de novembro 12/11"]


def test_moment_tokens_nudge():
    res = build("{{ now | date('DD/MM/YYYY') }}")
    assert "M201" in {n.code for n in res.nudges}


def test_currency_follows_locale():
    assert text_of(build("---\nlocale: pt-BR\n---\n{{ 1234.5 | currency('BRL') }}")) == ["R$\xa01.234,50"]


def test_undefined_variable_nudges():
    res = build("Hello {{ name }}!")
    assert text_of(res) == ["Hello !"]
    assert "M130" in {n.code for n in res.nudges}


def test_pix_payload_matches_bcb_example():
    from bobina.codes import pix_payload

    assert pix_payload("123e4567-e12b-12d1-a456-426655440000", "Fulano de Tal", "BRASILIA") == (
        "00020126580014br.gov.bcb.pix0136123e4567-e12b-12d1-a456-4266554400005204000053039865802BR"
        "5913Fulano de Tal6008BRASILIA62070503***63041D3D"
    )


def test_receipt_template_totals_and_pix():
    src = "---\ntemplate: receipt\nlocale: pt-BR\nshop: Zé\nitems:\n  - [Pão, 6, 0.80]\n  - [Café, 1, 18.90]\npay_to: a@b.c\n---\n"
    res = build(src)
    from bobina.rows import QRRow

    qr = [r for r in res.rows if isinstance(r, QRRow)][0]
    assert "br.gov.bcb.pix" in qr.data and "540523.70" in qr.data
    assert not [n for n in res.nudges if n.code == "M131"]


def test_required_template_field_nudges():
    assert "M131" in {n.code for n in build("---\ntemplate: receipt\n---\n").nudges}


def test_lang_is_an_alias_of_locale():
    from bobina.engine import build

    a = build("---\nlocale: pt-BR\n---\n{{ 4.5 | currency('BRL') }}").data
    b = build("---\nlang: pt-BR\n---\n{{ 4.5 | currency('BRL') }}").data
    assert a == b and b"4,50" in b
