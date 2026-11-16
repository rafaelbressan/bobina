"""The MTP-II's native QR, from paper (13/11, measured 16/11 against a raster QR ruler, each code decoded to count its
modules): the module parameter (GS ( k fn 167) is the minimum version, capped at 6, and every module is 5 dots
(docs/printers/mtp-ii-58.md, Codes). The preview, check's length and the terminal view draw it as it prints; a size
the firmware cannot give (module=, width=) and content above version 6 print as an exact image (Q113). Profiles
whose native QR takes the module in dots (ESC/POS) are unchanged."""

import pytest
from PIL import ImageOps

from bobina import escpos, imaging, preview, profile, view
from bobina.emulator import Emulator
from bobina.engine import build
from bobina.rows import BitmapRow, QRRow

V2 = "https://example.com/v2"  # the content of the printed strip: version 2 at ECC M
V5 = "https://example.com/" + "a" * 50  # 70 bytes: version 5 at ECC M
BIG = "https://example.com/" + "x" * 280  # version 13: never tested native
STANDARD = "netbye-nbtp-5880"  # a 384-dot printer whose native QR follows ESC/POS (module = dots)

# (content, parameter sent, version printed, width measured on the paper in dots)
MEASURED = [(V2, 3, 3, 146), (V2, 6, 6, 206), (V2, 8, 6, 206), (V5, 3, 5, 187), (V5, 6, 6, 206), (V5, 8, 6, 206)]


def ink_width(im) -> int:
    box = ImageOps.invert(im.convert("L")).getbbox()
    return box[2] - box[0]


def qrs(res) -> list:
    return [r for r in res.rows if isinstance(r, QRRow)]


def images(res) -> list:
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "qr"]


def q113(res) -> list:
    return [n for n in res.nudges if n.code == "Q113"]


@pytest.mark.parametrize("data, param, version, measured", MEASURED)
def test_the_preview_draws_each_measured_code_as_it_printed(data, param, version, measured):
    p = profile.load("mtp-ii-58")
    needed = imaging.qr_version(data, "M")
    assert needed == (2 if data == V2 else 5)
    assert p.qr_native_version(needed, param) == version
    row = QRRow(data, p.qr_fixed_module(), "M", version=version, param=param)
    im = preview.row_image(row, p, Emulator(p))
    assert ink_width(im) == (17 + 4 * version) * 5 and abs(ink_width(im) - measured) <= 2
    assert preview.heights([row], p) == im.height == (17 + 4 * version) * 5  # check's length: the same dots
    assert b"\x1d(k\x03\x001C" + bytes([param]) in escpos.encode([row], p)  # the parameter, not dots


@pytest.mark.parametrize("data, param, version", [(V2, 3, 3), (V5, 5, 5)])
def test_bobina_sends_the_smallest_code_the_tested_range_gives(data, param, version):
    res = build(f"```qr\n{data}\n```\n")
    [row] = qrs(res)
    assert (row.module, row.param, row.version) == (5, param, version) and not res.nudges
    assert b"\x1d(k\x03\x001C" + bytes([param]) in res.data
    assert ink_width(res.image) == (17 + 4 * version) * 5  # 145 and 185 dots: the paper's ~146 and ~187


def test_the_terminal_view_shows_the_printed_size():
    res = build(f"```qr\n{V2}\n```\n")
    [row] = qrs(res)
    braille = view.lines([row], res.profile)
    assert len(braille) == -(-145 // 24)  # 29 modules × 5 dots, 24 dots per terminal line


def test_content_above_version_6_prints_as_an_image():
    for doc in (f"```qr\n{BIG}\n```\n", f"```qr {{render=native}}\n{BIG}\n```\n"):
        res = build(doc)
        assert not qrs(res) and images(res)
        [n] = q113(res)
        assert n.severity == "note" and "version 13" in n.message and "tested up to version 6" in n.message
    assert "render=native ignored" in q113(res)[0].message
    # no size asked: the image keeps the printer's 5-dot modules (69 modules, 2 of quiet zone each side)
    assert images(res)[0].image.getbbox() and ink_width(res.image) == 69 * 5
    huge = "https://example.com/" + "x" * 480  # version 17, 85 modules: 5 dots would not fit the paper
    res = build(f"```qr\n{huge}\n```\n")
    assert images(res) and ink_width(res.image) == 85 * (384 // 85)  # the largest module that fits, silently
    assert [n.code for n in res.nudges] == ["Q113"]


def test_a_size_asked_prints_that_size_as_an_image():
    res = build(f"```qr {{module=8}}\n{V2}\n```\n")
    assert not qrs(res) and ink_width(res.image) == 25 * 8
    [n] = q113(res)
    assert n.message == "this printer's native QR always has 5-dot modules: module=8 printed as an image"
    assert n.suggestion.startswith("remove module= for the printer's own code (5-dot modules)")
    res = build(f"```qr {{width=half}}\n{V2}\n```\n")
    assert not qrs(res) and images(res) and "width=half printed as an image" in q113(res)[0].message
    assert ink_width(res.image) == 25 * (192 // 25)  # the largest integer module in half the paper


def test_module_3_asked_is_a_raster_qr_with_its_rules():
    res = build(f"```qr {{module=3}}\n{V2}\n```\n")
    assert images(res) and {"Q101", "Q113"} <= {n.code for n in res.nudges}  # raster reads from module 4


def test_render_native_keeps_the_printer_code_and_says_the_size_does_nothing():
    res = build(f"```qr {{render=native module=8}}\n{V2}\n```\n")
    [row] = qrs(res)
    assert (row.module, row.param, row.version) == (5, 3, 3)
    [n] = q113(res)
    assert "render=native: module=8 has no effect" in n.message and "remove render=native" in n.suggestion


def test_module_5_is_what_the_printer_gives_silently():
    res = build(f"```qr {{module=5}}\n{V2}\n```\n")
    assert qrs(res) and not res.nudges


def test_render_raster_is_unchanged():
    res = build(f"```qr {{render=raster}}\n{V2}\n```\n")
    assert images(res) and not res.nudges and ink_width(res.image) == 25 * 4  # profile default_module


def test_pay_and_contact_codes_take_the_same_path():
    pix = "```pay {{scheme=pix to=a@example.com name=A city=Rio amount=10{}}}\n```\n"
    res = build(pix.format(""))
    [row] = qrs(res)
    assert row.module == 5 and row.version == max(3, imaging.qr_version(row.data, "M")) and not q113(res)
    res = build(pix.format(" width=full"))
    assert not qrs(res) and images(res) and q113(res)
    res = build("```contact instagram {module=6}\nana\n```\n")
    assert not qrs(res) and images(res) and "module=6 printed as an image" in q113(res)[0].message
    [row] = qrs(build("```contact instagram\nana\n```\n"))
    assert (row.module, row.param) == (5, 3)


def test_the_pay_sign_template_asks_for_an_image_and_says_nothing():
    res = build("---\ntemplate: pay-sign\nscheme: pix\nto: ana@example.com\nname: Ana\ncity: Rio\n---\n")
    assert images(res) and not qrs(res) and not q113(res)


@pytest.mark.parametrize("pid", [p for p in sorted(profile.available()) if not profile.load(p).qr_fixed_module()])
def test_other_profiles_keep_the_module_in_dots(pid):
    p = profile.load(pid)
    for module in (3, 4, 8):
        res = build(f"```qr {{module={module}}}\n{V2}\n```\n", profile_name=pid)
        assert not q113(res)
        if not p.get("qr.native"):
            assert images(res) and not qrs(res)
            continue
        [row] = qrs(res)
        assert (row.module, row.version, row.param) == (module, 0, 0)
        assert escpos.qr(V2, module, "M") in res.data  # the bytes as before: the parameter is the module
        expected = imaging.place(imaging.qr_image(V2, module, "M"), p.width_dots, "center")
        assert preview.row_image(row, p, res.emulator).tobytes() == expected.tobytes()


def test_profile_show_says_the_native_qr_has_fixed_modules(capsys):
    from bobina import cli

    assert cli.main(["profile", "show", "mtp-ii-58"]) == 0
    assert "qr: native 5-dot modules up to version 6 ecc M" in capsys.readouterr().out
    assert cli.main(["profile", "show", STANDARD]) == 0
    assert "qr: module 4 ecc M" in capsys.readouterr().out
