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
def test_rotate_90_on_standing_columns_suggests_orientation_vertical_with_its_own_code(angle):
    res = build(cols("a", "b").replace("orientation=vertical ", f"rotate={angle} "))
    (note,) = [n for n in res.nudges if n.code == "L113"]
    assert note.severity == "note" and "orientation=vertical" in note.suggestion and "L112" not in codes(res)


@pytest.mark.parametrize("src", [cols("a", "b").replace("orientation=vertical ", "rotate=180 "), cols("a", "b")])
def test_no_rotate_hint_for_half_turns_or_turned_columns(src):
    assert "L113" not in codes(build(src))


@pytest.mark.parametrize("extra, word", [("rotate=90", "rotate=90"), ("rotate=180", "rotate=180"), (".flip", ".flip")])
def test_rotate_and_flip_on_turned_columns_are_ignored_and_said(extra, word):
    plain = build(cols("left", "right"))
    res = build(cols("left", "right", opts=extra))
    (row,) = labels(res)
    assert row.image.tobytes() == labels(plain)[0].image.tobytes()  # the label is not turned again
    assert any(f"already turns the label: {word} ignored" in m for m in said(res, "M101"))
    assert text(res) == text(plain) and "L113" not in codes(res)


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


# --- review fixes -------------------------------------------------------------------------------------------------


def _code_rows(res, kind: str) -> list[BitmapRow]:
    return [r for lab in labels(res) for c in lab.columns.columns for r in c.rows
            if isinstance(r, BitmapRow) and r.kind == kind]  # fmt: skip


def test_a_qr_too_tall_for_the_label_gets_the_largest_whole_module_that_fits():
    from bobina import imaging

    data = "https://example.com/p/4471"
    res = build(cols(f"```qr {{width=full}}\n{data}\n```", opts="length=200mm"))
    (qr,) = _code_rows(res, "qr")
    box = ink(qr.image)
    side = len(imaging.qr_matrix(data, "M", 0))
    assert box[3] - box[1] <= W and (box[3] - box[1]) % side == 0  # whole modules, not resampled
    assert (box[3] - box[1]) // side == (W // (side + 4))  # the largest module whose code (and quiet zone) fits
    assert "L112" not in codes(res) and "Q101" not in codes(res)


def test_a_data_matrix_too_tall_for_the_label_gets_a_smaller_whole_module():
    res = build(cols("```datamatrix {width=full}\nLOTE-4471-2026\n```", opts="length=200mm"))
    (dm,) = _code_rows(res, "datamatrix")
    assert ink(dm.image)[3] - ink(dm.image)[1] <= W and "L112" not in codes(res)


def test_a_barcode_too_tall_for_the_label_gets_shorter_bars_its_module_kept():
    from bobina.rows import BarcodeRow

    res = build(cols("```barcode {type=code128 height=600}\nPED-1042\n```"))
    (bar,) = [r for c in labels(res)[0].columns.columns for r in c.rows if isinstance(r, BarcodeRow)]
    assert bar.height < 600 and bar.module == 2 and "L112" not in codes(res) and "Q108" not in codes(res)


def test_a_barcode_squeezed_below_the_shortest_bars_is_said():
    from bobina.rows import BarcodeRow

    inner = cols("```barcode {type=code128 height=600}\nAB\n```").replace("\n", "\n")
    res = build(":::::: {.columns}\n::::: {.column width=5ch}\n" + inner + ":::::\n::: {}\nx\n:::\n::::::\n")
    bars = [r for row in [r for r in res.rows if isinstance(r, BitmapRow) and r.columns]
            for c in row.columns.columns for lab in c.rows if isinstance(lab, BitmapRow) and lab.columns
            for cc in lab.columns.columns for r in cc.rows if isinstance(r, BarcodeRow)]  # fmt: skip
    assert bars and bars[0].height < 40 and any("too short to scan" in m for m in said(res, "Q108"))


@pytest.mark.parametrize("shares", [("50%", "50%"), ("40%", "40%"), ("50%", "50%", "50%")])
def test_length_auto_holds_every_share_side_by_side(shares):
    bodies = [chr(ord("a") + k) for k in range(len(shares))]
    res = build(cols(*bodies, opts="length=auto", each=tuple(f"width={w}" for w in shares)))
    (row,) = labels(res)
    assert len(row.columns.columns) == len(shares) and "L110" not in codes(res)
    assert all(w >= 1 for _, w in spans(row))


def test_a_box_a_little_too_tall_is_drawn_smaller_but_never_below_70_percent():
    box = "::: {.box}\n" + "\n".join(f"line {i}" for i in range(13)) + "\n:::"  # ~420 dots
    res = build(cols(box, "x"))
    (note,) = said(res, "L112")
    pct = int(note.split("drawn at ")[1].split("%")[0])
    assert 70 <= pct < 100 and len(labels(res)) == 1


def test_text_too_tall_even_at_70_percent_goes_on_cut_at_a_blank_line_as_a_note():
    turned = "\n".join(f"line {i}" for i in range(30)) + " {rotate=180}"  # a turned block: 30 lines, ~900 dots
    res = build(cols(turned, "x"))
    (n,) = [n for n in res.nudges if n.code in ("L112", "L114")]
    assert n.code == "L112" and n.severity == "note" and "between its lines" in n.message and "70%" in n.message
    assert len(labels(res)) >= 2


def test_a_box_too_tall_even_at_70_percent_goes_on_cut_between_its_lines_its_side_lines_aside():
    box = "::: {.box}\n" + "\n".join(f"line {i}" for i in range(40)) + "\n:::"
    res = build(cols(box, "x"))
    (n,) = [n for n in res.nudges if n.code in ("L112", "L114")]
    assert n.code == "L112" and "between its lines" in n.message and n.message.startswith("column 1: ")


GRID = "| a | b |\n|---|---|\n" + "\n".join(f"| {i} | item {i} |" for i in range(40)) + "\n{style=grid}"


def test_a_box_with_no_blank_line_goes_on_cut_across_it_as_l114_one_problem():
    box = f"::: {{.box}}\n{GRID}\n:::"  # a grid's lines run through every row
    res = build(cols(box, "x"))
    (n,) = [n for n in res.nudges if n.code in ("L112", "L114")]  # one problem for the overflow, not two
    assert n.code == "L114" and n.severity == "warning" and n.message.startswith("column 1: ")
    assert "cut across its lines" in n.message and "read the labels together" in n.suggestion
    first = labels(res)[0]
    assert ink(first.image, (0, 0, W, 23 * CW))[2] - ink(first.image, (0, 0, W, 23 * CW))[0] <= W


def test_a_default_gap_with_no_room_is_said_as_the_default_never_none():
    from bobina.layout import Layout
    from bobina.model import Attrs
    from bobina.nudges import Nudges

    res = build("x\n")
    lay = Layout(res.profile, res.doc, None, Nudges())
    lay.said_widths([None, None, None], 4, 1, Attrs(), 1, "row")
    (msg,) = [n.message for n in lay.n]
    assert "the gap (1 letter, the default)" in msg and "None" not in msg


def standing(*bodies: str, opts: str = "", each: tuple = ()) -> str:
    return cols(*bodies, opts=opts, each=each).replace(" orientation=vertical", "", 1)


def test_wrap_judges_with_the_gap_asked_and_moves_a_column():
    res = build(standing("a", "b", "c", opts="wrap=wrap gap=15ch"))
    assert len([r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "columns"]) == 2
    assert said(res, "L110") and not any("no room for it" in m for m in said(res, "M101"))


def test_length_auto_past_300_mm_blames_the_content():
    line = "x" * 150
    res = build(cols(line, line, opts="length=auto"))
    (msg,) = [m for m in said(res, "M101") if "300 mm" in m]
    assert "the columns' content needs 301 letters, more than the 300 mm" in msg and "width" not in msg


def test_standing_wrap_never_draws_its_trials(monkeypatch):
    from bobina.layout import Layout

    calls = []
    real = Layout.laid_column

    def spy(self, col, letters, tall=None, pictures=True):
        calls.append(pictures)
        return real(self, col, letters, tall, pictures)

    monkeypatch.setattr(Layout, "laid_column", spy)
    build(standing("short", "Pneumoultramicroscopico", opts="wrap=wrap", each=("width=60%",)))
    assert calls.count(True) == 2 and calls.count(False) >= 2  # the trials are laid out, only what prints is drawn
    assert not hasattr(Layout, "column_at")


def test_the_lengths_in_dots_said_are_the_ones_printed():
    from pathlib import Path

    from bobina.layout import LENGTH_HINT

    guide = (Path(__file__).resolve().parents[1] / "docs" / "guides" / "layout-columns-turned.md").read_text()
    assert "575" in LENGTH_HINT and "`575` dots" in guide and "576" not in LENGTH_HINT + guide
    assert labels(build(cols("a", opts="length=575")))[0].image.height == MM72


# --- second review ------------------------------------------------------------------------------------------------


def _all_rows(rows) -> list:
    """Every row, the ones inside columns and boxes too."""
    out = []
    for r in rows:
        out.append(r)
        if isinstance(r, BitmapRow) and r.columns:
            out += _all_rows([x for c in r.columns.columns for x in c.rows])
        if isinstance(r, BitmapRow) and r.box:
            out += _all_rows(r.box.rows)
    return out


def _whole_modules(res, data: str) -> list[int]:
    """The height in modules of each QR drawn for `data`, asserting whole modules."""
    from bobina import imaging

    side = len(imaging.qr_matrix(data, "M", 0))
    out = []
    for r in _all_rows(res.rows):
        if isinstance(r, BitmapRow) and r.kind == "qr":
            box = ink(r.image)
            assert (box[3] - box[1]) % side == 0 and box[3] - box[1] <= W
            out.append((box[3] - box[1]) // side)
    return out


QR_DATA = "https://example.com/p/4471"


def test_standing_columns_inside_a_turned_column_fit_their_codes_to_the_label():
    inner = standing(f"```qr {{width=full}}\n{QR_DATA}\n```", "text").replace("::::", ":::::")
    res = build(cols(inner, opts="length=200mm").replace("::: {.column ", ":::::: {.column ", 1))
    assert _whole_modules(res, QR_DATA) and not {"L112", "L114"} & set(codes(res))


def test_a_qr_in_a_box_in_a_turned_column_fits_with_the_frame_never_resampled():
    res = build(cols(f'::: {{.box title="SCAN"}}\n```qr {{width=full}}\n{QR_DATA}\n```\n:::', opts="length=200mm"))
    (module,) = _whole_modules(res, QR_DATA)
    boxes = [r for r in _all_rows(res.rows) if isinstance(r, BitmapRow) and r.kind == "box"]
    assert module >= 2 and ink(boxes[0].image)[3] - ink(boxes[0].image)[1] <= W
    assert not {"L112", "L114"} & set(codes(res))


def test_a_block_holding_a_code_is_never_drawn_smaller():
    lines = "\n".join(f"line {i}" for i in range(12))
    res = build(cols(f"::: {{.box}}\n```qr\n{QR_DATA}\n```\n{lines}\n:::", "x"))
    assert not any("drawn at" in m for m in said(res, "L112") + said(res, "L114"))
    from bobina import imaging

    units = len(imaging.qr_matrix(QR_DATA, "M", 0)) + 4  # the QR picture: its modules and quiet zone
    spans = [sp for r in _all_rows(res.rows) if isinstance(r, BitmapRow) and r.kind == "box" for sp in r.code_spans]
    assert len(labels(res)) >= 2 and spans  # it goes on in another label
    assert all((b - a) % units == 0 for a, b, _ in spans) and not said(res, "Q101")  # whole, at its size, never cut


def test_a_code_cut_across_labels_says_it_will_not_scan():
    res = build(cols("```barcode {type=code128 orientation=vertical}\nPED-1042-2026-11-17-ABCDEFGH\n```", "x"))
    (n,) = [n for n in res.nudges if n.code in ("Q108", "L112", "L114")]
    assert n.code == "Q108" and n.severity == "warning" and "will not scan" in n.message
    assert "length=" in n.suggestion and "nothing is lost" not in n.message


def test_percent_widths_over_100_with_length_auto_blame_the_widths():
    res = build(cols("a", "b", "c", opts="length=auto", each=("width=50%", "width=50%", "width=50%")))
    (msg,) = [m for m in said(res, "M101") if "narrowed" in m]
    assert "% widths add up to 150%" in msg and "content needs" not in msg


@pytest.mark.parametrize("turn", ["", "orientation=vertical"])
def test_a_gap_that_moves_a_column_is_blamed_not_the_widths(turn):
    make = cols if turn else standing
    res = build(make("a", "b", "c", opts="wrap=wrap gap=25ch"))
    (n,) = [n for n in res.nudges if n.code == "L110"]
    assert "the gap of 25 letters between 3 columns leaves" in n.message and "widths ask" not in n.message
    assert "a smaller gap=" in n.suggestion


def test_a_data_matrix_stepped_down_says_one_q101_for_its_last_module():
    inner = cols("```datamatrix {width=full}\nLOTE-4471-2026-11-17\n```", opts="length=200mm")
    res = build(":::::: {.columns}\n::::: {.column width=6ch}\n" + inner + ":::::\n::: {}\nx\n:::\n::::::\n")
    q = said(res, "Q101")
    assert len(q) == 1 and "datamatrix module" in q[0]


def test_trials_are_split_and_the_barcode_imports_nothing_locally():
    import inspect

    from bobina.layout import Layout

    assert hasattr(Layout, "column_squeezed") and hasattr(Layout, "column_height")
    assert not hasattr(Layout, "column_probe") and "import preview" not in inspect.getsource(Layout.barcode)


# --- third review -------------------------------------------------------------------------------------------------


def test_a_picture_drawn_smaller_and_a_column_spilling_are_both_said(tmp_path):
    Image.new("1", (100, 900), 0).save(tmp_path / "bar.png")
    paragraphs = "\n\n".join(f"line {i}" for i in range(30))
    res = build(cols("![](bar.png){width=100}\n\n" + paragraphs, "x"), base_dir=str(tmp_path))
    notes = said(res, "L112")
    assert any("a picture" in m and "drawn smaller" in m for m in notes)
    assert any(m.startswith("column 1 is taller than the label") for m in notes)


def test_turned_pictures_keep_their_codes_where_they_go():
    from bobina.layout import _turned_spans

    spans = ((10, 40, "qr"),)
    assert _turned_spans(spans, 100, 0) == spans and _turned_spans(spans, 100, 180) == ((60, 90, "qr"),)
    assert _turned_spans(spans, 300, 90) == _turned_spans(spans, 300, 270) == ((0, 300, "qr"),)


def test_a_small_qr_in_a_turned_block_away_from_the_cut_is_never_said_cut():
    lines = "\n".join(f"line {i}" for i in range(30))
    res = build(cols(f"::: {{rotate=180}}\n```qr\n{QR_DATA}\n```\n\n{lines}\n:::", "x"))
    rotated = [r for r in _all_rows(res.rows) if isinstance(r, BitmapRow) and r.kind == "rotated"]
    assert "Q101" not in codes(res) and len(labels(res)) >= 2
    assert not rotated or all(b - a < 300 for r in rotated for a, b, _ in r.code_spans)  # the QR, not the block


def test_a_cut_at_a_codes_edge_is_clean():
    qrs = "\n\n".join(f"```qr\n{QR_DATA}/{i}\n```" for i in range(3))  # grey everywhere but the codes' edges
    res = build(cols(f"::: {{.box .shade}}\n{qrs}\n:::", "x"))
    found = [n for n in res.nudges if n.code in ("L112", "L114", "Q101")]
    assert found and {n.code for n in found} == {"L112"}


def test_a_code_cut_counts_the_labels_it_is_on_and_a_cut_through_text_is_said_too():
    barcode = "```barcode {type=code128 orientation=vertical}\nPED-1042-2026-11-17-ABCDEFGH\n```"
    res = build(cols(f"::: {{.box}}\n{GRID}\n\n{barcode}\n:::", "x"))
    (q,) = said(res, "Q108")
    on = int(q.split("cut across ")[1].split(" ")[0])
    assert 2 <= on < len(labels(res)) and said(res, "L114")  # both facts, each said once


@pytest.mark.parametrize(
    "box", ['.box title="SCAN"', '.box title="A LONG TITLE THAT WRAPS ON TWO LINES OR MORE" title-style=band']
)
def test_a_qr_in_any_box_fits_with_what_its_title_takes(box):
    res = build(cols(f"::: {{{box}}}\n```qr {{width=full}}\n{QR_DATA}\n```\n:::", opts="length=200mm"))
    (module,) = _whole_modules(res, QR_DATA)
    boxed = [r for r in _all_rows(res.rows) if isinstance(r, BitmapRow) and r.kind == "box"]
    assert module >= 2 and ink(boxed[0].image)[3] - ink(boxed[0].image)[1] <= W
    assert not {"L112", "L114", "Q101"} & set(codes(res))


def test_an_inside_title_takes_nothing_off_and_the_box_goes_on_never_through_its_code():
    res = build(cols(f'::: {{.box title="SCAN" title-style=inside}}\n```qr {{width=full}}\n{QR_DATA}\n```\n:::',
                     opts="length=200mm"))  # fmt: skip
    from bobina import imaging

    units = len(imaging.qr_matrix(QR_DATA, "M", 0)) + 4  # the QR picture: its modules and quiet zone
    spans = [sp for r in _all_rows(res.rows) if isinstance(r, BitmapRow) for sp in r.code_spans if r.kind == "box"]
    assert spans and all((b - a) % units == 0 for a, b, _ in spans) and "Q101" not in codes(res)


def _code_heights(monkeypatch, src: str) -> list:
    """The height each QR was laid out to fit (Layout.tall_max as _qr_code saw it)."""
    from bobina.layout import Layout

    seen, real = [], Layout._qr_code
    monkeypatch.setattr(Layout, "_qr_code", lambda self, *a, **k: seen.append(self.tall_max) or real(self, *a, **k))
    build(src)
    return seen


def test_a_box_turned_90_does_not_take_its_frame_off_the_codes_height(monkeypatch):
    qr = f"```qr\n{QR_DATA}\n```"
    assert set(_code_heights(monkeypatch, cols(f"::: {{.box rotate=90}}\n{qr}\n:::"))) == {W}
    assert all(h < W for h in _code_heights(monkeypatch, cols(f"::: {{.box rotate=180}}\n{qr}\n:::")))


def test_a_turned_block_draws_its_rows_once(monkeypatch):
    from bobina import layout

    calls = []
    real = layout.preview.row_image
    monkeypatch.setattr(layout.preview, "row_image", lambda r, *a: calls.append(r) or real(r, *a))
    res = build("one\ntwo\nthree {rotate=90}\n")
    rotated = [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "rotated"]
    assert rotated and len(calls) == len(set(map(id, calls)))  # no row drawn twice


def test_widths_and_a_gap_that_move_a_column_suggest_both():
    res = build(standing("a", "b", opts="wrap=wrap gap=3ch", each=("width=15ch", "width=15ch")))
    (n,) = [n for n in res.nudges if n.code == "L110"]
    assert "the widths and the gap of 3 letters ask for 33 of the 32" in n.message
    assert "smaller widths or a smaller gap= keep them on one row" in n.suggestion
