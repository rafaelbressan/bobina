"""Features not tested on paper (src/bobina/features.py): code pages, the cutter, native barcodes on imported
profiles. They are tested on the bytes here; a job that uses one gets note P301, and the docs carry the mark."""

from pathlib import Path

from bobina import cli, features
from bobina.engine import build

ROOT = Path(__file__).resolve().parents[1]
ESC, GS = b"\x1b", b"\x1d"
CP = {"encoding": "codepage", "codepages": {"cp860": 3, "cp858": 19}}


def _codes(res):
    return [n.code for n in res.nudges.items] if hasattr(res.nudges, "items") else [n.code for n in res.nudges]


# --- code pages -----------------------------------------------------------------------------------------------


def test_utf8_profiles_send_utf8_and_no_code_page():
    data = build("ação\n").data
    assert "ação".encode() in data and ESC + b"t" not in data


def test_a_code_page_profile_selects_the_page_and_encodes_in_it():
    data = build("ação\n", overrides=CP).data
    assert b"a" + ESC + b"t\x03" + "ção".encode("cp860") in data  # ASCII as is, the page set before the first accent


def test_a_character_missing_from_the_first_page_switches_page():
    data = build("pão €\n", overrides=CP).data
    assert ESC + b"t\x03" in data and ESC + b"t\x13" + "€".encode("cp858") in data


def test_a_character_in_no_page_goes_raster():
    res = build("→ ok\n", overrides=CP)
    assert "→".encode() not in res.data and GS + b"v0" in res.data  # the line is drawn instead


def test_code_pages_get_the_untested_note():
    assert "P301" in _codes(build("ação\n", overrides=CP))
    assert "P301" not in _codes(build("ascii only\n", overrides=CP))  # nothing went through a code page
    assert "P301" not in _codes(build("ação\n"))  # UTF-8 on the measured MTP-II


# --- cutter -----------------------------------------------------------------------------------------------------


def test_a_cutter_cuts_after_the_final_feed():
    data = build("oi\n", overrides={"cutter": "partial"}).data
    assert data.endswith(GS + b"V\x01")  # function A: cut where the paper is, no second feed
    assert build("oi\n", overrides={"cutter": "full"}).data.endswith(GS + b"V\x00")
    assert GS + b"V" not in build("oi\n").data  # no cutter: no cut command
    assert "P301" in _codes(build("oi\n", overrides={"cutter": "full"}))


def test_each_label_of_a_batch_is_cut(tmp_path, capsys):
    from bobina.engine import build_batch

    b = build_batch("# {{ n }}\n", rows_data=[{"n": "a"}, {"n": "b"}], overrides={"cutter": "partial"})
    assert b.data.count(GS + b"V\x01") == 2


# --- native barcodes on imported profiles -----------------------------------------------------------------------


def test_native_barcodes_on_an_imported_profile_get_the_note():
    over = {"measured": False, "barcode.native": ["code128"]}
    res = build("```barcode {type=code128}\nABC123\n```\n", overrides=over)
    assert GS + b"k" in res.data and "P301" in _codes(res)


# --- where the mark shows ----------------------------------------------------------------------------------------


def test_profile_show_lists_the_untested_features(capsys):
    assert cli.main(["profile", "show", "epson-tm-t20ii"]) == cli.OK
    out = capsys.readouterr().out
    assert features.MARK in out and "code pages" in out


def test_every_untested_feature_is_marked_in_the_docs():
    tested = (ROOT / "docs" / "TESTED.md").read_text(encoding="utf-8")
    for key, f in features.untested().items():
        assert f["title"] in tested, key
    cli_md = (ROOT / "docs" / "CLI.md").read_text(encoding="utf-8") + (ROOT / "docs" / "FORMAT.md").read_text(
        encoding="utf-8"
    )
    assert cli_md.count(features.MARK) >= len(features.untested())


def test_multi_byte_and_right_to_left_pages_never_carry_text():
    res = build("漢字 שלום\n", overrides={"encoding": "codepage", "codepages": {"cp932": 1, "cp862": 36}})
    assert b"\x1bt" not in res.data and GS + b"v0" in res.data  # raster, as before code pages


def test_the_importer_keeps_only_safe_pages():
    import importlib.util

    spec = importlib.util.spec_from_file_location("imp", ROOT / "tools" / "import_profiles.py")
    imp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(imp)
    assert imp.codec("CP860") == "cp860" and imp.codec("CP932") is None and imp.codec("CP864") is None
