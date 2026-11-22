"""A span's own size (Um [BRS]{size=2x} dois): only the span grows, the line is as tall as its tallest letter and
every letter sits on one baseline. In the printer font GS ! changes where the span starts and ends; in a raster font
each span is drawn at its own px. Wrapping counts each letter's real width; the views show it."""

from PIL import Image

from bobina import rasterfont, view
from bobina.engine import build
from bobina.rows import BitmapRow, TextRow

ESC, GS = b"\x1b", b"\x1d"
TERMINUS = "---\nfonts:\n  body: Terminus\nsize: 16px\n---\n"


def text_rows(res):
    return [r for r in res.rows if isinstance(r, TextRow)]


def codes(res):
    return [n.code for n in res.nudges]


def shown(doc: str) -> list[str]:
    res = build(doc)
    return [ln.rstrip() for ln in view.lines(res.rows, res.profile, max_feed_lines=0)]


def ink_box(im: Image.Image, x0: int, x1: int):
    """(top, bottom) rows of ink between columns x0 and x1 of a mode-1 image (None: no ink)."""
    box = Image.eval(im.convert("L").crop((x0, 0, x1, im.height)), lambda v: 255 - v).getbbox()
    return None if box is None else (box[1], box[3])


def glyphs(im: Image.Image) -> list[tuple[int, int]]:
    """(top, bottom) of each letter of a drawn line, left to right: the runs of columns with ink."""
    out, cur = [], None
    for x in range(im.width):
        box = ink_box(im, x, x + 1)
        if box and cur:
            cur = (min(cur[0], box[0]), max(cur[1], box[1]))
        elif box:
            cur = box
        elif cur:
            out.append(cur)
            cur = None
    return out + ([cur] if cur else [])


# --- printer font -------------------------------------------------------------------------------------------------


def test_only_the_span_grows_and_gs_bang_goes_back_after_it():
    res = build("Um [BRS]{size=2x} dois")
    [row] = text_rows(res)
    assert row.native and row.scale == (1, 1) and row.mixed()
    assert [c.scale for c in row.cells if c.ch in "BRS"] == [(2, 2)] * 3
    assert all(c.scale is None for c in row.cells if c.ch in "Umdois ")
    assert ESC + b"3\x36" + ESC + b"a\x00" + GS + b"!\x00Um " + GS + b"!\x11BRS" + GS + b"!\x00 dois\n" in res.data


def test_the_line_is_as_tall_as_its_tallest_span():
    res = build("Um [BRS]{size=2x} dois\n\nnext")
    first, second = text_rows(res)
    assert first.height() == 2 and res.emulator.row_height(first) == 48 + 6
    assert second.height() == 1 and res.emulator.row_height(second) == 24 + 6


def test_letters_of_every_size_sit_on_one_baseline():
    res = build("Um [BRS]{size=2x} dois")
    [row] = text_rows(res)
    im = res.emulator.render_row(row, res.profile.width_dots)
    small, big = ink_box(im, 0, 24), ink_box(im, 36, 108)  # "Um" (2 columns of 12), "BRS" (3 of 24, after a space)
    assert small[0] >= 24  # the small letters start in the lower half: nothing above them
    assert big[0] < 24  # the big ones reach up into the line's upper half
    assert abs(small[1] - big[1]) <= 6  # both stand on the foot of the line (the printer aligns the cells' feet)


def test_named_sizes_multipliers_and_stretches_map_as_on_a_line():
    res = build("Total: [R$ 42,00]{.bold size=large}")
    assert GS + b"!\x11" + ESC + b"E\x01R$ 42,00" in res.data  # large is 2x2 on mtp-ii-58, and bold
    assert GS + b"!\x01b" + GS + b"!\x00" in build("a [b]{size=1x2} c").data  # taller only
    assert GS + b"!\x10b" + GS + b"!\x00" in build("a [b]{size=2x1} c").data  # wider only
    assert GS + b"!\x22b" + GS + b"!\x00" in build("a [b]{size=3x} c").data


def test_a_size_in_dots_takes_the_nearest_multiplier_and_says_so():
    res = build("Um [BRS]{size=48px} dois")
    [row] = text_rows(res)
    assert row.native and [c.scale for c in row.cells if c.ch == "B"] == [(2, 2)]
    assert any(n.code == "F303" and "48px" in n.message for n in res.nudges)
    assert "M101" in codes(build("Um [BRS]{size=big} dois"))  # not a size: said, the span stays at the line's


def test_a_span_smaller_than_its_line():
    res = build("BIG [small]{size=normal} {size=2x}")
    [row] = text_rows(res)
    assert row.scale == (2, 2) and [c.scale for c in row.cells if c.ch == "s"] == [(1, 1)]
    assert GS + b"!\x11BIG " + GS + b"!\x00small\n" in res.data


def test_a_line_all_of_one_span_size_is_a_line_of_that_size():
    [row] = text_rows(build("[BRS]{size=2x}"))
    assert row.scale == (2, 2) and not row.mixed() and all(c.scale is None for c in row.cells)


def test_wrapping_counts_a_big_letter_as_the_columns_it_takes():
    # 26 letters, a space and BIG: 30 columns at 1x, but BIG takes 6 at 2x: it goes to the next line
    rows = text_rows(build("x" * 26 + " [BIG]{size=2x}"))
    assert ["".join(c.ch for c in r.cells) for r in rows] == ["x" * 26, "BIG"]
    assert rows[1].scale == (2, 2)
    rows = text_rows(build("Total a pagar hoje: [R$ 42,00]{size=2x}"))
    assert ["".join(c.ch for c in r.cells) for r in rows] == ["Total a pagar hoje: R$", "42,00"]
    assert all(r.width() <= 32 for r in rows) and rows[0].width() == 20 + 4


def test_a_big_word_longer_than_the_line_is_cut_where_it_fills_it():
    res = build("ab [" + "W" * 20 + "]{size=2x}")
    rows = text_rows(res)
    assert all(r.width() <= 32 for r in rows) and "L101" in codes(res)
    assert sum(c.ch == "W" for r in rows for c in r.cells) == 20


def test_an_inverted_line_with_a_big_span_is_one_band_as_tall_as_it():
    res = build("Um [BRS]{size=2x} {.invert}")
    [band] = [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "band"]
    assert band.image.height == 48 + 6 + 2 * 4  # the tallest letter, the line gap, the band's margins


def test_italic_and_big_spans_go_raster_as_the_line_and_keep_their_sizes():
    [row] = text_rows(build("Big [ital]{.italic size=2x} end"))
    assert not row.native and row.reason == "italic" and row.height() == 2


def test_span_styles_apply_in_the_printer_font():
    data = build("a [b]{.bold} [u]{.underline} [i]{.invert}").data
    assert ESC + b"E\x01b" + ESC + b"E\x00" in data
    assert ESC + b"-\x01u" + ESC + b"-\x00" in data
    assert GS + b"B\x01i" in data


def test_a_heading_with_a_span_of_another_size():
    [row] = text_rows(build("# TOTAL [R$ 9]{size=3x}"))
    assert row.scale == (2, 2) and row.height() == 3 and row.cells[-1].scale == (3, 3)


def test_mixed_sizes_get_the_untested_note_once():
    assert "P301" in codes(build("Um [BRS]{size=2x} dois"))
    assert "P301" not in codes(build("BRS multichain {size=2x}"))  # one size for the line: tested


# --- terminal view ------------------------------------------------------------------------------------------------


def test_the_view_shows_the_span_big_on_the_line_s_baseline():
    assert shown("Um [BRS]{size=2x} dois")[:2] == ["", "Um B R S  dois"]
    assert shown("a [b]{size=3x} c")[:3] == ["", "", "a b   c"]
    assert shown("BIG [small]{size=normal} {size=2x}")[:2] == ["", "B I G   small"]


def test_a_quoted_line_with_a_big_span_has_its_bar_from_top_to_foot():
    res = build("> Um [BRS]{size=2x} dois")
    [row] = [r for r in res.rows if isinstance(r, BitmapRow)]
    assert ink_box(row.image, 4, 8) == (0, row.image.height)  # the bar, drawn the whole height of the line
    assert shown("> Um [BRS]{size=2x} dois")[:2] == ["│", "│ Um B R S  dois"]


def test_the_view_of_a_line_of_one_size_is_unchanged():
    assert shown("BRS {size=2x}")[:2] == ["B R S", ""]


# --- raster fonts -------------------------------------------------------------------------------------------------


def test_raster_spans_are_drawn_at_their_own_px_on_one_baseline():
    res = build(TERMINUS + "Um [BRS]{size=40px} dois\n\nUm BRS dois\n")
    mixed, plain = [r for r in res.rows if isinstance(r, BitmapRow)]
    assert mixed.image.height > plain.image.height + 16  # as tall as its tallest span
    letters = glyphs(mixed.image)
    assert len(letters) == len("UmBRSdois")
    assert max(b for _, b in letters) - min(b for _, b in letters) <= 1  # no descenders: one baseline for all
    assert min(t for t, _ in letters[2:5]) < min(t for t, _ in letters[:2]) - 12  # BRS rises above Um


def test_raster_span_styles_apply():
    def drawn(doc):
        return [r for r in build(TERMINUS + doc).rows if isinstance(r, BitmapRow)][0].image.tobytes()

    plain = drawn("a word b\n")
    for style in ("bold", "italic", "underline", "strike", "invert"):
        assert drawn(f"a [word]{{.{style}}} b\n") != plain, style
        assert drawn(f"a [word]{{.{style} size=32px}} b\n") != drawn("a [word]{size=32px} b\n"), style


def test_an_inverted_word_beside_bigger_letters_keeps_its_own_height():
    path = rasterfont.resolve("Terminus").path
    t = rasterfont.Tok("ab", path, 16, invert=True)
    fa, fd = t.font.getmetrics()
    im = rasterfont.draw_tok(t, fa + 24, fa + 24 + fd)  # a line whose tallest letters rise 24 dots higher
    assert im.getpixel((0, 0)) == 255 and im.getpixel((0, im.height - 1)) == 0
    same = rasterfont.draw_tok(t, fa, fa + fd)  # among letters of its size: the whole line's height, as before
    assert same.getpixel((0, 0)) == 0
