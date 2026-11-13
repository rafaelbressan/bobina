"""Tables turned along the paper (orientation=vertical, or auto when the columns are cramped), like a book's spine:
the header on the right, the text read from top to bottom. Checked on the drawn dots, on 58 and 80 mm paper."""

import pytest

from bobina.engine import build
from bobina.rows import BitmapRow, TextRow

PROFILES = {"mtp-ii-58": 384, "epson-tm-t20iii": 576}


def table(ncol: int, nrow: int = 4, cell=lambda r, c: f"v{r}{c}", head=lambda c: f"Col{c}", attrs: str = "") -> str:
    lines = ["| " + " | ".join(head(c) for c in range(ncol)) + " |", "|" + "---|" * ncol]
    lines += ["| " + " | ".join(cell(r, c) for c in range(ncol)) + " |" for r in range(nrow)]
    return "\n".join(lines) + "\n" + (f"\n{{{attrs}}}\n" if attrs else "")


def codes(res) -> list[str]:
    return [n.code for n in res.nudges]


def turned(res) -> list:
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "table"]


def ink_columns(im) -> list[int]:
    """Black dots per column of a mode '1' image."""
    px = im.load()
    return [sum(1 for y in range(im.height) if px[x, y] == 0) for x in range(im.width)]


def rule_x(im) -> int:
    """The header rule: after the turn, the longest run of ink in one column."""
    cols = ink_columns(im)
    return cols.index(max(cols))


@pytest.mark.parametrize("profile", PROFILES)
def test_a_narrow_table_stays_standing(profile):
    res = build(table(3), profile_name=profile)
    assert not turned(res) and "L106" not in codes(res)
    assert any(isinstance(r, TextRow) for r in res.rows)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("ncol", [8, 12])
def test_a_cramped_table_turns_by_itself_and_says_so(profile, ncol):
    if profile == "epson-tm-t20iii" and ncol == 8:  # 48 columns: 8 columns of 4 characters still fit standing
        res = build(table(ncol), profile_name=profile)
        assert not turned(res)
        return
    res = build(table(ncol), profile_name=profile)
    assert turned(res) and "L106" in codes(res)
    note = next(n for n in res.nudges if n.code == "L106")
    assert f"{ncol} columns" in note.message and "VERTICALLY" in note.message


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("ncol", [3, 8, 12])
def test_vertical_always_turns_without_a_note_and_horizontal_never(profile, ncol):
    v = build(table(ncol, attrs="orientation=vertical"), profile_name=profile)
    assert turned(v) and "L106" not in codes(v)
    h = build(table(ncol, attrs="orientation=horizontal"), profile_name=profile)
    assert not turned(h) and "L106" not in codes(h)


@pytest.mark.parametrize("profile", PROFILES)
def test_the_header_is_on_the_right_like_a_books_spine(profile):
    res = build(table(8, nrow=3, cell=lambda r, c: "", attrs="orientation=vertical"), profile_name=profile)
    (row,) = turned(res)
    im = row.image
    x = rule_x(im)
    cols = ink_columns(im)
    assert sum(cols[x + 3 :]) > 0  # the header's letters: right of the rule
    assert sum(cols[: x - 3]) == 0  # empty body cells: nothing on the left


@pytest.mark.parametrize("profile", PROFILES)
def test_text_reads_from_top_to_bottom(profile):
    """The first column of the table (Col0) is at the top of the turned block, the last at the bottom."""
    res = build(table(8, nrow=1, attrs="orientation=vertical"), profile_name=profile)
    im = turned(res)[0].image
    px = im.load()
    rows_with_ink = [y for y in range(im.height) if any(px[x, y] == 0 for x in range(im.width))]
    assert rows_with_ink[0] < im.height // 4 and rows_with_ink[-1] > im.height // 2


@pytest.mark.parametrize("profile,width", PROFILES.items())
@pytest.mark.parametrize("nrow", [1, 10, 40, 120])
def test_nothing_leaves_the_paper_and_many_rows_go_on_in_blocks(profile, width, nrow):
    res = build(table(8, nrow=nrow, attrs="orientation=vertical"), profile_name=profile)
    blocks = turned(res)
    for r in blocks:
        assert r.image.width == width
        x = rule_x(r.image)
        assert sum(ink_columns(r.image)[x + 3 :]) > 0  # every block repeats the header on its right
    if nrow >= 40:
        assert len(blocks) > 1
    body_dots = sum(sum(ink_columns(b.image)[: rule_x(b.image) - 3]) for b in blocks)
    assert body_dots > 0


def test_blocks_share_one_length_along_the_paper():
    res = build(table(4, nrow=30, cell=lambda r, c: str(r) * 2, attrs="orientation=vertical"))
    assert len(turned(res)) > 1  # 30 rows do not fit across 58 mm in one block
    # the turned blocks share one length along the paper (same columns), so the table reads the same in each
    assert len({b.image.height for b in turned(res)}) == 1


def test_long_cells_do_not_wrap_when_turned_and_a_long_table_says_its_length():
    long = "x" * 60
    res = build(table(6, nrow=3, cell=lambda r, c: long, attrs="orientation=vertical"))
    (row,) = turned(res)
    assert row.image.height >= 6 * 60 * 12  # along the paper: every character of every cell, never wrapped
    assert "L102" in codes(res)


@pytest.mark.parametrize("profile", PROFILES)
def test_icons_and_cjk_keep_their_two_columns(profile):
    cell = lambda r, c: ":fragile:" if c == 0 else "漢字" if c == 1 else f"v{r}"  # noqa: E731
    res = build(table(8, cell=cell, attrs="orientation=vertical"), profile_name=profile)
    assert turned(res) and "M161" not in codes(res)
    stand = build(table(8, cell=cell, attrs="orientation=horizontal"), profile_name=profile)
    assert all(r.image.width == PROFILES[profile] for r in turned(res)) and not turned(stand)


def test_data_stays_literal_in_a_turned_table():
    src = "| a | b | c | d | e | f | g | h |\n|---|---|---|---|---|---|---|---|\n| {{ x }} | 1 | 2 | 3 | 4 | 5 | 6 | 7 |\n\n{orientation=vertical}\n"
    res = build(src, fields={"x": "**:fragile:**"})
    assert turned(res) and "M161" not in codes(res)


@pytest.mark.parametrize("align", [".left", ".right", ".center", ""])
def test_the_turned_block_is_placed_like_any_object(align):
    res = build(table(5, nrow=2, attrs=f"orientation=vertical width=half {align}".strip()))
    (row,) = turned(res)
    x0, _, x1, _ = row.image.getbbox() if row.image.mode != "1" else row.image.point(lambda v: 255 - v).getbbox()
    w = row.image.width
    if align == ".left":
        assert x0 < w // 8
    elif align == ".right":
        assert x1 > w - w // 8
    else:
        assert abs((x0 + x1) // 2 - w // 2) < w // 8


def test_width_half_makes_narrower_blocks():
    full = turned(build(table(6, nrow=20, attrs="orientation=vertical")))
    half = turned(build(table(6, nrow=20, attrs="orientation=vertical width=half")))
    assert len(half) > len(full)


def test_compact_has_no_say_on_a_turned_table():
    a = turned(build(table(8, attrs="orientation=vertical .compact")))
    b = turned(build(table(8, attrs="orientation=vertical")))
    assert [r.image.tobytes() for r in a] == [r.image.tobytes() for r in b]


def test_an_unknown_orientation_is_a_note_and_auto_decides():
    res = build(table(3, attrs="orientation=sideways"))
    assert "M101" in codes(res) and not turned(res)


def test_the_column_alignment_survives_the_turn():
    right = build("| a | n |\n|---|--:|\n| x | 1 |\n| y | 22 |\n\n{orientation=vertical}\n")
    left = build("| a | n |\n|---|---|\n| x | 1 |\n| y | 22 |\n\n{orientation=vertical}\n")
    assert turned(right)[0].image.tobytes() != turned(left)[0].image.tobytes()
