"""::: blocks (Pandoc fenced divs, as in Quarto) and boxes (docs/guides/layout.md): how the lines of colons open and
close blocks, what a box draws, and what the terminal views show."""

import re
from pathlib import Path

import pytest
from PIL import ImageOps

from bobina import view
from bobina.engine import build
from bobina.model import Div, Fence, Heading, Paragraph
from bobina.rows import BitmapRow, QRRow, RawRow
from bobina.templating import Tainted

ROOT = Path(__file__).resolve().parents[1]
W = 384  # mtp-ii-58


def codes(res) -> list[str]:
    return [n.code for n in res.nudges]


def said(res, code: str) -> list[str]:
    return [n.message for n in res.nudges if n.code == code]


def boxes(res) -> list[BitmapRow]:
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "box"]


def seen(res) -> list[str]:
    return view.lines(res.rows, res.profile)


def ink(im, box=None):
    """The ink's bounding box (x0, y0, x1, y1) of a mode '1' image, or of the part `box` of it."""
    g = im.convert("L")
    return ImageOps.invert(g.crop(box) if box else g).getbbox()


# --- the lines of colons -----------------------------------------------------------------------------------------


def test_a_box_holds_the_blocks_up_to_its_line_of_colons():
    res = build('::: {.box title="MESA"}\n# 109\n\nhello\n:::\nafter\n')
    d, after = res.doc.blocks
    assert isinstance(d, Div) and d.attrs.has("box") and d.attrs.kv["title"] == "MESA" and d.closed
    assert [type(b) for b in d.children] == [Heading, Paragraph]
    assert isinstance(after, Paragraph) and not [c for c in codes(res) if c != "P301"]


def test_a_word_opens_a_block_and_empty_braces_too():
    res = build("::: box\nx\n:::\n\n::: {}\ny\n:::\n")
    a, b = res.doc.blocks
    assert a.attrs.classes == {"box"} and not b.attrs.classes and not b.attrs.kv
    assert [c for c in codes(res) if c != "P301"] == []  # ::: {} is a valid opener: its content prints as it is
    assert any("y" in ln for ln in seen(res))


def test_a_line_of_colons_closes_the_innermost_block_more_colons_change_nothing():
    res = build(":::: {.box}\nouter\n\n::: {.box .dashed}\ninner\n:::\n\nouter again\n::::\n")
    (outer,) = res.doc.blocks
    kinds = [type(b) for b in outer.children]
    assert kinds == [Paragraph, Div, Paragraph] and outer.children[1].attrs.has("dashed")
    res = build("::: {.box}\na\n::: {.box}\nb\n:::\nc\n:::\n")  # three colons everywhere: the same tree
    assert [type(b) for b in res.doc.blocks[0].children] == [Paragraph, Div, Paragraph]


def test_a_block_never_closed_prints_and_says_what_it_holds():
    res = build("::: {.box}\n# 109\n\n::: {.box}\nx\n:::\n")
    (d,) = res.doc.blocks
    assert not d.closed and len(boxes(res)) == 1
    msg = said(res, "M105")
    assert msg == ["::: {.box} at line 1 is never closed: the heading 109 and the box at line 4 are inside it"]
    assert [n.suggestion for n in res.nudges if n.code == "M105"] == ["add a line of ::: where it should end"]


def test_a_block_never_closed_names_many_blocks_in_short():
    res = build("::: {.box}\na\n\nb\n\nc\n\nd\n\ne\n")
    assert said(res, "M105")[0].endswith("the text at line 2, the text at line 4, the text at line 6 and 2 more "
                                         "blocks are inside it")  # fmt: skip


def test_a_line_of_colons_with_nothing_open_is_said_and_ignored():
    res = build("text\n:::\nmore\n")
    assert said(res, "M101") == ["a line of ::: with no ::: block open: ignored"]
    assert [type(b) for b in res.doc.blocks] == [Paragraph, Paragraph]
    assert not any(":::" in ln for ln in seen(res))


def test_an_unknown_class_prints_its_content_and_is_named():
    res = build("::: {.warning}\nCareful\n:::\n")
    assert said(res, "M101") == ["unknown class '.warning'"]
    assert any("Careful" in ln for ln in seen(res)) and not boxes(res)


def test_a_setting_a_plain_block_does_not_take_is_said():
    res = build("::: {width=40%}\nx\n:::\n")
    assert said(res, "M101") == ["width= does nothing on a ::: block without .box"]


def test_colons_inside_a_code_block_are_text():
    res = build("```\n::: {.box}\n:::\n```\n")
    assert [type(b) for b in res.doc.blocks] == [Fence] and "::: {.box}" in res.doc.blocks[0].content
    assert not [c for c in codes(res) if c.startswith("M")]


def test_a_line_of_colons_ends_a_paragraph_a_list_a_quote_and_a_table():
    src = "::: {.box}\ntext\n- a\n- b\n> q\n:::\n\n::: {.box}\n| a | b |\n|---|---|\n| 1 | 2 |\n:::\nafter\n"
    res = build(src)
    assert len(res.doc.blocks) == 3 and res.doc.blocks[0].closed and res.doc.blocks[1].closed
    assert [type(b).__name__ for b in res.doc.blocks[0].children] == ["Paragraph", "ListBlock", "Quote"]
    assert [type(b).__name__ for b in res.doc.blocks[1].children] == ["Table"] and not codes(res)[:-1]


def test_colons_from_data_stay_text():
    res = build("::: {.box}\n{{ d }}\n:::\nend\n", fields={"d": Tainted(":::\n# X")})
    (d, end) = res.doc.blocks
    assert d.closed and [type(b) for b in d.children] == [Paragraph]
    assert any(":::" in ln for ln in seen(res)) and "M105" not in codes(res)


def test_colons_from_data_rendered_as_markdown_cannot_close_the_documents_box():
    res = build("::: {.box}\n{{ d | markdown }}\n\nmine\n:::\n", fields={"d": Tainted("hello\n:::\n# X")})
    (d,) = res.doc.blocks
    assert d.closed and isinstance(d.children[-1], Paragraph) and "M123" in codes(res)  # its ::: line: removed


def test_a_value_with_spaces_and_no_quotes_keeps_its_words():
    res = build("::: {.box title=TABLE 4}\nx\n:::\n")
    assert res.doc.blocks[0].attrs.kv["title"] == "TABLE 4"
    assert said(res, "M101") == ["title=TABLE 4: a value with spaces goes in quotes"]
    assert [n.suggestion for n in res.nudges if n.code == "M101"] == ['title="TABLE 4"']


def test_settings_without_braces_are_read_and_said():
    res = build("::: box shade\nx\n:::\n")
    assert res.doc.blocks[0].attrs.classes == {"box", "shade"}
    assert said(res, "M101") == ["::: box shade: the settings go in braces"]


# --- boxes -------------------------------------------------------------------------------------------------------


def test_a_box_is_one_image_with_its_frame_and_text_inside():
    res = build("::: {.box}\nhello\n:::\n")
    (b,) = boxes(res)
    assert b.image.width == W and ink(b.image) == (0, 0, W, b.image.height)  # the frame: the whole width
    assert "P301" not in codes(res)  # tested on paper 18/11 (docs/TESTED.md)


def test_the_view_draws_the_frame_its_title_and_the_text():
    res = build('::: {.box title="MESA"}\nhello\n:::\n')
    lines = [ln for ln in seen(res) if ln.strip()]
    assert lines[0] == "┌──────────── MESA ────────────┐"
    assert lines[1].startswith("│hello") and lines[1].endswith("│") and len(lines[1]) == 32
    assert lines[2] == "└" + "─" * 30 + "┘"


def test_text_inside_wraps_at_the_width_inside_the_frame():
    res = build("::: {.box}\n" + "word " * 20 + "\n:::\n")
    inside = [ln[1:-1].rstrip() for ln in seen(res) if ln.startswith("│")]
    assert len(inside) > 1 and max(len(x) for x in inside) <= 30


def test_title_inside_is_the_first_line_bold():
    res = build('::: {.box title="Order 42" title-style=inside}\n2x Coffee\n:::\n')
    (b,) = boxes(res)
    first = b.box.rows[0]
    assert first.cells[0].bold and "".join(c.ch for c in first.cells).startswith("Order 42")
    lines = [ln for ln in seen(res) if ln.strip()]
    assert lines[0] == "┌" + "─" * 30 + "┐" and lines[1].startswith("│Order 42")


def test_title_on_a_band_is_white_on_black_across_the_top():
    res = build('::: {.box title="WAITERS" title-style=band}\n- Ana\n:::\n')
    (b,) = boxes(res)
    band = b.box.rows[0]
    assert band.kind == "band"
    row = b.image.convert("L").crop((2, 4, W - 2, 5))  # a line of the band, inside the frame
    assert ink(row) == (0, 0, W - 4, 1)  # black from side to side (the title is lower)


def test_a_wrong_title_style_is_said_with_the_three_values():
    for bad in ("faixa", "BAND"):
        res = build(f'::: {{.box title="X" title-style={bad}}}\ny\n:::\n')
        assert said(res, "M101") == [f"title-style={bad}"]
        assert [n.suggestion for n in res.nudges if n.code == "M101"] == ["border, inside or band"]


def test_a_long_title_is_cut_on_the_border_and_said():
    title = "A TITLE FAR LONGER THAN THE BORDER HOLDS"
    res = build(f'::: {{.box title="{title}"}}\nx\n:::\n')
    (b,) = boxes(res)
    assert b.box.title.endswith("…") and len(b.box.title) == 26
    assert said(res, "L109") == [f'title "{title}" is longer than the border holds (26 letters): cut with …']


@pytest.mark.parametrize("style", ["band", "inside"])
def test_a_long_title_wraps_in_a_band_or_inside(style):
    res = build(f'::: {{.box title="A TITLE FAR LONGER THAN THE BORDER HOLDS" title-style={style}}}\nx\n:::\n')
    assert "L109" not in codes(res)
    text = [ln for ln in seen(res) if "TITLE" in ln or "BORDER" in ln]
    assert len(text) == 2


def test_each_line_style_draws_its_own_frame():
    tops = {}
    for style in ("solid", "dashed", "dotted", "double"):
        (b,) = boxes(build(f"::: {{.box .{style}}}\nx\n:::\n"))
        top = b.image.convert("L").crop((0, 0, W, 1))
        tops[style] = sum(1 for x in range(W) if top.getpixel((x, 0)) < 128)
        assert ink(b.image, (0, 0, 1, b.image.height))  # the left side is inked at its top
    assert tops["solid"] == tops["double"] == W > tops["dashed"] > tops["dotted"] > 0
    (b,) = boxes(build("::: {.box .double}\nx\n:::\n"))
    col = [b.image.convert("L").getpixel((W // 2, y)) < 128 for y in range(8)]
    assert col == [True, True, False, False, True, True, False, False]  # two lines, one line apart
    lines = [ln for ln in seen(build("::: {.box .double}\nx\n:::\n")) if ln.strip()]
    assert lines[0].startswith("╔═") and lines[1].startswith("║")


def test_thickness_is_in_dots_and_below_two_is_said():
    (b,) = boxes(build("::: {.box thickness=4}\nx\n:::\n"))
    assert [b.image.convert("L").getpixel((W // 2, y)) < 128 for y in range(5)] == [True] * 4 + [False]
    res = build("::: {.box thickness=1}\nx\n:::\n")
    assert said(res, "B101") == ["box thickness 1 prints broken"]
    res = build("::: {.box thickness=thick}\nx\n:::\n")
    assert said(res, "M101") == ["thickness=thick"] and boxes(res)


@pytest.mark.parametrize(
    "settings, left, width",
    [
        ("width=half", 0, 192),
        ("width=half .center", 96, 192),
        ("width=half .right", 192, 192),
        ("width=16ch .right", 192, 192),
        ("width=30mm .center", 72, 240),  # 30 mm is 240 dots: 20 letters, centred on the letters
        ("width=third", 0, 120),  # whole letters: 128 dots are 10 of them
    ],
)
def test_width_and_place(settings, left, width):
    (b,) = boxes(build(f"::: {{.box {settings}}}\nx\n:::\n"))
    x0, _, x1, _ = ink(b.image)
    assert (x0, x1 - x0) == (left, width)


def test_a_box_is_never_wider_than_the_paper():
    res = build("::: {.box width=100mm}\nx\n:::\n")
    (b,) = boxes(res)
    assert ink(b.image)[2] == W
    assert said(res, "M101") == ["width=100mm: wider than the 32 letters there are, the box takes them"]
    for src in ("- item\n\n  ::: {.box}\n  inside a list\n  :::\n", "> ::: {.box}\n> inside a quote\n> :::\n"):
        (b,) = boxes(build(src))
        assert b.image.width == W and ink(b.image, (12, 0, W, b.image.height))[0] == 12 and ink(b.image)[2] == W


def test_shade_puts_grey_dots_inside_and_none_on_the_letters():
    plain, grey = (boxes(build(f"::: {{.box{s}}}\nWWWW\n:::\n"))[0].image.convert("L") for s in ("", " .shade"))
    inside = (4, 4, W - 4, plain.height - 4)
    assert ink(plain, inside) and ink(grey, inside)

    def black(im):
        return im.crop(inside).tobytes().count(0)

    assert black(grey) - black(plain) > 200
    x0, y0, x1, y1 = ink(plain, (12, 4, W - 12, plain.height - 4))  # the letters
    halo = (12 + x0 - 2, 4 + y0, 12 + x1, 4 + y1)  # beside them, the grey stays away
    assert grey.crop(halo).tobytes() == plain.crop(halo).tobytes()


def test_boxes_nest_and_the_view_draws_both():
    res = build(':::: {.box title="OUT"}\nouter\n\n::: {.box .dashed title="IN"}\ninner\n:::\n::::\n')
    (b,) = boxes(res)
    (inner,) = [r for r in b.box.rows if isinstance(r, BitmapRow) and r.box]
    assert inner.box.cols == 30 and inner.image.width == 360
    lines = [ln for ln in seen(res) if ln.strip()]
    assert lines[0].startswith("┌─") and " OUT " in lines[0]
    assert any(ln.startswith("│┌╌") and " IN " in ln for ln in lines) and any(ln.startswith("│╎inner") for ln in lines)


def test_a_qr_code_inside_is_sized_as_an_image_that_fits():
    res = build("::: {.box}\n```qr\nhttps://example.com/receipt/276712\n```\n:::\n")
    (b,) = boxes(res)
    assert not [r for r in res.rows if isinstance(r, QRRow)]
    assert [r.kind for r in b.box.rows] == ["qr"] and b.box.rows[0].image.width == 360


def test_raw_bytes_cannot_go_inside_a_box():
    res = build("::: {.box}\nx\n\n```raw\n1b 40\n```\n:::\n")
    assert isinstance(res.rows[-2], RawRow) and boxes(res)
    assert said(res, "M101") == ["a ```raw block cannot go inside a box: its bytes are sent after the box"]


def test_settings_a_box_does_not_take_are_said():
    res = build("::: {.box size=large .wavy}\nx\n:::\n")
    assert said(res, "M101") == [".wavy, size= do nothing on a box"]
    res = build("::: {.box .dashed .double}\nx\n:::\n")
    assert said(res, "M101") == [".dashed .double: a box has one line, .dashed is used"]


@pytest.mark.parametrize("style", ["border", "inside", "band"])
def test_a_title_from_data_is_printed_as_written(style):
    src = f'::: {{.box title="{{{{ t }}}}" title-style={style}}}\nx\n:::\n'
    res = build(src, fields={"t": Tainted("**A** :::")})
    assert any("**A** :::" in ln for ln in seen(res))


def test_the_documents_examples_print_clean():
    guide = (ROOT / "docs" / "guides" / "layout.md").read_text(encoding="utf-8")
    examples = re.findall(r"```markdown\n(.*?)```", guide, re.S)
    assert len(examples) >= 5
    for src in examples:
        res = build(src)
        assert boxes(res) and [c for c in codes(res) if c != "P301"] == [], src  # P301: a band title's bold white


# --- review fixes ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("src", ["::: {.box .flip}\nhi\n\n```raw\n1b 40\n```\n:::\n",
                                 "::: {.box rotate=90}\nhi\n\n```raw\n1b 40\n```\n:::\n",
                                 "::: {.note rotate=90}\nhi\n\n```raw\n1b 40\n```\n:::\n"])  # fmt: skip
def test_raw_bytes_are_kept_after_a_turned_block(src):
    res = build(src)
    assert [r.data for r in res.rows if isinstance(r, RawRow)] == [b"\x1b@"]


def test_boxes_deep_in_boxes_keep_four_letters_inside_and_never_crash():
    opens = "".join(f"{':' * (10 - i)} {{.box .double thickness=12}}\n" for i in range(5))
    closes = "".join(f"{':' * (6 + i)}\n" for i in range(5))
    res = build(opens + "hi\n" + closes)
    assert "no room for that line" in " ".join(said(res, "M101"))
    assert "prints without its frame" in " ".join(said(res, "L111"))

    def walk(row):
        b = row.box
        assert b.inner >= 4 * 12 and b.left + b.cols <= row.image.width // 12
        for r in b.rows:
            if isinstance(r, BitmapRow) and r.box:
                assert r.image.width == b.inner
                walk(r)

    (top,) = boxes(res)
    walk(top)
    assert any(" hi " in ln for ln in seen(res))


def test_a_thick_double_frame_under_a_border_title_is_never_clipped():
    (b,) = boxes(build("::: {.box .double thickness=12 title=HELLO}\nx\n:::\n"))
    im = b.image.convert("L")
    assert [im.getpixel((20, y)) < 128 for y in (0, 11, 12)] == [True, True, False]  # the whole outer line
    assert ink(im, (100, 0, 284, 40))  # the title over it


@pytest.mark.parametrize(
    "src, left, width",
    [
        ("> ::: {.box width=full}\n> x\n> :::\n", 24, 360),
        ("- item\n\n  ::: {.box width=half}\n  x\n  :::\n", 24, 180),
        ("> ::: {.box width=50% .right}\n> x\n> :::\n", 204, 180),
        ("::: {.box width=16,5ch}\nx\n:::\n", 0, 192),
        ("::: {.box width=half align=center}\nx\n:::\n", 96, 192),
    ],
)
def test_width_is_of_the_room_the_box_has(src, left, width):
    res = build(src)
    (b,) = boxes(res)
    gutter = 12 if src[0] in ">-" else 0  # the quote's bar is not the box
    x0, _, x1, _ = ink(b.image, (gutter, 0, W, b.image.height))
    assert (gutter + x0, x1 - x0) == (left, width) and "M101" not in codes(res)


def test_a_wide_table_inside_a_box_widens_the_box_in_the_view():
    table = '| | {prefix="R$ "} |\n|---|--:|\n| SUBTOTAL | 105,70 |\n| TROCO | 7,57 |\n{font=Terminus size=16px}\n'
    lines = seen(build("::: {.box}\n" + table + "\n:::\nafter\n"))
    assert len({len(ln) for ln in lines}) == 1 and len(lines[0]) > 32
    framed = [ln for ln in lines if ln.startswith("│")]
    assert framed and all(ln.rstrip().endswith("│") for ln in framed)


def test_a_turned_box_is_placed_as_written_and_its_quote_bars_stay_upright():
    (b,) = boxes(build("::: {.box rotate=90 .right}\nhi\n:::\n"))
    assert ink(b.image)[2] == W
    (b,) = boxes(build("> ::: {.box rotate=90}\n> hi\n> :::\n"))
    im = b.image.convert("L")
    assert all(im.getpixel((5, y)) < 128 for y in range(im.height))  # the bar, from top to bottom
    assert ink(im, (12, 0, W, im.height))[0] == 12  # the box after the gutter, on the left as written
    lines = [ln for ln in seen(build("::: {.box .flip}\nhi\n:::\n")) if ln.strip()]
    assert "↻ box printed turned 180°" in lines[0] and lines[1].startswith("┌")


@pytest.mark.parametrize(
    "value",
    ["one\r:::\rtwo", "one\r\n:::\r\ntwo", "one\n> :::\ntwo", "one\n- :::\ntwo", "one\n1. :::\ntwo", "  :::\nx"],
)
def test_colons_from_data_never_close_the_documents_box_whatever_the_line_breaks(value):
    res = build("::: {.box}\n{{ d | markdown }}\n\nmine\n:::\nend\n", fields={"d": Tainted(value)})
    d = res.doc.blocks[0]
    assert d.closed and isinstance(d.children[-1], Paragraph) and len(res.doc.blocks) == 2
    assert "M101" not in codes(res) and "M105" not in codes(res)


@pytest.mark.parametrize("value", ["x\r::: {.box title=HACK}\ry", "x\n> ::: {.box}\ny", "x\n- ::: box\ny"])
def test_colons_from_data_never_open_a_box(value):
    res = build("{{ d | markdown }}\n", fields={"d": Tainted(value)})
    assert not boxes(res)


def test_a_raw_block_from_data_never_hides_behind_a_carriage_return():
    res = build("{{ d | markdown }}\n", fields={"d": Tainted("x\r```raw\r1b 40\r```")})
    assert not [r for r in res.rows if isinstance(r, RawRow)] and "M121" in codes(res)


def test_a_code_block_in_data_is_removed_with_its_colons():
    res = build("{{ d | markdown }}\n", fields={"d": Tainted("intro\n```\n::: {.box}\n```")})
    assert not [b for b in res.doc.blocks if isinstance(b, (Fence, Div))] and "M123" in codes(res)


def test_a_block_holding_a_box_turns_as_a_block():
    res = build("::: {rotate=90}\n::: {.box}\nx\n:::\n\ntext after\n:::\n")
    (row,) = [r for r in res.rows if isinstance(r, BitmapRow)]
    assert row.kind == "rotated"  # the whole block, the box and the text after it


def test_the_turned_mark_fits_a_narrow_box():
    res = build("::: {.box rotate=90 width=8ch}\nx\n:::\n")
    (b,) = boxes(res)
    lines = [ln.rstrip() for ln in seen(res) if ln.strip()]
    assert "↻ 90°" in lines[0] and len(lines[0]) <= b.box.left + b.box.cols


def test_a_double_line_too_wide_for_a_small_cell_becomes_one_line():
    res = build("::: {.box .double width=6ch}\nabcd\n:::\n", overrides={"native.cell": [8, 16]})
    (b,) = boxes(res)
    assert b.box.style == "solid" and b.box.inner >= 4 * 8
    assert said(res, "M101") == [".double: no room for two lines in a 6-letter box, one is drawn"]


def test_a_turned_box_is_shown_where_it_prints():
    (b,) = boxes(build("::: {.box rotate=90 width=10ch .center}\nabc\n:::\n"))
    x0 = ink(b.image)[0]
    assert b.box.left == min(x0, W - 120) // 12


@pytest.mark.parametrize("src", ["::: {.box align=middle}\nx\n:::\n", "```qr {align=middle}\nhello\n```\n"])
def test_a_wrong_align_is_said(src):
    res = build(src)
    assert said(res, "M101") == ["align=middle"]
    assert [n.suggestion for n in res.nudges if n.code == "M101"] == ["left, center or right"]


def test_align_justify_on_a_box_is_said():
    res = build("::: {.box align=justify}\nx\n:::\n")
    assert said(res, "M101") == ["align=justify"] and boxes(res)
