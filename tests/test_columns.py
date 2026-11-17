"""Columns side by side (:::: {.columns}, docs/guides/layout-columns.md): which ::: blocks are columns, their widths,
valign=, wrap=, what they print and what the terminal views show."""

import random

import pytest
from PIL import ImageOps

from bobina import view
from bobina.engine import build
from bobina.model import Div, Fence, Paragraph
from bobina.rows import BitmapRow
from bobina.templating import Tainted

W = 384  # mtp-ii-58: 32 letters of 12 dots
CW = 12
QR = "```qr\nhttps://exemplo.com/consulta/276712\n```\n"
NFCE = (
    ":::: {.columns valign=middle}\n::: {.column width=40%}\n" + QR + ":::\n::: {.column width=60%}\n"
    "CONSUMIDOR NÃO IDENTIFICADO\nNFC-e nº 276712 · Série 4\n15/11/2026 11:33\n:::\n::::\n"
)


def codes(res) -> list[str]:
    return [n.code for n in res.nudges]


def said(res, code: str) -> list[str]:
    return [n.message for n in res.nudges if n.code == code]


def rows_of_columns(res) -> list[BitmapRow]:
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "columns"]


def spans(row: BitmapRow) -> list[tuple[int, int]]:
    """Each column's (first letter, letters) on the paper."""
    return [(c.left, c.inner // CW) for c in row.columns.columns]


def ink(im, box=None):
    g = im.convert("L")
    return ImageOps.invert(g.crop(box) if box else g).getbbox()


def cols(*bodies: str, opts: str = "", each: tuple = ()) -> str:
    out = f":::: {{.columns {opts}}}\n"
    for k, body in enumerate(bodies):
        out += f"::: {{.column {each[k] if k < len(each) else ''}}}\n{body}\n:::\n"
    return out + "::::\n"


# --- which blocks are columns ------------------------------------------------------------------------------------


def test_each_block_inside_columns_is_one_column_left_to_right():
    res = build(cols("left", "middle", "right"))
    (d,) = res.doc.blocks
    assert d.attrs.has("columns") and len(d.children) == 3 and all(isinstance(c, Div) for c in d.children)
    (row,) = rows_of_columns(res)
    assert [x for x, _ in spans(row)] == [0, 11, 22]  # 10 letters each, a letter between them
    assert [c for c in codes(res) if c != "P301"] == []


def test_any_braces_open_a_column_even_empty_ones():
    res = build(":::: {.columns}\n::: {}\nA\n:::\n::: {width=40%}\nB\n:::\n::::\n")
    (d,) = res.doc.blocks
    assert len(d.children) == 2 and [c for c in codes(res) if c != "P301"] == []


def test_text_outside_a_column_becomes_a_column_of_its_own_and_is_said():
    res = build(":::: {.columns}\nstray text\n\n::: {.column}\nB\n:::\n::::\n")
    (d,) = res.doc.blocks
    first, second = d.children
    assert isinstance(first.children[0], Paragraph) and second.children[0].runs[0].text == "B"
    assert any("outside any column" in m for m in said(res, "M101"))
    assert len(rows_of_columns(res)[0].columns.columns) == 2


def test_a_bare_line_of_colons_after_a_column_closes_the_columns_and_says_how_to_open_one():
    src = ":::: {.columns}\n::: {width=40%}\n" + QR + ":::\n:::\nCUSTOMER\n:::\n::::\n"  # the study's mistake
    res = build(src)
    msgs = said(res, "M101")
    assert any("closes the :::: {.columns} of line 1, right after a column" in m for m in msgs)
    hints = [n.suggestion for n in res.nudges if n.code == "M101"]
    assert any("::: {.column}" in h for h in hints)
    d, text = res.doc.blocks[:2]
    assert len(d.children) == 1 and isinstance(text, Paragraph)  # one column; the text prints under it


def test_columns_closed_by_as_many_colons_as_they_opened_with_are_not_said():
    res = build("::: {.columns}\n::: {}\nA\n:::\n::: {}\nB\n:::\n:::\n")
    assert [c for c in codes(res) if c != "P301"] == []


def test_a_box_right_inside_columns_is_a_column_drawn_as_a_box():
    res = build(':::: {.columns}\n::: {.box title="PAID" width=40%}\nok\n:::\n::: {}\nnote\n:::\n::::\n')
    (d,) = res.doc.blocks
    box_col = d.children[0]
    assert box_col.attrs.kv == {"width": "40%"} and box_col.children[0].attrs.has("box")
    assert "width" not in box_col.children[0].attrs.kv  # the box fills its column
    (row,) = rows_of_columns(res)
    assert spans(row)[0] == (0, 12)


def test_a_column_outside_columns_prints_its_blocks_and_is_said():
    res = build("::: {.column width=40%}\nA\n:::\n")
    assert any("outside :::: {.columns}" in m for m in said(res, "M101"))
    assert not rows_of_columns(res) and any("A" in ln for ln in view.lines(res.rows, res.profile))


def test_unknown_settings_on_columns_are_said():
    res = build(":::: {.columns wrap=sometimes valign=up gap=wide .box}\n::: {.column .bold}\nA\n:::\n::::\n")
    msgs = " | ".join(said(res, "M101"))
    for part in ("wrap=sometimes", "valign=up", "gap=wide", ".box does nothing on :::: {.columns}", ".bold"):
        assert part in msgs, part


# --- widths -------------------------------------------------------------------------------------------------------


def test_percent_widths_are_of_the_text_room_and_fill_it_exactly():
    (row,) = rows_of_columns(build(cols("A", "B", each=("width=40%", "width=60%"))))
    (x0, w0), (x1, w1) = spans(row)
    assert (w0, w1) == (12, 19) and w0 + 1 + w1 == 32 and x1 == 13  # 31 letters of text room: 12.4 and 18.6


def test_letters_mm_and_dots_and_auto_share_what_is_left():
    (row,) = rows_of_columns(build(cols("A", "B", "C", "D", each=("width=6ch", "width=10mm", "width=48", ""))))
    widths = [w for _, w in spans(row)]
    assert widths[:3] == [6, 6, 4] and sum(widths) + 3 == 32  # 10 mm = 80 dots: 6 letters; 48 dots: 4


def test_gap_sets_the_letters_between_columns():
    for gap, second in (("gap=0", 16), ("gap=3ch", 18), ("gap=2", 16)):  # 2 dots: no whole letter
        (row,) = rows_of_columns(build(cols("A", "B", opts=gap)))
        assert spans(row)[1][0] == second, gap


def test_widths_asking_for_more_than_the_paper_are_narrowed_and_said():
    res = build(cols("A", "B", each=("width=20ch", "width=20ch")))
    (row,) = rows_of_columns(res)
    assert sum(w for _, w in spans(row)) + 1 <= 32
    assert any("ask for 41 of the 32 letters" in m for m in said(res, "M101"))


def test_widths_in_capitals_are_said():
    res = build(cols("A", "B", each=("width=40PCT",)))
    assert any("lowercase" in m for m in said(res, "M101"))


def test_never_wider_than_the_paper_whatever_the_columns():
    rnd = random.Random(643)
    widths = ["", "width=40%", "width=60%", "width=12ch", "width=30mm", "width=200", "width=half", "width=1ch"]
    bodies = ["word", "a longer line of words to wrap", QR.strip(), "# Big", "- a\n- b", "Supercalifragilistic"]
    for _ in range(25):
        n = rnd.randint(1, 6)
        opts = " ".join([rnd.choice(["", "wrap=wrap", "wrap=wrap-reverse"]), rnd.choice(["", "gap=0", "gap=2ch"])])
        src = cols(*(rnd.choice(bodies) for _ in range(n)), opts=opts, each=tuple(rnd.choice(widths) for _ in range(n)))
        res = build(src)
        for r in rows_of_columns(res):
            assert r.image.width == W
            right = [x + w for x, w in spans(r)]
            assert all(w >= 1 for _, w in spans(r)) and max(right) <= 32, src
            assert [x for x, _ in spans(r)] == sorted(x for x, _ in spans(r))  # side by side, never on each other


# --- valign ---------------------------------------------------------------------------------------------------------


def _tops(src: str) -> list[int]:
    (row,) = rows_of_columns(build(src))
    out = []
    for c in row.columns.columns:
        x0 = c.left * CW
        out.append(ink(row.image, (x0, 0, x0 + c.inner, row.image.height))[1])
    return out


def test_valign_top_is_the_default_and_middle_and_bottom_move_the_shorter_column():
    tall = "one\ntwo\nthree\nfour\nfive"
    top = _tops(cols(tall, "short"))
    middle = _tops(cols(tall, "short", opts="valign=middle"))
    bottom = _tops(cols(tall, "short", opts="valign=bottom"))
    assert top[0] == top[1] and top[0] < middle[1] < bottom[1] and middle[0] == top[0]


def test_valign_center_is_middle_without_a_word():
    res = build(cols("a\nb\nc", "x", opts="valign=center"))
    assert _tops(cols("a\nb\nc", "x", opts="valign=center")) == _tops(cols("a\nb\nc", "x", opts="valign=middle"))
    assert [c for c in codes(res) if c != "P301"] == []


def test_a_columns_valign_wins_over_the_columns():
    tops = _tops(cols("a\nb\nc\nd", "x", "y", opts="valign=bottom", each=("", "valign=top", "")))
    assert tops[1] == tops[0] < tops[2]


# --- wrap -----------------------------------------------------------------------------------------------------------

HEADER = cols("Rua Exemplo, 190\nBotafogo", "Seg a Sáb 7h–22h", opts="wrap=wrap", each=("width=20ch", "width=20ch"))


def test_nowrap_squeezes_text_into_its_column():
    res = build(cols("Rua Exemplo, 190 · Botafogo · Rio de Janeiro", "Seg a Sáb 7h–22h"))
    (row,) = rows_of_columns(res)
    assert len(row.columns.columns) == 2 and "L110" not in codes(res)


def test_nowrap_shrinks_a_qr_and_says_when_it_may_not_scan():
    res = build(cols(QR.strip(), "text", each=("width=6ch",)))
    (row,) = rows_of_columns(res)
    assert any("may not scan" in m for m in said(res, "Q101"))
    qr_ink = ink(row.image, (0, 0, 6 * CW, row.image.height))
    assert qr_ink and qr_ink[2] <= 6 * CW  # never past its column


def test_wrap_moves_a_column_whose_widths_do_not_fit_to_a_new_row_under():
    res = build(HEADER)
    first, second = rows_of_columns(res)
    assert len(first.columns.columns) == len(second.columns.columns) == 1
    assert "Seg" in "".join(view.lines([second], res.profile))
    (note,) = said(res, "L110")
    assert "column 2 does not fit beside column 1" in note and "41 of the 32 letters" in note and "under" in note


def test_wrap_reverse_puts_the_new_row_above():
    res = build(HEADER.replace("wrap=wrap", "wrap=wrap-reverse"))
    first, second = rows_of_columns(res)
    assert "Seg" in "".join(view.lines([first], res.profile)) and "above" in said(res, "L110")[0]


def test_wrap_keeps_columns_side_by_side_on_wider_paper():
    res = build("---\nprofile: epson-tm-t20ii\n---\n" + HEADER)
    (row,) = rows_of_columns(res)
    assert len(row.columns.columns) == 2 and "L110" not in codes(res)


def test_wrap_moves_a_column_whose_longest_word_does_not_fit():
    res = build(cols("short", "Pneumoultramicroscopico", opts="wrap=wrap", each=("width=60%",)))
    assert len(rows_of_columns(res)) == 2 and "content does not fit" in said(res, "L110")[0]
    assert "L101" not in codes(res)  # on its own row the word fits: nothing cut


def test_wrap_moves_a_qr_that_would_go_below_the_module_that_scans():
    res = build(cols("text", QR.strip(), opts="wrap=wrap", each=("width=80%",)))
    assert len(rows_of_columns(res)) == 2 and "Q101" not in codes(res)


def test_wrap_leaves_columns_that_fit_alone():
    res = build(cols("a", "b", "c", opts="wrap=wrap"))
    assert len(rows_of_columns(res)) == 1 and "L110" not in codes(res)


# --- what they hold -------------------------------------------------------------------------------------------------


def test_the_nfce_footer_a_qr_beside_three_lines_in_the_middle():
    res = build(NFCE)
    (row,) = rows_of_columns(res)
    assert spans(row) == [(0, 12), (13, 19)] and [c for c in codes(res) if c != "P301"] == []
    qr = ink(row.image, (0, 0, 12 * CW, row.image.height))
    text = ink(row.image, (13 * CW, 0, W, row.image.height))
    assert abs((qr[1] + qr[3]) / 2 - (text[1] + text[3]) / 2) <= 2  # their middles meet
    assert "P301" in codes(res) and "columns side by side" in said(res, "P301")[0]


def test_a_box_inside_a_column():
    res = build(cols("Text beside a box, long enough to wrap.", '::: {.box title="PAID"}\nR$ 9\n:::'))
    (row,) = rows_of_columns(res)
    lines = view.lines(res.rows, res.profile)
    assert any("┌" in ln and "PAID" in ln and ln.index("┌") > 15 for ln in lines)
    assert spans(row) == [(0, 16), (17, 15)]


def test_columns_inside_columns():
    inner = ":::: {.columns gap=0}\n::: {}\nx\n:::\n::: {}\ny\n:::\n::::"
    res = build(":::::: {.columns}\n::: {}\nleft\n:::\n::::: {.column}\n" + inner + "\n:::::\n::::::\n")
    (row,) = rows_of_columns(res)
    inside = row.columns.columns[1].rows
    assert any(isinstance(r, BitmapRow) and r.kind == "columns" for r in inside)
    assert [c for c in codes(res) if c != "P301"] == []


def test_a_raw_block_in_a_column_is_sent_after_the_columns():
    res = build(cols("```raw\n1b 40\n```", "x"))
    assert any("cannot go inside a column" in m for m in said(res, "M101"))


def test_columns_in_a_quote_keep_its_bar():
    res = build("> " + cols("left", "right").replace("\n", "\n> "))
    (row,) = rows_of_columns(res)
    assert row.columns.columns[0].left == 2
    assert any(ln.startswith("│") and "left" in ln and "right" in ln for ln in view.lines(res.rows, res.profile))


# --- the terminal view -------------------------------------------------------------------------------------------


def test_the_view_draws_the_columns_side_by_side_at_their_paper_columns():
    res = build(cols("left", "right", each=("width=40%",)))
    lines = view.lines(res.rows, res.profile)
    ln = next(ln for ln in lines if "left" in ln)
    assert ln.index("left") == 0 and ln.index("right") == 13 and len(ln) == 32


def test_the_view_widens_for_a_column_in_a_smaller_font_rather_than_cut():
    table = "| a | b | c |\n|---|---|---|\n| 1234567 | 2345678 | 3456789 |\n{font=Terminus size=16px}"
    res = build(cols(table, "x", each=("width=60%",)))
    frame = view.width(res.rows, res.profile)
    lines = view.lines(res.rows, res.profile, frame=frame)
    assert all(len(ln) == frame for ln in lines) and any("3456789" in ln for ln in lines)


def test_the_view_of_the_nfce_footer():
    res = build(NFCE)
    lines = view.lines(res.rows, res.profile)
    text = [ln for ln in lines if "CONSUMIDOR" in ln or "15/11/2026" in ln]
    assert len(text) == 2 and all(len(ln) == 32 for ln in text)
    assert [ln.find("CONSUMIDOR") for ln in text][0] == 13 and text[1].find("15/11/2026") == 13
    assert all(any(0x2800 < ord(ch) <= 0x28FF for ch in ln[:12]) for ln in text)  # the QR beside them, in braille


# --- data ---------------------------------------------------------------------------------------------------------


def test_colons_from_data_never_open_or_close_columns():
    src = ":::: {.columns}\n::: {.column}\n{{ d }}\n:::\n::: {.column}\nB\n:::\n::::\nend\n"
    res = build(src, fields={"d": Tainted(":::\n:::: {.columns}\n::: {.column}")})
    d, end = res.doc.blocks
    assert len(d.children) == 2 and d.closed and isinstance(end, Paragraph)
    assert "M105" not in codes(res) and any(":::" in ln for ln in view.lines(res.rows, res.profile))


def test_colons_from_data_as_markdown_never_close_the_documents_columns():
    src = ":::: {.columns}\n::: {.column}\n{{ d | markdown }}\n:::\n::: {.column}\nB\n:::\n::::\n"
    res = build(src, fields={"d": Tainted("hello\n:::\n::::\n::: {.column}\nX")})
    (d,) = res.doc.blocks
    assert len(d.children) == 2 and "M123" in codes(res)


@pytest.mark.parametrize("value", ["wrap=wrap", "{width=1ch}", ".columns"])
def test_settings_from_data_stay_text(value):
    res = build(":::: {.columns}\n::: {.column}\n{{ d }}\n:::\n::::\n", fields={"d": Tainted(value)})
    (d,) = res.doc.blocks
    (col,) = d.children
    assert isinstance(col.children[0], Paragraph) and not isinstance(col.children[0], Fence)


def test_a_stray_line_of_colons_after_columns_says_how_to_open_a_column():
    res = build("::: {.columns}\n::: {}\nA\n:::\n:::\nB\n:::\n")
    hints = [n.suggestion for n in res.nudges if n.code == "M101"]
    assert len(hints) == 1 and "::: {.column}" in hints[0]


def test_more_columns_than_letters_never_stand_past_the_paper():
    res = build(cols(*"abcdefghijklmnopqrst"))
    first, second = rows_of_columns(res)
    assert len(first.columns.columns) == 16 and len(second.columns.columns) == 4 and said(res, "L110")


def test_a_bare_line_of_colons_right_after_the_columns_open_says_how_to_open_a_column():
    res = build(":::: {.columns wrap=wrap}\n:::\nRua Exemplo\n:::\n::::\n")  # the study's other mistake
    assert any("before any column" in m for m in said(res, "M101"))
    assert any("to open a column write ::: {.column}" in n.suggestion for n in res.nudges)
