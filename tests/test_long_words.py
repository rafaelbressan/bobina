""":name: a word longer than the line: cut to fill lines in every font, never lost; an address cut after its / ? & = - _
. or #; said once (L101), with the width in that font's columns."""

import re

import pytest

from bobina import rasterfont, view
from bobina.engine import build
from bobina.rows import TextRow

URL = "https://www.nfce.fazenda.rj.gov.br/consulta?chave=33261133381266008560650040002779781004569942"
WORD = "Pneumoultramicroscopicossilicovulcanoconiotico"


def view_lines(res) -> list[str]:
    """The terminal view's lines, frames and padding off: the letters the paper shows, line by line."""
    out = []
    for ln in view.lines(res.rows, res.profile):
        ln = re.sub(r"[│┌┐└┘─]", "", ln).strip()
        if ln and not set(ln) <= set("┄⟶ "):
            out.append(ln)
    return out


def cuts(res) -> list:
    return [n for n in res.nudges if n.code == "L101"]


@pytest.mark.parametrize(
    "src",
    [
        f"{URL} {{font=Terminus size=16px}}",
        f'{WORD} {{font="Atkinson Hyperlegible" size=28px}}',
        f"::: {{.box}}\n{URL} {{font=Terminus size=16px}}\n:::",
        f"> {URL} {{font=Terminus size=16px}}",
        f"- {URL} {{font=Terminus size=16px}}",
        f"{URL} {{render=raster}}",
    ],
)
def test_a_raster_word_wider_than_the_line_keeps_every_letter_and_is_said_once(src):
    res = build(src + "\n")
    word = URL if URL[:20] in src else WORD
    assert word in "".join(view_lines(res)).replace("- ", "", 1)  # every letter, on lines that fit the paper
    assert len(cuts(res)) == 1


def test_the_address_in_terminus_16px_breaks_after_its_question_mark():
    res = build(f"{URL} {{font=Terminus size=16px}}\n")
    assert view_lines(res) == [
        "https://www.nfce.fazenda.rj.gov.br/consulta?",
        "chave=332611333812660085606500400027797810045699",
        "42",
    ]
    (n,) = cuts(res)
    assert n.message == "word 'https://www.nfce.faz…' split at 48 columns in Terminus 16px"
    assert "size=12px" in n.suggestion and "```qr" in n.suggestion  # an address: a QR code carries it whole


def test_a_column_and_its_neighbour_keep_every_letter():
    src = f":::: {{.columns}}\n::: {{.column width=50%}}\n{URL} {{font=Terminus size=12px}}\n:::\n::: {{.column}}\nao lado\n:::\n::::\n"
    res = build(src)
    text = "".join(ln.replace("ao lado", "").strip() for ln in view_lines(res))
    assert text == URL and "ao lado" in view_lines(res)[0] and len(cuts(res)) == 1
    assert "size=12px" not in cuts(res)[0].suggestion  # already 12px: not a smaller size again


def test_thirty_icons_glued_all_print():
    res = build(":fragile:" * 30 + " {render=raster}\n")
    assert sum(ln.count("◆") for ln in view_lines(res)) == 30 and len(cuts(res)) == 1


def test_the_printer_font_prefers_the_address_punctuation():
    res = build(URL + "\n")
    lines = ["".join(c.ch for c in r.cells).rstrip() for r in res.rows if isinstance(r, TextRow)]
    assert lines == ["https://www.nfce.fazenda.rj.gov.", "br/consulta?chave=", URL[50:82], URL[82:]]
    assert len(cuts(res)) == 1 and "```qr" in cuts(res)[0].suggestion


def test_a_word_without_punctuation_is_cut_at_the_last_letter_that_fits():
    res = build("x" * 40 + "\n")
    assert [len(r.cells) for r in res.rows if isinstance(r, TextRow)] == [32, 8]
    assert "```qr" not in cuts(res)[0].suggestion


@pytest.mark.parametrize(
    ("text", "at"),
    [
        ("consulta?chave", 9),
        ("gov.br", 4),
        ("a/b", 2),
        ("x-y", 2),
        ("2026-11", 5),  # a - between digits (a date, a range): fine
        ("a_b", 2),
        ("page#top", 5),
    ],
)
def test_soft_places(text, at):
    assert rasterfont.soft_break(text, at)


@pytest.mark.parametrize(
    ("text", "at"),
    [
        ("19.90", 3),  # a decimal
        ("https://x", 7),  # between two slashes
        ("abc", 2),
        ("a.", 2),  # the end of the word: nothing to cut
    ],
)
def test_not_soft_places(text, at):
    assert not rasterfont.soft_break(text, at)


def test_a_decimal_is_not_a_preferred_break():
    word = "12345678901234567890123.4567890123456789"
    res = build(word + "\n")
    lines = ["".join(c.ch for c in r.cells) for r in res.rows if isinstance(r, TextRow)]
    assert lines == [word[:32], word[32:]]


def test_a_break_that_leaves_the_line_less_than_half_full_is_not_taken():
    word = "abc/" + "d" * 40
    res = build(word + "\n")
    assert ["".join(c.ch for c in r.cells) for r in res.rows if isinstance(r, TextRow)] == [word[:32], word[32:]]


def test_chinese_and_thai_fill_their_lines_as_before_without_a_cut():
    thai = "ภาษาไทยเขียนติดกันโดยไม่มีช่องว่างระหว่างคำภาษาไทยเขียนติดกันโดยไม่มีช่องว่าง"
    res = build(f"{thai} {{font=Terminus size=16px}}\n")
    lines = view_lines(res)
    assert len(lines) == 2 and "".join(lines) == thai and not cuts(res)
    said: list = []  # Chinese (whatever font draws it): filled line by line between any two letters, not a cut
    t = rasterfont.Tok("中文没有空格" * 6, rasterfont.resolve("DejaVu Sans").path, 24)
    out = rasterfont.layout_lines([t], 384, 0, split=lambda word, room: said.append(word))
    assert "".join(x.text for ln in out for x in ln) == t.text and len(out) == 2 and not said
    assert all(sum(x.width() for x in ln) <= 384 for ln in out)


def test_every_raster_line_fits_its_room():
    t = rasterfont.Tok(URL, rasterfont.resolve("Terminus").path, 16)
    said: list = []
    lines = rasterfont.layout_lines([t], 384, 0, split=lambda word, room: said.append(room))
    assert all(sum(x.width() for x in ln) <= 384 for ln in lines) and "".join(x.text for ln in lines for x in ln) == URL
    assert said == [384]


def test_one_letter_wider_than_the_line_is_kept_whole():
    t = rasterfont.Tok("W", rasterfont.resolve("Terminus").path, 32)
    assert [[x.text for x in ln] for ln in rasterfont.layout_lines([t], 4, 0)] == [["W"]]
