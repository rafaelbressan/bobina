"""Fonts for other scripts (Thai, Devanagari, CJK…): downloaded once, pinned, never from the tests.

conftest.py replaces scriptfonts.fetch with one that fails: every download here is a fake one, serving a tiny font
built in the test (two Thai letters, or two CJK ones, drawn as squares)."""

import dataclasses
import hashlib
import json
import re
import time
import unicodedata

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.unicodedata import Scripts
from PIL import Image

from bobina import cli, rasterfont, scriptfonts
from bobina.engine import build
from bobina.rows import BitmapRow, TextRow
from bobina.scriptfonts import fetch as real_fetch  # the real one: only its refusals are tested (no network)

THAI = "กส"


def tiny_font(chars: str) -> bytes:
    """A TrueType font with a filled square for each of `chars` (and .notdef, space)."""
    names = [".notdef", "space"] + [f"uni{ord(c):04X}" for c in chars]
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({32: "space", **{ord(c): f"uni{ord(c):04X}" for c in chars}})
    glyphs = {}
    for n in names:
        pen = TTGlyphPen(None)
        if n.startswith("uni"):
            pen.moveTo((100, 0))
            pen.lineTo((100, 700))
            pen.lineTo((700, 700))
            pen.lineTo((700, 0))
            pen.closePath()
        glyphs[n] = pen.glyph()
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (800, 100) for n in names})
    fb.setupHorizontalHeader(ascent=900, descent=-200)
    fb.setupNameTable({"familyName": "Tiny Test", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=900, sTypoDescender=-200, usWinAscent=900, usWinDescent=200)
    fb.setupPost()
    import io

    out = io.BytesIO()
    fb.save(out)
    return out.getvalue()


LICENSE_TEXT = b"SIL OPEN FONT LICENSE Version 1.1 (test copy)\n"


@pytest.fixture
def fake_pack(monkeypatch):
    """Replaces the 'thai' pack with a tiny font; returns the list of URLs fetched."""
    font = tiny_font(THAI)
    real = scriptfonts.PACKS["thai"]
    pack = dataclasses.replace(
        real,
        size=len(font),
        sha256=hashlib.sha256(font).hexdigest(),
        license_size=len(LICENSE_TEXT),
        license_sha256=hashlib.sha256(LICENSE_TEXT).hexdigest(),
    )
    monkeypatch.setitem(scriptfonts.PACKS, "thai", pack)
    fetched = []

    def fetch(url, size):
        fetched.append(url)
        return font if url == pack.url else LICENSE_TEXT

    monkeypatch.setattr(scriptfonts, "fetch", fetch)
    return fetched


def codes(res):
    return [n.code for n in res.nudges]


# -- the pinned table ------------------------------------------------------------------------------------


def test_pinned_table_is_consistent():
    files = set()
    for pid, p in scriptfonts.PACKS.items():
        assert pid == p.id and re.fullmatch(r"[a-z]+(-[a-z]+)?", pid)
        for url, size, sha in ((p.url, p.size, p.sha256), (p.license_url, p.license_size, p.license_sha256)):
            assert url.startswith("https://raw.githubusercontent.com/"), url
            commit = re.search(r"/([0-9a-f]{40})/", url)
            assert commit and commit.group(1) in (scriptfonts.NOTO, scriptfonts.CJK, scriptfonts.GF), url
            assert re.fullmatch(r"[0-9a-f]{64}", sha), (pid, url)
            assert 0 < size <= scriptfonts.MAX_BYTES
        assert p.url.startswith("https://raw.githubusercontent.com/notofonts/")  # fonts only from notofonts
        assert p.file.startswith(p.family.replace(" ", "") + "-Regular.") and p.file not in files
        files.add(p.file)
        for s in p.scripts:
            assert s in Scripts.NAMES, f"{pid}: {s} is not a Unicode script code"
    # every script bobina knows a sample of is drawn by the bundled font or by a pack
    for s in scriptfonts.SAMPLES:
        assert scriptfonts._bundled_draws(s) or scriptfonts.packs_for(s), s
    assert scriptfonts.PACKS["chinese"].size > 1_000_000  # the notice must say MB, not KB
    assert scriptfonts.human_size(scriptfonts.PACKS["chinese"].size) == "8.3 MB"


def test_fetch_refuses_anything_but_pinned_https():
    for url in ("http://raw.githubusercontent.com/x", "https://example.com/font.ttf", "file:///etc/passwd"):
        with pytest.raises(scriptfonts.FontDownloadError, match="refused"):
            real_fetch(url, 100)


# -- scripts ---------------------------------------------------------------------------------------------


def test_script_runs_keep_digits_and_marks_with_their_run():
    assert scriptfonts.split_runs("Olá(สวัสดี)") == [("Latn", "Olá("), ("Thai", "สวัสดี)")]
    assert scriptfonts.split_runs("12 中文あ") == [("Hani", "12 中文"), ("Hira", "あ")]
    assert scriptfonts.split_runs("...") == [("Zyyy", "...")]
    assert scriptfonts.direction("123 שלום") == "R" and scriptfonts.direction("12") == ""


def test_support_answers_for_scripts_and_languages(fake_pack):
    assert scriptfonts.support("pt_BR") == "ready"
    assert scriptfonts.support("ar") == "ready"  # the bundled DejaVu Sans draws Arabic
    assert scriptfonts.support("ja-JP") == "download"
    assert scriptfonts.support("Devanagari") == "download"
    assert scriptfonts.support("xx") == "none"
    assert scriptfonts.support("th") == "download"
    scriptfonts.download(scriptfonts.PACKS["thai"])
    assert scriptfonts.support("th") == "ready" and scriptfonts.support("Thai") == "ready"


def test_han_follows_the_language_then_the_kana_around_it():
    ids = lambda **kw: scriptfonts.packs_for("Hani", **kw)[0].id  # noqa: E731
    assert ids() == "chinese"
    assert ids(context="漢字とかな") == "japanese"
    assert ids(context="한국 漢字") == "korean"
    assert ids(lang="zh-TW") == "chinese-traditional"
    assert ids(lang="ja") == "japanese"


# -- first use, offline, off -----------------------------------------------------------------------------


def test_first_use_downloads_once_with_the_license_then_works_offline(fake_pack, tmp_path):
    res = build(f"Olá {THAI} ok")
    assert "F304" in codes(res) and "F302" not in codes(res) and "F305" not in codes(res)
    d = tmp_path / "data" / "fonts" / "thai"
    assert sorted(p.name for p in d.iterdir()) == ["NotoSansThai-Regular.ttf", "OFL.txt"]
    assert (d / "OFL.txt").read_bytes() == LICENSE_TEXT
    n = len(fake_pack)
    again = build(f"Olá {THAI} ok")
    assert len(fake_pack) == n, "a font already here is never fetched again"
    assert "F304" not in codes(again)
    rows = [r for r in again.rows if isinstance(r, BitmapRow)]
    assert rows and rows[0].text_rows[0].cells[0].ch == "O"


def test_no_network_prints_with_boxes_and_says_how_to_get_the_font(tmp_path):
    res = build(f"Olá {THAI}")  # conftest's fetch fails like a machine without network
    f305 = [n for n in res.nudges if n.code == "F305"]
    assert f305 and "no network in tests" in f305[0].message and "bobina fonts get thai" in f305[0].suggestion
    assert "F302" not in codes(res)  # F305 already says why the letters are boxes
    assert any(isinstance(r, BitmapRow) for r in res.rows)  # it prints anyway
    assert not (tmp_path / "data" / "fonts" / "thai").exists()


def test_downloads_off_in_config_never_fetch(fake_pack, tmp_path):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "config.toml").write_text("font_downloads = false\n")
    res = build(THAI)
    assert fake_pack == [] and "config.toml" in next(n.message for n in res.nudges if n.code == "F305")


def test_a_file_that_does_not_match_its_checksum_is_thrown_away(fake_pack, monkeypatch, tmp_path):
    monkeypatch.setattr(scriptfonts, "fetch", lambda url, size: b"x" * size)
    res = build(THAI)
    assert "does not match" in next(n.message for n in res.nudges if n.code == "F305")
    assert not (tmp_path / "data" / "fonts" / "thai").exists()


def test_the_letters_are_drawn_with_the_downloaded_font(fake_pack):
    def ink(res):
        return sum(r.image.convert("L").histogram()[0] for r in res.rows if isinstance(r, BitmapRow))

    scriptfonts._FAILED["thai"] = ("offline", time.monotonic())  # first: as without network (boxes)
    boxes = ink(build(THAI))
    scriptfonts._FAILED.clear()
    drawn = ink(build(THAI))
    assert scriptfonts.installed(scriptfonts.PACKS["thai"]) is not None
    assert drawn > 2 * boxes  # two filled squares (the tiny font), not two outlined boxes


# -- terminal, JSON, MCP ----------------------------------------------------------------------------------


def test_notice_before_the_download_on_the_terminal(fake_pack, monkeypatch, capsys):
    before = []
    fetch = scriptfonts.fetch

    def watched(url, size):
        before.append(capsys.readouterr().err)  # what the terminal showed before the first byte
        return fetch(url, size)

    monkeypatch.setattr(scriptfonts, "fetch", watched)
    assert cli.main(["check", THAI]) == cli.OK
    assert "bobina: downloading Noto Sans Thai" in before[0] and "SIL Open Font License 1.1" in before[0]
    assert "F304" in capsys.readouterr().err


def test_noninteractive_json_has_the_notice_in_the_problems_only(fake_pack, monkeypatch, capsys):
    monkeypatch.setenv("BOBINA_NONINTERACTIVE", "1")
    assert cli.main(["check", "--json", THAI]) == cli.OK
    out, err = capsys.readouterr()
    data = json.loads(out)
    assert "F304" in [p["code"] for p in data["problems"]]
    assert "downloading" not in err


# -- the fonts command -------------------------------------------------------------------------------------


def test_fonts_get_by_name_language_or_document(fake_pack, tmp_path, capsys):
    assert cli.main(["fonts", "get", "thai"]) == cli.OK
    assert "downloaded" in capsys.readouterr().out
    assert cli.main(["fonts", "get", "th"]) == cli.OK
    assert "already here" in capsys.readouterr().out
    doc = tmp_path / "menu.bob.md"
    doc.write_text(f"# Menu\n\n{THAI}\n", encoding="utf-8")
    assert cli.main(["fonts", "get", str(doc), "--json"]) == cli.OK
    assert json.loads(capsys.readouterr().out)[0]["status"] == "present"
    assert cli.main(["fonts", "get", "klingon"]) == cli.USAGE
    assert cli.main(["fonts", "scripts", "--json"]) == cli.OK
    rows = {r["name"]: r for r in json.loads(capsys.readouterr().out)}
    assert rows["thai"]["status"] == "downloaded" and rows["devanagari"]["status"] == "on first use"


def test_fonts_get_without_network_fails_with_exit_4(capsys):
    assert cli.main(["fonts", "get", "devanagari"]) == cli.UNREACHABLE
    assert "no network" in capsys.readouterr().err


# -- drawing --------------------------------------------------------------------------------------------


def test_lines_that_shape_are_drawn_whole_not_cell_by_cell():
    res = build("plain\n\nمرحبا بالعالم")
    assert isinstance(res.rows[1], TextRow) and res.rows[1].native
    assert any(isinstance(r, BitmapRow) for r in res.rows)
    assert "F302" not in codes(res)  # DejaVu Sans draws Arabic: nothing to download


def test_right_to_left_words_are_ordered_from_the_right():
    dv = rasterfont.resolve("DejaVu Sans").path
    toks = [rasterfont.Tok(t, dv, 20, space=t == " ") for t in ["שלום", " ", "עולם", " ", "123", " ", "test"]]
    order = [t.text for t in rasterfont.visual_order(toks, rtl=True) if not t.space]
    assert order == ["test", "123", "עולם", "שלום"]
    ltr = [rasterfont.Tok(t, dv, 20, space=t == " ") for t in ["a", " ", "שלום", " ", "עולם", " ", "b"]]
    assert [t.text for t in rasterfont.visual_order(ltr, rtl=False) if not t.space] == ["a", "עולם", "שלום", "b"]


def test_text_without_spaces_wraps_between_letters():
    dv = rasterfont.resolve("DejaVu Sans").path
    tok = rasterfont.Tok("ສະບາຍດີ" * 12, dv, 24)  # Lao, no spaces: DejaVu Sans draws it
    lines = rasterfont.layout_lines([tok], 384, 0)
    assert len(lines) > 1 and all(sum(t.width() for t in ln) <= 384 for ln in lines)
    assert "".join(t.text for ln in lines for t in ln) == tok.text
    assert not any(unicodedata.category(ln[0].text[0]).startswith("M") for ln in lines[1:])  # never a mark first


# -- review fixes ----------------------------------------------------------------------------------------


def test_a_word_split_across_fonts_still_wraps():
    dv = rasterfont.resolve("DejaVu Sans").path
    at = rasterfont.resolve("Atkinson Hyperlegible").path
    toks = [
        rasterfont.Tok("ສະບາຍດີ" * 6, dv, 24),
        rasterfont.Tok("(123)", at, 24, glue=True),  # a digit run in another font, inside the same word
        rasterfont.Tok("ສະບາຍດີ" * 6, dv, 24, glue=True),
    ]
    lines = rasterfont.layout_lines(toks, 384, 0)
    assert len(lines) > 2 and all(sum(t.width() for t in ln) <= 384 for ln in lines)
    assert "".join(t.text for ln in lines for t in ln) == "".join(t.text for t in toks)


def test_an_installed_font_without_a_letter_still_draws_the_others(fake_pack, tmp_path):
    scriptfonts.download(scriptfonts.PACKS["thai"])  # the tiny font: ก and ส, no ข
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "config.toml").write_text("font_downloads = false\n")
    res = build(THAI + "ข")
    assert "F305" not in codes(res), "the font is here: never say it is not downloaded"
    f302 = next(n for n in res.nudges if n.code == "F302")
    assert "ข" in f302.message and "ก" not in f302.message and "Noto Sans Thai" in f302.suggestion


def test_tracking_never_spaces_out_joined_letters():
    plain = build("مرحبا")
    spaced = build("مرحبا {tracking=4}")
    img = lambda r: [x for x in r.rows if isinstance(x, BitmapRow)][0].image.tobytes()  # noqa: E731
    assert img(spaced) == img(plain)
    assert any(n.code == "M103" and "tracking" in n.message for n in spaced.nudges)


def test_right_to_left_list_items_have_their_bullet_on_the_right():
    res = build("- שלום")
    im = [r for r in res.rows if isinstance(r, BitmapRow)][0].image.convert("L")
    box = Image.eval(im, lambda v: 255 - v).getbbox()
    assert box[0] > im.width // 2, "bullet and word both sit at the right edge"


def test_a_failed_download_is_tried_again_after_a_while(fake_pack):
    scriptfonts._FAILED["thai"] = ("no network", time.monotonic() - scriptfonts.FAILED_TTL_S - 1)
    assert "F304" in codes(build(THAI))
    scriptfonts._FAILED["devanagari"] = ("no network", time.monotonic())
    assert "no network" in next(n.message for n in build("नमस्ते").nudges if n.code == "F305")


def test_fonts_get_document_follows_its_lang(tmp_path, capsys):
    doc = tmp_path / "tw.bob.md"
    doc.write_text("---\nlang: zh-TW\n---\n中文\n", encoding="utf-8")
    assert cli.main(["fonts", "get", str(doc), "--json"]) == cli.UNREACHABLE  # no network in tests
    assert [r["name"] for r in json.loads(capsys.readouterr().out)] == ["chinese-traditional"]


def test_language_names_are_understood():
    found, unknown = scriptfonts.resolve_names(["Hindi", "JAPANESE", "mandarin", "Cantonese", "tamil", "Korean"])
    assert [p.id for p in found] == ["devanagari", "japanese", "chinese", "chinese-traditional", "tamil", "korean"]
    assert unknown == [] and scriptfonts.support("Hindi") == "download"
    assert scriptfonts.resolve_names(["Portuguese"]) == ([], [])  # the bundled fonts draw it: nothing to get


@pytest.mark.parametrize("argv", [["list", "x"], ["scripts", "x"], ["test", "Terminus", "x"], ["mark", "A", "20", "x"]])
def test_fonts_subcommands_refuse_extra_words(argv, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["fonts", *argv])
    assert e.value.code == cli.USAGE and "unrecognized arguments: x" in capsys.readouterr().err


def test_downloads_off_is_read_once_per_document(monkeypatch):
    calls = []
    monkeypatch.setattr(scriptfonts, "downloads_off", lambda: calls.append(1) or "off for the test")
    build("ภาษาไทย\n\nनमस्ते\n\nภาษา नमस्ते")
    assert len(calls) == 1


def test_packs_needed_by_script():
    assert [p.id for p in scriptfonts.packs_needed("日本語のテキスト and สวัสดี")] == ["japanese", "thai"]
    assert [p.id for p in scriptfonts.packs_needed("中文", "ko")] == ["korean"]
