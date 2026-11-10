"""calibrate compare finds the paper in real photos. It knows the preview, so among the boxes the paper's straight
edges suggest it keeps the one whose print looks like the ticket: a lamp's reflection beside it (touching or a few
dots away), another bright strip, an off-centre ticket, a tight crop, a shadow, a dark image along the ticket or a
slight tilt do not fool it."""

import pytest
from PIL import Image, ImageDraw

from bobina import profile as profiles
from bobina.fidelity import find_paper

MTP = profiles.load("mtp-ii-58")


def _exact(height: int = 1400, block: bool = False) -> Image.Image:
    """A preview with a recognisable rhythm of ink: bands of different heights at irregular places."""
    im = Image.new("L", (384, height), 255)
    d = ImageDraw.Draw(im)
    for y0, y1 in ((40, 120), (200, 230), (330, 520), (610, 640), (700, 760), (900, 1150), (1250, 1270)):
        if y0 < height:
            d.rectangle((0, y0, 383, min(y1, height - 1)), fill=0)
    if block:
        d.rectangle((40, 150, 340, height - 1), fill=0)  # a dark image along most of the ticket
    return im


def _photo(exact, size=(1200, 2000), at=(400, 150), reflection=None, strip=None, shadow=False, tilt=0.0, crop=None):
    scale = 400 / (58 * 8)  # the paper is 400 px wide in the photo: 58 mm at 8 dots/mm
    printable = round(384 * scale)
    paper = Image.new("L", (400, round(exact.height * scale) + 60), 240)
    ink = exact.resize((printable, round(exact.height * scale))).point(lambda v: 10 if v < 128 else 240)
    paper.paste(ink, ((400 - printable) // 2, 30))
    if shadow:
        ImageDraw.Draw(paper).rectangle((0, paper.height * 3 // 5, 399, paper.height * 3 // 5 + 20), fill=60)
    photo = Image.new("L", size, 40)  # dark table
    d = ImageDraw.Draw(photo)
    if reflection:
        d.ellipse(reflection, fill=235)
    if strip:
        d.rectangle(strip, fill=235)
    t = paper.rotate(tilt, expand=True, fillcolor=40) if tilt else paper
    photo.paste(t, (at[0] - (t.width - paper.width) // 2, at[1] - (t.height - paper.height) // 2))
    return (photo.crop(crop) if crop else photo), paper.size


CASES = {
    "reflection touching a corner": ({}, {"reflection": (-200, -200, 520, 420)}, 0.03),
    "shadow across the margins": ({}, {"shadow": True}, 0.03),
    "2 degree tilt": ({}, {"tilt": 2}, 0.06),
    "dark image along most of the ticket": ({"block": True}, {}, 0.03),
    "reflection 10 dots away": ({"height": 900}, {"at": (150, 200), "reflection": (560, 100, 1100, 650)}, 0.03),
    "short ticket beside a reflection": (
        {"height": 600},
        {"at": (150, 200), "reflection": (560, 100, 1100, 650)},
        0.03,
    ),
    "off-centre ticket, strip to its right": ({}, {"at": (150, 150), "strip": (1000, 0, 1100, 1999)}, 0.03),
    "off-centre ticket, strip nearer the middle": ({}, {"at": (100, 150), "strip": (650, 0, 750, 1999)}, 0.03),
    "tight crop touching the right border": ({}, {"crop": (100, 0, 800, 2000)}, 0.03),
    "tight crop touching both sides": ({}, {"crop": (400, 100, 800, 1900)}, 0.03),
    "big landscape photo, strong strip": (
        {},
        {"size": (4032, 3024), "at": (1500, 600), "strip": (3000, 0, 3300, 3023)},
        0.03,
    ),
}


@pytest.mark.parametrize("name", CASES)
def test_the_preview_picks_the_paper(name):
    ex_kw, ph_kw, tol = CASES[name]
    exact = _exact(**ex_kw)
    photo, (w, h) = _photo(exact, **ph_kw)
    paper = find_paper(photo, exact, MTP, 58.0)
    assert abs(paper.width - w) <= tol * w and abs(paper.height - h) <= tol * h, (name, paper.size, (w, h))


def test_without_a_preview_a_plain_photo_still_works():
    photo, (w, h) = _photo(_exact(), reflection=(-200, -200, 520, 420))
    paper = find_paper(photo)
    assert abs(paper.width - w) <= 0.03 * w and abs(paper.height - h) <= 0.03 * h
