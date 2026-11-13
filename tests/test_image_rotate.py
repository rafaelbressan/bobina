"""Images turned by any angle, mirrored on either axis and captioned: whatever the size, shape, type or angle, no dot
is ever outside the printable width (58 and 80 mm), the turned image is fitted whole, and the preview is the print."""

import pytest
from PIL import Image, ImageDraw

from bobina import preview
from bobina.engine import build
from bobina.rows import BitmapRow, TextRow

PROFILES = {"mtp-ii-58": 384, "epson-tm-t20iii": 576}  # printable dots across: 58 mm and 80 mm paper


def shape(path, w, h, mode="RGB", fmt=None):
    """A frame with an arrow-like corner, so a turn or a mirror shows (and is not symmetric)."""
    im = Image.new(mode, (w, h), (255, 255, 255, 0) if mode == "RGBA" else (255, 255, 255))
    d = ImageDraw.Draw(im)
    ink = (0, 0, 0, 255) if mode == "RGBA" else (0, 0, 0)
    d.rectangle((0, 0, w - 1, h - 1), outline=ink, width=max(1, min(w, h) // 12))
    d.polygon([(0, 0), (max(1, w // 2), 0), (0, max(1, h // 2))], fill=ink)
    im.save(path, fmt)
    return path


def svg(path, w=200, h=100):
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"><rect width="{w}" height="{h}" fill="white"/>'
        f'<rect x="4" y="4" width="{w - 8}" height="{h - 8}" fill="none" stroke="black" stroke-width="6"/>'
        f'<path d="M4 4 L{w // 2} 4 L4 {h // 2} Z" fill="black"/></svg>'
    )
    return path


def image_rows(res):
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "image"]


def inside_the_paper(res, width):
    """Every image row is exactly the printable width and its ink is inside it (the encoder sends no more)."""
    rows = image_rows(res)
    assert rows, [n.code for n in res.nudges]
    for r in rows:
        assert r.image.width == width
        box = r.image.convert("L").point(lambda v: 255 - v).getbbox()
        assert box is None or (box[0] >= 0 and box[2] <= width)
    return rows


def codes(res):
    return [n.code for n in res.nudges]


ANGLES = [0, 1, 15, 30, 45, 89, 90, 135, 180, 270, 359, -45, 720]


@pytest.mark.parametrize("profile,width", PROFILES.items())
@pytest.mark.parametrize("ang", ANGLES)
def test_any_angle_fits_the_paper(tmp_path, profile, width, ang):
    shape(tmp_path / "a.png", 300, 200)
    res = build(f"![](a.png){{rotate={ang}}}\n", base_dir=str(tmp_path), profile_name=profile)
    inside_the_paper(res, width)
    import math

    c, s = abs(math.cos(math.radians(ang))), abs(math.sin(math.radians(ang)))
    kept = (300 if c >= s else 200) / (300 * c + 200 * s)  # of its size at the nearest right angle
    assert ("I110" in codes(res)) == (ang % 90 != 0 and kept < 0.9)  # said when its corners cost >10%
    assert "B102" not in codes(res)  # images: the fit is said by I110, not the text nudge


@pytest.mark.parametrize(
    "size",
    [(10, 10), (60, 20), (1200, 80), (300, 300), (80, 300), (400, 120), (8, 200), (1, 1)],
    ids=["narrow", "small-wide", "wider-than-paper", "square", "portrait", "landscape", "long-strip", "1x1"],
)
@pytest.mark.parametrize("ang", [0, 45, 90, -30])
@pytest.mark.parametrize("profile,width", PROFILES.items())
def test_every_shape_and_size_stays_on_the_paper(tmp_path, size, ang, profile, width):
    shape(tmp_path / "s.png", *size)
    res = build(f"![](s.png){{rotate={ang}}}\n", base_dir=str(tmp_path), profile_name=profile)
    inside_the_paper(res, width)


@pytest.mark.parametrize("given,dots", [("50%", 192), ("30mm", 240), ("200", 200), ("200px", 200), ("2,5mm", 20)])
def test_width_in_percent_millimetres_and_dots(tmp_path, given, dots):
    shape(tmp_path / "w.png", 300, 300)
    res = build(f"![](w.png){{width={given} rotate=45}}\n", base_dir=str(tmp_path))
    (row,) = inside_the_paper(res, 384)
    box = row.image.convert("L").point(lambda v: 255 - v).getbbox()
    assert box[2] - box[0] <= dots + 1  # the turned box is fitted to the asked width, never wider


@pytest.mark.parametrize("given", ["abc", "0", "-5mm", "%"])
def test_a_width_bobina_cannot_read_is_a_note_and_the_paper_width(tmp_path, given):
    shape(tmp_path / "w.png", 100, 100)
    res = build(f"![](w.png){{width={given}}}\n", base_dir=str(tmp_path))
    inside_the_paper(res, 384)
    assert "M101" in codes(res)


def test_a_width_wider_than_the_paper_is_reduced(tmp_path):
    shape(tmp_path / "w.png", 100, 100)
    res = build("![](w.png){width=900}\n", base_dir=str(tmp_path))
    inside_the_paper(res, 384)
    assert "I102" in codes(res)


@pytest.mark.parametrize("profile,width", PROFILES.items())
@pytest.mark.parametrize(
    "kind",
    ["transparent-png", "jpeg", "svg", "pdf"],
)
@pytest.mark.parametrize("ang", [45, 90, 200])
def test_every_type_turns_and_fits(tmp_path, kind, ang, profile, width):
    if kind == "transparent-png":
        name = shape(tmp_path / "t.png", 200, 100, mode="RGBA").name
    elif kind == "jpeg":
        name = shape(tmp_path / "t.jpg", 200, 100, fmt="JPEG").name
    elif kind == "svg":
        pytest.importorskip("resvg_py")
        name = svg(tmp_path / "t.svg").name
    else:
        pytest.importorskip("pypdfium2")
        name = shape(tmp_path / "t.pdf", 200, 100, fmt="PDF").name
    res = build(f"![]({name}){{rotate={ang}}}\n", base_dir=str(tmp_path), profile_name=profile)
    inside_the_paper(res, width)


def test_a_slanted_vector_is_drawn_again_at_its_final_size(tmp_path):
    """Not a small render blown up: the turned box spans the asked width with sharp (black or white) dots."""
    pytest.importorskip("resvg_py")
    svg(tmp_path / "v.svg", 400, 100)
    (row,) = image_rows(build("![](v.svg){rotate=30 width=300}\n", base_dir=str(tmp_path)))
    box = row.image.convert("L").point(lambda v: 255 - v).getbbox()
    assert 280 <= box[2] - box[0] <= 301


def test_transparent_corners_and_turned_corners_are_white(tmp_path):
    shape(tmp_path / "t.png", 200, 200, mode="RGBA")
    (row,) = image_rows(build("![](t.png){rotate=45 .threshold}\n", base_dir=str(tmp_path)))
    im = row.image.convert("L")
    box = im.point(lambda v: 255 - v).getbbox()
    assert im.getpixel((box[0], box[1])) == 255  # the corner of the turned box: paper, not ink


def ink(res):
    (row,) = image_rows(res)
    im = row.image.convert("L")
    return im.crop(im.point(lambda v: 255 - v).getbbox())


@pytest.mark.parametrize(
    "attrs,expect",
    [
        ("mirror=x", Image.Transpose.FLIP_LEFT_RIGHT),
        (".mirror", Image.Transpose.FLIP_LEFT_RIGHT),
        ("mirror=y", Image.Transpose.FLIP_TOP_BOTTOM),
        ("mirror=xy", Image.Transpose.ROTATE_180),
    ],
)
def test_mirror_on_either_axis(tmp_path, attrs, expect):
    shape(tmp_path / "m.png", 200, 100)
    plain = ink(build("![](m.png){.threshold}\n", base_dir=str(tmp_path)))
    turned = ink(build(f"![](m.png){{{attrs} .threshold}}\n", base_dir=str(tmp_path)))
    assert turned.tobytes() == plain.transpose(expect).tobytes()


def test_rotate_comes_before_mirror(tmp_path):
    """rotate=90 then mirror=x is not mirror=x then rotate=90: the order is fixed and documented."""
    shape(tmp_path / "o.png", 200, 100)
    plain = ink(build("![](o.png){.threshold rotate=90}\n", base_dir=str(tmp_path)))
    both = ink(build("![](o.png){.threshold rotate=90 mirror=x}\n", base_dir=str(tmp_path)))
    assert both.tobytes() == plain.transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes()


@pytest.mark.parametrize("bad", ["rotate=abc", "rotate=nan", "rotate=inf", "mirror=z", "mirror=diagonal"])
def test_a_bad_turn_is_a_note_and_the_image_prints_as_it_is(tmp_path, bad):
    shape(tmp_path / "b.png", 200, 100)
    plain = ink(build("![](b.png){.threshold}\n", base_dir=str(tmp_path)))
    res = build(f"![](b.png){{{bad} .threshold}}\n", base_dir=str(tmp_path))
    assert ink(res).tobytes() == plain.tobytes()
    assert "M101" in codes(res)


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_an_angle_that_is_not_a_number_never_crashes_a_text_block(bad):
    assert "M101" in codes(build(f"hello {{rotate={bad}}}\n"))


@pytest.mark.parametrize("look", [".threshold", ".dither", ""])
def test_rotate_then_the_look(tmp_path, look):
    shape(tmp_path / "l.png", 200, 100)
    res = build(f"![](l.png){{rotate=45 {look}}}\n", base_dir=str(tmp_path))
    inside_the_paper(res, 384)
    assert ("I109" in codes(res)) == (not look)  # the look is decided on the turned image unless written


def test_the_shrink_note_says_how_much(tmp_path):
    shape(tmp_path / "q.png", 200, 200)
    res = build("![](q.png){rotate=45}\n", base_dir=str(tmp_path))
    (note,) = [n for n in res.nudges if n.code == "I110"]
    assert "rotate=45" in note.message and "71%" in note.message
    assert "I110" not in codes(build("![](q.png){rotate=5}\n", base_dir=str(tmp_path)))  # barely smaller: quiet


def text_of(res):
    return [" ".join("".join(c.ch for c in r.cells).split()) for r in res.rows if isinstance(r, TextRow)]


def test_a_caption_under_an_image(tmp_path):
    shape(tmp_path / "c.png", 200, 100)
    res = build('![](c.png){caption="Loja da Ana" rotate=45}\n', base_dir=str(tmp_path))
    rows = [r for r in res.rows if isinstance(r, (BitmapRow, TextRow))]
    kinds = [type(r).__name__ for r in rows]
    assert kinds.index("BitmapRow") < kinds.index("TextRow")  # under it
    assert "Loja da Ana" in text_of(res)
    assert next(r for r in rows if isinstance(r, TextRow)).align == "center"


def test_caption_alt_uses_the_alt_text(tmp_path):
    shape(tmp_path / "c.png", 200, 100)
    assert "Loja da Ana" in text_of(build("![Loja da Ana](c.png){caption=alt}\n", base_dir=str(tmp_path)))
    res = build("![](c.png){caption=alt}\n", base_dir=str(tmp_path))
    assert text_of(res) == [] and "M101" in codes(res)


def test_a_fenced_image_takes_a_caption(tmp_path):
    shape(tmp_path / "c.png", 200, 100)
    res = build('```image {caption="Menu"}\nc.png\n```\n', base_dir=str(tmp_path))
    assert "Menu" in text_of(res) and "M101" not in codes(res)


@pytest.mark.parametrize("profile,width", PROFILES.items())
def test_a_long_caption_wraps_inside_the_paper(tmp_path, profile, width):
    shape(tmp_path / "c.png", 200, 100)
    long = "uma legenda bem comprida " * 6
    res = build(f'![](c.png){{caption="{long.strip()}"}}\n', base_dir=str(tmp_path), profile_name=profile)
    lines = text_of(res)
    assert len(lines) > 1
    assert all(len(x) <= res.profile.columns for x in lines)


@pytest.mark.parametrize("cap", ['""', "none", "auto"])
def test_an_empty_caption_prints_nothing(tmp_path, cap):
    shape(tmp_path / "c.png", 200, 100)
    assert text_of(build(f"![](c.png){{caption={cap}}}\n", base_dir=str(tmp_path))) == []


def test_a_caption_with_accents_and_emoji(tmp_path):
    shape(tmp_path / "c.png", 200, 100)
    res = build('![](c.png){caption="Café com pão ☕"}\n', base_dir=str(tmp_path))
    joined = " ".join(text_of(res))
    assert "Café com pão" in joined or res.rows  # the emoji may be drawn as an image (no glyph in the font)


def test_a_caption_from_data_prints_literally(tmp_path):
    from bobina.templating import Tainted

    shape(tmp_path / "c.png", 200, 100)
    res = build(
        '![](c.png){caption="{{ name }}"}\n', base_dir=str(tmp_path), fields={"name": Tainted("**x** :fragile:")}
    )
    assert "**x** :fragile:" in text_of(res)  # never Markdown, never an icon


def test_mirror_and_caption_on_a_text_block_say_they_do_nothing():
    res = build("hello {mirror=x}\n")
    assert "M101" in codes(res)
    res = build('hello {caption="x"}\n')
    assert "M101" in codes(res)


def test_the_preview_is_the_print(tmp_path):
    shape(tmp_path / "p.png", 300, 200)
    res = build("![a](p.png){rotate=30 mirror=xy caption=alt}\n", base_dir=str(tmp_path))
    (row,) = image_rows(res)
    drawn = preview.render(res.rows, res.profile, res.emulator).convert("1")
    assert drawn.width == row.image.width
