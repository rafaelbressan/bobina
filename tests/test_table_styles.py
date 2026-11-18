"""Table styles (style= on the table's {…} line) and tables drawn in a raster font (font=, size=). plain is the
table as it always printed; receipt and lines stay native text with dividers; grid, header-invert and zebra are
drawn. A font draws the whole table in it, a column as wide as the font's "0". Checked on the rows and the dots."""

from pathlib import Path

import pytest

from bobina import imaging
from bobina.engine import build
from bobina.rows import BitmapRow, TextRow

STYLES = ("plain", "receipt", "lines", "grid", "header-invert", "zebra")
BILL = "| Item | Qty | Price |\n|---|--:|--:|\n| Espresso | 2 | 9,00 |\n| Cheese bread | 1 | 39,00 |\n" \
       "| Pie | 1 | 28,00 |\n| Water | 3 | 12,00 |\n"  # fmt: skip
TOTALS = "| | |\n|---|--:|\n| SUBTOTAL | 88,00 |\n| TOTAL | 96,80 |\n"


def styled(table: str, attrs: str, **kw):
    return build(table + "{" + attrs + "}\n", **kw)


def codes(res) -> list[str]:
    return [n.code for n in res.nudges]


def texts(res) -> list[str]:
    return ["".join(c.ch for c in r.cells).strip() for r in res.rows if isinstance(r, TextRow)]


def dividers(res) -> list:
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "divider"]


def drawn(res) -> list:
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind in ("text", "band")]


def ink(im) -> int:
    return sum(im.convert("L").histogram()[:128])


def kind_of(div) -> str:
    """solid, dashed or dotted: from the dots of a divider's stroke row."""
    im = div.image.convert("L")
    y = next(y for y in range(im.height) if any(im.getpixel((x, y)) < 128 for x in range(im.width)))
    row = [im.getpixel((x, y)) < 128 for x in range(im.width)]
    share = sum(row) / len(row)
    return "solid" if share > 0.95 else "dashed" if share > 0.5 else "dotted"


# --- plain is the table as it always was ----------------------------------------------------------------------------


@pytest.mark.parametrize("table", [BILL, TOTALS])
def test_plain_is_the_default_and_prints_as_before(table):
    assert build(table).image.tobytes() == styled(table, "style=plain").image.tobytes()
    assert not codes(styled(table, "style=plain"))


# --- receipt, lines: native text and dividers -----------------------------------------------------------------------


def test_receipt_puts_a_dashed_rule_above_and_below_titles_that_are_not_bold():
    res = styled(BILL, "style=receipt")
    first, title, under = res.rows[1:4]
    assert isinstance(first, BitmapRow) and kind_of(first) == "dashed"
    assert isinstance(title, TextRow) and title.native and not any(c.bold for c in title.cells)
    assert isinstance(under, BitmapRow) and kind_of(under) == "dashed"
    assert texts(res) == texts(build(BILL))  # the body as plain prints it
    assert not drawn(res) and not codes(res)


def test_bold_written_in_a_receipt_title_stays_bold():
    res = styled("| **Item** | Qty |\n|---|--:|\n| a | 1 |\n", "style=receipt")
    title = next(r for r in res.rows if isinstance(r, TextRow))
    assert [c.bold for c in title.cells if c.ch != " "] == [True] * 4 + [False] * 3


def test_lines_draws_a_dotted_line_between_rows_but_not_inside_a_wrapped_row():
    long = "| Item | Qty |\n|---|--:|\n| " + "word " * 12 + "| 1 |\n| b | 2 |\n| c | 3 |\n"
    res = styled(long, "style=lines")
    kinds = [kind_of(d) for d in dividers(res)]
    assert kinds == ["solid", "dotted", "dotted"]  # the title rule, then one between each two rows
    assert sum(1 for t in texts(res) if t.startswith("word")) > 1  # the first row wrapped: no line inside it
    assert not drawn(res)


# --- grid --------------------------------------------------------------------------------------------------------


def full_columns(im) -> list[int]:
    """x of the columns of dots inked from the top of the image to its bottom."""
    g = im.convert("L")
    return [x for x in range(g.width) if all(g.getpixel((x, y)) < 128 for y in range(g.height))]


def test_grid_draws_its_lines_in_the_space_between_columns_and_a_border():
    res = styled("| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |\n", "style=grid .compact")
    pieces = drawn(res)
    assert len(pieces) == 3 and not [r for r in res.rows if isinstance(r, TextRow)]  # top border, titles, a row
    xs = full_columns(pieces[1].image)
    runs = [[xs[0]]]
    for x in xs[1:]:
        runs[-1].append(x) if x == runs[-1][-1] + 1 else runs.append([x])
    assert len(runs) == 4 and all(len(r) >= 2 for r in runs)  # 2 borders, 2 lines between: B101, 2 dots or more
    # half a column of room, then 1 column each, 1 column of space between them (12 dots a column)
    assert [r[0] for r in runs] == [0, 6 + 12 + 5, 6 + 36 + 5, 6 + 60 + 6 - 2]


def test_grid_keeps_every_text_column_of_a_table_that_fits():
    """The lines between the columns go in the column of space plain leaves there; only the border takes room."""
    row = " | ".join(["abcdef"] * 4)
    table = f"| {row} |\n|---|---|---|---|\n| {row} |\n"  # 4 x 6 + 3 spaces = 27 of 32 columns
    assert "L101" not in codes(styled(table, "style=grid"))
    assert [ln.split() for ln in texts(build(table))] == [["abcdef"] * 4] * 2


def test_a_grid_row_holds_all_its_wrapped_lines_between_two_rules():
    long = "| Item | Qty |\n|---|--:|\n| " + "word " * 12 + "| 1 |\n"
    res = styled(long, "style=grid")
    body = drawn(res)[-1]
    assert len(body.text_rows) > 1  # the wrapped lines, in one piece with the rule under it


# --- header-invert ------------------------------------------------------------------------------------------------


def test_header_invert_prints_the_titles_on_a_black_band_and_the_body_plain():
    res = styled(BILL, "style=header-invert")
    band = drawn(res)
    assert len(band) == 1 and ink(band[0].image) > band[0].image.width * band[0].image.height * 0.6
    assert "Item" in "".join(c.ch for c in band[0].text_rows[0].cells)
    assert not dividers(res)
    assert texts(res) == texts(build(BILL))[1:]  # every body line native, as plain prints it
    assert codes(res) == ["P301"]  # the printer font's titles are bold and 24 dots: no F204, no F206; drawn a
    # dot taller, not tested on paper yet


# --- zebra --------------------------------------------------------------------------------------------------------


def test_zebra_shades_every_other_body_row():
    res = styled(BILL, "style=zebra")
    shaded = drawn(res)
    assert [("".join(c.ch for c in r.text_rows[0].cells)).split()[0] for r in shaded] == ["Cheese", "Water"]
    assert [t.split() for t in texts(res)[1:]] == [["Espresso", "2", "9,00"], ["Pie", "1", "28,00"]]  # native
    assert "P301" not in codes(res)  # tested on paper (MTP-II, 16/11)
    assert not any(isinstance(r, BitmapRow) and r.untested for r in styled("| a |\n|---|\n| 1 |\n", "style=zebra").rows)


def test_an_untested_drawing_still_says_p301(monkeypatch):
    """The P301 path for what a row draws stays: a feature marked untested again gets the note."""
    from bobina import features

    monkeypatch.setitem(features.FEATURES["zebra"], "tested_on_paper", False)
    note = next(n for n in styled(BILL, "style=zebra").nudges if n.code == "P301")
    assert "zebra" in note.message
    assert "P301" not in codes(build(BILL))


def test_the_shade_is_sparse_square_dots_away_from_the_letters():
    from PIL import Image

    im = imaging.shade(Image.new("1", (96, 48), 1), (0, 0, 96, 48))
    share = ink(im) / (96 * 48)
    assert 0.05 < share < 0.25  # a light grey
    px = im.convert("L").load()
    for y in range(48):  # never a lone dot (1-dot checkerboards smear on the MTP-II): each dot has a neighbour
        for x in range(96):
            if px[x, y] < 128:
                assert any(0 <= x + dx < 96 and 0 <= y + dy < 48 and px[x + dx, y + dy] < 128
                           for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))  # fmt: skip
    res = styled(BILL, "style=zebra")
    row = drawn(res)[0].image.convert("L")
    plain = next(r for r in build(BILL).rows if isinstance(r, TextRow) and "Cheese" in "".join(c.ch for c in r.cells))
    from bobina.emulator import Emulator
    from bobina.profile import load

    letters = Emulator(load("mtp-ii-58")).render_row(plain, 384).convert("L")
    halo_x, halo_y = imaging.SHADE_HALO
    for y in range(letters.height):  # no dot of the shade within the halo of a letter
        for x in range(letters.width):
            if row.getpixel((x, y)) < 128 and letters.getpixel((x, y)) >= 128:
                near = [(a, b) for a in range(max(0, x - halo_x), min(384, x + halo_x + 1))
                        for b in range(max(0, y - halo_y), min(letters.height, y + halo_y + 1))]  # fmt: skip
                assert all(letters.getpixel(p) >= 128 for p in near), (x, y)


# --- headerless tables and turned tables, in every style ------------------------------------------------------------


@pytest.mark.parametrize("style", STYLES)
def test_a_table_without_titles_gets_no_title_band_or_rule(style):
    res = styled(TOTALS, f"style={style}")
    assert [kind_of(d) for d in dividers(res)] == (["dotted"] if style == "lines" else [])  # between rows only
    words = texts(res) + ["".join(c.ch for c in r.cells) for p in drawn(res) for r in p.text_rows]
    assert {w.split()[0] for w in words if w.strip()} == {"SUBTOTAL", "TOTAL"}
    if style == "header-invert":
        assert not drawn(res)
    if style == "grid":
        assert len(drawn(res)) == 3  # the top border and the two rows


WIDE = "| " + " | ".join(f"Col{i}" for i in range(8)) + " |\n|" + "---|" * 8 + "\n" + \
       "".join("| " + " | ".join(f"v{r}{c}" for c in range(8)) + " |\n" for r in range(4))  # fmt: skip


@pytest.mark.parametrize("style", STYLES)
def test_a_turned_table_is_drawn_in_its_style(style):
    res = styled(WIDE, f"style={style} orientation=vertical")
    turned = [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "table"]
    assert len(turned) == 1 and len(turned[0].text_rows) == 5
    plain = next(r for r in styled(WIDE, "orientation=vertical").rows if isinstance(r, BitmapRow))
    assert (turned[0].image.tobytes() == plain.image.tobytes()) is (style == "plain")
    if style == "grid":  # turned, the rules between rows run across the paper: full rows of ink
        g = turned[0].image.convert("L")
        assert sum(1 for y in range(g.height) if ink(g.crop((0, y, g.width, y + 1))) > 0.3 * g.width) >= 16


def test_a_turned_table_without_titles_keeps_its_style_and_no_titles():
    res = styled("| | |\n|---|---|\n| a | 1 |\n| b | 2 |\n", "style=zebra orientation=vertical")
    turned = next(r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "table")
    assert [("".join(c.ch for c in r.cells)).split()[0] for r in turned.text_rows] == ["a", "b"]
    assert turned.untested == ("zebra",)


# --- wrong values ------------------------------------------------------------------------------------------------


def test_an_unknown_style_is_said_with_the_six_names_and_prints_plain():
    res = styled(BILL, "style=recibo")
    note = next(n for n in res.nudges if n.code == "M101")
    assert note.message == "style=recibo: unknown style; plain, receipt, lines, grid, header-invert, zebra"
    assert res.image.tobytes() == build(BILL).image.tobytes()


def test_an_uppercase_style_says_values_are_lowercase_and_prints_plain():
    res = styled(BILL, "style=RECEIPT")
    note = next(n for n in res.nudges if n.code == "M101")
    assert "lowercase" in note.message and "style=receipt" in note.suggestion
    assert res.image.tobytes() == build(BILL).image.tobytes()


def test_style_is_a_key_of_tables_only():
    res = build("Hello {style=receipt}\n")
    assert any(n.code == "M101" and "style=" in n.message for n in res.nudges)
    assert "M101" not in codes(styled(BILL, "style=lines .compact"))
    assert "M101" not in codes(build(BILL + "\n{style=grid}\n"))  # after a blank line too


# --- font= and size= ------------------------------------------------------------------------------------------------

MARKET = (
    "| IT | CÓD | DESCRIÇÃO | QTD | UN | UNIT | TOTAL |\n|---|--:|---|--:|---|--:|--:|\n"
    "| 001 | 7891 | ARROZ BRANCO 5KG | 1 | un | 24,90 | 24,90 |\n"
    "| 003 | 7369 | BANANA PRATA ORG | 1.635 | kg | 9,99 | 16,33 |\n"
)


def test_a_table_in_a_font_is_drawn_and_seven_columns_fit_on_58_mm():
    res = styled(MARKET, "font=Terminus size=16px", profile_name="mtp-ii-58")
    assert not [r for r in res.rows if isinstance(r, TextRow)]
    assert len(drawn(res)) == 3 and len(dividers(res)) == 1  # one line each, and the title rule
    assert not codes(res)  # no word cut, not turned, Terminus at 16px is above its tested minimum
    plain = build(MARKET, profile_name="mtp-ii-58")
    assert "L106" in codes(plain) or "L101" in codes(plain)  # in the printer font it does not fit


@pytest.mark.parametrize("profile,fit", [("mtp-ii-58", 48), ("epson-tm-t20ii", 72)])
def test_a_column_in_a_font_is_as_wide_as_its_zero(profile, fit):
    def cut(n):
        res = styled(f"| a |\n|---|\n| {'0' * n} |\n", "font=Terminus size=16px", profile_name=profile)
        return "L101" in codes(res)

    assert not cut(fit) and cut(fit + 1)


def test_a_proportional_font_lines_its_columns_up_by_the_dot():
    table = "| A | B |\n|---|---|\n| iiii | Xa |\n| WWWW | Xb |\n| mm | Xc |\n"
    res = styled(table, 'font="Atkinson Hyperlegible" size=20px .compact')
    starts = []
    for r in drawn(res)[1:]:
        g = r.image.convert("L")
        inked = [x for x in range(g.width) if any(g.getpixel((x, y)) < 128 for y in range(g.height))]
        starts.append(next(b for a, b in zip(inked, inked[1:], strict=False) if b - a > 8))  # after the gap
    assert len(set(starts)) == 1 and starts[0] > 0


def test_wrapping_alignment_and_cell_styles_work_in_a_font():
    table = "| Item | Price |\n|---|--:|\n| a long description that wraps | **9,00** |\n| *it* ~~st~~ | 1,00 |\n"
    res = styled(table, "font=Terminus size=16px")
    lines = ["".join(c.ch for c in r.text_rows[0].cells) for r in drawn(res)]
    assert len(lines) == 3 and lines[1].startswith("a long description")  # the view: the paper's 32 columns
    price = drawn(res)[1].image.convert("L")  # --: : the price at the right edge of the paper
    assert max(x for x in range(price.width) if any(price.getpixel((x, y)) < 128 for y in range(price.height))) > 370
    narrow = styled(table, "font=Terminus size=16px .compact")
    assert len(drawn(narrow)) == 3
    squeezed = styled(table.replace("Price", "Price of the whole thing written here"), "font=Terminus size=20px")
    assert len(drawn(squeezed)) > 3  # wrapped into more lines
    bold = styled("| a |\n|---|\n| **XX** |\n", "font=Terminus size=16px .compact")
    thin = styled("| a |\n|---|\n| XX |\n", "font=Terminus size=16px .compact")
    assert ink(drawn(bold)[-1].image) > ink(drawn(thin)[-1].image)


def test_a_table_without_titles_in_a_font_and_turned_in_a_font():
    res = styled(TOTALS, "font=Terminus size=16px")
    assert len(drawn(res)) == 2 and not dividers(res)
    turned = styled(WIDE, "font=Terminus size=16px orientation=vertical")
    table = next(r for r in turned.rows if isinstance(r, BitmapRow) and r.kind == "table")
    native = next(r for r in styled(WIDE, "orientation=vertical").rows if isinstance(r, BitmapRow))
    assert table.image.height < native.image.height  # smaller letters: a shorter strip of paper


@pytest.mark.parametrize("style", STYLES)
def test_every_style_works_in_a_font(style):
    res = styled(BILL, f"style={style} font=Terminus size=20px")
    assert not [r for r in res.rows if isinstance(r, TextRow)]
    assert not codes(res)


def test_size_alone_draws_terminus_or_the_printer_font_look_at_its_multiples():
    small = styled(BILL, "size=16px")
    assert drawn(small) and styled(BILL, "font=Terminus size=16px").image.tobytes() == small.image.tobytes()
    big = styled(BILL, "size=2x")
    assert big.image.tobytes() == styled(BILL, "font=Spleen size=48px").image.tobytes()
    assert big.rows and not codes(big) or set(codes(big)) <= {"L101", "L106"}


def test_font_problems_are_said_as_in_paragraphs():
    assert "F201" in codes(styled(BILL, "font=Terminus size=10px"))
    assert "F203" in codes(styled(BILL, 'font="No Such Font 123" size=16px'))
    assert "F205" in codes(styled(BILL, "font=Terminus size=900px"))
    assert "F204" in codes(styled(BILL, "style=header-invert font=Terminus size=16px"))
    assert "F204" not in codes(styled(BILL, "style=header-invert font=Terminus size=24px"))
    bad = styled(BILL, "size=tiny")
    assert any(n.code == "M101" and "size=tiny" in n.message for n in bad.nudges)


def test_font_problems_are_said_when_the_table_turns_too():
    res = styled(WIDE, "font=Terminus size=10px orientation=auto", profile_name="mtp-ii-58")
    assert "F201" in codes(res)


def test_a_grid_in_a_quote_keeps_the_quote_bar():
    res = build("> | a | b |\n> |---|---|\n> | 1 | 2 |\n> {style=grid}\n")
    piece = drawn(res)[1].image.convert("L")
    assert any(piece.getpixel((5, y)) < 128 for y in range(piece.height))  # the bar, in the quote's gutter
    assert "M101" not in codes(res)


# --- review fixes -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", ["0x", "1x0", "0"])
def test_a_size_of_nothing_is_clamped_never_a_failed_job(size):
    for doc in (BILL + "{size=" + size + "}\n", "Hello {font=Terminus size=" + size + "}\n"):
        res = build(doc)
        assert "F205" in codes(res) and res.rows, doc


def test_a_size_means_the_same_in_a_table_and_in_a_paragraph():
    def height(doc):
        im = build(doc).image.convert("L")
        box = im.point(lambda v: 255 - v).getbbox()
        return box[3] - box[1]

    assert height("W {font=Terminus size=2x}\n") == height("W {font=Terminus size=48px}\n")  # was 20px, silently
    table = styled("| W |\n|---|\n| W |\n", "font=Terminus size=2x")
    assert table.image.tobytes() == styled("| W |\n|---|\n| W |\n", "font=Terminus size=48px").image.tobytes()
    for doc in ("Hello {font=Terminus size=tiny}\n", BILL + "{size=tiny}\n"):
        assert any(n.code == "M101" and "size=tiny: not a size" in n.message for n in build(doc).nudges), doc


def view_of(res) -> list[str]:
    from bobina import view

    return view.lines(res.rows, res.profile, color=True)


@pytest.mark.parametrize("attrs", ["style=grid", "style=zebra", "font=Terminus size=16px"])
def test_a_drawn_table_reads_as_plain_text_in_the_terminal(attrs):
    shown = view_of(styled(BILL, attrs))
    assert not any("\x1b[7m" in ln for ln in shown)  # reverse video is for white-on-black bands only
    assert any("Cheese" in ln for ln in shown)


def test_only_the_header_invert_band_reads_reversed_in_the_terminal():
    import re

    shown = view_of(styled(BILL, "style=header-invert"))
    assert [re.sub(r"\x1b\[[0-9;]*m", "", ln).split() for ln in shown if "\x1b[7m" in ln] == [["Item", "Qty", "Price"]]


def mapped(res) -> list[str]:
    return [ln for r in drawn(res) for ln in ("".join(c.ch for c in t.cells) for t in r.text_rows)]


TOTALS_RS = '| | {prefix="R$ "} |\n|---|--:|\n| SUBTOTAL | 105,70 |\n| TROCO | 7,57 |\n'


def test_a_table_in_a_smaller_font_shows_every_cell_whole_on_its_own_grid():
    """More character columns than the paper's 32: the table's own grid, each column as wide as it prints, every
    cell whole, right-aligned values ending at their column's right edge."""
    res = styled(MARKET, "font=Terminus size=16px", profile_name="mtp-ii-58")
    assert mapped(res) == ["IT   CÓD DESCRIÇÃO            QTD UN  UNIT TOTAL",
                           "001 7891 ARROZ BRANCO 5KG       1 un 24,90 24,90",
                           "003 7369 BANANA PRATA ORG   1.635 kg  9,99 16,33"]  # fmt: skip
    assert all(r.wide_view for r in drawn(res))


def test_totals_in_a_smaller_font_end_at_the_tables_right_edge():
    shown = mapped(styled(TOTALS_RS, "font=Terminus size=16px", profile_name="mtp-ii-58"))
    assert shown == ["SUBTOTAL".ljust(39) + "R$ 105,70", "TROCO".ljust(41) + "R$ 7,57"]  # 48 columns


def test_totals_in_a_large_font_are_a_map_of_the_paper_ending_at_its_margin():
    res = styled(TOTALS_RS, "font=Terminus size=32px", profile_name="mtp-ii-58")
    assert mapped(res) == ["SUBTOTAL".ljust(23) + "R$ 105,70", "TROCO".ljust(25) + "R$ 7,57"]  # 32 columns
    assert not any(r.wide_view for r in drawn(res))


def test_a_proportional_font_loses_no_letter_in_the_view():
    """A proportional font's letters are narrower or wider than a column: the view takes the wider of the two, so
    no letter is lost (here 34 character columns: a frame wider than the paper)."""
    table = BILL.replace("Cheese bread", "Cheese bread with butter")
    shown = mapped(styled(table, 'font="Atkinson Hyperlegible" size=20px', profile_name="mtp-ii-58"))
    assert shown[:3] == ["Item                     Qty Price", "Espresso                   2  9,00",
                         "Cheese bread with butter   1 39,00"]  # fmt: skip
    assert "…" not in "".join(shown) and len({len(ln) for ln in shown}) == 1  # prices end in one place


def test_a_turned_lines_table_has_no_dotted_rule_under_the_titles_of_any_block():
    rows = "".join(f"| item {k} | {k} |\n" for k in range(12))
    table = "| Item | Qty |\n|---|--:|\n" + rows

    def blocks(attrs):
        res = styled(table, attrs + " orientation=vertical width=200")
        out = [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "table"]
        boxes = [r.image.convert("L").point(lambda v: 255 - v).getbbox() for r in out]
        return [(len(r.text_rows) - 1, box[2] - box[0]) for r, box in zip(out, boxes, strict=True)]

    plain = blocks("style=plain")  # titles and n rows: top + n * row dots along the paper
    (n1, w1), (n2, w2) = plain[0], plain[-1]
    row = (w1 - w2) // (n1 - n2)
    top = w1 - n1 * row
    lines = blocks("style=lines")
    assert len(lines) > 1
    for n, w in lines:  # a dotted rule (6 dots) between two rows of a block, none right under its titles
        assert w == top + n * row + 6 * (n - 1)


def test_zebra_is_marked_on_the_rows_that_draw_it_even_turned_or_rotated():
    res = styled(BILL, "style=zebra")
    assert [r.untested for r in res.rows if isinstance(r, BitmapRow) and r.untested] == [("zebra",)] * 2
    for attrs in ("style=zebra orientation=vertical", "style=zebra rotate=90"):
        assert any(isinstance(r, BitmapRow) and r.untested == ("zebra",) for r in styled(BILL, attrs).rows), attrs
    assert not any(isinstance(r, BitmapRow) and r.untested for r in styled(BILL, "style=grid rotate=90").rows)


def test_the_format_cheat_sheet_shows_what_a_table_takes(capsys):
    from bobina import cli

    cli.main(["help", "format"])
    out = capsys.readouterr().out
    assert "style=plain|receipt|lines|grid|header-invert|zebra" in out
    assert "font=Terminus size=16px" in out and "48 columns on 58 mm" in out and "| | |" in out


# --- second review --------------------------------------------------------------------------------------------------

ANSI = r"\x1b\[[0-9;]*m"


def boxed_lines(text: str) -> list[str]:
    """The lines of the first view box in a command's output, without colours."""
    import re

    out = [re.sub(ANSI, "", ln) for ln in text.splitlines()]
    top = next(i for i, ln in enumerate(out) if ln.startswith("┌"))
    end = next(i for i, ln in enumerate(out) if ln.startswith("└") and i > top)
    return out[top : end + 1]


@pytest.mark.parametrize("command", [["view"], ["print", "--dry-run", "--yes"]])
def test_the_frame_is_as_wide_as_the_widest_table_line(isolated, capsys, command):
    """The supermarket example (Terminus 16px): the frame grows to the table's widest line, every value whole; the
    paper's own text keeps its 32 columns inside it."""
    from bobina import cli

    example = Path(__file__).resolve().parents[1] / "examples" / "tables" / "supermarket.bob.md"
    doc = isolated / "supermarket.bob.md"
    doc.write_text(example.read_text(encoding="utf-8") + "\nThanks {.center}\n", encoding="utf-8")
    cli.main([*command, str(doc), "--profile", "mtp-ii-58"])
    box = boxed_lines(capsys.readouterr().out)
    inner = [ln[1:-1] for ln in box[1:-1]]
    assert {len(ln) for ln in box} == {50} and max(len(ln.rstrip()) for ln in inner) == 48  # 48 columns, 2 sides
    assert any(ln.startswith("SUBTOTAL") and ln.endswith("R$ 105,70") for ln in inner)
    assert any(ln.startswith("001 2000000 ARROZ") for ln in inner) and "…" not in "".join(inner)
    assert any(ln.rstrip() == " " * 13 + "Thanks" for ln in inner)  # centred on the paper's 32 columns


def test_a_bad_front_matter_size_is_said_once_at_its_line():
    doc = "---\nsize: tiny\n---\nA {font=Terminus}\n\nB {font=Terminus}\n\n" + BILL + "{font=Terminus}\n\nC\n"
    res = build(doc)
    notes = [n for n in res.nudges if n.code == "M101"]
    assert [(n.line, "size: tiny" in n.message) for n in notes] == [(2, True)]
    assert not any("size=" in n.message for n in res.nudges)  # the table gave only font=


def test_an_unreadable_block_size_falls_back_to_the_document_size():
    front = "---\nsize: large\n---\n"
    for bad, good in (
        ("W {font=Terminus size=tiny}\n", "W {font=Terminus}\n"),
        ("| W |\n|---|\n| W |\n{font=Terminus size=tiny}\n", "| W |\n|---|\n| W |\n{font=Terminus}\n"),
    ):
        res = build(front + bad)  # fmt: skip
        assert "M101" in codes(res)
        assert res.image.tobytes() == build(front + good).image.tobytes(), bad


def test_only_what_is_white_on_black_on_paper_reads_reversed_in_the_terminal():
    import re

    def reversed_words(doc):
        return [re.sub(ANSI, "", ln).split() for ln in view_of(build(doc)) if "\x1b[7m" in ln]

    assert reversed_words("Hello there {font=Terminus}\n") == []  # a raster paragraph
    assert reversed_words("> Quoted big {size=2x}\n") == []  # a quote's bar drawn into a 2x line
    assert reversed_words("SALE {font=Terminus size=24px .bold .invert}\n") == [["SALE"]]  # a band
    assert reversed_words("SALE {.invert}\n") == [["SALE"]]
    assert reversed_words("Hi [you]{.invert} {font=Terminus}\n") == [["Hi", "you"]]  # the word, by its cell


@pytest.mark.parametrize("size,said", [("2x1", True), ("1x2", True), ("2x", False), ("3x3", False)])
def test_a_multiplier_whose_width_and_height_differ_is_said_in_a_raster_font(size, said):
    for doc in (f"W {{font=Terminus size={size}}}\n", BILL + f"{{font=Terminus size={size}}}\n"):
        notes = [n for n in build(doc).nudges if n.code == "F303"]
        assert bool(notes) is said, doc
        if said:
            assert "scales evenly" in notes[0].message and "height" in notes[0].message
