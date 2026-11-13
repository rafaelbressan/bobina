"""Images choose photo (dither) or logo (threshold) by themselves; .dither, .threshold and threshold=N% force it;
rotate= and .mirror turn the source before it is fitted to the paper."""

import random

import pytest
from PIL import Image, ImageDraw

from bobina import imaging
from bobina.engine import build


def logo(path, color=(0, 0, 0)):
    im = Image.new("RGB", (120, 60), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((5, 5, 50, 55), fill=color)
    d.polygon([(70, 10), (115, 30), (70, 50)], fill=color)
    im.save(path)
    return path


def photo(path):
    rnd = random.Random(7)
    im = Image.new("RGB", (120, 80))
    im.putdata([(min(255, x * 2 + rnd.randint(0, 40)), min(255, y * 3 + rnd.randint(0, 40)), 90 + rnd.randint(0, 60))
                for y in range(80) for x in range(120)])  # fmt: skip
    im.save(path)
    return path


def codes(res):
    return [n.code for n in res.nudges]


def test_line_art_tells_a_logo_from_a_photo(tmp_path):
    assert imaging.line_art(Image.open(logo(tmp_path / "l.png")))
    assert imaging.line_art(Image.open(logo(tmp_path / "b.png", (20, 20, 120))))  # dark blue on white
    assert not imaging.line_art(Image.open(photo(tmp_path / "p.png")))
    fog = Image.new("RGB", (64, 64), (200, 200, 200))
    ImageDraw.Draw(fog).rectangle((0, 0, 31, 63), fill=(180, 180, 180))
    assert not imaging.line_art(fog)  # flat but no ink against paper: a foggy photo, dithered


def test_the_cut_falls_between_ink_and_paper_and_a_flat_image_stays_paper():
    im = Image.new("L", (10, 10), 240)
    ImageDraw.Draw(im).rectangle((0, 0, 4, 9), fill=200)
    assert 200 < imaging.threshold_level(im) <= 240
    flat = Image.new("L", (10, 10), 100)
    assert imaging.photo(flat, 10, 1.0, "threshold").convert("L").getextrema() == (255, 255)  # not solid black


def shoe(path, size=(400, 300)):
    """A product on a white background: shaded, mostly paper."""
    im = Image.new("RGB", size, "white")
    px, rnd = im.load(), random.Random(1)
    for y in range(size[1]):
        for x in range(size[0]):
            if ((x - 200) / 150) ** 2 + ((y - 170) / 60) ** 2 < 1:
                v = int(40 + 120 * ((x - 50) / 300)) + rnd.randint(-10, 10)
                px[x, y] = (v, int(v * 0.7), int(v * 0.5))
    im.save(path)
    return path


def test_a_product_on_white_is_a_photo_and_a_jpeg_logo_is_a_logo(tmp_path):
    assert not imaging.line_art(Image.open(shoe(tmp_path / "s.png")))
    Image.open(logo(tmp_path / "l.png")).save(tmp_path / "l.jpg", quality=75)
    assert imaging.line_art(Image.open(tmp_path / "l.jpg"))


def notes(res):
    return [n.message for n in res.nudges if n.code == "I109"]


def test_the_note_says_what_was_seen_and_what_was_done(tmp_path):
    logo(tmp_path / "l.png")
    photo(tmp_path / "p.png")
    shoe(tmp_path / "s.png")
    drawing = ["l.png looks like a drawing: printed in black and white"]
    assert notes(build("![](l.png)\n", base_dir=str(tmp_path))) == drawing
    assert notes(build("![](p.png)\n", base_dir=str(tmp_path))) == ["p.png looks like a photo: dithered"]
    assert notes(build("![](s.png)\n", base_dir=str(tmp_path))) == ["s.png looks like a photo: dithered"]
    assert notes(build("![](l.png)\n", base_dir=str(tmp_path))) == drawing  # the cached dots say it again


def test_a_transparent_logo_counts_as_drawn_on_white(tmp_path):
    im = Image.new("RGBA", (120, 60), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle((10, 10, 60, 50), fill=(0, 0, 0, 255))
    im.save(tmp_path / "t.png")
    assert notes(build("![](t.png)\n", base_dir=str(tmp_path))) == [
        "t.png looks like a drawing: printed in black and white"
    ]


def test_forcing_and_the_document_default_skip_the_guess(tmp_path):
    logo(tmp_path / "l.png")
    for src in (
        "![](l.png){.dither}\n",
        "![](l.png){.threshold}\n",
        "![](l.png){threshold=40%}\n",
        "![](l.png){dither=atkinson}\n",
        "---\nimage: {dither: bayer}\n---\n![](l.png)\n",
    ):
        assert "I109" not in codes(build(src, base_dir=str(tmp_path))), src  # the writer chose: nothing to say
    sharp = build("![](l.png){.threshold}\n", base_dir=str(tmp_path))
    dithered = build("![](l.png){.dither}\n", base_dir=str(tmp_path))
    assert sharp.data != dithered.data and "I109" not in codes(sharp)


@pytest.mark.parametrize("bad", ["abc", "0", "100%", "-5%"])
def test_a_bad_threshold_is_a_nudge_and_still_prints(tmp_path, bad):
    logo(tmp_path / "l.png")
    res = build(f"![](l.png){{threshold={bad}}}\n", base_dir=str(tmp_path))
    assert "M101" in codes(res) and res.data


def test_threshold_percent_moves_the_cut(tmp_path):
    Image.linear_gradient("L").resize((64, 64)).save(tmp_path / "g.png")
    light = build("![](g.png){threshold=20%}\n", base_dir=str(tmp_path)).rows
    dark = build("![](g.png){threshold=80%}\n", base_dir=str(tmp_path)).rows

    def black(rows):
        return sum(r.image.histogram()[0] for r in rows if hasattr(r, "image"))

    assert black(dark) > black(light)


def test_rotate_and_mirror_turn_the_source(tmp_path):
    logo(tmp_path / "l.png")

    def image(src):
        return next(r.image for r in build(src, base_dir=str(tmp_path)).rows if hasattr(r, "image"))

    flat = image("![](l.png){width=50%}\n")
    turned = image("![](l.png){width=50% rotate=90}\n")
    assert turned.height > flat.height  # the tall side now runs down the paper, at the same width
    mirrored = image("![](l.png){width=100% .mirror}\n")
    plain = image("![](l.png){width=100%}\n")
    assert mirrored.transpose(Image.FLIP_LEFT_RIGHT).tobytes() == plain.tobytes()


def test_rotate_on_an_image_is_not_turned_twice(tmp_path):
    logo(tmp_path / "l.png")
    res = build("![](l.png){rotate=90}\n", base_dir=str(tmp_path))
    assert [r.kind for r in res.rows if hasattr(r, "image")] == ["image"]  # not the "rotated" block bitmap
    assert "L104" not in codes(res)


def test_bad_rotate_on_an_image_is_a_nudge(tmp_path):
    logo(tmp_path / "l.png")
    res = build("![](l.png){rotate=sideways}\n", base_dir=str(tmp_path))
    assert "M101" in codes(res) and res.data


def test_dither_class_dithers_even_when_the_default_is_a_threshold(tmp_path):
    photo(tmp_path / "p.png")
    doc = "---\nimage: {dither: threshold}\n---\n"
    sharp = build(doc + "![](p.png)\n", base_dir=str(tmp_path)).data
    soft = build(doc + "![](p.png){.dither}\n", base_dir=str(tmp_path)).data
    fs = build("![](p.png){dither=floyd-steinberg}\n", base_dir=str(tmp_path)).data
    assert sharp != soft and soft == fs


def test_dither_threshold_written_keeps_its_fixed_cut(tmp_path):
    photo(tmp_path / "p.png")
    fixed = build("![](p.png){dither=threshold}\n", base_dir=str(tmp_path)).data
    half = build("![](p.png){threshold=50%}\n", base_dir=str(tmp_path)).data  # 50% of 255 = 128
    assert fixed == half


def test_image_attributes_on_other_blocks_say_they_do_nothing():
    res = build("# Title {.mirror}\n\nText {threshold=40%}\n")
    msgs = [n.message for n in res.nudges if n.code == "M101"]
    assert any("'mirror' works on images only" in m for m in msgs)


def test_a_vector_turned_sideways_is_drawn_at_its_final_size(tmp_path):
    pytest.importorskip("resvg_py")
    (tmp_path / "w.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect x="10" y="10" width="180" height="80"'
        ' fill="black"/><path d="M40 50 L60 30 L60 70 Z" fill="white"/></svg>'
    )
    rows = build("![](w.svg){width=50% rotate=90}\n", base_dir=str(tmp_path)).rows
    im = next(r.image for r in rows if hasattr(r, "image")).convert("L")
    box = im.point(lambda v: 255 - v).getbbox()
    assert box[2] - box[0] <= im.width // 2 + 2  # the turned drawing fits the asked width …
    assert box[3] - box[1] > 1.6 * (box[2] - box[0])  # … and keeps its proportions (tall now)
    assert set(im.getdata()) <= {0, 255}
