""":name: icons in documents: what becomes an icon and what never does (code, escapes, data), how it is drawn
(native rows, 2x-4x, raster fonts, inverted), the M161 hint and bobina help icons."""

from pathlib import Path

import pytest
from PIL import ImageChops

from bobina import cli, icons
from bobina.engine import build
from bobina.nudges import Nudges
from bobina.parser import parse
from bobina.rows import TextRow

ROOT = Path(__file__).resolve().parents[1]


def runs_text(src: str) -> tuple[str, list]:
    n = Nudges()
    doc = parse(src, n)
    return "".join(r.text for r in doc.blocks[0].runs), list(n)


def icon(name: str) -> str:
    return icons.char_for(name)


def test_known_names_become_icons_in_any_case_and_through_aliases():
    text, problems = runs_text("A :fragile: B :Keep_Dry: C :this-way-up: D :home:\n")
    assert text == f"A {icon('fragile')} B {icon('keep-dry')} C {icon('this-side-up')} D {icon('house')}"
    assert not problems


@pytest.mark.parametrize(
    "src",
    [
        "10:30:00",
        "a:b:c",
        "http://example.com/:x:y",
        "x::y",
        "ratio 1:2:3",
        "word:fragile:",
        ":fragile:word",
        "https://x.com/:heart:",
        "see https://shop.example/:id: here",
    ],
)
def test_colons_that_are_not_a_shortcode_stay_text(src):
    text, problems = runs_text(src + "\n")
    assert text == src and not any(icons.is_icon(c) for c in text) and not problems


def test_code_and_escaped_colons_stay_text():
    text, _ = runs_text("`:fragile:` and \\:fragile:\n")
    assert text == ":fragile: and :fragile:"
    n = Nudges()
    doc = parse("```\n:fragile:\n```\n", n)
    assert doc.blocks[0].content == ":fragile:\n"


def test_an_unknown_name_is_printed_as_written_with_the_closest_names():
    text, problems = runs_text("x :fragil: y :fragil:\n")
    assert text == "x :fragil: y :fragil:"
    assert [p.code for p in problems] == ["M161"]  # once per name
    assert ":fragile:" in problems[0].suggestion and "bobina help icons" in problems[0].suggestion


def test_data_never_becomes_an_icon():
    raw = icon("heart")
    res = build("{{ a }} {{ b }}\n", fields=_tainted({"a": ":fragile:", "b": f"x{raw}y"}))
    cells = "".join(c.ch for r in res.rows if isinstance(r, TextRow) for c in r.cells)
    assert ":fragile:" in cells and "xy" in cells and not any(icons.is_icon(c) for c in cells)


def _tainted(d):
    from bobina.templating import Tainted

    return {k: Tainted(v) for k, v in d.items()}


def test_an_icon_is_two_columns_and_its_line_an_image():
    res = build("Box :fragile: here\n")
    row = next(r for r in res.rows if isinstance(r, TextRow))
    cell = next(c for c in row.cells if icons.is_icon(c.ch))
    assert cell.wide and not row.native and row.reason == "icon"
    assert not any(n.code in ("F301", "F302") for n in res.nudges)  # not a missing glyph


def test_large_icons_are_drawn_from_their_own_size():
    res = build(":fragile: {size=4x}\n")
    row = next(r for r in res.rows if isinstance(r, TextRow))
    im = res.emulator.render_row(row, res.profile.width_dots).convert("L")
    mark = icons.load("fragile", 96).convert("L")
    assert ImageChops.difference(im.crop((0, 0, 96, 96)), mark).getbbox() is None


def test_raster_fonts_draw_icons_at_their_line_height():
    res = build(':fragile: big {font="Atkinson Hyperlegible" size=large}\n')
    assert res.image.getbbox() is not None
    assert not any(n.code in ("F301", "F302") for n in res.nudges)


def test_the_terminal_view_marks_the_icon():
    from bobina import view

    res = build("A :fragile:\n")
    row = next(r for r in res.rows if isinstance(r, TextRow))
    assert "A ◆" in view.text_lines(row, 32, False)[0]


def test_every_icon_has_every_size_and_the_lucide_license_ships():
    for name in icons.names():
        for px in icons.SIZES:
            assert icons.load(name, px).size == (px, px), (name, px)
    assert (ROOT / "src/bobina/icons/licenses/Lucide-LICENSE.txt").is_file()
    assert "src/bobina/icons/licenses/*" in (ROOT / "pyproject.toml").read_text()


def test_every_alias_names_a_real_icon():
    for alias, name in icons.ALIASES.items():
        assert icons.canonical(alias) == name, alias


def test_help_icons_lists_names_and_aliases(capsys):
    assert cli.main(["help", "icons"]) == cli.OK
    out = capsys.readouterr().out
    assert ":fragile:" in out and ":this-side-up:" in out and ":home: = :house:" in out
    assert "Wash (" in out and ":wash-30:" in out and "wash at up to 30 °C" in out and "GINETEX" in out


def test_m161_names_the_line_of_the_unknown_name():
    n = Nudges()
    parse("line one\nline two\nline three :fragil:\n", n)
    assert [x.line for x in n if x.code == "M161"] == [3]


def test_a_missing_glyph_next_to_an_icon_is_still_said():
    res = build(":fragile: \U0001f9ff\n")  # a glyph no font has after the icon
    assert any(x.code == "F301" for x in res.nudges)
    assert not any(x.code == "F302" and icons.is_icon(x.message[6:7]) for x in res.nudges)


def test_an_icon_in_a_table_keeps_two_columns():
    res = build("| a | b |\n|---|---|\n| :fragile: | x |\n")
    cells = [c for r in res.rows if isinstance(r, TextRow) for c in r.cells if icons.is_icon(c.ch)]
    assert cells and all(c.wide for c in cells)


def test_raster_icons_keep_underline_and_strike():
    plain = build(':fragile: x {font="Atkinson Hyperlegible"}\n').image
    struck = build('~~:fragile:~~ x {font="Atkinson Hyperlegible"}\n').image
    assert ImageChops.difference(plain.convert("L"), struck.convert("L")).getbbox() is not None


def test_icons_use_a_private_area_symbol_fonts_do_not():
    assert all(ord(icons.char_for(n)) >= 0x100000 for n in icons.names())
    assert not icons.is_icon("\U000f0018")  # a Nerd Fonts glyph stays a glyph


def test_the_step_pause_shows_a_mark_for_an_icon():
    from bobina.cli import steps

    res = build("# :fragile: Glass\n")
    assert steps.title(res) == "◆ Glass"


def test_every_category_icon_exists_with_a_meaning():
    from bobina.icons.catalog import CATEGORIES

    for _key, _title, _about, items in CATEGORIES:
        for name, meaning in items:
            assert icons.canonical(name) == name and meaning, name


def test_the_icons_guide_and_its_pictures_are_current():
    import importlib.util

    from PIL import Image

    from bobina.icons import catalog

    spec = importlib.util.spec_from_file_location("gen", ROOT / "tools" / "gen_icon_docs.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.PAGE.read_text(encoding="utf-8") == catalog.docs_page(), "run: python tools/gen_icon_docs.py"
    for _key, _title, _about, items in catalog.CATEGORIES:
        for name, _m in items:
            got = Image.open(gen.PICTURES / f"{name}.png").convert("L")
            assert ImageChops.difference(got, gen.icon_png(name).convert("L")).getbbox() is None, name
    for slug, _t, _w, src in catalog.USES:
        got = Image.open(gen.PICTURES / f"use-{slug}.png").convert("L")
        want = gen.use_png(src).convert("1", dither=0).convert("L")
        assert got.size == want.size and ImageChops.difference(got, want).getbbox() is None, slug
