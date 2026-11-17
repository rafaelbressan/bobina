"""Data rendered as Markdown (`{{ value | markdown }}` on a --data/--set value) never enters the document's source:
it is a placeholder there, like every value, and once the document is parsed the value, parsed alone, is spliced
in with text markup only (paragraphs, emphasis, inline code, links as text, headings, lists, quotes, tables,
rules). It never sets attributes, defines links, opens or closes a block, or meets the template's text. Data stays
data through every operation of the template, and never carries bobina's reserved characters (SECURITY.md,
FORMAT §7.4)."""

import time

import pytest
from PIL import Image

from bobina import view
from bobina.engine import build
from bobina.model import Div, Fence, Heading, ListBlock, Paragraph, Quote, Table
from bobina.nudges import SecurityError
from bobina.rows import BitmapRow, QRRow, RawRow
from bobina.templating import Tainted

T = Tainted
RAW = "x\n```raw\n1b 40\n```\n"  # each probe would send ESC @ (reset) if it became a raw block
BOX = "x\n::: {.box title=HACK}\ny"


def codes(res) -> set[str]:
    return {n.code for n in res.nudges}


def said(res, code: str) -> list:
    return [n for n in res.nudges if n.code == code]


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


def printed(res) -> str:
    return "\n".join(view.lines(res.rows, res.profile))


def md(template: str, **values):
    return build(template, fields={k: T(v) for k, v in values.items()})


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "secret.png"
    Image.new("L", (40, 20), 0).save(p)
    return str(p)


# --- data stays data through every operation of the template ------------------------------------------------------


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
        assert not raws(res) and len(said(res, "M121")) == 1


def test_loops_set_blocks_macros_and_caller_keep_data_data(photo):
    for src in (
        "{% for c in d %}{{ c | markdown }}{% endfor %}\nend\n",
        "{% for x in [d, 'ok'] %}{{ x | markdown }}{% endfor %}\nend\n",
        "{% set x %}{{ d }}{% endset %}{{ x | markdown }}\n",
        "{% set x %}{{ d | markdown }}{% endset %}{{ x | replace(x[0], '') | markdown }}\n",
        "{% macro m(v) %}{{ v | markdown }}{% endmacro %}{{ m(d) | markdown }}\n",
        "{% macro m() %}{{ caller() | markdown }}{% endmacro %}{% call m() %}{{ d | markdown }}{% endcall %}\n",
    ):
        for value in (RAW, f"![x]({photo})"):
            res = md(src, d=value)
            assert not raws(res) and not images(res) and not fences(res), src


def test_bytes_cannot_launder_data():
    with pytest.raises(SecurityError):
        md("{{ d.encode().decode() | markdown }}\n", d=RAW)


def test_data_column_names_are_data_too(photo):
    res = build("{% for k in row %}{{ k | markdown }}{% endfor %}\n", fields={"row": {T(f"![x]({photo})"): T("v")}})
    assert not images(res) and "M122" in codes(res)


# --- only text markup, said at the document's line, once ---------------------------------------------------------


@pytest.mark.parametrize(
    "value, code",
    [
        ("x\n```raw\n1b 40\n", "M121"),  # never closed
        ("x\n```raw\n1b 40\n`````\n", "M121"),  # closed by a longer fence
        ("x\n> ```raw\n> 1b 40\n> ```\n", "M121"),  # in a quote
        ("x\n- ```raw\n  1b 40\n  ```\n", "M121"),  # in a list item
        ("x\n~~~raw\n1b 40\n~~~\n", "M121"),
        ("```qr\nhttps://evil.example\n```", "M123"),  # data does not make objects
        ('```pay {scheme=pix to="x@y.z" name=A city=B}\n```', "M123"),
        ("```barcode\n123\n```", "M123"),
        ("```contact whatsapp\n+55 11 90000-0000\n```", "M123"),
        ("```\nplain code\n```", "M123"),
        ("para\n\n    indented code\n", "M123"),
        ("x\n::: {.box}\ny\n:::", "M123"),
        ("one\n:::\ntwo", "M123"),
        ("[logo]: /etc/passwd\n", "M123"),
        ('[logo]:\n  /etc/passwd\n  "title"\n', "M123"),  # a definition over lines
    ],
)
def test_blocks_data_may_not_bring_are_refused_at_the_documents_line_once(value, code):
    res = md("intro\n\n{{ d | markdown }}\n", d=value)
    assert not raws(res) and not fences(res) and not divs(res)
    (refusal,) = said(res, code)
    assert refusal.line == 3


def test_text_markup_from_data_works():
    value = "# Title\n\n**bold** and *it* ~~old~~ `code` [link](https://x.example)\n\n- a\n- b\n\n> q\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n---"  # noqa: E501
    res = md("{{ d | markdown }}\n", d=value)
    kinds = {type(b) for b in walk(res.doc.blocks)}
    assert {Heading, Paragraph, ListBlock, Quote, Table} <= kinds and codes(res) == {"M120"}
    assert "`code`" not in printed(res) and "code" in printed(res)  # no escape ever printed


def test_data_never_sets_attributes():
    res = md("```qr\nhttps://shop.example\n```\n{{ d | markdown }}\n", d="{module=1 width=10 .left}")
    assert isinstance(res.doc.blocks[0], Fence) and not res.doc.blocks[0].attrs.kv
    assert "{module=1 width=10 .left}" in printed(res)
    res = md("# Sale {{ d | markdown }}\n", d="now {.invert size=huge}")
    heading = res.doc.blocks[0]
    assert not heading.attrs.classes and "{.invert size=huge}" in "".join(r.text for r in heading.runs)


def test_a_payment_cannot_be_rewritten_by_data():
    tpl = '```pay {scheme=pix to="shop@example.com" name=Shop city=Rio amount=10.00}\n```\n{{ d | markdown }}\n'
    res = md(tpl, d="{amount=500 to=thief@example.com}")
    (pay,) = fences(res)
    assert pay.attrs.kv["amount"] == "10.00" and pay.attrs.kv["to"] == "shop@example.com"


def test_data_never_defines_a_link_the_document_uses(photo, tmp_path):
    logo = tmp_path / "logo.png"
    Image.new("L", (40, 20), 255).save(logo)
    for value in (f"[logo]: {photo}", f"[logo]:\n  {photo}", f"\\[x]\n[logo]: {photo}"):
        res = md(f"![logo][logo]\n\n[logo]: {logo}\n\n{{{{ d | markdown }}}}\n", d=value)
        assert [b.src for b in res.doc.blocks if type(b).__name__ == "Image"] == [str(logo)]
        assert "M123" in codes(res) or value.startswith("\\")  # after a paragraph line it is only text
    res = md(f"{{{{ d | markdown }}}}: {photo}\n\n![logo][logo]\n", d="[logo]")  # [label] then the document's
    assert not images(res)


def test_two_values_on_one_line_never_join_into_markup(photo):
    for a, b in (("```", "raw\n1b 40\n```"), (":", ":: {.box title=HACK}\ny"), ("!", f"[x]({photo})"),
                 ("``", "`raw\n1b 40\n```"), ("[logo]", ": /etc/passwd")):  # fmt: skip
        res = md("{{ a | markdown }}{{ b | markdown }}\nz\n\n![logo][logo]\n", a=a, b=b)
        assert not raws(res) and not divs(res) and not images(res) and not fences(res), (a, b)


def test_in_the_documents_code_the_value_is_plain_text_with_no_escapes():
    value = "x\n```\n~~~\n::: {.box title=HACK}\nq\n```"
    res = md("~~~\n{{ d | markdown }}\n~~~\nend `{{ d | markdown }}`\n", d=value)
    (fence,) = fences(res)
    assert res.rendered.resolve(fence.content) == value + "\n" and not divs(res)
    assert "\\" not in printed(res) and isinstance(res.doc.blocks[-1], Paragraph)


@pytest.mark.parametrize("value", ["x\n```\n", "x\n~~~\n", "x\n````", "one\n:::\ntwo", "one\r:::\rtwo",
                                   "one\n> :::\ntwo", "one\n- :::\ntwo"])  # fmt: skip
def test_data_never_swallows_or_closes_the_documents_box(value):
    res = md("::: {.box}\n{{ d | markdown }}\n\nmine\n:::\nend\n", d=value)
    (box,) = divs(res)
    assert box.closed and isinstance(box.children[-1], Paragraph) and isinstance(res.doc.blocks[-1], Paragraph)
    assert "M105" not in codes(res)


def test_the_documents_raw_block_never_takes_data_and_its_image_block_never_a_path(photo):
    with pytest.raises(SecurityError):
        md("```raw\n{{ d | markdown }}\n```\n", d="1b 40")
    with pytest.raises(SecurityError):
        md("```image\n{{ d | markdown }}\n```\n", d=photo)


def test_data_never_chooses_a_code_blocks_kind():
    res = md("```{{ lang | markdown }}\n1b 40\n```\n", lang="raw")
    (fence,) = fences(res)
    assert fence.kind == "text" and fence.content == "1b 40\n" and not raws(res) and "M123" in codes(res)


def test_the_documents_box_title_and_qr_caption_may_come_from_data():
    res = md('::: {.box title="{{ t | markdown }}"}\nx\n:::\n', t="**TABLE** 4")
    assert divs(res) and "**TABLE** 4" in printed(res)
    res = md('```qr {caption="{{ c | markdown }}"}\nhttps://shop.example\n```\n', c="Menu *today*")
    (qr,) = fences(res)
    assert qr.kind == "qr" and qr.attrs.kv["caption"] and "M123" not in codes(res)
    assert [r for r in res.rows if isinstance(r, (QRRow, BitmapRow))]


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


# --- no false positives ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("data", ["for", "Shop", "secret", "100"])
def test_data_that_appears_in_the_authors_own_text_changes_nothing(data, tmp_path):
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


def test_a_value_with_a_placeholder_character_cannot_show_another_values_text():
    res = md("A={{ a }}\n\nB={{ b }}\n", a="SECRET", b="\ue0000\ue001")
    assert printed(res).count("SECRET") == 1 and "M124" in codes(res)
    res = build("A={{ a }}\n\nB={{ b[0] }}\n", fields={"a": "SECRET", "b": ["\ue0000\ue001"]})  # in a list too
    assert printed(res).count("SECRET") == 1 and "M124" in codes(res)
    res = build("{% for k in row %}{{ k }}{% endfor %}\n", fields={"row": {T("\ue0000\ue001"): T("v")}})  # a key
    assert "M124" in codes(res)


def test_ordinary_data_is_untouched_and_not_copied():
    fields = {"d": T("Café 10:30 · R$ 4,50"), "rows": [{"a": T("1")}]}
    from bobina.nudges import Nudges
    from bobina.templating import clean_data

    assert clean_data(fields, Nudges()) is fields
    res = build("{{ d }}\n", fields=fields)
    assert "Café 10:30 · R$ 4,50" in printed(res) and "M124" not in codes(res)
