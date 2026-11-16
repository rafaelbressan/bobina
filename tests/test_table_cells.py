"""A cell's own {…} (at the end of its text, title or body), span= (a body cell over the columns after it) and a
row's {…} (after the pipe that closes it). Every rule of each, the wrong values, how they combine with each other and
with style=, a font and a turned table, and that none of it ever prints wider than the paper."""

import random
import unicodedata

import pytest
from PIL import ImageChops

from bobina.engine import build
from bobina.rows import BitmapRow, TextRow
from bobina.templating import Tainted

BILL = "| Item | Qty | Price |\n|---|--:|--:|\n"


def lines(res) -> list[str]:
    """Every printed line of text, the drawn ones as the terminal views show them."""
    out = []
    for r in res.rows:
        if isinstance(r, TextRow):
            out.append("".join(c.ch for c in r.cells).rstrip())
        elif isinstance(r, BitmapRow) and r.text_rows:
            out += ["".join(c.ch for c in v.cells).rstrip() for v in r.text_rows]
    return out


def codes(res) -> list[str]:
    return [n.code for n in res.nudges]


def said(res, code: str) -> list[str]:
    return [n.message for n in res.nudges if n.code == code]


def text_rows(res) -> list[TextRow]:
    """Each printed line as cells: a native line, or a drawn line's view."""
    out = []
    for r in res.rows:
        if isinstance(r, TextRow):
            out.append(r)
        elif isinstance(r, BitmapRow) and r.text_rows and r.kind != "divider":
            out += r.text_rows
    return out


def cells_of(res, text: str) -> list:
    """The cells of `text` on the first line that has it."""
    for r in text_rows(res):
        s = "".join(c.ch for c in r.cells)
        if text in s:
            i = s.index(text)
            return r.cells[i : i + len(text)]
    raise AssertionError(f"{text!r} not in {lines(res)}")


def drawn_with(res, text: str) -> BitmapRow:
    return next(r for r in res.rows if isinstance(r, BitmapRow) and r.text_rows
                and any(text in "".join(c.ch for c in v.cells) for v in r.text_rows))  # fmt: skip


def black(im, box) -> float:
    """The share of black dots in box (x0, y0, x1, y1) of an image."""
    part = im.convert("L").crop(box)
    return sum(part.histogram()[:128]) / (part.width * part.height)


# --- classes at the end of a cell ------------------------------------------------------------------------------------


@pytest.mark.parametrize("cls", ["bold", "italic", "underline", "strike"])
@pytest.mark.parametrize("where", ["title", "body"])
def test_each_text_class_styles_its_cell_only(cls, where):
    doc = f"| Item {{.{cls}}} | Price |\n|---|--:|\n| Rice | 9,00 |\n" if where == "title" else (
        f"| Item | Price |\n|---|--:|\n| Rice {{.{cls}}} | 9,00 |\n")  # fmt: skip
    res = build(doc + "{style=receipt}\n")  # receipt: titles not bold, so .bold shows there too
    word = "Item" if where == "title" else "Rice"
    other = "Price" if where == "title" else "9,00"
    assert all(getattr(c, cls) for c in cells_of(res, word)) and not any(getattr(c, cls) for c in cells_of(res, other))
    assert not codes(res) and "{" not in "".join(lines(res))


def test_a_title_cell_keeps_its_column_settings_and_takes_classes():
    res = build('| Item | Price {width=9ch prefix="R$ " .right .underline} |\n|---|---|\n| Rice | 9,00 |\n')
    assert lines(res) == ["Item                       Price", "Rice                   R$ 9,00"]  # the title only
    assert all(c.underline for c in cells_of(res, "Price")) and not codes(res)


@pytest.mark.parametrize("where", ["title", "body"])
def test_invert_turns_its_cell_white_on_black_continuously(where):
    doc = (BILL.replace("Price |", "Price {.invert} |") + "| Rice | 1 | 9,00 |\n" if where == "title"
           else BILL + "| Cheese bread | 1 | 39,00 {.invert} |\n")  # fmt: skip
    res = build(doc)
    word = "Price" if where == "title" else "39,00"
    row = drawn_with(res, word)
    assert all(c.invert for c in cells_of(res, word))  # in the terminal views too
    assert not any(c.invert for c in cells_of(res, "1" if where == "body" else "Item"))
    im, cell = row.image, 12  # the printer font: 12 dots a column, the last column at the paper's edge
    assert black(im, (im.width - 3 * cell, 0, im.width, im.height)) > 0.6  # the cell: white letters on black
    assert black(im, (0, 0, 5 * cell, im.height)) < 0.3  # the first cell: black letters on paper
    assert "P301" not in codes(res)


@pytest.mark.parametrize("where", ["title", "body"])
def test_shade_puts_grey_dots_behind_its_cell_and_says_p301(where):
    doc = (BILL.replace("Item |", "Item {.shade} |") + "| Rice | 1 | 9,00 |\n" if where == "title"
           else BILL + "| Rice {.shade} | 1 | 9,00 |\n")  # fmt: skip
    res = build(doc)
    word = "Item" if where == "title" else "Rice"
    row = drawn_with(res, word)
    assert row.untested == ("zebra",) and "P301" in codes(res)
    im = row.image
    assert 0 < black(im, (70, 0, 250, im.height)) < 0.2  # light dots after the word, in its cell
    plain = build(doc.replace(" {.shade}", "")).image
    changed = ImageChops.difference(res.image.convert("L"), plain.convert("L")).getbbox()
    assert changed[2] <= 22 * 12 + 6  # only in its cell: up to the middle of the space after the Item column


def test_an_alignment_class_overrides_the_column_for_that_cell_only():
    res = build(BILL + "| Rice | 1 {.left} | 9,00 |\n| Bean | 2 | 7,00 {.center} |\n| Salt {.right} | 3 | 1,00 |\n")
    assert lines(res)[1:] == ["Rice                   1    9,00", "Bean                     2 7,00",
                              "                  Salt   3  1,00"]  # fmt: skip


def test_unknown_and_idle_names_in_a_cell_are_said_and_taken_out():
    res = build(BILL + "| Rice {.boldd} | 1 {.compact} | 9,00 {size=2} |\n")
    assert said(res, "M101") == ["unknown class '.boldd'", ".compact at the end of a table cell does nothing",
                                 "size= at the end of a table cell does nothing"]  # fmt: skip
    assert "{" not in "".join(lines(res))


def test_an_escaped_brace_and_data_stay_text():
    res = build(BILL + "| Rice \\{.bold} | 1 | 9,00 \\{span=all} |\n")
    assert lines(res)[1].startswith("Rice {.bold}") and lines(res)[1].endswith("9,00 {span=all}")
    assert not any(c.bold for c in cells_of(res, "Rice")) and not codes(res)
    data = build(BILL + "| {{ item }} | 1 | 9,00 |\n", fields={"item": Tainted("Rice {span=all .invert}")})
    assert lines(data)[1].startswith("Rice {span=all") and lines(data)[2].strip() == ".invert}" and not codes(data)
    assert not any(isinstance(r, BitmapRow) and r.text_rows for r in data.rows)  # nothing inverted: plain lines


# --- span= ------------------------------------------------------------------------------------------------------------


def test_span_all_starts_where_it_is_written_and_goes_to_the_end():
    res = build(BILL + "| Rice | 1 | 9,00 |\n| Discount on rice - 1,00 {span=all} |\n")
    assert lines(res)[2] == "Discount on rice - 1,00" and not codes(res)
    later = build(BILL + "| Rice | 1 | 9,00 |\n| | Discount on rice - 1,00 {span=all} |\n")  # from Qty on: it wraps
    assert lines(later)[2:] == [" " * 24 + "Discount", " " * 23 + "on rice -", " " * 28 + "1,00"]


def test_span_starting_in_the_third_column():
    head = "| IT | CODE | DESCRIPTION | TOTAL |\n|---|---|---|--:|\n"
    res = build(head + "| 001 | 7891 | RICE WHITE TYPE 1 | 24,90 |\n| | | Discount -2,49 {span=all} |\n{.compact}\n")
    assert lines(res)[2] == " " * lines(res)[0].index("DESCRIPTION") + "Discount -2,49"
    assert not codes(res)


def test_span_n_takes_this_column_and_n_minus_1_more():
    res = build(BILL + "| Rice | 1 | 9,00 |\n| Two columns of text {span=2} | | 5,00 |\n")
    assert lines(res)[2] == "Two columns of text         5,00" and not codes(res)


def test_a_spanning_cell_does_not_count_in_the_column_widths():
    plain = build(BILL + "| Rice | 1 | 9,00 |\n{.compact}\n")
    spanned = build(BILL + "| Rice | 1 | 9,00 |\n| A long note across every column {span=all} |\n{.compact}\n")
    assert lines(spanned)[:2] == lines(plain)  # the columns as wide as without it: the note wraps in them
    assert all(len(ln) <= len(lines(plain)[0]) for ln in lines(spanned))


def test_a_span_aligns_as_its_first_column_or_its_own_class():
    res = build(BILL + "| Rice | 1 | 9,00 |\n| | ok {span=all} |\n| | fine {span=all .left} |\n")
    assert lines(res)[2].endswith("ok") and lines(res)[2].index("ok") > lines(res)[3].index("fine")


def test_a_span_larger_than_what_is_left_goes_to_the_end_and_says_so():
    res = build(BILL + "| Rice | 1 | 9,00 |\n| | Note {span=5} |\n")
    assert said(res, "M101") == ["span=5: 2 columns from here to the end of the row"]
    assert lines(res)[2].strip() == "Note"


def test_a_covered_cell_with_text_stops_the_span_before_it_and_says_so():
    res = build(BILL + "| A long note here {span=all} | | 9,00 |\n")
    assert said(res, "M101") == ["span=all stops before '9,00': that cell has text"]
    assert lines(res)[1].endswith("9,00") and "A long" in "".join(lines(res))  # nothing disappears


def test_span_1_is_silent_and_a_short_row_is_filled():
    res = build(BILL + "| Rice {span=1} | 1 |\n")
    assert lines(res)[1] == "Rice                     1" and not codes(res)  # the empty Price cell added


@pytest.mark.parametrize("value", ["0", "-1", "abc", "2.5", '""', ""])
def test_a_wrong_span_is_said_and_the_cell_prints_in_its_column(value):
    res = build(BILL + f"| Rice {{span={value}}} | 1 | 9,00 |\n")
    shown = value.strip('"')
    assert said(res, "M101") == [f"span={shown}: a whole number from 1, or all"]
    assert lines(res)[1] == "Rice                     1  9,00"


def test_span_in_capitals_says_values_are_lowercase():
    res = build(BILL + "| | Note {span=ALL} |\n")
    assert said(res, "M101") == ["span=ALL: values are lowercase: span=all"]
    assert lines(res)[1].strip() == "Note"


def test_span_in_a_title_cell_is_said_and_ignored():
    res = build("| Item {span=all} | Price |\n|---|--:|\n| Rice | 9,00 |\n")
    assert said(res, "M101") == ["span=all in a title cell: a title spans nothing (ignored)"]
    assert lines(res)[0] == "Item                       Price"


def test_a_span_in_a_grid_has_no_vertical_line_inside_it():
    res = build(BILL + "| Rice | 1 | 9,00 |\n| A note across {span=all} |\n{style=grid}\n")
    rows = [r for r in res.rows if isinstance(r, BitmapRow) and r.text_rows]
    normal, spanned = rows[1].image, rows[2].image

    def verticals(im):
        y = im.height // 2
        xs = [x for x in range(im.width) if im.convert("L").getpixel((x, y)) < 128]
        return [x for x in xs if all(im.convert("L").getpixel((x, yy)) < 128 for yy in range(2, im.height - 3))]

    assert len(verticals(normal)) > len(verticals(spanned)) >= 2  # the borders only


def test_zebra_shades_the_whole_span_and_a_shaded_span_its_columns():
    res = build(BILL + "| Rice | 1 | 9,00 |\n| A note {span=all} |\n{style=zebra}\n")
    im = drawn_with(res, "A note").image
    assert black(im, (im.width - 60, 0, im.width, im.height)) > 0  # the dots reach the last column
    own = build(BILL + "| Rice | 1 | 9,00 |\n| | A note {span=all .shade} |\n")
    im = drawn_with(own, "A note").image
    assert black(im, (0, 0, 40, im.height)) == 0 and black(im, (im.width - 40, 0, im.width, im.height)) > 0


def test_a_turned_table_follows_the_same_rule():
    res = build(BILL + "| Rice | 1 | 9,00 |\n| A note across the turned table {span=all} |\n{orientation=vertical}\n")
    turned = next(r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "table")
    text = ["".join(c.ch for c in v.cells) for v in turned.text_rows]
    assert any(t.startswith("A note across the turned table") for t in text)  # one line: the length is free
    assert turned.image.width <= 384 and not codes(res)


def test_a_span_in_a_font_table_wraps_in_the_summed_width():
    res = build(BILL + "| Rice | 1 | 9,00 |\n| | A long note that wraps in two columns only {span=all} |\n"
                "{font=Terminus size=16px .compact}\n")  # fmt: skip
    assert all(r.image.width <= 384 for r in res.rows if isinstance(r, BitmapRow))
    assert sum("note" in ln or "wraps" in ln or "columns" in ln for ln in lines(res)) >= 2


# --- a row's {…}, after its closing pipe ----------------------------------------------------------------------------


def test_a_brace_after_the_closing_pipe_styles_the_row():
    res = build(BILL + "| Rice | 1 | 9,00 |\n| TOTAL | | 19,00 | {.bold}\n")
    assert all(c.bold for c in cells_of(res, "TOTAL")) and all(c.bold for c in cells_of(res, "19,00"))
    assert not any(c.bold for c in cells_of(res, "Rice"))
    assert lines(res)[2] == "TOTAL                      19,00" and not codes(res)


@pytest.mark.parametrize("row", ["| a | {.shade} |", "| a | {.shade}|x |", "| {.bold} |"])
def test_a_cell_that_is_only_a_brace_before_a_closing_pipe_stays_a_cell(row):
    res = build("| A | B |\n|---|---|\n" + row + "\n")
    if ".shade" in row:  # the second cell, empty and shaded
        assert "P301" in codes(res)
    assert "{" not in "".join(lines(res))
    assert not any(c.bold for r in text_rows(res)[1:] for c in r.cells)  # a cell, not the row


def test_row_and_cell_attributes_combine_the_cell_winning_on_alignment():
    res = build(BILL + "| Rice {.italic .left} | 1 | 9,00 | {.bold .center}\n")
    assert all(c.bold and c.italic for c in cells_of(res, "Rice"))
    assert all(c.bold and not c.italic for c in cells_of(res, "9,00"))
    assert lines(res)[1] == "Rice                    1  9,00"  # 1 centered in Qty (the row's), Rice left (its own)


def test_an_inverted_row_is_one_band_across_the_row_gaps_included():
    res = build(BILL + "| Rice | 1 | 9,00 |\n| TOTAL | | 9,00 | {.invert .bold}\n")
    row = drawn_with(res, "TOTAL")
    assert row.kind == "band"
    im = row.image.convert("L")
    y = im.height - 2  # under the letters: one black band from edge to edge
    assert all(im.getpixel((x, y)) < 128 for x in range(im.width))


def test_a_shaded_row_and_an_inverted_cell_in_it():
    res = build(BILL + "| Rice | 1 {.invert} | 9,00 | {.shade}\n")
    row = drawn_with(res, "Rice")
    assert row.untested == ("zebra",) and row.kind == "text"
    assert all(c.invert for c in cells_of(res, "1")) and not any(c.invert for c in cells_of(res, "Rice"))


def test_a_row_with_a_span_covers_the_span():
    res = build(BILL + "| Rice | 1 | 9,00 |\n| | Discount {span=all} | {.invert}\n")
    row = drawn_with(res, "Discount")
    assert row.kind == "band" and not codes(res)


@pytest.mark.parametrize("style", ["plain", "receipt", "lines", "grid", "header-invert", "zebra"])
def test_a_brace_after_the_title_row_styles_the_title_row_only_and_notes_m104(style):
    res = build("| Item | Price | {.invert}\n|---|--:|\n| Rice | 9,00 |\n" + f"{{style={style}}}\n")
    assert said(res, "M104") == ["a {…} after the title row makes GitHub and Obsidian show the table as text"]
    assert next(n for n in res.nudges if n.code == "M104").line == 1
    assert drawn_with(res, "Item").kind == "band" and "Rice" in lines(res)[-1]
    rice = [r for r in res.rows if isinstance(r, (TextRow, BitmapRow)) and "Rice" in "".join(
        c.ch for v in ([r] if isinstance(r, TextRow) else r.text_rows or []) for c in v.cells)]  # fmt: skip
    assert not isinstance(rice[0], BitmapRow) or rice[0].kind != "band"


def test_a_title_row_brace_in_a_code_block_stays_as_written():
    res = build("```\n| Item | Price | {.invert}\n|---|--:|\n```\n")
    assert "| Item | Price | {.invert}" in lines(res) and not codes(res)


def test_what_a_row_does_not_take_is_said():
    res = build(BILL + "| Rice | 1 | 9,00 | {.strike span=2 .boldd}\n")
    assert said(res, "M101") == ["unknown class '.boldd'", ".strike, span= after a table row do nothing"]
    assert lines(res)[1] == "Rice                     1  9,00"


def test_a_row_brace_from_data_stays_literal():
    res = build(BILL + "| Rice | 1 | 9,00 | {{ extra }}\n", fields={"extra": Tainted("{.invert}")})
    assert not codes(res) and not any(isinstance(r, BitmapRow) and r.kind == "band" for r in res.rows)


# --- never wider than the paper -------------------------------------------------------------------------------------


@pytest.mark.parametrize("profile", ["mtp-ii-58", "epson-tm-t20iii"])
def test_no_cell_row_or_span_attribute_makes_a_line_wider_than_the_paper(profile):
    """Random tables with random cell classes, spans and row classes, in every style, standing, turned or in a
    font: no line of text and no drawn row passes the paper."""

    def cols_of(text: str) -> int:
        return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)

    rng = random.Random(11)
    paper, dots = (32, 384) if profile == "mtp-ii-58" else (48, 576)
    classes = [".bold", ".italic", ".invert", ".shade", ".left", ".center", ".right", ".underline", ".strike"]
    for _ in range(80):
        n = rng.randint(1, 9)
        head = " | ".join(f"H{i}" + (f" {{width={rng.choice([2, 5, 12])}ch}}" if rng.random() < 0.3 else "")
                          for i in range(n))  # fmt: skip
        body = []
        for _ in range(rng.randint(1, 4)):
            cells = []
            for _ in range(n):
                text = rng.choice(["x" * rng.randint(1, 14), "字" * rng.randint(1, 3), "", "a long note across"])
                tail = " ".join(rng.sample(classes, rng.randint(0, 2)))
                if rng.random() < 0.25:
                    tail += f" span={rng.choice(['all', '2', '3', '9'])}"
                cells.append(f"{text} {{{tail}}}" if tail.strip() else text)
            row = "| " + " | ".join(cells[: rng.randint(1, n)]) + " |"
            if rng.random() < 0.3:
                row += " {" + " ".join(rng.sample(classes[:-1], 2)) + "}"
            body.append(row)
        table = f"| {head} |\n|" + "---|" * n + "\n" + "\n".join(body) + "\n"
        attrs = [f"style={rng.choice(['plain', 'receipt', 'lines', 'grid', 'header-invert', 'zebra'])}"]
        attrs += rng.sample(["orientation=vertical", "orientation=horizontal", "font=Terminus size=16px", ".compact"],
                            rng.randint(0, 2))  # fmt: skip
        res = build(table + "{" + " ".join(attrs) + "}\n", profile_name=profile)
        native = not any(a.startswith("font=") for a in attrs)  # a font table's views count the font's columns
        for r in res.rows:
            if isinstance(r, TextRow):
                assert cols_of("".join(c.ch for c in r.cells)) <= paper, (table, attrs)
            elif isinstance(r, BitmapRow):
                assert r.image.width <= dots, (table, attrs)
                if r.kind != "table" and native:  # a standing table's views stop where the paper does
                    assert all(cols_of("".join(c.ch for c in v.cells)) <= paper for v in r.text_rows or []), (
                        table, attrs)  # fmt: skip
