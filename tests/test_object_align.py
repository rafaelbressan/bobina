"""Every object is placed the same way: .left, .center (the default) or .right, and width=full|half|third|50%|30mm|dots
sizes it. Checked on the drawn dots (where the ink is), not only on the absence of a warning, on 58 and 80 mm paper."""

import pytest
from PIL import Image, ImageDraw

from bobina import preview
from bobina.engine import build
from bobina.rows import BarcodeRow, BitmapRow, QRRow, TextRow

PROFILES = {"mtp-ii-58": 384, "epson-tm-t20iii": 576}
BTC = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"

OBJECTS = {  # each with room to move: narrower than 58 mm paper
    "image": "![](logo.png){{width=120 {a}}}\n",
    "qr": "```qr {{module=3 {a}}}\nhttps://example.com\n```\n",
    "barcode": "```barcode {{type=code128 {a}}}\nAB12\n```\n",
    "datamatrix": "```datamatrix {{module=4 {a}}}\nhello\n```\n",
    "pdf417": "```pdf417 {{module=2 columns=2 {a}}}\nhello\n```\n",
    "pay": f'```pay {{{{scheme=bitcoin to="{BTC}" module=3 caption=none {{a}}}}}}\n```\n',
    "contact": "```contact whatsapp {{module=3 caption=none {a}}}\n+55 11 90000-0000\n```\n",
    "table": "| Item | Qty |\n|---|--:|\n| Bread | 6 |\n\n{{.compact {a}}}\n",
}
OBJECT_ROWS = (BitmapRow, BarcodeRow, QRRow, TextRow)


def logo(tmp_path):
    im = Image.new("RGB", (120, 60), "white")
    ImageDraw.Draw(im).rectangle((0, 0, 119, 59), fill="black")
    im.save(tmp_path / "logo.png")


def ink_box(res, kinds=OBJECT_ROWS):
    """Left and right edge of the ink of the object's rows, drawn as the preview (= the print) draws them."""
    rows = [r for r in res.rows if isinstance(r, kinds) and getattr(r, "kind", "") != "divider"]
    im = preview.render(rows, res.profile, res.emulator).convert("L")
    box = im.point(lambda v: 255 - v).getbbox()
    assert box, [n.code for n in res.nudges]
    return box[0], box[2], im.width


def render(tmp_path, kind, attrs, profile):
    logo(tmp_path)
    return build(OBJECTS[kind].format(a=attrs), base_dir=str(tmp_path), profile_name=profile)


@pytest.mark.parametrize("profile,width", PROFILES.items())
@pytest.mark.parametrize("kind", OBJECTS)
def test_left_center_right_move_the_ink(tmp_path, kind, profile, width):
    left = ink_box(render(tmp_path, kind, ".left", profile))
    right = ink_box(render(tmp_path, kind, ".right", profile))
    center = ink_box(render(tmp_path, kind, ".center", profile))
    assert left[2] == right[2] == center[2] == width  # every row is the printable width: nothing outside it
    assert left[0] < center[0] < right[0], (left, center, right)
    assert left[0] <= 24 and right[1] >= width - 24  # at the edges (a code keeps its quiet zone)
    assert abs((center[0] + center[1]) / 2 - width / 2) <= 24  # centred
    if kind != "table":  # objects are centred unless aligned; a table starts at the left
        assert ink_box(render(tmp_path, kind, "", profile))[:2] == center[:2]
    else:
        assert ink_box(render(tmp_path, kind, "", profile))[:2] == left[:2]


@pytest.mark.parametrize("profile,width", PROFILES.items())
@pytest.mark.parametrize("kind", ["image", "qr", "barcode", "datamatrix", "pdf417", "pay", "contact"])
def test_width_full_fills_the_paper_and_half_fills_half(tmp_path, kind, profile, width):
    full = ink_box(render(tmp_path, kind, "width=full", profile))
    half = ink_box(render(tmp_path, kind, "width=half", profile))
    assert full[1] - full[0] > half[1] - half[0]
    assert full[1] - full[0] >= width * 0.6  # codes keep integer modules and quiet zones: near, not exactly, full
    assert half[1] - half[0] <= width // 2 + 2


@pytest.mark.parametrize("given", ["third", "50%", "30mm", "200", "200px"])
def test_every_width_word_works_on_a_code(tmp_path, given):
    res = render(tmp_path, "qr", f"width={given}", "mtp-ii-58")
    a, b, _ = ink_box(res)
    assert b - a <= 240 and "M101" not in [n.code for n in res.nudges]


@pytest.mark.parametrize("old", ["size=full", "size=half", ".justify"])
@pytest.mark.parametrize("kind", ["image", "qr", "barcode", "datamatrix", "pay", "contact"])
def test_the_old_words_say_what_to_write(tmp_path, kind, old):
    res = render(tmp_path, kind, old, "mtp-ii-58")
    (note,) = [n for n in res.nudges if n.code == "M101" and ("text size" in n.message or "justify" in n.message)]
    assert "width=" in note.suggestion


@pytest.mark.parametrize("align", [".left", ".center", ".right"])
@pytest.mark.parametrize("kind", ["image", "qr", "pay", "contact"])
def test_a_caption_follows_its_object(tmp_path, kind, align):
    logo(tmp_path)
    doc = OBJECTS[kind].format(a=f'{align} caption="Loja"').replace(" caption=none", "")
    res = build(doc, base_dir=str(tmp_path))
    caption = [r for r in res.rows if isinstance(r, TextRow)]
    assert caption and all(r.align == align[1:] for r in caption)
    obj = ink_box(res, (BitmapRow, QRRow))
    cap = ink_box(res, (TextRow,))
    if align == ".left":
        assert cap[0] <= obj[0] + 24
    elif align == ".right":
        assert cap[1] >= obj[1] - 24
    else:
        assert abs((cap[0] + cap[1]) - (obj[0] + obj[1])) <= 48


@pytest.mark.parametrize("profile,width", PROFILES.items())
@pytest.mark.parametrize("align", [".left", ".right"])
def test_a_turned_captioned_image_keeps_its_place(tmp_path, profile, width, align):
    logo(tmp_path)
    res = build(f'![](logo.png){{width=120 rotate=30 caption="Loja" {align}}}\n', base_dir=str(tmp_path),
                profile_name=profile)  # fmt: skip
    a, b, w = ink_box(res, (BitmapRow,))
    assert w == width
    assert (a <= 24) if align == ".left" else (b >= width - 24)


def test_a_compact_table_keeps_its_columns_when_aligned(tmp_path):
    res = render(tmp_path, "table", ".right", "mtp-ii-58")
    lines = ["".join(c.ch for c in r.cells) for r in res.rows if isinstance(r, TextRow)]
    ends = {len(x) for x in lines}
    assert ends == {res.profile.columns}  # every line ends at the right edge: the grid is intact
    assert len({x.index("Qty" if "Qty" in x else "6") for x in lines}) <= 2


CAPTIONED = ["image", "qr", "barcode", "datamatrix", "pdf417", "pay", "contact"]


def captioned(tmp_path, kind, attrs):
    logo(tmp_path)
    doc = OBJECTS[kind].format(a=f'caption="Loja" {attrs}').replace(" caption=none", "")
    return build(doc, base_dir=str(tmp_path))


@pytest.mark.parametrize("kind", CAPTIONED)
@pytest.mark.parametrize(
    "obj,cap",
    [(".right", "left"), (".left", "right"), ("width=full", "center")],
    ids=["object-right-caption-left", "object-left-caption-right", "object-full-caption-center"],
)
def test_the_caption_has_its_own_alignment(tmp_path, kind, obj, cap):
    res = captioned(tmp_path, kind, f"{obj} caption-align={cap}")
    caption = [r for r in res.rows if isinstance(r, TextRow) and "Loja" in "".join(c.ch for c in r.cells)]
    assert caption and all(r.align == cap for r in caption), [n.code for n in res.nudges]
    a, b, w = ink_box(res, (TextRow,))
    if cap == "left":
        assert a <= 24
    elif cap == "right":
        assert b >= w - 24
    else:
        assert abs((a + b) / 2 - w / 2) <= 24
    obj_a, obj_b, _ = ink_box(res, (BitmapRow, QRRow, BarcodeRow))
    if obj == ".right":
        assert obj_b >= w - 24  # the object stays where it was put
    elif obj == ".left":
        assert obj_a <= 24


@pytest.mark.parametrize("kind", CAPTIONED)
def test_by_default_the_caption_follows_and_a_bad_value_says_so(tmp_path, kind):
    res = captioned(tmp_path, kind, ".right")
    assert all(
        r.align == "right" for r in res.rows if isinstance(r, TextRow) and "Loja" in "".join(c.ch for c in r.cells)
    )
    res = captioned(tmp_path, kind, ".right caption-align=middle")
    assert any(n.code == "M101" and "caption-align" in n.message for n in res.nudges)


# --------------------------------------------------------------- review: edges that must never crash or mislead


@pytest.mark.parametrize("given", ["inf", "inf%", "infmm", "nan", "-inf"])
@pytest.mark.parametrize("kind", ["image", "qr", "barcode", "datamatrix", "pay", "contact"])
def test_an_infinite_width_is_a_note(tmp_path, kind, given):
    res = render(tmp_path, kind, f"width={given}", "mtp-ii-58")
    assert any(n.code == "M101" and "width=" in n.message for n in res.nudges)


def test_a_barcode_width_never_goes_below_a_scannable_module(tmp_path):
    res = build("```barcode {type=code128 width=third}\nABCDEFGHIJ1234567\n```\n")
    assert "Q108" in [n.code for n in res.nudges]
    rows = [r for r in res.rows if isinstance(r, BarcodeRow)]
    assert all(r.module >= 2 for r in rows)


def test_a_vertical_barcode_with_a_tiny_width_still_prints():
    res = build("```barcode {type=code128 orientation=vertical width=5}\nAB12\n```\n")
    assert [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "barcode"]


def test_a_missing_image_prints_no_lonely_caption(tmp_path):
    res = build('![](nope.png){caption="Loja"}\n', base_dir=str(tmp_path))
    assert not [r for r in res.rows if isinstance(r, TextRow)]


def test_size_on_a_payment_or_contact_is_said_once(tmp_path):
    for doc in (OBJECTS["contact"], OBJECTS["pay"]):
        res = build(doc.format(a="size=full"))
        notes = [n for n in res.nudges if n.code == "M101"]
        assert len(notes) == 1 and "width=full" in notes[0].suggestion


def test_a_datamatrix_fitted_too_small_says_so():
    res = build("```datamatrix {width=40}\n" + "x" * 40 + "\n```\n")
    assert "Q101" in [n.code for n in res.nudges]


@pytest.mark.parametrize("doc", ["hello {mirror=x}\n", "```qr {mirror=x}\nhi\n```\n", "# Title {mirror=y}\n"])
def test_mirror_on_anything_but_an_image_is_said_once(doc):
    assert [n.code for n in build(doc).nudges if "mirror" in n.message] == ["M101"]
