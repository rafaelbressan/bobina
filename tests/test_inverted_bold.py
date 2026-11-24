"""White text on black below the size the paper holds prints bold (paper, MTP-II 18/11: the printer font at 1x closed
up, even bold; at 2x it held; 24/11: plain small text in an inverted box printed thin, bold held up), and bobina says
so (F206)."""

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


def test_a_span_at_2x1_on_an_inverted_line_is_heavy_too():
    src = "A-B [xy-z]{size=2x1} {.invert}\n"  # sizes mixed on a line (drawn, one baseline): 24 dots tall, bold
    res, thin = build(src), build(src, overrides=OFF)
    assert white(drawn(res)[0].image) > white(drawn(thin)[0].image) and "F206" in codes(res)
    assert "2x1 on line 1" in said(res, "F206")[0]


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


# --- inverted boxes ---------------------------------------------------------------------------------------------

BOX = "::: {{.box .invert}}\n{}\n:::\n"
QR_BESIDE = (
    "::::: {.box .invert}\n:::: {.columns valign=middle}\n::: {.column width=40%}\n```qr\nhttps://bobina.md\n```\n"
    ":::\n::: {.column}\naponte a câmera\n:::\n::::\n:::::\n"
)


def box_of(res) -> BitmapRow:
    return next(r for r in drawn(res) if r.kind == "box")


def test_plain_small_text_in_an_inverted_box_prints_bold():
    src = BOX.format("texto normal pequeno")
    res, thin = build(src), build(src, overrides=OFF)
    assert box_of(res).image.height - box_of(thin).image.height <= 1  # BOX_ROOM under a descender grown a dot
    assert white(box_of(res).image) > white(box_of(thin).image) * 1.3
    assert said(res, "F206") == ["inverted text printed bold (1x on line 2): ink fills thin white strokes"]
    assert untested(res) and "F206" not in codes(thin) and not untested(thin)


def test_a_column_beside_a_qr_in_an_inverted_box_prints_bold_and_the_qr_keeps_its_tile():
    res, thin = build(QR_BESIDE), build(QR_BESIDE, overrides=OFF)
    im, ref = box_of(res).image.convert("L"), box_of(thin).image.convert("L")
    assert im.size == ref.size and white(im) > white(ref)  # "aponte a câmera" heavier
    left = (0, 0, im.width * 2 // 5, im.height)  # the QR's column: its white tile, black on white, as before
    assert im.crop(left) == ref.crop(left) and white(im.crop(left)) > 1000  # a tile, not all black
    assert "Q114" in codes(res) and said(res, "F206") == [
        "inverted text printed bold (1x on line 9): ink fills thin white strokes"
    ]


def test_lists_headings_and_tables_in_an_inverted_box_print_bold():
    for body in ("- one\n- two", "## Total", "| Item | Price |\n|---|---|\n| Rice | 9,00 |", "```\nT-7 10:03\n```"):
        src = BOX.format(body)
        res, thin = build(src), build(src, overrides=OFF)
        assert white(box_of(res).image) > white(box_of(thin).image), body
        assert untested(res), body


def test_a_word_inverted_inside_an_inverted_box_stays_black_and_thin():
    src = BOX.format("Order [T-7]{.invert} ready")
    res = build(src)
    rows = box_of(res).box.rows
    cells = next(r for r in rows if isinstance(r, TextRow)).cells
    assert [c.heavy for c in cells if c.ch.strip()] == [True] * 5 + [False] * 3 + [True] * 5  # Order, T-7, ready


def test_header_invert_titles_in_an_inverted_box_are_black_on_paper_and_stay_thin():
    src = BOX.format(BILL + "{style=header-invert}")
    res, thin = build(src), build(src, overrides=OFF)
    im, ref = box_of(res).image, box_of(thin).image
    assert white(im) > white(ref)  # the body rows: white on black, heavy
    top = (0, 0, im.width, 50)  # the titles' band, white on paper here (the box's black around): as they were
    assert im.crop(top) == ref.crop(top) and white(im.crop(top)) > 50 * im.width // 2
    assert said(res, "F206") == ["inverted text printed bold (1x on the table at line 2): ink fills thin white strokes"]


def test_a_band_or_border_title_of_an_inverted_box_is_drawn_heavier():
    for how in ("band", "border"):
        src = f'::: {{.box .invert title="SALE" title-style={how}}}\nPAID {{size=2x}}\n:::\n'  # 2x: as it was
        res, thin = build(src), build(src, overrides=OFF)
        assert white(box_of(res).image) > white(box_of(thin).image), how  # bold already: a dot taller
        assert "F206" not in codes(res) and untested(res), how


def test_a_box_in_an_inverted_box_has_a_black_band_title_and_a_white_border_title():
    def inner(how: str) -> str:
        return f'::: {{.box .invert}}\n::: {{.box title="SALE" title-style={how}}}\nPAID {{size=2x}}\n:::\n:::\n'

    band, thin = build(inner("band")), build(inner("band"), overrides=OFF)
    assert box_of(band).image == box_of(thin).image and not untested(band)  # its band white: the title black, thin
    border, thin = build(inner("border")), build(inner("border"), overrides=OFF)
    assert white(box_of(border).image) > white(box_of(thin).image) and untested(border)  # on the black: white


def test_a_raster_font_in_an_inverted_box_takes_its_bold_face():
    res = build(FONT + BOX.format("Thanks {size=24px}"))
    assert said(res, "F206") == ["inverted text printed bold (24px on line 6): ink fills thin white strokes"]
    assert "F204" not in codes(res) and not untested(res)  # a real bold face: R2-12 tested it on paper


def test_an_inverted_image_in_an_inverted_box_is_unchanged(tmp_path):
    from PIL import Image

    Image.new("RGB", (200, 60), "white").save(tmp_path / "logo.png")
    src = BOX.format("![](logo.png){width=half}")
    res, thin = build(src, base_dir=str(tmp_path)), build(src, base_dir=str(tmp_path), overrides=OFF)
    assert box_of(res).image == box_of(thin).image and "F206" not in codes(res) and not untested(res)


# --- the paper strip ------------------------------------------------------------------------------------------------


def test_the_paper_strip_is_about_9_cm_and_only_notes_the_bold():
    res = build((ROOT / "docs" / "printers" / "strips" / "inverted-bold.bob.md").read_text(encoding="utf-8"))
    assert set(codes(res)) == {"F206", "P301", "Q114"}  # Q114: the QR's white tile in the inverted box
    assert 80 <= preview.render(res.rows, res.profile).height * 25.4 / 203 <= 100  # mm
