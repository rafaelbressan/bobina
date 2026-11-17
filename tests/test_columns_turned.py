"""Turned columns (:::: {.columns orientation=vertical}, docs/guides/layout-columns-turned.md): a label along the
roll, length= long and as tall as the paper is wide, printed turned clockwise like a turned table."""

import random

import pytest
from PIL import Image, ImageOps

from bobina import view
from bobina.engine import build
from bobina.model import Paragraph
from bobina.rows import BitmapRow
from bobina.templating import Tainted

W = 384  # mtp-ii-58: the label's height
CW = 12
MM72 = 575  # 72 mm at 203 dpi: the default length, 47 letters
EPSON = "---\nprofile: epson-tm-t20ii\n---\n"


def codes(res) -> list[str]:
    return [n.code for n in res.nudges]


def said(res, code: str) -> list[str]:
    return [n.message for n in res.nudges if n.code == code]


def labels(res) -> list[BitmapRow]:
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "columns"]


def spans(row: BitmapRow) -> list[tuple[int, int]]:
    """Each column's (first letter, letters) along the label."""
    return [(c.left, c.inner // CW) for c in row.columns.columns]


def ink(im, box=None):
    g = im.convert("L")
    return ImageOps.invert(g.crop(box) if box else g).getbbox()


def cols(*bodies: str, opts: str = "", each: tuple = ()) -> str:
    out = f":::: {{.columns orientation=vertical {opts}}}\n"
    for k, body in enumerate(bodies):
        out += f"::: {{.column {each[k] if k < len(each) else ''}}}\n{body}\n:::\n"
    return out + "::::\n"


def text(res) -> str:
    return "\n".join(view.lines(res.rows, res.profile))


# --- length and widths --------------------------------------------------------------------------------------------


def test_the_default_label_is_72_mm_long_and_as_tall_as_the_paper_is_wide():
    res = build(cols("left", "right"))
    (row,) = labels(res)
    assert row.image.size == (W, MM72)
    assert spans(row) == [(0, 23), (24, 23)]  # 47 letters along the roll, a letter between the columns
    assert [c for c in codes(res) if c != "P301"] == []


def test_widths_in_percent_share_the_length():
    (row,) = labels(build(cols("name", "price", each=("width=60%", "width=40%"))))
    assert spans(row) == [(0, 28), (29, 18)]  # 60% and 40% of the 46 letters the gap leaves


def test_letters_and_mm_widths_hold_along_the_roll_and_auto_takes_the_rest():
    (row,) = labels(build(cols("a", "b", "c", each=("width=10ch", "width=20mm"))))
    assert spans(row) == [(0, 10), (11, 13), (25, 22)]  # 20 mm: 160 dots, 13 letters; auto: 47 - 10 - 13 - 2


@pytest.mark.parametrize(
    "length, dots",
    [("40mm", 320), ("4cm", 320), ("4,5cm", 360), ("480", 480), ("480dots", 480), ("480px", 480)],
)
def test_length_in_mm_cm_and_dots(length, dots):
    res = build(cols("a", "b", opts=f"length={length}"))
    (row,) = labels(res)
    assert row.image.size == (W, dots) and "M101" not in codes(res)


@pytest.mark.parametrize("length", ["abc", "0", "5", "-3mm", "10in"])
def test_a_length_it_cannot_read_is_said_and_72_mm_used(length):
    res = build(cols("a", "b", opts=f"length={length}"))
    assert labels(res)[0].image.height == MM72 and any(f"length={length}" in m for m in said(res, "M101"))


def test_a_length_past_300_mm_is_said_and_cut_to_300():
    res = build(cols("a", opts="length=5000mm"))
    assert labels(res)[0].image.height == 2398 and any("300 mm used" in m for m in said(res, "M101"))


def test_a_length_in_capitals_is_said_and_read():
    res = build(cols("a", opts="length=40MM"))
    assert labels(res)[0].image.height == 320 and any("lowercase" in m for m in said(res, "M101"))


def test_length_auto_is_as_long_as_the_text_needs_on_one_line():
    res = build(cols("Arroz integral 5 kg", "R$ 21,90", opts="length=auto"))
    (row,) = labels(res)
    assert spans(row) == [(0, 19), (20, 8)] and row.image.height == 28 * CW
    assert any("Arroz integral 5 kg" in ln and "R$ 21,90" in ln for ln in view.lines(res.rows, res.profile))


def test_length_auto_with_shares_gives_each_share_what_its_content_needs():
    (row,) = labels(build(cols("Arroz integral 5 kg", "R$ 21,90", opts="length=auto", each=("width=60%", "width=40%"))))
    assert [w for _, w in spans(row)] == [19, 12]  # the shortest label in which 60% holds 19 letters


def test_length_auto_keeps_a_qr_at_its_size_and_fits_an_image_to_the_height(tmp_path):
    Image.new("1", (100, 300), 0).save(tmp_path / "bar.png")  # three times as tall as wide
    qr = "```qr\nhttps://example.com/p/4471\n```"
    (row,) = labels(build(cols(qr, "![](bar.png)", opts="length=auto"), base_dir=str(tmp_path)))
    (_, w_qr), (_, w_img) = spans(row)
    assert 9 <= w_qr <= 14  # the QR at its own size, not stretched along the label
    assert w_img == 10  # 120 dots wide: 360 tall; one letter more would pass the 384 of the label


# --- placing and turning ------------------------------------------------------------------------------------------


def _across(src: str) -> list[tuple[int, int]]:
    """Each column's ink across the paper (left, right) in the printed label."""
    (row,) = labels(build(src))
    out = []
    for c in row.columns.columns:
        y0 = c.left * CW
        box = ink(row.image, (0, y0, W, y0 + c.inner))
        out.append((box[0], box[2]))
    return out


def test_turned_clockwise_like_a_turned_table_the_top_on_the_right_the_first_column_first():
    res = build(cols("FIRST", "", "", each=("width=10ch",)))
    (row,) = labels(res)
    box = ink(row.image)
    assert box[3] <= 10 * CW  # the first column prints first: at the start of the label along the roll
    assert box[2] > W - 30  # its top line is at the paper's right edge
    assert "top on the right" in view.TURNED_COLUMNS[0]


def test_valign_places_each_column_across_the_height_as_read():
    tall = "one\ntwo\nthree"
    top = _across(cols(tall, "x"))
    middle = _across(cols(tall, "x", opts="valign=middle"))
    bottom = _across(cols(tall, "x", opts="valign=bottom"))
    assert top[1][1] > W - 20 and bottom[1][0] < 20  # top: the right edge; bottom: the left edge
    assert abs((middle[1][0] + middle[1][1]) / 2 - W / 2) <= 12 and abs((middle[0][0] + middle[0][1]) / 2 - W / 2) <= 12
    assert _across(cols(tall, "x", opts="valign=center")) == middle


def test_a_columns_valign_wins_over_the_columns():
    spots = _across(cols("a", "b", opts="valign=bottom", each=("valign=top",)))
    assert spots[0][1] > W - 20 and spots[1][0] < 20


def test_turned_columns_on_80_mm_are_72_mm_tall():
    res = build(EPSON + cols("Café", "R$ 9"))
    (row,) = labels(res)
    assert row.image.size == (576, MM72) and spans(row) == [(0, 23), (24, 23)]


# --- too tall for the label ---------------------------------------------------------------------------------------

LINES = "\n\n".join(f"line {i}" for i in range(14))  # 14 paragraphs: 576 dots, the label has 384


def test_nowrap_content_taller_than_the_label_goes_on_in_another_label_nothing_cut():
    res = build(cols(LINES, "short"))
    first, second = labels(res)
    assert first.image.size == second.image.size == (W, MM72)
    shown = text(res)
    assert all(f"line {i}" in shown for i in range(14)) and shown.count("short") == 1
    (note,) = said(res, "L112")
    assert "column 1 is taller than the label (576 of the 384 dots" in note and "1 more label" in note
    second_text = "\n".join(view.lines([second], res.profile))
    assert "line 13" in second_text and "line 0" not in second_text  # cut between paragraphs, in order


def test_a_block_taller_than_the_label_is_drawn_smaller_to_fit_it(tmp_path):
    Image.new("1", (100, 300), 0).save(tmp_path / "bar.png")
    res = build(cols("![](bar.png){width=60mm}", "beside"), base_dir=str(tmp_path))
    (row,) = labels(res)
    assert any("drawn smaller to fit it" in m for m in said(res, "L112"))
    box = ink(row.image, (0, 0, W, 23 * CW))
    assert box[2] - box[0] <= W  # the whole bar, across the paper


def test_wrap_moves_a_column_too_tall_beside_the_others_to_a_new_label_after():
    long = " ".join(["palavra12"] * 40)  # 20 lines in 23 letters, 10 in 47
    res = build(cols("price", long, opts="wrap=wrap"))
    first, second = labels(res)
    assert "price" in "".join(view.lines([first], res.profile)) and "palavra12" in "".join(
        view.lines([second], res.profile)
    )
    (note,) = said(res, "L110")
    assert "column 2 does not fit beside column 1" in note and "a new label, after this one" in note
    assert "L112" not in codes(res)


def test_wrap_reverse_puts_the_new_label_before():
    long = " ".join(["palavra12"] * 40)
    res = build(cols("price", long, opts="wrap=wrap-reverse"))
    first, _ = labels(res)
    assert "palavra12" in "".join(view.lines([first], res.profile)) and "before this one" in said(res, "L110")[0]


def test_wrap_moves_a_column_whose_widths_do_not_fit_the_length():
    res = build(cols("a", "b", opts="wrap=wrap length=40mm", each=("width=20ch", "width=20ch")))
    assert len(labels(res)) == 2 and "a new label" in said(res, "L110")[0]


def test_wrap_leaves_a_column_too_tall_even_alone_and_it_goes_on_in_another_label():
    res = build(cols("price", LINES, opts="wrap=wrap"))
    assert "L110" not in codes(res) and said(res, "L112") and len(labels(res)) == 2


# --- what is said -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("angle", ["90", "270", "-90"])
def test_rotate_90_on_columns_suggests_orientation_vertical(angle):
    res = build(cols("a", "b").replace("orientation=vertical ", f"rotate={angle} "))
    (note,) = [n for n in res.nudges if n.code == "L112"]
    assert note.severity == "note" and "orientation=vertical" in note.suggestion


@pytest.mark.parametrize("src", [cols("a", "b").replace("orientation=vertical ", "rotate=180 "), cols("a", "b")])
def test_no_rotate_hint_for_half_turns_or_turned_columns(src):
    assert "L112" not in codes(build(src))


def test_an_unknown_orientation_is_said_and_the_columns_stand():
    res = build(cols("a", "b").replace("vertical", "sideways"))
    assert "orientation=sideways" in said(res, "M101") and labels(res)[0].image.height < 100


def test_length_on_standing_columns_does_nothing_and_is_said():
    res = build(cols("a", "b").replace("orientation=vertical", "length=40mm"))
    assert any("length=40mm does nothing" in m for m in said(res, "M101"))


def test_columns_in_a_quote_stand_and_say_why():
    res = build("> " + cols("left", "right").replace("\n", "\n> "))
    (row,) = labels(res)
    assert not row.columns.turned and any("outside quotes and lists" in m for m in said(res, "M101"))


def test_turned_columns_get_the_untested_note():
    (p301,) = said(build(cols("a", "b")), "P301")
    assert "turned columns" in p301


# --- the terminal view --------------------------------------------------------------------------------------------


def test_the_view_shows_the_label_standing_under_a_mark_as_a_turned_table_does():
    res = build(cols("Café Torrado", "R$ 18,90", each=("width=60%",)))
    lines = view.lines(res.rows, res.profile)
    (mark,) = [i for i, ln in enumerate(lines) if "↻" in ln]
    assert "columns printed turned, top on the right" in lines[mark]
    ln = next(ln for ln in lines if "Café" in ln)
    assert ln.index("Café") == 0 and ln.index("R$") == 28  # the label as read: 47 letters, wider than the paper
    assert view.width(res.rows, res.profile) == 47


# --- never wider than the paper -----------------------------------------------------------------------------------


def test_never_wider_than_the_paper_and_columns_never_overlap():
    rnd = random.Random(644)
    widths = ["", "width=40%", "width=60%", "width=12ch", "width=30mm", "width=1ch"]
    bodies = ["word", "a longer line of words to wrap", "```qr\nhttps://example.com/x\n```", "# Big", "- a\n- b",
              LINES, "R$ 9 {size=3x}"]  # fmt: skip
    lengths = ["", "length=auto", "length=30mm", "length=10cm"]
    for profile in ("", EPSON):
        for _ in range(12):
            n = rnd.randint(1, 4)
            opts = " ".join([rnd.choice(["", "wrap=wrap", "wrap=wrap-reverse"]), rnd.choice(lengths),
                             rnd.choice(["", "valign=middle", "valign=bottom"])])  # fmt: skip
            src = profile + cols(*(rnd.choice(bodies) for _ in range(n)), opts=opts,
                                 each=tuple(rnd.choice(widths) for _ in range(n)))  # fmt: skip
            res = build(src)
            paper = res.profile.width_dots
            for r in labels(res):
                assert r.image.width == paper and r.columns.turned, src
                ends = [x + w for x, w in spans(r)]
                assert all(w >= 1 for _, w in spans(r)) and max(ends) * CW <= r.image.height, src
                assert all(e < x for e, (x, _) in zip(ends, spans(r)[1:], strict=False)), src  # side by side


# --- data ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["orientation=vertical", "{length=auto}", ":::\n::::\n::: {.column}"])
def test_settings_and_colons_from_data_never_turn_or_close_the_columns(value):
    src = ":::: {.columns}\n::: {.column}\n{{ d }}\n:::\n::::\nend\n"
    res = build(src, fields={"d": Tainted(value)})
    d, end = res.doc.blocks
    assert len(d.children) == 1 and isinstance(end, Paragraph)
    assert not labels(res)[0].columns.turned and "M105" not in codes(res)


def test_data_inside_turned_columns_stays_text():
    src = cols("{{ d }}", "B") + "end\n"
    res = build(src, fields={"d": Tainted(":::\n::::\n{.columns orientation=horizontal}")})
    d, end = res.doc.blocks
    assert len(d.children) == 2 and isinstance(end, Paragraph) and labels(res)[0].columns.turned
