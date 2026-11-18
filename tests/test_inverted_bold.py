"""White text on black below the size the paper holds prints bold (paper, MTP-II 18/11: the printer font at 1x closed
up, even bold; at 2x it held), and bobina says so (F206). And a span's attributes: size= on part of a line, and the
names a span does not take (M101)."""

from pathlib import Path

from bobina import chat, escpos, preview
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
    assert said(res, "F206") == ["inverted text at 1x printed bold: ink fills thin white strokes"]
    assert untested(res) and "F206" not in codes(thin) and not untested(thin)


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


def test_a_native_inverted_word_gets_esc_e_with_gs_b():
    res = build("Total [9,00]{.invert} now\n")
    row = next(r for r in res.rows if isinstance(r, TextRow))
    assert row.native and all(c.bold for c in row.cells if c.invert)
    assert not any(c.bold for c in row.cells if not c.invert)
    data = escpos.text_row(row, Emulator(load()))
    assert ESC + b"E\x01" + GS + b"B\x01" + b"9,00" in data and "F206" in codes(res)


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
    assert said(res, "F206") == ["inverted text at 1x printed bold: ink fills thin white strokes"]


def test_a_table_in_a_raster_font_takes_its_bold_face_and_no_p301():
    res = build(BILL + "| Tea | 2 | 18,00 | {.invert}\n{font=Terminus size=20px}\n")
    assert said(res, "F206") == ["inverted text at 20px printed bold: ink fills thin white strokes"]
    assert "P301" not in codes(res)  # a real bold face: R2-12 tested it on paper


# --- raster fonts -------------------------------------------------------------------------------------------------


def test_a_raster_line_below_48px_takes_the_bold_face():
    res = build(FONT + "Thanks {.invert size=24px}\n")
    assert said(res, "F206") == ["inverted text at 24px printed bold: ink fills thin white strokes"]
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


# --- spans ---------------------------------------------------------------------------------------------------------


def test_a_span_size_on_part_of_a_line_prints_the_line_as_tall_as_its_tallest_part():
    res = build("Um [BRS]{size=2x} dois\n")
    row = drawn(res)[0]
    assert not [r for r in res.rows if isinstance(r, TextRow)] and row.image.height >= 48
    assert "".join(c.ch for c in row.text_rows[0].cells).strip() == "Um BRS dois"
    small = build("Um BRS dois\n")  # one line, not two: the baseline is shared
    assert len(drawn(res)) == 1 and isinstance(small.rows[1], TextRow)


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


def test_a_span_in_a_table_cell_says_what_it_does_not_take():
    res = build("| A | B |\n|---|---|\n| [x]{.center} | y |\n")
    assert any(".center on part of a line" in m for m in said(res, "M101"))


# --- the paper strip ------------------------------------------------------------------------------------------------


def test_the_paper_strip_is_about_6_cm_and_only_notes_the_bold():
    res = build((ROOT / "docs" / "printers" / "strips" / "inverted-bold.bob.md").read_text(encoding="utf-8"))
    assert set(codes(res)) == {"F206", "P301"}
    assert 50 <= preview.render(res.rows, res.profile).height * 25.4 / 203 <= 70  # mm
