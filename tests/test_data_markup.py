"""Data rendered as Markdown (`{{ value | markdown }}` on a --data/--set value) never makes raw bytes, images or
::: blocks, and never opens or closes the document's own code blocks and boxes (SECURITY.md, FORMAT §7.4). Where the
value lands is recorded while the template renders and checked on the parse of the whole document
(parser.data_markup), so a value split in two, put in a quote or a list item, or joined to other text is seen as
markdown-it sees it."""

import pytest
from PIL import Image

from bobina.engine import build
from bobina.model import Div, Fence, Paragraph
from bobina.rows import BitmapRow, RawRow
from bobina.templating import Tainted

ESC_AT = b"\x1b\x40"  # what every raw probe would send: ESC @ (reset)


def codes(res) -> set[str]:
    return {n.code for n in res.nudges}


def raw_bytes(res) -> list[bytes]:
    return [r.data for r in res.rows if isinstance(r, RawRow)]


def divs(blocks) -> list[Div]:
    out = []
    for b in blocks:
        if isinstance(b, Div):
            out += [b, *divs(b.children)]
        for it in getattr(b, "items", []):
            out += divs(it.children)
        if not isinstance(b, Div) and isinstance(getattr(b, "children", None), list):
            out += divs(b.children)
    return out


def md(template: str, **values) -> object:
    return build(template, fields={k: Tainted(v) for k, v in values.items()})


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "secret.png"
    Image.new("L", (40, 20), 0).save(p)
    return str(p)


@pytest.mark.parametrize(
    "value",
    [
        "x\n```raw\n1b 40\n",  # never closed: it runs to the end of the document
        "x\n```raw\n1b 40\n`````\n",  # closed by a longer fence
        "x\n> ```raw\n> 1b 40\n> ```\n",  # in a quote
        "x\n- ```raw\n  1b 40\n  ```\n",  # in a list item
        "x\r```raw\r1b 40\r```",  # carriage returns
        "x\r\n```raw\r\n1b 40\r\n```",
        "x\n~~~raw\n1b 40\n~~~\n",
    ],
)
def test_data_never_makes_a_raw_block(value):
    res = md("{{ d | markdown }}\n", d=value)
    assert not raw_bytes(res) and ESC_AT not in res.data[2:] and "M121" in codes(res)


def test_two_values_joined_on_one_line_never_make_a_raw_block():
    res = md("{{ a | markdown }}{{ b | markdown }}\n", a="```", b="raw\n1b 40\n```")
    assert not raw_bytes(res) and "M121" in codes(res)


def test_the_documents_raw_block_never_takes_bytes_from_data():
    res = md("```raw\n{{ d | markdown }}\n```\n", d="1b 40")
    assert not raw_bytes(res) and "M121" in codes(res)


@pytest.mark.parametrize("expr", ["d", "(d ~ '')", "('' ~ d)", "d | upper | lower", "d.replace('Q', 'Q')", "d[0:]",
                                  "d | trim", "[d] | join", "'%s' | format(d)", "{'k': d}.k"])  # fmt: skip
def test_data_never_chooses_an_image_whatever_string_operation_comes_first(expr, photo):
    res = md("{{ " + expr + " | markdown }}\n", d=f"![x]({photo})")
    assert not [r for r in res.rows if isinstance(r, BitmapRow)] and "M122" in codes(res)


def test_the_documents_image_block_never_takes_its_path_from_data(photo):
    res = md("```image\n{{ d | markdown }}\n```\n", d=photo)
    assert not [r for r in res.rows if isinstance(r, BitmapRow)] and "M122" in codes(res)


@pytest.mark.parametrize("expr", ["d", "(d ~ '')", "d | upper", "d | replace('a', 'a')", "d[0:]", "[d] | join"])
def test_data_never_opens_a_box(expr):
    res = md("{{ " + expr + " | markdown }}\nafter\n", d="x\n::: {.box title=HACK}\ny")
    assert not divs(res.doc.blocks) and "M123" in codes(res)


def test_two_values_joined_on_one_line_never_make_a_line_of_colons():
    res = md("{{ a | markdown }}{{ b | markdown }}\nz\n", a=":", b=":: {.box title=HACK}\ny")
    assert not divs(res.doc.blocks) and "M123" in codes(res)


@pytest.mark.parametrize("value", ["one\n:::\ntwo", "one\r:::\rtwo", "one\n> :::\ntwo", "one\n- :::\ntwo"])
def test_data_never_closes_the_documents_box(value):
    res = md("::: {.box}\n{{ d | markdown }}\n\nmine\n:::\nend\n", d=value)
    (box,) = divs(res.doc.blocks)
    assert box.closed and isinstance(box.children[-1], Paragraph) and "M105" not in codes(res)


def test_data_never_closes_the_documents_code_block():
    res = md("~~~\n{{ d | markdown }}\n~~~\nend\n", d="x\n```\n~~~\n::: {.box title=HACK}\nq\n```")
    fences = [b for b in res.doc.blocks if isinstance(b, Fence)]
    assert len(fences) == 1 and "::: {.box title=HACK}" in fences[0].content and not divs(res.doc.blocks)
    assert "M123" in codes(res)


def test_a_code_fence_data_leaves_open_never_swallows_the_document():
    res = md("::: {.box}\n{{ d | markdown }}\n:::\nend\n", d="x\n```\n")
    (box,) = divs(res.doc.blocks)
    assert box.closed and isinstance(res.doc.blocks[-1], Paragraph) and "M123" in codes(res)


def test_a_code_block_data_opens_and_closes_stays_one():
    res = md("{{ d | markdown }}\n", d="intro\n```\n::: {.box}\n```")
    (fence,) = [b for b in res.doc.blocks if isinstance(b, Fence)]
    assert fence.content == "::: {.box}\n" and "M123" not in codes(res)


def test_plain_values_are_unchanged_and_the_authors_markdown_still_works():
    res = md("{{ d }}\n", d="::: {.box}\n```raw\n1b 40\n```")
    assert [type(b) for b in res.doc.blocks] == [Paragraph] and not raw_bytes(res) and codes(res) == set()
    res = build("{{ v | markdown }}\n", fields={"v": "::: {.box}\n**hi**\n:::"})  # the author's own value
    assert divs(res.doc.blocks) and "M123" not in codes(res)
