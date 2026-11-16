"""Things that printed wrong without a word: an attribute at the end of an inner line of a paragraph, inline
styles in table cells, cells cut in the middle of a word, table attributes that do nothing, and an attribute line
right under a table."""

from bobina.engine import build
from bobina.rows import BitmapRow, FeedRow, TextRow
from bobina.templating import Tainted


def text_rows(res):
    return [r for r in res.rows if isinstance(r, TextRow)]


def lines(res):
    return ["".join(c.ch for c in r.cells) for r in text_rows(res)]


def codes(res):
    return [n.code for n in res.nudges]


def feeds_between_text(res):
    """The feeds after the first text row and before the last one (block gaps)."""
    idx = [i for i, r in enumerate(res.rows) if isinstance(r, TextRow)]
    return [r for r in res.rows[idx[0] : idx[-1]] if isinstance(r, FeedRow)]


# --- 1. an attribute at the end of an inner line closes the lines above it ----------------------------------------


def test_an_inner_line_attribute_closes_the_lines_above_it():
    res = build("A\nB {.center}\nC\nD {.right}\n")
    assert lines(res) == ["A", "B", "C", "D"]
    assert [r.align for r in text_rows(res)] == ["center", "center", "right", "right"]
    assert not feeds_between_text(res)  # line breaks, not paragraphs: no block gap between the segments
    assert not res.nudges


def test_the_lines_after_the_last_attribute_keep_the_document_alignment():
    res = build("Pedido #85328948 {.center}\nMesa 4\n")
    assert lines(res) == ["Pedido #85328948", "Mesa 4"]
    assert [r.align for r in text_rows(res)] == ["center", "left"]


def test_only_the_last_line_with_an_attribute_is_the_whole_paragraph_as_before():
    res = build("A\nB {.center}\n")
    assert lines(res) == ["A", "B"] and [r.align for r in text_rows(res)] == ["center", "center"]
    assert len(res.doc.blocks) == 1


def test_an_attribute_line_of_its_own_inside_a_paragraph_prints_no_empty_line():
    res = build("A\n{.center}\nB\n")
    assert lines(res) == ["A", "B"] and [r.align for r in text_rows(res)] == ["center", "left"]
    res = build("A\n{.center}\n")
    assert lines(res) == ["A"]


def test_a_span_at_the_end_of_an_inner_line_stays_a_span():
    res = build("Total [R$ 9,00]{.bold}\nobrigado {.center}\n")
    assert lines(res) == ["Total R$ 9,00", "obrigado"]
    first = text_rows(res)[0]
    assert [c.bold for c in first.cells if c.ch != " "] == [False] * 5 + [True] * 6
    assert [r.align for r in text_rows(res)] == ["center", "center"]  # one paragraph: the last line's attribute


def test_a_value_from_data_is_never_an_attribute_on_an_inner_line():
    res = build("{{ v }}\nB {.right}\n", fields={"v": Tainted("Pedido {.center}")})
    assert lines(res) == ["Pedido {.center}", "B"]
    assert [r.align for r in text_rows(res)] == ["right", "right"]
    res = build("Pedido {{ v }}\nB\n", fields={"v": Tainted("{.center}")})
    assert lines(res) == ["Pedido {.center}", "B"]
    assert [r.align for r in text_rows(res)] == ["left", "left"]


def test_inner_line_attributes_are_checked_like_any_other():
    res = build("A {.centre}\nB\n")
    assert "M101" in codes(res) and lines(res) == ["A", "B"]


def test_inner_line_attributes_work_in_list_items_and_quotes():
    res = build("- milk {.right}\n  bread\n")
    assert lines(res) == ["• milk", "  bread"]
    assert [r.align for r in text_rows(res)] == ["right", "left"]
    res = build("> A {.center}\n> B\n")
    assert [r.align for r in text_rows(res)] == ["left", "left"]  # a quote centres inside its bar: by padding
    assert lines(res)[0].strip().endswith("A") and "{" not in "".join(lines(res))


def test_a_done_task_strikes_every_segment():
    res = build("- [x] milk {.right}\n  bread\n")
    rows = text_rows(res)
    assert all(c.strike for r in rows for c in r.cells if c.ch.isalpha())


# --- 2. inline styles in table cells ------------------------------------------------------------------------------

BILL = "| ITEM | VALOR |\n|---|--:|\n| Couvert | 9,00 |\n| **(=) TOTAL** | **27,00** |\n"


def test_bold_in_a_table_cell_prints_bold_natively():
    res = build(BILL)
    total = next(r for r in text_rows(res) if "TOTAL" in "".join(c.ch for c in r.cells))
    assert total.native
    assert all(c.bold for c in total.cells if c.ch != " ")
    couvert = next(r for r in text_rows(res) if "Couvert" in "".join(c.ch for c in r.cells))
    assert not any(c.bold for c in couvert.cells)


def test_italic_strike_and_mono_in_cells_keep_the_grid_and_print_as_their_style():
    res = build("| a | b |\n|---|---|\n| *it* | ~~st~~ |\n| `mo` | x |\n")
    rows = text_rows(res)
    styled = rows[1]
    assert "".join(c.ch for c in styled.cells).split() == ["it", "st"]
    assert not styled.native and styled.reason in ("italic", "strike")
    letters = [c for c in styled.cells if c.ch != " "]
    assert [(c.italic, c.strike) for c in letters] == [(True, False)] * 2 + [(False, True)] * 2
    assert "".join(c.ch for c in rows[2].cells).split() == ["mo", "x"] and rows[2].native


def test_column_widths_measure_the_visible_text_not_the_markers():
    plain = build("| A | B |\n|---|---|\n| (=) TOTAL | 1 |\n{.compact}\n")
    bold = build("| A | B |\n|---|---|\n| **(=) TOTAL** | 1 |\n{.compact}\n")
    assert lines(plain) == lines(bold)


def test_styles_in_a_turned_table_are_drawn():
    res = build(
        "| " + " | ".join(f"c{i}" for i in range(4)) + " |\n|" + "---|" * 4 + "\n| **a** | b | c | d |\n"
        "\n{orientation=vertical}\n"
    )
    table = next(r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "table")
    body = table.text_rows[1]
    assert [c.bold for c in body.cells if c.ch != " "] == [True, False, False, False]


# --- 3. cells wrap at spaces, columns keep their longest word -----------------------------------------------------

FOUR = (
    "| Q | DESCRICAO | VLITM | VLTOT |\n|---|---|--:|--:|\n"
    "| 1 | CHA GEL INTUICAO | 18,00 | 18,00 |\n| 1 | ABACAXI PEROLA GRANDE | 18,00 | 18,00 |\n"
)


def test_cells_wrap_at_spaces():
    res = build(FOUR, profile_name="mtp-ii-58")
    out = lines(res)
    words = {w for line in out for w in line.split()}
    assert {"DESCRICAO", "ABACAXI", "PEROLA", "GRANDE", "INTUICAO"} <= words
    assert all(len(line) <= 32 for line in out)
    assert "L101" not in codes(res)


SEVEN = (
    "| ITEM | CODIGO | DESCRICAO | QTD. | UN. | VL.UNIT | VL.TOTAL |\n|--:|---|---|--:|---|--:|--:|\n"
    "| 001 | 7896016500213 | AGUA MINERAL SEM GAS 500ML | 2 | UN | 4,50 | 9,00 |\n"
    "| 002 | 7891000100103 | ABACAXI PEROLA GRANDE | 1 | KG | 18,00 | 18,00 |\n"
)


def test_seven_columns_on_80mm_keep_the_data_whole_and_say_the_header_word_they_cut():
    """Their longest words take 43 of the 42 columns: one column gives way, a header word's before any data, and
    VL.UNIT wraps after its dot. What was cut is said."""
    res = build(SEVEN, profile_name="epson-tm-t20ii")
    out = lines(res)
    assert all(len(line) <= 48 for line in out)
    words = {w for line in out for w in line.split()}
    data = {"7896016500213", "7891000100103", "AGUA", "MINERAL", "500ML", "ABACAXI", "PEROLA", "GRANDE", "18,00"}
    assert data <= words
    assert {"ITEM", "CODIGO", "QTD.", "UN.", "VL.", "UNIT", "TOTAL"} <= words
    cut = [n for n in res.nudges if n.code == "L101"]
    assert len(cut) == 1 and "DESCRICAO" in cut[0].message
    assert "L106" not in codes(res)  # readable standing: never turned


def test_a_column_keeps_its_longest_word_when_the_table_can_afford_it():
    res = build(SEVEN.replace("DESCRICAO", "DESCR."), profile_name="epson-tm-t20ii")
    assert "L101" not in codes(res)
    assert "DESCR." in lines(res)[0].split()


def test_a_word_longer_than_any_column_can_be_is_split_and_said():
    word = "X" * 40
    res = build(f"| a | b |\n|---|---|\n| {word} | 1 |\n", profile_name="mtp-ii-58")
    assert "L101" in codes(res)
    note = next(n for n in res.nudges if n.code == "L101")
    assert "XXXX" in note.message
    assert "".join("".join(line.split()[:1]) for line in lines(res)[1:]).count("X") == 40  # nothing lost


def test_a_wide_icon_is_never_cut_from_its_column():
    res = build("| a | b |\n|---|---|\n| :heart: :heart: :heart: | 1 |\n{.compact}\n")
    assert all(r.columns() <= 32 for r in text_rows(res))


# --- 4. attributes a table does not take say so -------------------------------------------------------------------


def test_keys_a_table_does_not_take_are_said_with_the_ones_it_takes():
    res = build("| a | b |\n|---|---|\n| 1 | 2 |\n\n{leading=4 tracking=2}\n")
    notes = [n for n in res.nudges if n.code == "M101"]
    assert {"leading=", "tracking="} <= {w for n in notes for w in ("leading=", "tracking=") if w in n.message}
    assert any("font=" in n.suggestion and "style=" in n.suggestion for n in notes)
    res = build("| a | b |\n|---|---|\n| 1 | 2 |\n\n{font=Terminus size=16px}\n")  # a table takes them now
    assert "M101" not in codes(res)


def test_classes_a_table_does_not_take_are_said():
    res = build("| a | b |\n|---|---|\n| 1 | 2 |\n\n{.bold .invert}\n")
    msgs = " ".join(n.message for n in res.nudges if n.code == "M101")
    assert ".bold" in msgs and ".invert" in msgs


def test_attributes_a_table_takes_are_not_nudged():
    for attrs in (".compact", ".compact .center", ".compact .right", "orientation=horizontal", "rotate=180", ".flip",
                  ".compact align=right", "#bill"):  # fmt: skip
        res = build(f"| a | b |\n|---|---|\n| 1 | 2 |\n\n{{{attrs}}}\n")
        assert "M101" not in codes(res), attrs
    res = build("| a | b |\n|---|---|\n| 1 | 2 |\n\n{orientation=vertical width=half .left}\n")
    assert "M101" not in codes(res)


# --- 5. an attribute line right under a table ---------------------------------------------------------------------


def test_an_attribute_line_right_under_a_table_applies_to_it():
    glued = build("| a | b |\n|---|---|\n| 1 | 2 |\n{.compact}\n")
    apart = build("| a | b |\n|---|---|\n| 1 | 2 |\n\n{.compact}\n")
    assert lines(glued) == lines(apart) == ["a b", "1 2"]
    assert glued.doc.blocks[0].attrs.has("compact")
    assert not glued.nudges


def test_a_row_that_only_looks_like_attributes_stays_a_row():
    res = build("| a | b |\n|---|---|\n| {.compact} | 2 |\n")  # a cell, written with its pipes: data
    assert "{.compact}" in "".join(lines(res))
    res = build("| a | b |\n|---|---|\n| 1 | 2 |\n{not attributes here}\n")
    assert "{not attributes here}" in "".join(lines(res))


def test_an_attribute_line_under_a_table_is_checked():
    res = build("| a | b |\n|---|---|\n| 1 | 2 |\n{.compactt}\n")
    assert "M101" in codes(res) and "{" not in "".join(lines(res))


# --- 6. a header of empty cells is no header (Pandoc's headerless pipe table) -------------------------------------

TOTALS = "Conta\n\n| | |\n|---|--:|\n| SUBTOTAL: | 157,50 |\n| TOTAL : | 176,40 |\n"


def test_a_header_of_empty_cells_prints_no_header_and_no_rule():
    res = build(TOTALS, profile_name="mtp-ii-58")
    assert lines(res) == ["Conta", "SUBTOTAL:" + " " * 17 + "157,50", "TOTAL :" + " " * 19 + "176,40"]
    assert not any(isinstance(r, BitmapRow) and r.kind == "divider" for r in res.rows)


def test_a_header_with_one_word_is_still_a_header():
    res = build("| | Valor |\n|---|--:|\n| a | 1 |\n")
    assert lines(res)[0].split() == ["Valor"]
    assert any(isinstance(r, BitmapRow) and r.kind == "divider" for r in res.rows)


def test_a_turned_table_without_a_header_has_none():
    res = build("| | | | |\n|---|---|---|---|\n| a | b | c | d |\n\n{orientation=vertical}\n")
    table = next(r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "table")
    assert ["".join(c.ch for c in r.cells).split() for r in table.text_rows] == [["a", "b", "c", "d"]]
    px = table.image.load()  # no rule: no column of ink across the whole table
    longest = max(sum(1 for y in range(table.image.height) if px[x, y] == 0) for x in range(table.image.width))
    assert longest < table.image.height // 2
    assert len(lines(build("| | | | |\n|---|---|---|---|\n| a | b | c | d |\n"))) == 1


# --- review fixes -------------------------------------------------------------------------------------------------


def test_an_empty_or_id_only_brace_on_an_inner_line_stays_text():
    assert lines(build("Mesa {#5}\nPedido 12\n")) == ["Mesa {#5}", "Pedido 12"]
    assert lines(build("A {}\nB\n")) == ["A {}", "B"]


def test_an_attribute_line_under_a_table_is_found_after_unusual_line_separators():
    for sep in (" ", "\x0c", "\x85"):
        res = build(f"Intro x{sep}y\n\n| a | b |\n|---|---|\n| 1 | 2 |\n{{.compact}}\n")
        table = next(b for b in res.doc.blocks if type(b).__name__ == "Table")
        assert table.attrs.has("compact") and "{.compact}" not in "".join(lines(res)), repr(sep)


def test_a_loose_paragraph_in_a_done_task_is_not_struck_in_any_of_its_segments():
    res = build("- [x] Done\n\n  More A {.right}\n  More B\n")
    more = [r for r in text_rows(res) if "More" in "".join(c.ch for c in r.cells)]
    assert len(more) == 2
    assert not any(c.strike for r in more for c in r.cells)


def test_a_span_size_or_font_in_a_cell_is_said_to_do_nothing():
    res = build("| [Total]{size=large} | [x]{font=serif} |\n|---|---|\n| 1 | 2 |\n")
    msgs = " ".join(n.message for n in res.nudges if n.code == "M101")
    assert "size=" in msgs and "font=" in msgs and "cell" in msgs


def test_when_not_even_the_data_words_fit_only_the_longest_is_cut():
    """The date (32 columns, no place to wrap) can never fit 31; the other column keeps its words whole (it wraps
    at its dots) and only the date is cut, once."""
    res = build("| D | V |\n|---|---|\n| 15/11/2026-15/12/2026-15/01/2027 | VL.TOTAL.GERAL.DO.PEDIDO |\n",
                profile_name="mtp-ii-58")  # fmt: skip
    words = {w for line in lines(res) for w in line.split()}
    assert {"VL.", "TOTAL.", "GERAL.", "DO.", "PEDIDO"} <= words
    cut = [n for n in res.nudges if n.code == "L101"]
    assert len(cut) == 1 and "15/11/2026" in cut[0].message


def test_a_cut_column_keeps_its_shorter_data_words_whole():
    """natural [40, 10], data words [40, 4], 31 columns: the 40-letter word is cut, the 25-letter one in the same
    column stays whole (27 columns), and the header word of the other column gives way (4 columns)."""
    long, mid = "A" * 40, "B" * 25
    res = build(f"| H | HEADERWORD |\n|---|---|\n| {long} | abcd |\n| {mid} | ab |\n", profile_name="mtp-ii-58")
    assert mid in {w for line in lines(res) for w in line.split()}


def test_a_turned_trial_that_does_not_print_says_nothing():
    long = "a long remark about this one item " * 6
    head = "| " + " | ".join(f"Col{c}" for c in range(7)) + " |\n|" + "---|" * 7 + "\n"
    body = "".join("| " + " | ".join(long if (r, c) == (0, 6) else f"it{r:02}{c}" for c in range(7)) + " |\n"
                   for r in range(60))  # fmt: skip
    res = build(head + body + "\n{width=abc}\n")
    assert not any(isinstance(r, BitmapRow) and r.kind == "table" for r in res.rows)  # it stands
    assert len([n for n in res.nudges if n.code == "M101" and "width" in n.message]) == 1
    assert "L104" not in codes(res)


def test_attribute_problems_are_reported_on_their_own_line():
    res = build("A {.center}\nB {.foo}\n{.bar}\nC\n")
    at = {n.message: n.line for n in res.nudges if n.code == "M101"}
    assert at == {"unknown class '.foo'": 2, "unknown class '.bar'": 3}
    res = build("| a | b |\n|---|---|\n| 1 | 2 |\n{leading=4}\n")
    assert [n.line for n in res.nudges if n.code == "M101"] == [4]
    res = build("| a | b |\n|---|---|\n| 1 | 2 |\n\n{style=fancy}\n")
    assert [n.line for n in res.nudges if n.code == "M101"] == [5]


def test_a_header_of_any_kind_of_blank_is_no_header():
    res = build("| &#12288; | &nbsp; |\n|---|---|\n| a | b |\n")
    assert not any(isinstance(r, BitmapRow) and r.kind == "divider" for r in res.rows)
    assert lines(res)[0].split() == ["a", "b"]


def test_the_table_hint_lists_everything_a_table_takes():
    res = build("| a | b |\n|---|---|\n| 1 | 2 |\n\n{leading=4}\n")
    hint = next(n.suggestion for n in res.nudges if n.code == "M101")
    for word in (".compact", ".left", ".center", ".right", ".flip", "align=", "orientation=", "width=", "rotate=",
                 "font=", "size=", "style=", "#id"):  # fmt: skip
        assert word in hint


# --- second review ------------------------------------------------------------------------------------------------


def test_one_long_word_is_said_once_in_a_cell_and_in_a_paragraph():
    word = "".join(chr(65 + i % 26) for i in range(70))  # ABC…: each cut leaves a different rest of the word
    cell = build(f"| {word} | b |\n|---|---|\n| 1 | 2 |\n{{.compact}}\n", profile_name="mtp-ii-58")
    para = build(word + "\n", profile_name="mtp-ii-58")
    for res in (cell, para):
        assert [n.code for n in res.nudges].count("L101") == 1


def test_every_segment_of_a_list_items_first_text_takes_the_same_path_done_or_open():
    for box in ("[ ] ", "[x] ", ""):
        res = build(f"- {box}milk {{rotate=90}}\n  bread {{.flip}}\n  eggs\n")
        out = lines(res)
        assert out[0].endswith(" milk") and [x.strip() for x in out[1:]] == ["bread", "eggs"], box
        assert len({len(x) - len(x.lstrip()) for x in out[1:]}) == 1  # the same indent: one path
        assert not any(isinstance(r, BitmapRow) and r.kind == "rotated" for r in res.rows), box
        notes = [n for n in res.nudges if n.code == "M101"]
        assert {n.line for n in notes} == {1, 2} and all("list item" in n.message for n in notes), box


def test_a_loose_paragraph_in_a_list_is_still_a_block_of_its_own():
    res = build("- milk\n\n  bread {rotate=180}\n")
    assert any(isinstance(r, BitmapRow) and r.kind == "rotated" for r in res.rows)
    assert "M101" not in codes(res)


def test_each_idle_table_attribute_is_said_on_the_line_it_was_written_on():
    res = build("| a | b |\n|---|---|\n| 1 | 2 |\n{.bold}\n\n{leading=4}\n")
    at = {n.line: n.message for n in res.nudges if n.code == "M101"}
    assert set(at) == {4, 6} and ".bold" in at[4] and "leading=" in at[6]


def test_a_span_size_in_a_body_cell_is_said_on_its_row():
    res = build("| a | b |\n|---|---|\n| 1 | 2 |\n| [big]{size=large} | 3 |\n")
    note = next(n for n in res.nudges if n.code == "M101")
    assert note.line == 4
    assert "table's font" in note.suggestion and "orientation=" not in note.suggestion  # its own hint, not a table's


def test_a_code_span_across_a_newline_keeps_the_line_numbers():
    res = build("A `x\ny` B\nC {.foo}\nD\n")
    assert [n.line for n in res.nudges if n.code == "M101"] == [3]
    res = build("A `x\ny` B\nC {.foo}\n")
    assert [n.line for n in res.nudges if n.code == "M101"] == [3]


def test_a_wide_character_on_a_line_narrower_than_it_is_not_said_to_be_split():
    from bobina.layout import word_tokens, wrap_words
    from bobina.rows import Cell

    said = []
    out = wrap_words(word_tokens([Cell("中", wide=True)]), 1, 0, lambda w, at: said.append(at))
    assert [[c.ch for c in line] for line in out] == [["中"]] and not said
    out = wrap_words(word_tokens([Cell("中", wide=True), Cell("文", wide=True)]), 1, 0, lambda w, at: said.append(at))
    assert [[c.ch for c in line] for line in out] == [["中"], ["文"]] and said == [1]
