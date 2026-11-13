from bobina.engine import build
from bobina.rows import BitmapRow, FeedRow, QRRow, RawRow, TextRow


def text_rows(res):
    return [r for r in res.rows if isinstance(r, TextRow)]


def line_text(r):
    return "".join(c.ch for c in r.cells)


def test_wraps_on_words_at_32_columns():
    res = build("Um parágrafo bem comprido para testar a quebra de linha feita pelo bobina.")
    lines = [line_text(r) for r in text_rows(res)]
    assert all(len(line) <= 32 for line in lines)
    assert " ".join(lines) == "Um parágrafo bem comprido para testar a quebra de linha feita pelo bobina."


def test_long_word_is_split_with_nudge():
    res = build("x" * 40)
    assert [len(line_text(r)) for r in text_rows(res)] == [32, 8]
    assert "L101" in {n.code for n in res.nudges}


def test_headings_are_native_scaled():
    res = build("# A\n\n## B\n\n### C")
    assert [(r.scale, r.native, r.cells[0].bold) for r in text_rows(res)] == [
        ((2, 2), True, True),
        ((1, 2), True, True),
        ((1, 1), True, True),
    ]
    assert [line_text(r) for r in text_rows(res)] == ["A", "B", "C"]


def test_unsupported_features_go_raster_per_line():
    res = build("plain\nwith *italic*\nwith → arrow")
    rows = text_rows(res)
    assert [r.native for r in rows] == [True, False, False]
    assert "F301" in {n.code for n in res.nudges}


def test_tasks_are_drawn_and_done_is_struck():
    res = build("- [ ] milk\n- [x] bread")
    rows = text_rows(res)
    assert rows[0].cells[0].ch == "☐" and not rows[0].native
    assert rows[1].cells[0].ch == "☑" and all(c.strike for c in rows[1].cells[2:])


def test_tasks_plain_is_native():
    res = build("---\ntasks: {done: plain}\n---\n- [x] bread")
    assert line_text(text_rows(res)[0]) == "[x] bread" and text_rows(res)[0].native


def test_invert_heading_becomes_continuous_band():
    res = build("# SALE {.invert}")
    assert any(isinstance(r, BitmapRow) and r.kind == "band" for r in res.rows)


def test_top_margin_and_tear_feed():
    res = build("x")
    assert isinstance(res.rows[0], FeedRow) and res.rows[0].dots == 24
    assert isinstance(res.rows[-1], FeedRow) and res.rows[-1].dots == 88


def test_qr_native_and_raster():
    assert any(isinstance(r, QRRow) for r in build("```qr\nhttps://x\n```").rows)
    res = build("```qr {render=raster module=3}\nhttps://x\n```")
    assert any(isinstance(r, BitmapRow) and r.kind == "qr" for r in res.rows)
    assert "Q101" in {n.code for n in res.nudges}


def test_raw_block_bytes_and_nudge():
    res = build("```raw\n1b 40 # init\n```")
    assert any(isinstance(r, RawRow) and r.data == b"\x1b@" for r in res.rows)
    assert "P201" in {n.code for n in res.nudges}


def test_divider_thickness_nudge():
    assert "B101" in {n.code for n in build("--- {.dashed thickness=1}").nudges}


def test_table_columns_align_compact():
    res = build("| Item | Qty |\n|---|--:|\n| Bread | 6 |\n| Coffee | 12 |\n\n{.compact}")
    lines = [line_text(r) for r in text_rows(res)]
    assert lines == ["Item   Qty", "Bread    6", "Coffee  12"]


def test_table_stretches_to_paper_width():
    res = build("| Item | Qty |\n|---|--:|\n| Bread | 6 |")
    lines = [line_text(r) for r in text_rows(res)]
    assert lines == ["Item" + " " * 25 + "Qty", "Bread" + " " * 26 + "6"]


def test_unknown_attribute_nudges():
    assert "M101" in {n.code for n in build("text {.sparkle}").nudges}


def test_missing_image_nudges_but_prints_rest():
    res = build("![x](nope.png)\n\nafter")
    assert "I101" in {n.code for n in res.nudges}
    assert line_text(text_rows(res)[0]) == "after"


def test_raster_font_block_and_minimum_size_nudge():
    res = build("---\nfonts: {body: Atkinson Hyperlegible}\n---\nhello\n\ntiny {size=10px}")
    kinds = [r.kind for r in res.rows if isinstance(r, BitmapRow)]
    assert kinds == ["text", "text"]
    assert "F201" in {n.code for n in res.nudges}


def test_headings_stay_native_when_only_body_is_raster():
    res = build("---\nfonts: {body: Atkinson Hyperlegible}\n---\n# Title\n\nbody")
    assert isinstance([r for r in res.rows if not isinstance(r, FeedRow)][0], TextRow)


def test_span_font_alias_makes_block_raster():
    res = build("---\nfonts: {hand: Barlow Condensed}\n---\nSigned [Ana]{font=hand}")
    assert any(isinstance(r, BitmapRow) and r.kind == "text" for r in res.rows)


def test_missing_font_falls_back_with_nudge():
    res = build('text {font="No Such Font 123"}')
    assert "F203" in {n.code for n in res.nudges}


def test_raster_rows_keep_text_for_the_terminal_view():
    res = build("---\nfonts: {body: Atkinson Hyperlegible}\n---\nhello world")
    r = [r for r in res.rows if isinstance(r, BitmapRow)][0]
    assert "".join(c.ch for c in r.text_rows[0].cells) == "hello world"


def test_flip_native_reverses_rows_and_sets_upside_down():
    res = build("first\nsecond {.flip}")
    rows = text_rows(res)
    assert [line_text(r) for r in rows] == ["second", "first"] and all(r.upside_down for r in rows)
    assert b"\x1b{\x01" in res.data


def test_rotate_is_raster_and_fits_width():
    res = build("```text {rotate=90}\nVERTICAL LABEL\n```")
    r = [r for r in res.rows if isinstance(r, BitmapRow)][0]
    assert r.kind == "rotated" and r.image.width == 384 and r.image.height > r.image.width // 3


def test_long_barcode_goes_vertical_automatically():
    res = build("```barcode {type=code128}\nbobina-long-barcode-0123456789-ABCDEFGHIJ\n```")
    r = [r for r in res.rows if isinstance(r, BitmapRow)][0]
    assert r.kind == "barcode" and r.image.height > r.image.width
    assert "Q110" in {n.code for n in res.nudges}


def test_barcode_stretches_with_integer_module():
    from bobina.rows import BarcodeRow

    r = [r for r in build("```barcode {type=code128 width=full}\nBOB-128\n```").rows if isinstance(r, BarcodeRow)][0]
    from bobina import codes

    assert r.module == 384 // len(codes.bars("code128", "BOB-128")[0]) and r.module > 2


def test_qr_width_full_uses_largest_integer_module():
    r = [r for r in build("```qr {width=full}\nhttps://example.com/full\n```").rows if isinstance(r, QRRow)][0]
    from bobina import imaging

    n = len(imaging.qr_matrix("https://example.com/full", "M"))
    assert r.module == min(16, 384 // n) and (r.module + 1) * n > 384


def test_auto_vertical_is_a_visible_warning_and_explicit_choice_is_silent():
    long = "bobina-long-barcode-0123456789-ABCDEFGHIJ"
    auto = build(f"```barcode {{type=code128}}\n{long}\n```")
    n = [n for n in auto.nudges if n.code == "Q110"][0]
    assert n.severity == "warning" and "VERTICALLY" in n.message
    chosen = build(f"```barcode {{type=code128 orientation=vertical}}\n{long}\n```")
    assert "Q110" not in {n.code for n in chosen.nudges}


def test_vertical_barcode_has_quiet_zone_and_feed_module():
    res = build("```barcode {type=code128 orientation=vertical}\nVERT-01\n```")
    r = [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "barcode"][0]
    from PIL import ImageOps

    im = r.image.convert("L")
    ink = [ImageOps.invert(im.crop((0, y, im.width, y + 1))).getbbox() is not None for y in range(im.height)]
    q = res.profile.get("barcode.quiet_modules") * res.profile.get("barcode.min_module_feed")  # 10 x 4
    assert not any(ink[:q]) and not any(ink[-q:]) and ink[q]
    explicit = build("```barcode {type=code128 orientation=vertical module=2}\nVERT-01\n```")
    assert "Q108" in {n.code for n in explicit.nudges}


def test_glyph_missing_everywhere_is_reported():
    res = build("ancient \U00010348 letter")  # Gothic hwair: not in Spleen nor DejaVu Sans
    assert "F302" in {n.code for n in res.nudges}


def test_render_attribute_forces_text_blocks():
    forced = build("plain text {render=raster}")
    assert any(isinstance(r, BitmapRow) and r.kind == "text" for r in forced.rows)
    native = build("---\nfonts: {body: Atkinson Hyperlegible}\n---\nback to the printer font {render=native}")
    assert any(isinstance(r, TextRow) and r.native for r in native.rows)


def test_tracking_native_spaces_letters_and_wraps_on_the_real_width():
    res = build("x" * 40 + " {tracking=4}")
    rows = text_rows(res)
    assert [len(line_text(r)) for r in rows] == [24, 16]  # (12 + 4) dots per char -> 24 columns
    assert all(r.tracking == 4 for r in rows) and b"\x1b \x04" in res.data and b"\x1b \x00" in res.data


def test_indent_in_columns_and_millimetres():
    cols = text_rows(build("hello {indent=4}"))[0]
    assert line_text(cols).startswith("    hello")
    mm = text_rows(build("hello {indent=3mm}"))[0]  # 24 dots = 2 columns
    assert line_text(mm).startswith("  hello")


def test_leading_native_sets_line_spacing():
    res = build("a\nb {leading=20}")
    assert b"\x1b3\x2c" in res.data  # 24 + 20 = 44
    assert all(res.emulator.row_height(r) == 44 for r in text_rows(res))


def test_tracking_and_indent_in_raster_fonts():
    from PIL import ImageOps

    def ink_box(src):
        r = [r for r in build(src).rows if isinstance(r, BitmapRow) and r.kind == "text"][0]
        return ImageOps.invert(r.image.convert("L")).getbbox()

    fm = "---\nfonts: {body: Atkinson Hyperlegible}\n---\n"
    plain, spaced = ink_box(fm + "spacing"), ink_box(fm + "spacing {tracking=6}")
    assert spaced[2] - spaced[0] > plain[2] - plain[0] + 30
    assert ink_box(fm + "indented {indent=40px}")[0] >= 40


def test_invalid_spacing_value_nudges():
    assert "M101" in {n.code for n in build("x {tracking=wide}").nudges}


def test_cldr_spaces_stay_native_text():
    res = build("6:44\u202fPM · R$\u00a04,50")
    assert "F301" not in {n.code for n in res.nudges}
    assert b"6:44 PM \xc2\xb7 R$ 4,50" in res.data


def test_mtp_ii_does_not_double_esc_sp_at_2x():
    """Paper, 09/11: "tracking 4" at 2x is as wide as 10 glyphs of 24 dots plus 4 dots each, not 8."""
    from bobina import engine
    from bobina.rows import TextRow

    res = engine.build("tracking 4 {tracking=4 size=2x}\n")
    row = next(r for r in res.rows if isinstance(r, TextRow) and r.native)
    img = res.emulator.render_row(row, 384)
    xs = [x for x in range(img.width) if any(img.getpixel((x, y)) == 0 for y in range(img.height))]
    assert xs[-1] - xs[0] < 10 * 24 + 10 * 4  # with doubling it would reach 10 * 24 + 9 * 8
    assert xs[-1] - xs[0] > 9 * 24 + 9 * 4 - 8


def test_mtp_ii_code39_preview_is_as_wide_as_the_paper():
    """Paper, 09/11: ABC-123 at module 2 is 258 dots (wide = 2 modules, with the mod-43 char)."""
    from bobina import engine
    from bobina.preview import barcode_image
    from bobina.rows import BarcodeRow

    res = engine.build("```barcode {type=code39}\nABC-123\n```\n")
    row = next(r for r in res.rows if isinstance(r, BarcodeRow))
    img = barcode_image(row, res.emulator)
    xs = [x for x in range(img.width) if img.getpixel((x, 0)) == 0]
    assert xs[-1] - xs[0] + 1 == 258


def test_tracking_follows_the_paper_where_measured_and_the_spec_elsewhere():
    """The MTP-II never scales ESC SP with the width (paper: 2x on 09/11, 3x and 4x on 13/11). A printer nobody
    measured keeps the spec (the gap scales), so lines wrap early, never overflow."""
    from bobina import profile

    p = profile.load("mtp-ii-58")
    assert [p.tracking_gap(4, w) for w in (1, 2, 3, 4)] == [4, 4, 4, 4]
    other = profile.load("epson-tm-t20ii")
    assert other.tracking_gap(4, 3) == 12


def test_vertical_code39_length_is_the_one_bobina_draws():
    """Q110 tells the length of the vertical image (3:1 bars, feed-direction module), not of the firmware's 2:1."""
    import re

    from bobina import engine
    from bobina.rows import BitmapRow

    data = "ABCDEFGHIJKLMNOP-123"
    for attrs in ("type=code39", "type=code39 module=3"):  # raised to the feed minimum (4), or as given
        res = engine.build(f"```barcode {{{attrs}}}\n{data}\n```\n")
        msg = next(n.message for n in res.nudges if n.code == "Q110")
        mm = int(re.search(r"about (\d+) mm", msg).group(1))
        drawn = next(r for r in res.rows if isinstance(r, BitmapRow)).image.height
        assert abs(mm - drawn / 8) <= 1, (attrs, mm, drawn / 8)


def test_tracking_widths_accept_one_number():
    from bobina.profile import Profile

    one = Profile("x", "x", 384, 203, {"native": {"tracking_unscaled_at": 2}})
    odd = Profile("x", "x", 384, 203, {"native": {"tracking_unscaled_at": "2"}})
    assert one.tracking_gap(4, 2) == 4 and one.tracking_gap(4, 3) == 12
    assert odd.tracking_gap(4, 2) == 8  # not a width: the spec


LONG = "a quoted line that keeps going well past the edge of the paper roll, word after word"


def test_quote_wraps_inside_its_bar():
    rows = [line_text(r) for r in text_rows(build(f"> {LONG}"))]
    assert len(rows) > 1 and all(len(t) <= 32 for t in rows)
    assert all(t.startswith("│ ") for t in rows)
    assert " ".join(t[2:] for t in rows) == LONG


def test_nested_quote_and_quote_in_list_keep_to_the_paper():
    rows = [line_text(r) for r in text_rows(build(f"> > {LONG}\n\n- item\n  > {LONG}"))]
    nested = [t for t in rows if t.startswith("│ │ ")]
    in_list = [t for t in rows if t.startswith("  │ ")]
    assert len(nested) > 1 and len(in_list) > 1
    assert all(len(t) <= 32 for t in rows)
    assert " ".join(t[4:] for t in nested) == " ".join(t[4:] for t in in_list) == LONG


def test_quote_on_a_wider_paper_uses_its_columns():
    res = build(f"> {LONG} {LONG}", profile_name="epson-tm-t20iii")  # 48 columns
    rows = [line_text(r) for r in text_rows(res)]
    assert all(len(t) <= 48 for t in rows) and max(len(t) for t in rows) > 40


def test_quote_in_a_raster_font_has_its_bar_drawn():
    res = build(f'> {LONG} {{font="Atkinson Hyperlegible"}}\n\n> > nested {{font="Atkinson Hyperlegible"}}')
    outer, nested = [r for r in res.rows if isinstance(r, BitmapRow)]
    px = outer.image.load()
    assert all(px[x, y] == 0 for y in range(outer.image.height) for x in (5, 6))  # the bar, as │ prints
    assert all(px[x, y] for y in range(outer.image.height) for x in range(8, 24))  # the gap before the words
    assert all(line_text(v).startswith("│ ") for v in outer.text_rows)
    npx = nested.image.load()
    assert all(npx[5, y] == 0 and npx[29, y] == 0 for y in range(nested.image.height))
    assert [line_text(v) for v in nested.text_rows] == ["│ │ nested"]


def test_inverted_quote_gets_a_white_bar():
    (band,) = [r for r in build("> inverted {.invert}").rows if isinstance(r, BitmapRow)]
    px = band.image.load()
    assert all(px[5, y] and px[6, y] and not px[2, y] for y in range(band.image.height))


def bar_columns(im, y):
    px = im.load()
    return [x for x in range(im.width) if px[x, y] == 0]


def test_right_to_left_quote_has_its_bar_where_the_text_starts():
    res = build('> שלום עולם, זהו ציטוט ארוך מספיק כדי לעבור לשורה הבאה בנייר {font="Atkinson Hyperlegible"}')
    (row,) = [r for r in res.rows if isinstance(r, BitmapRow)]
    w, px = row.image.width, row.image.load()
    assert all(px[w - 6, y] == 0 and px[w - 7, y] == 0 for y in range(row.image.height))  # the bar, mirrored
    assert all(px[x, y] for y in range(row.image.height) for x in range(w - 24, w - 8))  # its gap: no letter
    assert not any(px[x, y] == 0 for y in range(row.image.height) for x in (5, 6))  # nothing on the left
    assert all(line_text(v).endswith(" │") for v in row.text_rows)


def test_a_heading_in_a_quote_keeps_the_bar_where_the_text_has_it():
    res = build("> # Big\n> text\n\n> > # Nested\n> > nested text")
    big, text, nested, nested_text = [r for r in res.rows if isinstance(r, (TextRow, BitmapRow))]
    assert isinstance(big, BitmapRow) and isinstance(nested, BitmapRow)  # 2x: the 1x bar is drawn in
    assert [line_text(text), line_text(nested_text)] == ["│ text", "│ │ nested text"]
    mid = big.image.height // 2
    assert bar_columns(big.image, mid)[:2] == [5, 6]  # the bar of the 1x rows, 1x wide
    assert min(x for x in bar_columns(big.image, mid) if x > 6) >= 24  # the heading starts after the gutter only
    nmid = nested.image.height // 2
    assert bar_columns(nested.image, nmid)[:4] == [5, 6, 29, 30]  # both bars, where │ │ nested text has them
    assert min(x for x in bar_columns(nested.image, nmid) if x > 30) >= 48
    assert [line_text(v) for v in nested.text_rows] == ["│ │ Nested"]


def test_centred_text_in_a_quote_is_centred_after_the_bar():
    (row,) = text_rows(build("> centred {.center}"))
    assert row.align == "left" and line_text(row).startswith("│ ") and line_text(row).strip("│ ") == "centred"
    assert line_text(row).index("c") == 2 + (30 - 7) // 2


def test_a_centred_caption_or_cells_outside_a_quote_get_no_bar():
    res = build('```qr {caption="  centred caption"}\nhttps://example.com\n```\n\n| a | b |\n|--:|--:|\n| 1 | 2 |')
    assert not any("│" in line_text(r) for r in text_rows(res))


def test_a_code_caption_inside_a_quote_gets_no_bar_over_its_text():
    res = build('> ```qr {caption="caption"}\n> https://example.com\n> ```')
    assert [line_text(r) for r in text_rows(res)] == ["caption"]


def test_a_printer_without_the_bar_glyph_prints_the_line_as_an_image(monkeypatch):
    from bobina.profile import Profile

    real = Profile.native_glyph
    monkeypatch.setattr(Profile, "native_glyph", lambda self, ch: ch != "│" and real(self, ch))
    res = build("> quoted")
    (row,) = text_rows(res)
    assert not row.native and row.reason == "glyph │"
    assert "F301" in {n.code for n in res.nudges}
