"""White text on black below the size the paper holds prints bold (paper, MTP-II 18/11: the printer font at 1x closed
up, even bold; at 2x it held), and bobina says so (F206). And a span's attributes: size= on part of a line, and the
names a span does not take (M101)."""

from pathlib import Path

from bobina import chat, escpos, preview, rasterfont
from bobina.emulator import Emulator
from bobina.engine import apply_overrides, build
from bobina.profile import load
from bobina.rows import BitmapRow, TextRow

ROOT = Path(__file__).resolve().parents[1]
ESC, GS = b"\x1b", b"\x1d"
OFF = {"raster.invert_bold_below_px": 0}  # a printer whose paper holds thin white text: no bold added
FONT = "---\nfonts:\n  body: Atkinson Hyperlegible\n---\n"


def codes(res) -> list[str]:
    return [n.code for n in res.nudges]


def said(res, code: str) -> list[str]:
    return [n.message for n in res.nudges if n.code == code]


def drawn(res) -> list[BitmapRow]:
    return [r for r in res.rows if isinstance(r, BitmapRow)]


def white(im) -> int:
    """White dots inside the black: the white letters' ink."""
    return im.convert("L").histogram()[255]


def untested(res) -> bool:
    return any("white-on-black" in m for m in said(res, "P301"))


# --- the printer font -------------------------------------------------------------------------------------------


def test_an_inverted_line_at_1x_prints_bold_and_a_dot_taller():
    res, thin = (
        build("ON-CHAIN SUPPLY {.invert .center}\n"),
        build("ON-CHAIN SUPPLY {.invert .center}\n", overrides=OFF),
    )
    band = drawn(res)[0]
    assert band.kind == "band" and all(c.bold for c in band.text_rows[0].cells if c.ch != " ")
    assert white(band.image) > white(drawn(thin)[0].image) * 1.5  # bold and taller: much more white letter
    assert said(res, "F206") == ["inverted text printed bold (1x on line 1): ink fills thin white strokes"]
    assert untested(res) and "F206" not in codes(thin) and not untested(thin)


def test_f206_is_said_once_for_the_document_with_every_place():
    src = (
        "A {.invert}\n\nB {.invert}\n\nC {.invert}\n\nTotal [9,00]{.invert}\n\n"
        + BILL
        + "| Tea | 2 | 18,00 | {.invert}\n| Pie | 1 | 9,00 | {.invert}\n\n"
        + BILL
        + "| Tea | 2 | 18,00 | {.invert}\n\n"
        + "Big {.invert size=2x}\n"
    )
    assert said(build(src), "F206") == [
        "inverted text printed bold (1x on lines 1, 3, 5, 7 and the tables at lines 9, 15): ink fills thin white "
        "strokes"
    ]
    res = build(FONT + "Thanks {.invert size=24px}\n\nA [b]{.invert} c {render=native}\n")
    assert said(res, "F206") == [
        "inverted text printed bold (24px on line 5; 1x on line 7): ink fills thin white strokes"
    ]


def test_a_word_inverted_inside_an_inverted_line_stays_black_and_thin():
    res, thin = build("A [b-c]{.invert} d {.invert}\n"), build("A [b-c]{.invert} d {.invert}\n", overrides=OFF)
    cells = drawn(res)[0].text_rows[0].cells
    assert [c.heavy for c in cells if c.ch.strip()] == [True, False, False, False, True]  # A, b-c, d
    im, ref = drawn(res)[0].image.convert("L"), drawn(thin)[0].image.convert("L")
    word = (2 * 12, 0, 5 * 12, im.height)  # b-c: black on white, as it was
    assert im.crop(word) == ref.crop(word) and im != ref


def test_a_drawn_quote_line_at_2x1_draws_its_inverted_word_heavy():
    src = "> [a-b]{.invert} c {size=2x1}\n"
    res, thin = build(src), build(src, overrides=OFF)
    assert white(drawn(res)[0].image) > white(drawn(thin)[0].image)
    assert any(c.heavy for v in drawn(res)[0].text_rows for c in v.cells)


def test_descenders_of_heavy_letters_are_whole():
    im = drawn(build("gy {.invert}\n"))[0].image.convert("L")
    bottom = max(y for y in range(im.height) if any(im.getpixel((x, y)) for x in range(24)))
    assert bottom > 4 + 24 - 1  # the descender's last row grew a dot down, into the line's gap


def test_a_heavy_inverted_word_keeps_its_cell_in_a_box():
    src = "::: {.box}\nOrder [T-7]{.invert} ready\n:::\n"
    box, thin = drawn(build(src))[0].image, drawn(build(src, overrides=OFF))[0].image
    assert box.size == thin.size and box != thin  # heavier white, the black box no dot taller


def test_a_heavy_stretched_hyphen_stays_two_dots_tall():
    def tallest(heavy: bool) -> int:
        path = rasterfont.resolve("Spleen").path
        t = rasterfont.Tok("-", path, 24, bold=True, invert=True, heavy=heavy, stretch=2.0)
        asc, desc = t.font.getmetrics()
        im = rasterfont.draw_tok(t, asc, asc + desc)
        column = "".join("w" if im.getpixel((im.width // 2, y)) > 127 else "k" for y in range(asc + desc))
        return max(len(r) for r in column.split("k"))

    assert (tallest(True), tallest(False)) == (2, 1)  # 2x1: thickened at its own size, never squashed back
    src = "A-B [xy-z]{size=2x1 .invert}\n"
    assert drawn(build(src))[0].image != drawn(build(src, overrides=OFF))[0].image and "F206" in codes(build(src))


def test_the_hyphen_is_two_dots_tall_white_on_black():
    def tallest(res) -> int:
        im = drawn(res)[0].image.convert("L")
        column = "".join("w" if im.getpixel((12 + 6, y)) else "k" for y in range(im.height))  # the hyphen's middle
        return max(len(r) for r in column.split("k"))

    assert tallest(build("A-B {.invert}\n")) == 2
    assert tallest(build("A-B {.invert}\n", overrides=OFF)) == 1  # what closed up on paper (18/11)


def test_an_inverted_line_at_2x_keeps_its_weight():
    res = build("BRS multichain {.invert .center size=2x}\n")
    assert not any(c.bold for c in drawn(res)[0].text_rows[0].cells)
    assert "F206" not in codes(res) and not untested(res)
    assert drawn(res)[0].image == drawn(build("BRS multichain {.invert .center size=2x}\n", overrides=OFF))[0].image


def test_text_already_bold_gets_no_note():
    res = build("**PAID** {.invert}\n")
    assert "F206" not in codes(res) and untested(res)  # drawn a dot taller all the same: not tested on paper


def test_a_native_inverted_run_is_one_esc_e_spaces_included():
    data = build("Total [9,00 EUR now]{.invert} ok\n").data
    run = ESC + b"E\x01" + GS + b"B\x01" + b"9,00 EUR now" + ESC + b"E\x00" + GS + b"B\x00"
    assert run in data and data.count(ESC + b"E\x01") == 1  # as before the review: no ESC E toggled at spaces
    assert build("Hello world\n").data == bytes.fromhex(  # a document with nothing inverted: bytes as before it all
        "1b401b4a181b331e1b61001d210048656c6c6f20776f726c640a1d21001b45001b2d001d42001b61001b4a58"
    )


def test_a_native_inverted_word_gets_esc_e_with_gs_b():
    res = build("Total [9,00]{.invert} now\n")
    row = next(r for r in res.rows if isinstance(r, TextRow))
    assert row.native and all(c.bold for c in row.cells if c.invert)
    assert not any(c.bold for c in row.cells if not c.invert)
    data = escpos.text_row(row, Emulator(load()))
    assert ESC + b"E\x01" + GS + b"B\x01" + b"9,00" in data and "F206" in codes(res)
    assert any("ESC E under GS B" in m for m in said(res, "P301"))  # what paper has to show


def test_a_band_box_title_is_drawn_heavier():
    src = '::: {.box title="ON-CHAIN SUPPLY" title-style=band}\nbody\n:::\n'
    res, thin = build(src), build(src, overrides=OFF)
    assert white(drawn(res)[0].image) > white(drawn(thin)[0].image)  # bold already: a dot taller
    assert "F206" not in codes(res) and untested(res)


# --- tables -------------------------------------------------------------------------------------------------------

BILL = "| Item | Qty | Price |\n|---|--:|--:|\n| Rice | 1 | 9,00 |\n"


def test_header_invert_titles_are_drawn_heavier_without_a_note():
    src = BILL + "{style=header-invert}\n"
    res, thin = build(src), build(src, overrides=OFF)
    assert white(drawn(res)[0].image) > white(drawn(thin)[0].image)
    assert codes(res) == ["P301"] and codes(thin) == []


def test_an_inverted_row_prints_bold():
    res = build(BILL + "| Tea-bag | 2 | 18,00 | {.invert}\n")
    row = next(r for r in drawn(res) if r.kind == "band")
    assert all(c.bold for v in row.text_rows for c in v.cells if c.ch.strip())
    assert said(res, "F206") == ["inverted text printed bold (1x on the table at line 1): ink fills thin white strokes"]


def test_an_inverted_word_in_a_table_cell_is_treated_as_in_a_paragraph():
    res = build("| Item | Price |\n|---|---|\n| [T-7]{.invert} tea | 9,00 |\n")
    row = next(r for r in res.rows if isinstance(r, TextRow) and "T-7" in "".join(c.ch for c in r.cells))
    assert all(c.heavy and c.bold for c in row.cells if c.invert and c.ch.strip())
    assert not any(c.heavy for c in row.cells if not c.invert)
    assert said(res, "F206") == ["inverted text printed bold (1x on the table at line 1): ink fills thin white strokes"]
    assert untested(res)


def test_a_word_inverted_inside_an_inverted_row_shows_black_in_the_view():
    def band(src):
        row = next(r for r in drawn(build(src)) if r.kind == "band")
        return {c.ch: c.invert for v in row.text_rows for c in v.cells if c.ch.strip()}

    table = band("| Item | Price |\n|---|---|\n| [T-7]{.invert} tea | 9,00 | {.invert}\n")
    assert not table["T"] and not table["7"] and table["e"] and table["9"]  # T-7 black on paper, the rest white
    line = band("A [b-c]{.invert} d {.invert}\n")
    assert line["A"] and not line["b"] and line["d"]
    titles = band("| Item | Price |\n|---|---|\n| Tea | 9,00 |\n{style=header-invert}\n")
    assert all(titles.values())


def test_a_table_without_white_text_looks_up_no_bold_face(monkeypatch):
    from bobina import layout

    asked, real = [], layout.rasterfont.resolve
    monkeypatch.setattr(layout.rasterfont, "resolve", lambda fam, bold=False: asked.append(bold) or real(fam, bold))
    build("| Item | Price |\n|---|---|\n| Tea | 9,00 |\n{style=receipt font=Terminus size=20px}\n")
    assert asked and True not in asked  # nothing printed white, nothing bold: no bold face looked up


def test_a_table_in_a_raster_font_takes_its_bold_face_and_no_p301():
    res = build(BILL + "| Tea | 2 | 18,00 | {.invert}\n{font=Terminus size=20px}\n")
    assert said(res, "F206") == [
        "inverted text printed bold (20px on the table at line 1): ink fills thin white strokes"
    ]
    assert "P301" not in codes(res)  # a real bold face: R2-12 tested it on paper


# --- raster fonts -------------------------------------------------------------------------------------------------


def test_a_raster_line_below_48px_takes_the_bold_face():
    res = build(FONT + "Thanks {.invert size=24px}\n")
    assert said(res, "F206") == ["inverted text printed bold (24px on line 5): ink fills thin white strokes"]
    assert "F204" not in codes(res) and "P301" not in codes(res)
    assert "F206" not in codes(build(FONT + "Thanks {.invert size=48px}\n"))


def test_f204_is_only_the_size_now():
    res = build(FONT + "Thanks {.invert size=16px}\n")
    assert said(res, "F204") == ["inverted text at 16px closes up"] and "F206" in codes(res)
    assert "F204" not in codes(build(FONT + "Thanks {.invert size=48px}\n"))  # regular at 48px held (18/11)


# --- chat ----------------------------------------------------------------------------------------------------------


def test_a_black_chat_bubble_has_bold_white_letters():
    heavy = chat.bubble_row(load(), "T-7 ok", inverted=True)
    thin = chat.bubble_row(apply_overrides(load(), OFF), "T-7 ok", inverted=True)
    assert white(heavy.image) > white(thin.image)


def test_a_black_chat_bubble_drawn_as_an_image_is_heavy_too():
    for text in ("שלום ok", "★ ok"):  # drawn whole (right to left), a glyph the printer font lacks
        heavy = chat.bubble_row(load(), text, inverted=True).image
        assert heavy != chat.bubble_row(apply_overrides(load(), OFF), text, inverted=True).image, text


def test_a_black_chat_bubble_still_reads_its_bold_markup():
    marked = chat.bubble_row(load(), "**T-7** ok", inverted=True)
    assert marked.image == chat.bubble_row(load(), "T-7 ok", inverted=True).image  # no asterisks printed
    thin = chat.bubble_row(apply_overrides(load(), OFF), "**T-7** ok", inverted=True)
    assert thin.image != chat.bubble_row(apply_overrides(load(), OFF), "T-7 ok", inverted=True).image  # bold kept


# --- spans ---------------------------------------------------------------------------------------------------------


def test_a_span_size_on_part_of_a_line_prints_the_line_as_tall_as_its_tallest_part():
    res = build("Pay [NOW]{size=2x} please\n")
    row = drawn(res)[0]
    assert not [r for r in res.rows if isinstance(r, TextRow)] and row.image.height >= 48
    assert "".join(c.ch for c in row.text_rows[0].cells).strip() == "Pay NOW please"
    small = build("Pay NOW please\n")  # one line, not two: the baseline is shared
    assert len(drawn(res)) == 1 and isinstance(small.rows[1], TextRow)


def test_a_word_wider_than_a_mixed_line_is_cut_as_a_native_line_cuts_it():
    word = "SUPERCALIFRAGILISTIC"
    res = build(f"Pay [{word}]{{size=4x}} now\n")
    seen = "".join(c.ch for v in drawn(res)[0].text_rows for c in v.cells).replace(" ", "")
    assert seen == f"Pay{word}now"  # every letter printed, none cropped at the paper's edge
    assert said(res, "L101")[0] == f"word '{word}…' split at 8 columns"  # 8 letters of 48 dots: the paper's 384
    native = build(f"[{word}]{{size=4x}}\n")  # the same word alone: native, the same cut and message
    assert said(native, "L101")[0] == said(res, "L101")[0]


def test_a_mixed_line_sizes_each_span_as_gs_would():
    def ink(src):  # the ink's width and height
        res = build(src)
        box = preview.render(res.rows, res.profile).convert("L").point(lambda v: 255 - v).getbbox()
        return box[2] - box[0], box[3] - box[1]

    plain, big = ink("a WW b\n"), ink("a [WW]{size=2x} b\n")
    assert ink("a [WW]{size=2x1} b\n") == (big[0], plain[1])  # twice as wide, as tall as the line
    assert ink("a [WW]{size=1x2} b\n") == (plain[0], big[1])  # as wide as the line, twice as tall
    res = build("a [WW]{size=2x1} b [x]{size=20px} c\n")
    assert not said(res, "F303")  # exact on a drawn line: nothing printed "natively"
    assert said(build("[x]{size=20px}\n"), "F303") == ["size 20px printed natively at 1x"]  # alone: native


def test_a_span_alone_on_its_line_takes_its_size_natively():
    res = build("[BRS]{size=2x}\n")
    row = next(r for r in res.rows if isinstance(r, TextRow))
    assert row.native and row.scale == (2, 2)
    band = build("[BRS]{size=2x} {.invert}\n")
    assert drawn(band)[0].text_rows[0].scale == (2, 2) and "F206" not in codes(band)


def test_a_named_span_size_is_the_printer_fonts():
    res = build("Total: [R$ 42,00]{.bold size=large}\n")
    assert drawn(res)[0].image.height >= 48 and not said(res, "M101")


def test_what_a_span_does_not_take_is_said():
    res = build("A [b]{.bold} [c]{.center} [s]{.shade} [x]{foo=1} [m]{.mono} [i]{#here} end\n")
    assert said(res, "M101") == [".center .shade foo= on part of a line does nothing: a span takes .bold .italic "
                                 ".underline .strike .invert .mono font= size="]  # fmt: skip
    assert not said(build("A [b]{.bold .italic .underline .strike .invert} end\n"), "M101")


def test_a_span_around_a_data_value_says_what_it_does_not_take():
    res = build("Hi [{{ name | markdown }}]{.center} there\n", fields={"name": "**Ana**"})  # spliced as Markdown
    assert any(m.startswith(".center on part of a line") for m in said(res, "M101"))


def test_a_span_in_a_table_cell_says_what_it_does_not_take():
    res = build("| A | B |\n|---|---|\n| [x]{.center} | y |\n")
    assert any(".center on part of a line" in m for m in said(res, "M101"))


# --- the paper strip ------------------------------------------------------------------------------------------------


def test_the_paper_strip_is_about_6_cm_and_only_notes_the_bold():
    res = build((ROOT / "docs" / "printers" / "strips" / "inverted-bold.bob.md").read_text(encoding="utf-8"))
    assert set(codes(res)) == {"F206", "P301"}
    assert 50 <= preview.render(res.rows, res.profile).height * 25.4 / 203 <= 70  # mm
