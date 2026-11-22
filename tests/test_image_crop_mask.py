"""crop=, mask= and .invert on images, and ::: {.box .invert}: a part of a screenshot printed on its own, a round coin
printed round (paper outside it, never ink), a white logo on black printed black on white, and a header band that
stays black from its logo to its last line. The preview is the print; the view shows the same."""

import pytest
from PIL import Image, ImageDraw

from bobina import view
from bobina.engine import build
from bobina.rows import BitmapRow

W = 384  # mtp-ii-58


def codes(res) -> list[str]:
    return [n.code for n in res.nudges]


def said(res, code: str) -> list[str]:
    return [n.message for n in res.nudges if n.code == code]


def picture(res) -> Image.Image:
    """The one image row's dots, mode 'L' (0: ink)."""
    (r,) = [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "image"]
    return r.image.convert("L")


def ink(im: Image.Image) -> float:
    """How much of `im` is black, 0 to 1."""
    return im.histogram()[0] / (im.width * im.height)


def quadrants(path, size=(200, 100), black=(0,), fmt=None):
    """An image cut in four (0 top-left, 1 top-right, 2 bottom-left, 3 bottom-right), the `black` ones black."""
    w, h = size
    im = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(im)
    for q in black:
        x, y = (q % 2) * w // 2, (q // 2) * h // 2
        d.rectangle((x, y, x + w // 2 - 1, y + h // 2 - 1), fill="black")
    im.save(path, fmt)
    return path


def run(tmp_path, attrs: str, name: str = "q.png") -> object:
    return build(f"![]({name}){{{attrs}}}\n", base_dir=str(tmp_path))


# --- crop= ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("crop", ["0,0,100,50", "0,0,50%,50%", "0,0,100px,50%", '"0, 0, 50%, 50"'])
def test_crop_keeps_the_part_asked_in_pixels_or_percentages(tmp_path, crop):
    quadrants(tmp_path / "q.png", black=(0,))  # only the top-left quarter is black
    res = run(tmp_path, f"crop={crop} .threshold")
    im = picture(res)
    assert im.size == (W, W // 2)  # the part kept (100x50) fills the width: crop comes before width=
    assert ink(im) == 1.0, codes(res)
    assert not {"I111", "M101"} & set(codes(res))


def test_crop_of_a_white_part_prints_no_ink(tmp_path):
    quadrants(tmp_path / "q.png", black=(0,))
    assert ink(picture(run(tmp_path, "crop=50%,50%,50%,50% .threshold"))) == 0.0


def test_crop_counts_the_pixels_of_the_file_even_in_a_big_jpeg(tmp_path):
    quadrants(tmp_path / "q.jpg", size=(2000, 2000), black=(0,), fmt="JPEG")  # drafted smaller without crop=
    res = run(tmp_path, "crop=0,0,1000,1000 .threshold", "q.jpg")
    assert ink(picture(res)) > 0.99 and "I111" not in codes(res)


def test_crop_counts_pixels_as_a_viewer_shows_them_after_the_exif_turn(tmp_path):
    quadrants(tmp_path / "q.jpg", size=(100, 200), black=(0,))
    im = Image.open(tmp_path / "q.jpg")
    exif = im.getexif()
    exif[0x0112] = 6  # stored 100x200, shown turned: 200x100, the black quarter top-right
    im.save(tmp_path / "t.jpg", exif=exif)
    assert ink(picture(run(tmp_path, "crop=100,0,100,50 .threshold", "t.jpg"))) > 0.9
    assert ink(picture(run(tmp_path, "crop=0,0,100,50 .threshold", "t.jpg"))) < 0.1


def test_a_crop_partly_outside_is_cut_to_the_image_and_said_with_its_size(tmp_path):
    quadrants(tmp_path / "q.png", black=(3,))
    res = run(tmp_path, "crop=100,50,300,300 .threshold")
    assert said(res, "I111") == ["crop=100,50,300,300 goes past the 200x100 px image: cut to 100,50,100,50"]
    assert ink(picture(res)) == 1.0  # the bottom-right quarter, all of it


@pytest.mark.parametrize("crop", ["300,0,10,10", "0,0,0,50", "-50,0,40,40"])
def test_a_crop_outside_the_image_or_empty_prints_it_whole_and_says_so(tmp_path, crop):
    quadrants(tmp_path / "q.png", black=(0,))
    res = run(tmp_path, f"crop={crop} .threshold")
    (msg,) = said(res, "I111")
    assert msg == f"crop={crop} is outside the 200x100 px image or has no size: printed uncropped"
    assert 0.2 < ink(picture(res)) < 0.3  # the whole image: one black quarter


@pytest.mark.parametrize("crop", ["1,2,3", "a,b,c,d", "0,0,50%"])
def test_a_crop_that_is_not_four_numbers_is_said_and_ignored(tmp_path, crop):
    quadrants(tmp_path / "q.png", black=(0,))
    res = run(tmp_path, f"crop={crop}")
    assert [m for m in said(res, "M101") if m.startswith("crop=")] == [f"crop={crop}"]
    assert picture(res).size == (W, W // 2)


def svg(path):
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100"'
                    ' fill="white"/><rect width="100" height="100" fill="black"/></svg>')  # fmt: skip
    return path


def test_an_svg_is_cropped_in_percentages(tmp_path):
    pytest.importorskip("resvg_py")
    svg(tmp_path / "s.svg")
    res = run(tmp_path, "crop=0,0,50%,100%", "s.svg")
    im = picture(res)
    assert im.size == (W, W) and ink(im) > 0.99 and codes(res) == []


def test_an_svg_cropped_in_pixels_is_said_and_printed_whole(tmp_path):
    pytest.importorskip("resvg_py")
    svg(tmp_path / "s.svg")
    res = run(tmp_path, "crop=0,0,100,100", "s.svg")
    assert said(res, "M101") == ["crop=0,0,100,100: an SVG or PDF is cropped in percentages: printed uncropped"]
    assert picture(res).size == (W, W // 2)


def test_crop_comes_before_the_turn(tmp_path):
    quadrants(tmp_path / "q.png", size=(200, 100), black=(0,))
    im = picture(run(tmp_path, "crop=0,0,100,100 rotate=90 .threshold"))  # the left half, turned
    assert im.size == (W, W)
    assert ink(im.crop((W // 2, 0, W, W // 2))) == 1.0  # its top-left quarter is now top-right
    assert ink(im.crop((0, 0, W // 2, W))) == 0.0


# --- mask= ---------------------------------------------------------------------------------------------------------


def black(path, size=(300, 300)):
    Image.new("RGB", size, "black").save(path)
    return path


def corners(im: Image.Image) -> list[int]:
    w, h = im.size
    return [im.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]


def test_mask_circle_leaves_the_corners_paper_and_the_centre_ink(tmp_path):
    black(tmp_path / "q.png")
    im = picture(run(tmp_path, "mask=circle"))
    assert im.size == (W, W)
    assert corners(im) == [255] * 4
    assert im.getpixel((W // 2, W // 2)) == 0
    assert im.getpixel((W // 2, 1)) == 0 and im.getpixel((1, W // 2)) == 0  # it touches the four sides


def test_mask_circle_on_a_wide_image_is_as_wide_as_its_height_and_centred(tmp_path):
    black(tmp_path / "q.png", (400, 200))
    im = picture(run(tmp_path, "mask=circle"))
    h = im.height
    assert im.getpixel((W // 2, h // 2)) == 0
    assert im.getpixel(((W - h) // 2 - 2, h // 2)) == 255 and im.getpixel(((W - h) // 2 + 2, h // 2)) == 0


def test_mask_ellipse_touches_the_four_sides(tmp_path):
    black(tmp_path / "q.png", (400, 200))
    im = picture(run(tmp_path, "mask=ellipse"))
    w, h = im.size
    assert corners(im) == [255] * 4
    assert im.getpixel((1, h // 2)) == 0 and im.getpixel((w - 2, h // 2)) == 0 and im.getpixel((w // 2, 1)) == 0


@pytest.mark.parametrize("radius,dots", [("3mm", 24), ("40", 40), ("40px", 40), ("25%", 48), (None, 19)])
def test_mask_rounded_rounds_the_corners_by_radius(tmp_path, radius, dots):
    black(tmp_path / "q.png", (400, 200))  # printed 384x192
    res = run(tmp_path, ".threshold mask=rounded" + (f" radius={radius}" if radius else ""))
    im = picture(res)
    assert corners(im) == [255] * 4 and codes(res) == []
    assert im.getpixel((dots, 0)) == 0 and im.getpixel((dots // 4, 0)) == 255  # the curve ends `dots` along
    assert im.getpixel((dots, dots)) == 0


def test_the_mask_edge_is_a_clean_line_of_dots(tmp_path):
    Image.new("RGB", (300, 300), (90, 90, 90)).save(tmp_path / "q.png")  # a grey that dithers
    plain = picture(run(tmp_path, ".dither"))
    im = picture(run(tmp_path, ".dither mask=circle"))
    for y in range(0, W, 7):  # inside the circle the same dots as without it; outside, no dot at all
        row = [x for x in range(W) if (x - W / 2 + 0.5) ** 2 + (y - W / 2 + 0.5) ** 2 < (W / 2 - 1) ** 2]
        outside = [x for x in range(W) if (x - W / 2 + 0.5) ** 2 + (y - W / 2 + 0.5) ** 2 > (W / 2 + 1) ** 2]
        assert all(im.getpixel((x, y)) == plain.getpixel((x, y)) for x in row)
        assert all(im.getpixel((x, y)) == 255 for x in outside)


def test_an_unknown_mask_names_the_shapes_and_prints_the_image_whole(tmp_path):
    black(tmp_path / "q.png")
    res = run(tmp_path, "mask=star")
    assert [(n.message, n.suggestion) for n in res.nudges if n.code == "M101"] == [
        ("mask=star", "circle, ellipse or rounded (radius=3mm)")
    ]
    assert ink(picture(res)) == 1.0


@pytest.mark.parametrize("attrs", ["radius=3mm", "mask=circle radius=3mm"])
def test_radius_without_mask_rounded_is_said(tmp_path, attrs):
    black(tmp_path / "q.png")
    assert said(run(tmp_path, attrs), "M101") == ["radius= does nothing without mask=rounded"]


def test_crop_mask_and_radius_are_image_settings_only():
    res = build("hello {crop=0,0,1,1 mask=circle radius=2}\n")
    assert sorted(said(res, "M101")) == ["unknown key 'crop='", "unknown key 'mask='", "unknown key 'radius='"]


# --- .invert --------------------------------------------------------------------------------------------------------


def test_invert_swaps_black_and_white_of_the_image(tmp_path):
    quadrants(tmp_path / "q.png", black=(0, 1))  # a black top half
    im = picture(run(tmp_path, ".invert .threshold"))
    assert ink(im.crop((0, 0, W, im.height // 2))) == 0.0 and ink(im.crop((0, im.height // 2, W, im.height))) == 1.0


def test_invert_with_a_mask_keeps_the_outside_paper(tmp_path):
    Image.new("RGB", (300, 300), "white").save(tmp_path / "q.png")  # white: all black once inverted
    im = picture(run(tmp_path, ".invert mask=circle"))
    assert corners(im) == [255] * 4 and im.getpixel((W // 2, W // 2)) == 0
    im = picture(run(tmp_path, ".invert mask=rounded radius=5mm"))
    assert corners(im) == [255] * 4 and im.getpixel((W // 2, 0)) == 0


def test_invert_keeps_the_corners_of_a_slanted_image_paper(tmp_path):
    Image.new("RGB", (300, 300), "white").save(tmp_path / "q.png")
    im = picture(run(tmp_path, ".invert rotate=45"))
    assert corners(im) == [255] * 4 and im.getpixel((W // 2, im.height // 2)) == 0


def test_the_view_shows_the_masked_image_round(tmp_path):
    black(tmp_path / "q.png")
    res = run(tmp_path, "mask=circle")
    lines = [ln for ln in view.lines(res.rows, res.profile) if ln.strip() and "┄" not in ln]
    assert lines[0][0] == " " and lines[0][-1] == " " and lines[-1][0] == " "  # the corners: no dots
    assert lines[len(lines) // 2][16] == "⣿"  # the middle: all dots


# --- ::: {.box .invert} ------------------------------------------------------------------------------------------------


def box_image(res) -> Image.Image:
    (r,) = [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "box"]
    return r.image.convert("L")


def test_an_inverted_box_is_one_black_band_with_its_text_white(tmp_path):
    res = build("::: {.box .invert}\nhello\n:::\n")
    assert codes(res) == ["P301"]  # .invert is a box setting now (it was M101); a tall black band: not on paper yet
    assert "inverted boxes" in said(res, "P301")[0]
    im = box_image(res)
    assert im.getpixel((0, 0)) == 0 and im.getpixel((W - 1, im.height - 1)) == 0  # black to its edges
    assert 0.6 < ink(im) < 1.0  # with white letters in it


def test_an_inverted_box_has_no_white_row_between_its_image_and_its_lines(tmp_path):
    Image.new("RGB", (200, 60), "white").save(tmp_path / "logo.png")  # a white logo background: black in the band
    src = "::: {.box .invert}\n![](logo.png){width=half}\n\n**BTC 61 200** {.center}\n\n**24h +4.2%**\n:::\n"
    im = box_image(build(src, base_dir=str(tmp_path)))
    for y in range(im.height):  # every row of the band is black at both its ends: no white gap anywhere
        assert im.getpixel((2, y)) == 0 and im.getpixel((W - 3, y)) == 0, y
    assert min(ink(im.crop((0, y, W, y + 1))) for y in range(im.height)) > 0.5


def test_an_image_inverted_inside_an_inverted_box_keeps_its_own_look(tmp_path):
    Image.new("RGB", (200, 60), "black").save(tmp_path / "logo.png")  # a screenshot's black: black in the band too
    src = "::: {.box .invert}\n![](logo.png){width=half .invert}\n:::\n"
    im = box_image(build(src, base_dir=str(tmp_path)))
    assert ink(im) == 1.0


def test_small_or_thin_text_in_an_inverted_box_is_said_to_close_up():
    res = build("::: {.box .invert}\nhello {font=Terminus size=16px}\n:::\n")
    assert said(res, "F204") == ["inverted text at 16px (not bold) closes up"]


def test_invert_inside_an_inverted_box_is_said_to_do_nothing():
    res = build("::: {.box .invert}\nhello {.invert}\n\n::: {.box .invert}\nx\n:::\n:::\n")
    assert said(res, "M101") == [
        ".invert does nothing inside an inverted box: its text is white on black already",
        ".invert does nothing on a box inside an inverted box: it is white on black already",
    ]
    im = box_image(res)
    assert im.getpixel((2, im.height // 2)) == 0  # still one band


def test_a_line_style_on_an_inverted_box_is_said():
    res = build("::: {.box .invert .dashed thickness=3}\nx\n:::\n")
    assert said(res, "M101") == [".dashed thickness=: an inverted box has no line to draw, it is black to its edges"]


def test_a_band_title_stays_white_on_black_and_a_border_title_is_white(tmp_path):
    for style in ("band", "border", "inside"):
        im = box_image(build(f"::: {{.box .invert title=HI title-style={style}}}\nx\n:::\n"))
        assert im.getpixel((2, 2)) == 0 and im.getpixel((2, im.height - 3)) == 0, style


def test_the_view_shows_an_inverted_box_with_heavy_lines_and_reversed_in_colour():
    res = build("::: {.box .invert}\nhello\n:::\n")
    plain = [ln for ln in view.lines(res.rows, res.profile) if ln.strip() and "┄" not in ln]
    assert plain[0].startswith("┏") and plain[1].startswith("┃hello") and plain[-1].startswith("┗")
    coloured = [ln for ln in view.lines(res.rows, res.profile, color=True) if ln.strip() and "┄" not in ln]
    assert all(ln.startswith("\x1b[7m") and ln.endswith("\x1b[0m") for ln in coloured)


# --- review fixes -------------------------------------------------------------------------------------------------


def test_a_band_title_of_a_box_inside_an_inverted_box_is_a_band_and_says_nothing():
    res = build("::: {.box .invert}\n::: {.box title=HI title-style=band}\nx\n:::\n:::\n")
    assert "M101" not in codes(res)  # nobody wrote .invert: the band is the inner box's own
    im = box_image(res)
    whitest = max(1 - ink(im.crop((0, y, W, y + 1))) for y in range(im.height))
    assert whitest > 0.7  # the inner band reads as a band: a white strip across the black, its title black


def test_the_colour_view_shows_a_bold_band_title_plain_inside_an_inverted_box():
    res = build("::: {.box .invert title=HELLO title-style=band}\nx\n:::\n")
    (title,) = [ln for ln in view.lines(res.rows, res.profile, color=True) if "H" in ln]
    assert "\x1b[1;7m" not in title and "\x1b[1;27m" in title  # bold, and plain again in the reversed box
    assert title.startswith("\x1b[7m") and title.endswith("\x1b[0m")


def test_the_colour_view_of_a_turned_inverted_box_leaves_its_mark_plain():
    res = build("::: {.box .invert rotate=90}\nhi\n:::\n")
    out = [ln for ln in view.lines(res.rows, res.profile, color=True) if "↻" in ln]
    assert out and "\x1b[7m" not in out[0]


def tile(res) -> tuple[Image.Image, tuple[int, int, int, int], tuple[int, int, int, int]]:
    """The inverted box's picture, the white tile of its first code as the paper shows it (in its rows, from the first
    all-white column, its left margin, to the last), and the code's ink inside the tile."""
    (b,) = [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "box"]
    im = b.image.convert("L")
    top, bottom, _ = b.code_spans[0]
    rows = im.crop((0, top, im.width, bottom))
    white = [x for x in range(im.width) if rows.crop((x, 0, x + 1, rows.height)).getextrema()[0] == 255]
    t = (white[0], top, white[-1] + 1, bottom)  # from its first all-white column (its margin) to its last
    inked = im.crop(t).point(lambda v: 255 - v).getbbox()
    return im, t, inked


def margins(t, inked) -> tuple[int, int, int, int]:
    """White dots left, above, right and below the code inside its tile."""
    w, h = t[2] - t[0], t[3] - t[1]
    return inked[0], inked[1], w - inked[2], h - inked[3]


def qr_module(im, t, inked) -> float:
    """A QR's module in dots, from its finder pattern: 7 modules of black along its top."""
    x0, y0 = t[0] + inked[0], t[1] + inked[1]
    return (next(x for x in range(x0, im.width) if im.getpixel((x, y0)) == 255) - x0) / 7


QR = "```qr\nhttps://example.com/pay/42\n```"


def test_a_qr_code_beside_text_in_an_inverted_box_keeps_4_modules_of_white_and_the_text_stays_inverted():
    src = (f"::: {{.box .invert}}\n:::: {{.columns}}\n::: {{.column width=50%}}\n{QR}\n:::\n::: {{.column}}\n"
           "**Pay here** with your phone\n:::\n::::\n:::\n")  # fmt: skip
    res = build(src)
    assert len(said(res, "Q114")) == 1 and "Q115" not in codes(res)
    im, t, inked = tile(res)
    module = qr_module(im, t, inked)
    assert module >= 3 and all(m >= 4 * module for m in margins(t, inked)), (module, margins(t, inked))
    assert im.getpixel((t[0] + inked[0] + round(3.5 * module), t[1] + inked[1] + round(3.5 * module))) == 0
    beside = im.crop((W // 2 + 12, t[1], W - 12, t[3]))  # the text's column, in the same rows
    assert ink(beside) > 0.7  # still white letters on black: only the code's tile is black on white


def test_a_paragraph_right_above_a_qr_code_leaves_it_4_modules_of_white():
    res = build(f"::: {{.box .invert}}\n**Pay here** {{.center}}\n{QR}\n:::\n")
    im, t, inked = tile(res)
    module = qr_module(im, t, inked)
    assert margins(t, inked)[1] >= 4 * module and margins(t, inked)[3] >= 4 * module
    assert ink(im.crop((t[0], t[1] - 2, t[2], t[1]))) == 1.0  # the band goes on right above the tile


def test_a_barcode_with_its_text_keeps_10_modules_of_white_beside_it():
    res = build("::: {.box .invert}\n```barcode {module=2}\nABC-123\n```\n:::\n")
    assert said(res, "Q114") and "Q115" not in codes(res)
    im, t, inked = tile(res)
    left, _, right, _ = margins(t, inked)
    assert left >= 10 * 2 and right >= 10 * 2
    text = im.crop((t[0] + inked[0], t[1] + inked[3] - 6, t[0] + inked[2], t[1] + inked[3]))
    assert 0 < ink(text) < 0.6  # its human-readable line is inside the tile, black on white


def test_a_barcode_too_wide_for_its_margin_says_how_many_modules_it_has():
    src = "::: {.box .invert width=half}\n```barcode {module=2}\nAB12\n```\n:::\n"  # 158 dots of bars in 168
    res = build(src)
    (msg,) = said(res, "Q115")
    assert msg.startswith("a barcode in an inverted box: 2 modules of white beside it, 10 wanted")
    assert [n.severity for n in res.nudges if n.code == "Q115"] == ["warning"] and "Q114" in codes(res)


def test_the_colour_view_shows_the_code_plain_and_the_band_beside_it_reversed():
    res = build(f"::: {{.box .invert}}\n**Pay here** {{.center}}\n{QR}\n:::\n")
    out = view.lines(res.rows, res.profile, color=True)
    code = [ln for ln in out if "\x1b[27m" in ln]
    assert all(ln.startswith("\x1b[7m") for ln in code)  # the QR's lines: plain over its tile, reversed around it
    assert sum("⣿" in ln.split("\x1b[27m")[1].split("\x1b[0;7m")[0] for ln in code) >= 3


def test_no_code_no_q114_and_a_code_in_turned_columns_in_an_inverted_box_is_a_warning():
    assert "Q114" not in codes(build("::: {.box .invert}\nhello\n:::\n"))
    src = f"::: {{.box .invert}}\n:::: {{.columns orientation=vertical}}\n::: {{.column}}\n{QR}\n:::\n::::\n:::\n"
    res = build(src)
    assert "Q114" not in codes(res)
    (msg,) = set(said(res, "Q115"))
    assert "turned columns inside an inverted box prints white on black" in msg


def test_a_tall_inverted_box_in_a_turned_label_is_cut_between_its_lines():
    box = "::: {.box .invert}\n" + "\n".join(f"line {i}" for i in range(40)) + "\n:::"
    src = f":::: {{.columns orientation=vertical}}\n::: {{.column}}\n{box}\n:::\n::: {{.column}}\nx\n:::\n::::\n"
    res = build(src)
    (n,) = [n for n in res.nudges if n.code in ("L112", "L114")]
    assert n.code == "L112" and "between its lines" in n.message


def test_shade_on_an_inverted_box_is_said_and_left_out():
    res = build("::: {.box .invert .shade}\nhello\n:::\n")
    assert said(res, "M101") == [".shade does nothing on an inverted box: it is black"]
    plain = box_image(build("::: {.box .invert}\nhello\n:::\n"))
    assert box_image(res).tobytes() == plain.tobytes()


def test_the_format_still_says_a_document_cannot_enable_the_network():
    from pathlib import Path

    fmt = (Path(__file__).resolve().parents[1] / "docs" / "FORMAT.md").read_text(encoding="utf-8")
    assert "A document cannot enable the network." in fmt.split("### 6.5 Images")[1].split("### 6.6")[0]


def test_an_inverted_box_inside_a_plain_box_in_a_turned_label_is_cut_between_its_lines():
    box = "::::: {.box}\n::: {.box .invert}\n" + "\n".join(f"line {i}" for i in range(40)) + "\n:::\n:::::"
    src = f":::: {{.columns orientation=vertical}}\n::: {{.column}}\n{box}\n:::\n::: {{.column}}\nx\n:::\n::::\n"
    (n,) = [n for n in build(src).nudges if n.code in ("L112", "L114")]
    assert n.code == "L112" and "between its lines" in n.message


def test_a_turned_tables_colour_view_is_cut_by_what_shows_never_inside_an_escape():
    import re

    rows = "\n".join(f"| a long product name {i} | {i} | 9,99 |" for i in range(3))
    res = build(f"| name | quantity | price |\n|---|---|---|\n{rows}\n{{orientation=vertical}}\n")
    plain = view.lines(res.rows, res.profile)
    coloured = view.lines(res.rows, res.profile, color=True)
    assert [re.sub(r"\x1b\[[0-9;]*m", "", ln) for ln in coloured] == plain
    assert not any(re.search(r"\x1b(?!\[[0-9;]*m)", ln) for ln in coloured)
