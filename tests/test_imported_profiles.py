"""Profiles imported from escpos-printer-db: load, print a document, and stay conservative until measured."""

import pytest

from bobina import cli, profile
from bobina.engine import build

IMPORTED = sorted(  # the shipped profiles only: a developer's own ~/.config profiles must not change the tests
    f.name[:-5] for f in profile._builtin_dir().iterdir()
    if f.name.endswith(".toml") and profile.load(f.name[:-5]).get("measured") is False
)  # fmt: skip


def test_there_are_imported_profiles_and_the_measured_one_is_kept():
    assert len(IMPORTED) >= 30
    assert profile.load("mtp-ii-58").get("measured", True) is not False


@pytest.mark.parametrize("pid", IMPORTED)
def test_an_imported_profile_prints_a_document(pid):
    p = profile.load(pid)
    assert p.get("source", "").startswith("escpos-printer-db")
    assert p.get("native.glyph_ranges") == [[0x20, 0x7E]]  # accents go raster until measured
    assert p.get("escpos.blank_rows_after_raster") is True  # safe mode
    res = build("# Pão de queijo\n\n- [ ] item\n\n```qr\nhttps://example.com\n```\n", profile_name=pid)
    assert res.data.startswith(b"\x1b@") and res.length_mm > 10
    assert p.columns >= 16


def test_profile_list_says_which_are_measured(capsys):
    assert cli.main(["profile", "list"]) == cli.OK
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if ln.startswith("mtp-ii-58"))
    assert "measured" in line and "not measured" not in line
    line = next(ln for ln in out.splitlines() if ln.startswith("epson-tm-t20ii "))
    assert "not measured" in line


def test_profile_show_names_the_source(capsys):
    assert cli.main(["profile", "show", "zijiang-zj-5870"]) == cli.OK
    out = capsys.readouterr().out
    assert "escpos-printer-db" in out and "bobina calibrate tear" in out


def test_imported_layout_never_exceeds_the_printer_columns():
    for pid in IMPORTED:
        p = profile.load(pid)
        assert p.columns * p.cell[0] <= p.width_dots


def test_variants_have_different_names():
    names = [profile.load(pid).name for pid in IMPORTED]
    assert len(names) == len(set(names))
