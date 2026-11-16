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
    [("6ch", 6), ("12mm", 8), ("25%", 7), ("72", 6), ("72px", 6), ("6.9ch", 6), ("auto", None)],
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
    assert said(res, "L107") == ["column widths add up to 43 columns, the paper has 32: scaled down"]  # c needs 1
    assert notes(res) == ["column widths: A 15 · B 14 · C 1 (+2 gaps = 32 of 32)"]
    hint = next(n.suggestion for n in res.nudges if n.code == "L107")
    assert "up to 2 for each auto column" in hint and "font=Terminus size=16px" in hint


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


def test_a_body_cell_brace_with_only_an_id_or_nothing_stays_text():
    for brace in ("{}", "{#x}"):
        res = build(f"| A | B |\n|---|---|\n| x | y {brace} |\n")
        assert lines(res)[1].endswith(f"y {brace}") and not codes(res)


@pytest.mark.parametrize("value", ["abc", "-3ch", "0", "0ch", "0.5ch", "9 ch"])
def test_an_unreadable_width_is_said_and_the_column_is_auto(value):
    res = build(f'| A {{width="{value}"}} | B |\n|---|---|\n| x | y |\n')
    assert said(res, "M101") == [f"width={value}"]  # as object_width says it, with the column's units
    hint = next(n.suggestion for n in res.nudges if n.code == "M101")
    assert hint.startswith("auto, 7ch, 20mm, 30% (of the text room)")
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
    res = build("| A {.compact align=right} | B |\n|---|---|\n| x | y |\n")
    assert said(res, "M101") == [".compact, align= at the end of a title cell do nothing"]


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


def test_check_says_each_distinct_set_of_widths_once_with_data(capsys, tmp_path):
    (tmp_path / "rows.csv").write_text("item\nRice\nBlack beans in a big bag\nRice\n")
    doc = tmp_path / "label.bob.md"
    doc.write_text("| N {width=3ch} | Item |\n|---|---|\n| 1 | {{ item }} |\n{.compact}\n")
    assert cli.main(["check", str(doc), "--data", str(tmp_path / "rows.csv")]) == cli.OK
    err = capsys.readouterr().err
    assert err.count("[L108]") == 2  # Rice twice: once; the label whose auto column is wider: its own
    assert "N 3 · Item 4 (+1 gap = 8 of 32)" in err and "N 3 · Item 24 (+1 gap = 28 of 32)" in err


# --- review fixes ------------------------------------------------------------------------------------------------


def test_percentages_are_of_the_text_room_and_100_percent_fills_it_without_l107():
    res = build("| A {width=50%} | B {width=50%} |\n|---|---|\n| x | y |\n")
    assert "L107" not in codes(res)
    assert notes(res) == ["column widths: A 16 · B 15 (+1 gap = 32 of 32)"]  # the text room, 31, filled
    res = build("| A {width=25%} | B {width=75%} |\n|---|---|\n| x | y |\n{font=Terminus size=16px}\n")
    assert "L107" not in codes(res) and notes(res)[0].endswith("A 12 · B 35 (+1 gap = 48 of 48)")


def test_half_and_third_are_shares_of_the_text_room_too():
    assert notes(build("| A {width=half} | B |\n|---|---|\n| x | y |\n")) == [
        "column widths: A 15 · B 16 (+1 gap = 32 of 32)"
    ]


def crowded(extra: str = "") -> str:
    """8 columns given 2ch and 6 auto ones of 2 characters: 8 + 12 + 13 gaps = 33 of 32 even with the widths
    shrunk to 1; at 1 each (14 + 13 = 27) they would fit."""
    head = [f"F{i} {{width=2ch}}" for i in range(8)] + [f"A{i}" for i in range(6)]
    return "| " + " | ".join(head) + " |\n|" + "---|" * 14 + "\n| " + " | ".join(["ab"] * 14) + " |\n" + extra


def test_a_table_with_widths_that_cannot_stand_turns_instead_of_running_past_the_paper():
    res = build(crowded())
    assert "L106" in codes(res) and "L107" not in codes(res)
    assert [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "table"]
    assert notes(res)[0].startswith("turned table, column widths: F0 2 · F1 2")  # the widths along the paper


def test_forced_horizontal_never_prints_past_the_paper_and_says_why():
    res = build(crowded("{orientation=horizontal}\n"))
    assert said(res, "L107") == ["a table of 14 columns needs at least 33 columns standing, the paper has 32: "
                                 "narrowed to fit"]  # fmt: skip
    assert "orientation=vertical" in next(n.suggestion for n in res.nudges if n.code == "L107")
    assert all(len(ln) <= 32 for ln in lines(res)) and notes(res)[0].endswith("= 32 of 32)")
    many = " | ".join(f"C{i}" for i in range(20))
    cut = build(f"| {many} |\n|" + "---|" * 20 + "\n| " + " | ".join("x" for _ in range(20)) + " |\n"
                "{orientation=horizontal}\n")  # fmt: skip
    assert "cut at the paper's edge" in said(cut, "L107")[0] and "column widths" not in said(cut, "L107")[0]
    assert all(len(ln) <= 32 for ln in lines(cut))


def test_a_table_in_a_quote_with_widths_that_cannot_stand_is_narrowed_not_overflowing():
    cells = " | ".join(f"C{i} {{width=4ch}}" for i in range(9))
    res = build(f"> | {cells} |\n> |" + "---|" * 9 + "\n> | " + " | ".join("abcd" for _ in range(9)) + " |\n")
    assert all(len(ln) <= 32 for ln in lines(res)) and "L107" in codes(res)


@pytest.mark.parametrize("profile", ["mtp-ii-58", "epson-tm-t20iii"])
def test_no_combination_of_widths_runs_past_the_paper(profile):
    """Random tables, some with wide characters (2 columns each, never split): no line passes the paper, a wide
    character is never in a column narrower than itself, and a table that does not fit says it was cut."""
    import random
    import unicodedata

    def cols_of(text: str) -> int:
        return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)

    rng = random.Random(7)
    paper = 32 if profile == "mtp-ii-58" else 48
    for _ in range(120):
        n = rng.randint(1, 16)
        cols = [rng.choice([None, 1, 2, 3, 7, 12, 20, 40]) for _ in range(n)]
        head = " | ".join(f"H{i} {{width={f'{w}ch' if w else 'auto'}}}" for i, w in enumerate(cols))  # check says
        body = " | ".join(rng.choice(["x" * rng.randint(1, 9), "字" * rng.randint(1, 3), "a字b"]) for _ in cols)
        doc = f"| {head} |\n|" + "---|" * n + f"\n| {body} |\n{{orientation=horizontal}}\n"
        res = build(doc, profile_name=profile)
        assert all(cols_of(ln) <= paper for ln in lines(res)), (cols, body, lines(res))
        widths = [int(w.rsplit(" ", 1)[1]) for w in notes(res)[0].split(": ", 1)[1].split(" (+")[0].split(" · ")]
        for w, cell in zip(widths, body.split(" | "), strict=True):
            assert "字" not in cell or w >= 2, (cols, body, widths)
        used = sum(widths) + n - 1
        cut = "cut at the paper's edge" in " ".join(said(res, "L107"))
        assert used <= paper or cut, (cols, body, notes(res))


def test_shrink_never_exceeds_its_room():
    from bobina.layout import _shrink

    assert sum(_shrink([40, 1, 1, 1, 1], 32)) <= 32
    for widths in ([40, 1, 1, 1, 1], [7, 7, 7], [100, 3], [1] * 10, [5, 50, 2, 9]):
        for cap in range(len(widths), 60):
            got = _shrink(widths, cap)
            assert sum(got) <= max(cap, len(widths)) and min(got) >= 1, (widths, cap, got)


def test_l108_shows_icons_by_name():
    res = build("| :fragile: Box {width=8ch} | B |\n|---|---|\n| x | y |\n")
    assert notes(res)[0].startswith("column widths: ◆ Box 8")  # as L101 shows a word, never the raw character


def test_chat_and_every_other_path_never_see_l108():
    from bobina.nudges import Nudges

    n = Nudges()
    n.add("L108", "column widths: A 1", 1)
    n.add("L101", "word split", 1)
    assert [x.code for x in n] == ["L101"] and [x.code for x in n.check_only] == ["L108"]


def test_an_escaped_brace_at_the_end_of_a_cell_stays_text():
    res = build("| A \\{width=3ch} | B |\n|---|---|\n| x | 9 \\{prefix=x} |\n")
    assert lines(res)[0].startswith("A {width=3ch}") and lines(res)[1].endswith("9 {prefix=x}")
    assert not codes(res) and not notes(res)


def test_a_real_brace_a_title_cell_does_not_take_is_still_said():
    res = build("| A {.flip} | B \\| C {width=3ch} |\n|---|---|\n| x | y |\n")
    assert said(res, "M101") == [".flip at the end of a title cell does nothing"]
    assert notes(res) == ["column widths: A 28 · B | C 3 (+1 gap = 32 of 32)"]  # an escaped pipe splits nothing


# --- second review ---------------------------------------------------------------------------------------------


def wide_table(n: int, extra: str = "") -> str:
    return "| " + " | ".join(["字"] * n) + " |\n|" + "---|" * n + "\n| " + " | ".join(["字"] * n) + " |\n" + extra


def test_a_column_with_a_wide_character_never_goes_below_2_and_a_table_that_cannot_keep_it_is_cut_and_says_so():
    res = build(wide_table(12, "{orientation=horizontal}\n"))  # 12 x 2 + 11 gaps = 35 of 32: it cannot fit
    assert "cut at the paper's edge" in said(res, "L107")[0] and "narrowed" not in said(res, "L107")[0]
    assert all(len(ln) + ln.count("字") <= 32 for ln in lines(res))  # 字 takes 2 columns
    fits = build(wide_table(10, "{orientation=horizontal}\n"))  # 10 x 2 + 9 = 29: every 字 whole
    assert "L107" not in codes(fits) and [ln.count("字") for ln in lines(fits)] == [10, 10]


def test_list_markers_before_a_row_do_not_shift_the_cells():
    for marker in ("-", "1."):
        pad = " " * (len(marker) + 1)
        res = build(f"{marker} | A \\{{width=5ch}} | B {{width=4ch}} |\n{pad}|---|---|\n{pad}| x | y |\n")
        assert lines(res)[0].lstrip(" •1.").startswith("A {width=5ch}"), (marker, lines(res))
        assert not codes(res) and " · B 4 (+1 gap = " in notes(res)[0], (marker, notes(res))


@pytest.mark.parametrize("profile", ["mtp-ii-58", "epson-tm-t20iii"])
@pytest.mark.parametrize("shares", [["50%", "50%"], ["third"] * 3, ["25%"] * 4])
def test_shares_adding_up_to_100_percent_fill_the_text_room(profile, shares):
    head = " | ".join(f"C{i} {{width={w}}}" for i, w in enumerate(shares))
    res = build(f"| {head} |\n|" + "---|" * len(shares) + "\n| " + " | ".join("x" for _ in shares) + " |\n",
                profile_name=profile)  # fmt: skip
    paper = 32 if profile == "mtp-ii-58" else 48
    assert notes(res)[0].endswith(f"= {paper} of {paper})") and "L107" not in codes(res)


@pytest.mark.parametrize("style", ["plain", "grid", "zebra", "header-invert"])
def test_a_cut_table_is_cut_on_the_right_even_when_placed_right(style):
    many = " | ".join(f"C{i}" for i in range(20))
    res = build(f"| {many} |\n|" + "---|" * 20 + "\n| " + " | ".join(f"{i % 10}" for i in range(20)) + " |\n"
                f"{{orientation=horizontal .right .compact style={style}}}\n")  # fmt: skip
    assert lines(res)[-1].startswith("0 1 2 3"), lines(res)  # the first columns kept, the last ones cut
    assert all(len(ln) <= 32 for ln in lines(res))
    assert said(res, "L107") == ["a table of 20 columns needs at least 39 columns standing, the paper has 32: cut at "
                                 "the paper's edge, even at its narrowest"] or style == "grid"  # fmt: skip


def test_a_squeezed_table_says_l107_once_not_l101_for_every_word():
    res = build(crowded("{orientation=horizontal}\n").replace("| ab |", "| abcdefgh |"))
    assert "L107" in codes(res) and "L101" not in codes(res)


def test_the_terminal_view_of_a_drawn_cut_table_stops_where_the_image_does():
    many = " | ".join(f"C{i}" for i in range(20))
    res = build(f"| {many} |\n|" + "---|" * 20 + "\n| " + " | ".join("x" for _ in range(20)) + " |\n"
                "{orientation=horizontal style=grid}\n")  # fmt: skip
    views = [r for r in res.rows if isinstance(r, BitmapRow) and r.text_rows]
    assert views and all(len("".join(c.ch for c in v.cells)) <= 32 for r in views for v in r.text_rows)


def test_an_empty_auto_column_costs_nothing_when_squeezed():
    head = [f"F{i} {{width=3ch}}" for i in range(9)] + [" "]
    table = "| " + " | ".join(head) + " |\n|" + "---|" * 10 + "\n| " + " | ".join(["abc"] * 9 + [" "]) + " |\n"
    res = build(table + "{orientation=horizontal}\n")
    used = int(notes(res)[0].rsplit("= ", 1)[1].split(" of")[0])
    assert used <= 32 and notes(res)[0].split(" · ")[-1].startswith("column 10 0")


def test_shrink_never_passes_its_room_even_below_one_each():
    from bobina.layout import _shrink

    for widths in ([1] * 10, [3, 3, 3], [40, 1, 1, 1, 1]):
        for cap in range(0, len(widths) + 1):
            assert sum(_shrink(widths, cap)) <= cap, (widths, cap)


# --- the spare room goes to the widest auto column; a font table's view is as wide as its paper ------------------


def test_the_spare_room_goes_to_the_widest_column_of_text():
    """The widest left-aligned auto column takes what is left of the paper (ties: the first); without one, the
    widest auto column."""
    res = build("| Qty | Item | Price |\n|--:|---|--:|\n| 2 | Espresso | 18,00 |\n| 1 | Bagel | 39,00 |\n")
    assert lines(res)[1] == "  2 " + "Espresso".ljust(22) + " 18,00"  # the description takes it, not Qty
    res = build("| Item | Qty | Price |\n|---|--:|--:|\n| Rice | 1 | 9,00 |\n")
    assert lines(res)[1] == "Rice".ljust(22) + "   1  9,00"  # Price is wider, but right-aligned: a number
    res = build("| | |\n|---|--:|\n| SUBTOTAL | 88,00 |\n| TOTAL | 96,80 |\n")
    assert lines(res)[0] == "SUBTOTAL".ljust(27) + "88,00"  # a total's label still does
    res = build("| ab | cd |\n|---|---|\n| x | y |\n")
    assert lines(res)[0] == "ab".ljust(30) + "cd"  # a tie: the first
    res = build("| a | bbb |\n|--:|--:|\n| 1 | 2 |\n")
    assert lines(res)[0] == "a" + " bbb".rjust(31)  # nothing left-aligned: the widest auto column


def test_a_short_code_column_on_58mm_leaves_the_room_to_the_description():
    res = build("| IT | CÓD | DESCRIÇÃO | TOTAL |\n|---|---|---|--:|\n| 001 | 1431 | CEBOLA KG | 14,25 |\n"
                "| 003 | 7369 | BANANA PRATA | 16,33 |\n", profile_name="mtp-ii-58")  # fmt: skip
    assert lines(res)[1] == "001 1431 " + "CEBOLA KG".ljust(17) + " 14,25"


def test_a_column_of_codes_is_not_text_even_left_aligned():
    """A left-aligned column with no letter in its body (a 13-digit code) is not text: the name gets the room."""
    res = build("| Código | Nome |\n|---|---|\n| 7896016500213 | Lentilha |\n| 2000000010014 | Arroz |\n")
    assert lines(res) == ["Código        Nome", "7896016500213 Lentilha", "2000000010014 Arroz"]


def test_the_view_of_a_font_table_without_titles_keeps_every_value_whole():
    """A headerless raster-font table in a smaller font: on its own grid of 48 columns, the label on the left, the
    value whole at the table's right edge, not next to its label."""
    res = build('| | {prefix="R$ "} |\n|---|--:|\n| SUBTOTAL | 105,70 |\n| TROCO | 7,57 |\n{font=Terminus size=16px}\n')
    assert notes(res)[0].endswith("(+1 gap = 48 of 48)")
    assert lines(res) == ["SUBTOTAL".ljust(39) + "R$ 105,70", "TROCO".ljust(41) + "R$ 7,57"]
