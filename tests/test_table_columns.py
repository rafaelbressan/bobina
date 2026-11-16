"""Column settings at the end of a title cell: width= (a column keeps it, the others share the rest), prefix= and
suffix= (around every body value), L107 when the widths are wider than the paper, and L108, the width each column
got, said by bobina check only. Checked on the text rows and on what the terminal views show."""

import json

import pytest

from bobina import cli
from bobina.engine import build
from bobina.rows import BitmapRow, TextRow
from bobina.templating import Tainted


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


def notes(res) -> list[str]:
    return [n.message for n in res.notes if n.code == "L108"]


def rules(res) -> list:
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "divider"]


# --- the settings are read at the end of a title cell, and taken out of its text ----------------------------------


def test_title_cell_settings_are_not_printed():
    res = build('| Item | Price {width=9ch prefix="R$ "} |\n|---|--:|\n| Rice | 24,90 |\n')
    assert lines(res) == ["Item                       Price", "Rice                    R$ 24,90"]
    assert not codes(res)


def test_a_title_row_with_only_settings_is_still_no_title():
    res = build('| | {prefix="R$ "} |\n|---|--:|\n| SUBTOTAL | 88,00 |\n| TOTAL | 96,80 |\n')
    assert lines(res) == ["SUBTOTAL                R$ 88,00", "TOTAL                   R$ 96,80"]
    assert not rules(res) and not codes(res)


# --- width= -------------------------------------------------------------------------------------------------------


def test_a_column_with_a_width_keeps_it_and_the_auto_column_takes_the_rest():
    res = build("| Code {width=6ch} | Item |\n|---|---|\n| 12 | Rice |\n")
    title, row = lines(res)
    assert title.index("Item") == 7 and row.index("Rice") == 7  # 6 columns, then the space between columns
    assert notes(res) == ["column widths: Code 6 · Item 25 (+1 gap = 32 of 32)"]


def test_text_wraps_inside_a_given_width_and_a_long_word_is_cut_without_l101():
    res = build("| IT {width=2ch} | CODE {width=7ch} | ITEM |\n|---|---|---|\n| 1 | 7891234567895 | RICE WHITE |\n")
    assert lines(res)[1:] == ["1  7891234 RICE WHITE", "   567895"]
    assert "L101" not in codes(res)


def test_an_auto_column_still_says_a_cut_word():
    res = build("| A {width=20ch} | B |\n|---|---|\n| x | ABCDEFGHIJKLMNOPQRSTUVWXYZ |\n")
    assert "L101" in codes(res)


def test_a_title_wider_than_its_column_wraps_like_the_body():
    res = build("| QUANTITY ORDERED {width=8ch} | Item |\n|---|---|\n| 2 | Rice |\n")
    assert lines(res)[:2] == ["QUANTITY Item", "ORDERED"]
    assert "L101" not in codes(res)


@pytest.mark.parametrize(
    ("width", "cols"),
    [("6ch", 6), ("12mm", 8), ("25%", 8), ("72", 6), ("72px", 6), ("6.9ch", 6), ("auto", None)],
)
def test_width_units(width, cols):
    res = build(f"| A {{width={width}}} | B |\n|---|---|\n| x | y |\n")
    a = 30 if cols is None else cols  # auto: the first column stretches to the paper edge
    assert notes(res) == [f"column widths: A {a} · B {31 - a} (+1 gap = 32 of 32)"]
    assert not codes(res)


def test_compact_still_keeps_the_auto_columns_narrow():
    res = build("| N {width=5ch} | Item |\n|---|---|\n| 1 | Rice |\n{.compact}\n")
    assert notes(res) == ["column widths: N 5 · Item 4 (+1 gap = 10 of 32)"]


def test_a_table_of_given_widths_only_is_as_wide_as_they_are_and_can_be_placed():
    res = build("| A {width=4ch} | B {width=4ch} |\n|---|---|\n| x | y |\n{.center}\n")
    assert lines(res) == ["           A    B", "           x    y"]  # 9 of 32: 23 columns left, 11 before it


def test_widths_wider_than_the_paper_shrink_in_proportion_and_auto_columns_keep_2():
    res = build("| A {width=20ch} | B {width=20ch} | C |\n|---|---|---|\n| a | b | c |\n")
    assert said(res, "L107") == ["column widths add up to 44 columns, the paper has 32: scaled down"]
    assert notes(res) == ["column widths: A 14 · B 14 · C 2 (+2 gaps = 32 of 32)"]
    hint = next(n.suggestion for n in res.nudges if n.code == "L107")
    assert "2 for each auto column" in hint and "font=Terminus size=16px" in hint


def test_auto_orientation_keeps_a_table_with_widths_standing():
    rows = "".join("| " + " | ".join(f"v{r}{c}" for c in range(8)) + " |\n" for r in range(4))
    cramped = "| " + " | ".join(f"Col{c}" for c in range(8)) + " |\n|" + "---|" * 8 + "\n" + rows
    assert "L106" in codes(build(cramped))  # 8 columns on 58 mm: about 3 characters each, it turns
    res = build(cramped.replace("Col0", "Col0 {width=4ch}", 1))
    assert "L106" not in codes(res) and not [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "table"]


def test_a_turned_table_keeps_a_given_width_along_the_paper():
    table = "| N {width=4ch} | Item |\n|---|---|\n| 1 | Rice white long grain |\n{orientation=vertical}\n"
    res = build(table)
    assert lines(res) == ["N    Item", "1    Rice white long grain"]
    assert notes(res) == ["turned table, column widths: N 4 · Item 21 (+1 gap = 26 along the paper)"]
    narrow = build(table.replace("4ch", "2ch").replace("| 1 |", "| 1234 |"))
    assert lines(narrow)[1:] == ["12 Rice white long grain", "34"]  # wraps inside it, the auto column does not


# --- a table in a font: columns as wide as its "0" -----------------------------------------------------------------


def test_widths_in_a_font_table_are_the_font_columns():
    res = build("| IT {width=3ch} | DESCRIPTION | TOTAL {width=6ch} |\n|---|---|--:|\n| 001 | RICE | 24,90 |\n"
                "{font=Terminus size=16px}\n")  # fmt: skip
    assert notes(res) == [
        "column widths in Terminus 16px columns: IT 3 · DESCRIPTION 37 · TOTAL 6 (+2 gaps = 48 of 48)"
    ]
    assert not codes(res)


def test_a_font_table_without_settings_says_its_widths_too():
    res = build("| A | B |\n|---|---|\n| x | y |\n{font=Terminus size=16px}\n")
    assert notes(res) == ["column widths in Terminus 16px columns: A 46 · B 1 (+1 gap = 48 of 48)"]


# --- prefix= and suffix= -------------------------------------------------------------------------------------------


def test_prefix_and_suffix_go_around_body_values_only():
    res = build('| Item | Price {prefix="R$ "} | Weight {suffix=" kg"} |\n|---|--:|--:|\n'
                "| Rice | 24,90 | 5 |\n| Bag | | |\n")  # fmt: skip
    title, rice, bag = lines(res)
    assert "R$" not in title and "kg" not in title
    assert rice.endswith("R$ 24,90   5 kg") and bag == "Bag"  # empty cells get neither


def test_the_width_counts_the_prefix():
    res = build('| A | P {prefix="R$ "} |\n|---|--:|\n| x | 9,00 |\n{.compact}\n')
    assert notes(res) == ["column widths: A 1 · P 7 (+1 gap = 9 of 32)"]


def test_prefix_takes_the_style_of_the_value():
    res = build('| | {prefix="R$ "} |\n|---|--:|\n| **TOTAL** | **96,80** |\n')
    row = next(r for r in res.rows if isinstance(r, TextRow))
    assert all(c.bold for c in row.cells if c.ch != " ")


def test_a_value_from_data_stays_literal_next_to_a_prefix():
    doc = '| Item | Price {prefix="R$ "} |\n|---|--:|\n| Rice | {{ price }} |\n'
    res = build(doc, fields={"price": Tainted("*9* {width=2}")})
    assert lines(res)[1].endswith("R$ *9* {width=2}")
    assert not codes(res)
    row = [r for r in res.rows if isinstance(r, TextRow)][1]
    assert not any(c.bold or c.italic for c in row.cells)


# --- what is wrong is said, the table prints -----------------------------------------------------------------------


@pytest.mark.parametrize("key", ["width=9ch", 'prefix="R$ "', 'suffix=" kg"'])
def test_a_column_setting_in_a_body_cell_is_said_and_not_printed(key):
    res = build(f"| A | B |\n|---|---|\n| x | 9,00 {{{key}}} |\n")
    name = key.split("=")[0]
    assert said(res, "M101") == [f"{name}= works at the end of a title cell, for its column"]
    assert res.nudges[0].line == 3 and "{" not in "".join(lines(res))


def test_a_body_cell_brace_without_column_settings_stays_text():
    res = build("| A | B |\n|---|---|\n| x | {.bold} |\n")
    assert lines(res)[1].endswith("{.bold}") and not codes(res)


@pytest.mark.parametrize("value", ["abc", "-3ch", "0", "0ch", "0.5ch", "9 ch"])
def test_an_unreadable_width_is_said_and_the_column_is_auto(value):
    res = build(f'| A {{width="{value}"}} | B |\n|---|---|\n| x | y |\n')
    assert said(res, "M101") == [f"width={value}: not a column width"]
    hint = next(n.suggestion for n in res.nudges if n.code == "M101")
    assert "auto, 7ch, 20mm, 30%" in hint
    assert notes(res) == ["column widths: A 30 · B 1 (+1 gap = 32 of 32)"]  # auto: as wide as the plain table


@pytest.mark.parametrize("value", ["9CH", "AUTO", "20MM"])
def test_a_width_in_capitals_says_values_are_lowercase(value):
    res = build(f"| A {{width={value}}} | B |\n|---|---|\n| x | y |\n")
    assert said(res, "M101") == [f"width={value}: values are lowercase"]
    assert f"width={value.lower()}" in res.nudges[0].suggestion


def test_an_unknown_key_in_a_title_cell_is_an_unknown_key():
    res = build("| A {widht=9ch} | B |\n|---|---|\n| x | y |\n")
    assert said(res, "M101") == ["unknown key 'widht='"] and lines(res)[0].startswith("A ")


def test_other_names_in_a_title_cell_do_nothing_and_say_so():
    res = build("| A {.bold align=right} | B |\n|---|---|\n| x | y |\n")
    assert said(res, "M101") == [".bold, align= at the end of a title cell do nothing"]


# --- L108: bobina check says the width each column got -------------------------------------------------------------


def test_l108_is_not_a_problem_of_the_print():
    res = build("| A {width=5ch} | B |\n|---|---|\n| x | y |\n")
    assert "L108" not in codes(res) and "L108" not in [n.code for n in res.visible_nudges()]
    assert [n.code for n in res.visible_nudges(check=True)] == ["L108"]


def test_a_plain_table_says_nothing():
    assert not notes(build("| A | B |\n|---|---|\n| x | y |\n"))


def test_check_says_the_widths_in_text(capsys):
    assert cli.main(["check", "| IT {width=3ch} | Item |\n|---|---|\n| 1 | Rice |\n"]) == cli.OK
    err = capsys.readouterr().err
    assert "· note    [L108] line 1: column widths: IT 3 · Item 28 (+1 gap = 32 of 32)" in err


def test_check_says_the_widths_in_json(capsys):
    assert cli.main(["check", "--json", "| IT {width=3ch} | Item |\n|---|---|\n| 1 | Rice |\n"]) == cli.OK
    problems = json.loads(capsys.readouterr().out)["problems"]
    assert [(p["code"], p["severity"], p["line"]) for p in problems] == [("L108", "note", 1)]
    assert problems[0]["message"] == "column widths: IT 3 · Item 28 (+1 gap = 32 of 32)"


def test_print_does_not_say_the_widths(capsys, tmp_path):
    out = tmp_path / "job.bin"
    assert cli.main(["print", "| IT {width=3ch} | Item |\n|---|---|\n| 1 | Rice |\n", "-o", str(out)]) == cli.OK
    assert "L108" not in capsys.readouterr().err


def test_allow_silences_l108(capsys):
    cli.main(["check", "--allow", "L108", "| IT {width=3ch} | Item |\n|---|---|\n| 1 | Rice |\n"])
    assert "L108" not in capsys.readouterr().err


def test_only_the_given_widths_shrink_and_each_auto_column_keeps_its_2():
    res = build("| A {width=30ch} | B {width=10ch} | C | D |\n|---|---|---|---|\n| a | b | cc | dd |\n")
    assert said(res, "L107") == ["column widths add up to 47 columns, the paper has 32: scaled down"]
    assert notes(res) == ["column widths: A 19 · B 6 · C 2 · D 2 (+3 gaps = 32 of 32)"]


def test_check_says_a_tables_widths_once_for_every_data_row(capsys, tmp_path):
    (tmp_path / "rows.csv").write_text("item\nRice\nBlack beans in a big bag\n")
    doc = tmp_path / "label.bob.md"
    doc.write_text("| N {width=3ch} | Item |\n|---|---|\n| 1 | {{ item }} |\n{.compact}\n")
    assert cli.main(["check", str(doc), "--data", str(tmp_path / "rows.csv")]) == cli.OK
    assert capsys.readouterr().err.count("[L108]") == 1
