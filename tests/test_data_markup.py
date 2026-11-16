"""Data rendered as Markdown (`{{ value | markdown }}` on a --data/--set value) brings text markup only (SECURITY.md,
FORMAT §7.4). Two layers: the value is parsed alone and written again with only paragraphs, emphasis, inline code,
links as text, headings, lists, quotes, tables, rules and {…} (parser.data_markdown), so that nothing in it can
open, close or continue a block around it; then, on the whole document, any block whose marker came from data is
refused again (parse, one pass). Data stays data through every operation of the template."""

import time

import pytest
from PIL import Image

from bobina.engine import build
from bobina.model import Div, Fence, Heading, ListBlock, Paragraph, Quote, Table
from bobina.rows import BitmapRow, RawRow
from bobina.templating import Tainted

T = Tainted
RAW = "x\n```raw\n1b 40\n```\n"  # each probe would send ESC @ (reset) if it became a raw block
BOX = "x\n::: {.box title=HACK}\ny"


def codes(res) -> set[str]:
    return {n.code for n in res.nudges}


def raws(res) -> list[bytes]:
    return [r.data for r in res.rows if isinstance(r, RawRow)]


def images(res) -> list:
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "image"]


def walk(blocks):
    for b in blocks:
        yield b
        if isinstance(getattr(b, "children", None), list):
            yield from walk(b.children)
        for it in getattr(b, "items", []):
            yield from walk(it.children)


def divs(res) -> list[Div]:
    return [b for b in walk(res.doc.blocks) if isinstance(b, Div)]


def fences(res) -> list[Fence]:
    return [b for b in walk(res.doc.blocks) if isinstance(b, Fence)]


def md(template: str, **values):
    return build(template, fields={k: T(v) for k, v in values.items()})


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "secret.png"
    Image.new("L", (40, 20), 0).save(p)
    return str(p)


# --- 1. data stays data through every operation ------------------------------------------------------------------


EXPRS = [
    "d", "(d ~ '')", "('' ~ d)", "('%s' % d)", "('%.400s' % d)", "('{}'.format(d))", "('%s' | format(d))",
    "(d * 1)", "d[0:]", "d | upper | lower", "d.replace('Q', 'Q')", "d | trim", "[d] | join", "d | list | join",
    "{'k': d}.k", "d | replace('Q', 'Q')", "d | map('lower') | join",
]  # fmt: skip


@pytest.mark.parametrize("expr", EXPRS)
def test_whatever_the_template_does_with_data_it_brings_no_raw_image_or_box(expr, photo):
    for value, code in ((RAW, "M121"), (f"![x]({photo})", "M122"), (BOX, "M123")):
        res = md("{{ " + expr + " | markdown }}\nafter\n", d=value)
        assert not raws(res) and not images(res) and not divs(res) and code in codes(res), (expr, value)


@pytest.mark.parametrize("crlf", ["\r\n", "\r"])
def test_line_breaks_of_any_kind(crlf):
    for expr in ("d", "('%s' % d)", "('{}'.format(d))"):
        res = md("{{ " + expr + " | markdown }}\n", d=RAW.replace("\n", crlf))
        assert not raws(res) and "M121" in codes(res)


def test_a_loop_over_the_letters_of_data_gives_data():
    res = md("{% for c in d %}{{ c | markdown }}{% endfor %}\nend\n", d=RAW)
    assert not raws(res) and not fences(res)
    res = md("{% for x in [d, 'ok'] %}{{ x | markdown }}{% endfor %}\nend\n", d=RAW)  # a list holding data
    assert not raws(res) and "M121" in codes(res)
    res = md(
        "{% macro m() %}{{ caller() | markdown }}{% endmacro %}{% call m() %}{{ d | markdown }}{% endcall %}", d=RAW
    )
    assert not raws(res)


def test_a_set_block_holding_data_is_data_even_with_its_marks_cut():
    src = "{% set x %}{{ d | markdown }}{% endset %}{{ x | replace(x[0], '') | markdown }}\n"
    res = md(src, d=RAW)
    assert not raws(res) and "M121" in codes(res)


def test_a_macro_called_with_data_gives_data(photo):
    src = "{% macro m(v) %}{{ v | markdown }}{% endmacro %}{{ m(d) | markdown }}\n"
    res = md(src, d=f"![x]({photo})")
    assert not images(res) and "M122" in codes(res)


# --- 2. only text markup, and nothing that reaches past the value -------------------------------------------------


@pytest.mark.parametrize(
    "value, code",
    [
        ("x\n```raw\n1b 40\n", "M121"),  # never closed
        ("x\n```raw\n1b 40\n`````\n", "M121"),  # closed by a longer fence
        ("x\n> ```raw\n> 1b 40\n> ```\n", "M121"),  # in a quote
        ("x\n- ```raw\n  1b 40\n  ```\n", "M121"),  # in a list item
        ("x\n~~~raw\n1b 40\n~~~\n", "M121"),
        ("```qr\nhttps://evil.example\n```", "M123"),  # a code of any kind: data does not make objects
        ('```pay {scheme=pix to="x@y.z" name=A city=B}\n```', "M123"),
        ("```barcode\n123\n```", "M123"),
        ("```contact whatsapp\n+55 11 90000-0000\n```", "M123"),
        ("```\nplain code\n```", "M123"),
        ("para\n\n    indented code\n", "M123"),
        ("x\n::: {.box}\ny\n:::", "M123"),
        ("[logo]: /etc/passwd\n", "M123"),  # a link definition the document's ![logo][logo] would use
    ],
)
def test_blocks_data_may_not_make_are_removed_and_said(value, code):
    res = md("{{ d | markdown }}\n", d=value)
    assert not raws(res) and not fences(res) and not divs(res) and code in codes(res)


def test_text_markup_from_data_works():
    value = "# Title\n\n**bold** and *it* ~~old~~ `code` [link](https://x.example)\n\n- a\n- b\n\n> q\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n---"  # noqa: E501
    res = md("{{ d | markdown }}\n", d=value)
    kinds = {type(b) for b in walk(res.doc.blocks)}
    assert {Heading, Paragraph, ListBlock, Quote, Table} <= kinds
    assert not codes(res) - {"M120"}


def test_two_values_on_one_line_never_join_into_markup(photo):
    for a, b in (("```", "raw\n1b 40\n```"), (":", ":: {.box title=HACK}\ny"), ("!", f"[x]({photo})"),
                 ("``", "`raw\n1b 40\n```"), ("[logo]", ": /etc/passwd")):  # fmt: skip
        res = md("{{ a | markdown }}{{ b | markdown }}\nz\n\n![logo][logo]\n", a=a, b=b)
        assert not raws(res) and not divs(res) and not images(res) and not fences(res), (a, b)


def test_data_never_closes_or_continues_the_documents_code_block():
    res = md("~~~\n{{ d | markdown }}\n~~~\nend\n", d="x\n```\n~~~\n::: {.box title=HACK}\nq\n```")
    (fence,) = fences(res)  # the document's, with what data may bring: its own code block is removed
    assert fence.content == "x\n" and not divs(res) and "M123" in codes(res)
    assert isinstance(res.doc.blocks[-1], Paragraph)


@pytest.mark.parametrize("value", ["x\n```\n", "x\n~~~\n", "x\n````", "one\n:::\ntwo", "one\r:::\rtwo",
                                   "one\n> :::\ntwo", "one\n- :::\ntwo"])  # fmt: skip
def test_data_never_swallows_or_closes_the_documents_box(value):
    res = md("::: {.box}\n{{ d | markdown }}\n\nmine\n:::\nend\n", d=value)
    (box,) = divs(res)
    assert box.closed and isinstance(box.children[-1], Paragraph) and isinstance(res.doc.blocks[-1], Paragraph)
    assert "M105" not in codes(res)


def test_the_documents_raw_and_image_blocks_never_take_data(photo):
    res = md("```raw\n{{ d | markdown }}\n```\n", d="1b 40")
    assert not raws(res) and "M121" in codes(res)
    res = md("```image\n{{ d | markdown }}\n```\n", d=photo)
    assert not images(res) and "M122" in codes(res)


def test_data_never_chooses_a_code_blocks_kind():
    res = md("```{{ lang | markdown }}\n1b 40\n```\n", lang="raw")
    (fence,) = fences(res)
    assert fence.kind == "text" and fence.content == "1b 40\n" and not raws(res) and "M123" in codes(res)


def test_a_long_chain_of_tildes_prints_quickly_and_says_it():
    start = time.perf_counter()
    res = md("{{ d | markdown }}\n", d="~~~\n" * 1000)
    assert time.perf_counter() - start < 5 and "M123" in codes(res) and "M313" not in codes(res)


def test_a_big_document_with_data_costs_about_what_it_costs_without():
    body = "Line of the document with some *text* in it.\n\n" * 9000  # ~400 KB
    value = ("- item **bold**\n" * 200) + RAW

    def took(src):
        start = time.perf_counter()
        build(src, fields={"d": T(value)})
        return time.perf_counter() - start

    plain = took(body + "{{ d }}\n")
    marked = took(body + "{{ d | markdown }}\n")
    assert marked < plain * 1.5 + 0.2


# --- no false positives -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("data", ["for", "Shop", "secret", "100"])
def test_data_that_appears_in_the_authors_own_text_changes_nothing(data, photo, tmp_path):
    folder = tmp_path / "secret-shop-for-100"
    folder.mkdir()
    logo = folder / "logo.png"
    Image.new("L", (40, 20), 0).save(logo)
    mine = f"::: {{.box title=Shop}}\nfor 100 :fragile:\n:::\n\n![logo]({logo})\n"
    res = build("{{ v | markdown }}\n\n{{ d }}\n", fields={"v": mine, "d": T(data)})
    assert divs(res) and images(res) and not codes(res) - {"P301", "I109"}


def test_plain_values_are_unchanged_and_the_authors_markdown_keeps_everything():
    res = md("{{ d }}\n", d="::: {.box}\n```raw\n1b 40\n```")
    assert [type(b) for b in res.doc.blocks] == [Paragraph] and not raws(res) and not codes(res)
    res = build("{{ v | markdown }}\n", fields={"v": "::: {.box}\n```qr\nhi\n```\n:::"})  # the author's own
    assert divs(res) and fences(res) and "M123" not in codes(res)


# --- data never carries bobina's reserved characters -------------------------------------------------------------


def printed(res) -> str:
    from bobina import view

    return "\n".join(view.lines(res.rows, res.profile))


def test_a_value_with_a_placeholder_character_cannot_show_another_values_text():
    res = md("A={{ a }}\n\nB={{ b }}\n", a="SECRET", b="0")
    assert printed(res).count("SECRET") == 1 and "M124" in codes(res)
    res = build("A={{ a }}\n\nB={{ b[0] }}\n", fields={"a": "SECRET", "b": ["0"]})  # in a list too
    assert printed(res).count("SECRET") == 1 and "M124" in codes(res)


def test_a_value_with_the_marks_of_data_cannot_fake_or_cut_one():
    res = md("{{ d | markdown }}\n", d="x\n```raw\n1b 40\n```\ny")
    assert not raws(res) and "M124" in codes(res) and "M121" in codes(res)
    res = md("{{ d }}\n", d="abc")
    assert "abc" in printed(res) and "M124" in codes(res)


def test_ordinary_data_is_untouched():
    res = md("{{ d }}\n", d="Café 10:30 · R$ 4,50")
    assert "Café 10:30 · R$ 4,50" in printed(res) and "M124" not in codes(res)
