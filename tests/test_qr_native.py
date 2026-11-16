"""The MTP-II's native QR, from paper (strips of 13/11 and 16/11, measured against a raster QR ruler, each code
decoded to count its modules): the module parameter (GS ( k fn 167) is the minimum version, capped at 6; every module
is 5 dots; content up to version 7 prints, version 8 and above print the firmware's "2QR CREAT ERR!" text
(docs/printers/mtp-ii-58.md, Codes). The preview, check's length and the terminal view draw the code as it prints;
module= (a size the firmware cannot give) and content above version 7 print as an exact image (Q113); width= prints
an image of that width, silently. Profiles whose native QR takes the module in dots (ESC/POS) are unchanged."""

import pytest
from PIL import ImageOps

from bobina import escpos, imaging, preview, profile, view
from bobina.emulator import Emulator
from bobina.engine import build
from bobina.rows import BitmapRow, QRRow

V2 = "https://example.com/v2"  # the content of the printed strip: version 2 at ECC M
V5 = "https://example.com/" + "a" * 50  # 70 bytes: version 5 at ECC M
V7 = "https://example.com/" + "a" * 100  # 120 bytes: version 7, printed natively on 16/11
V8 = "https://example.com/" + "a" * 130  # 150 bytes: version 8, printed "2QR CREAT ERR!" on 16/11
BIG = "https://example.com/" + "x" * 280  # version 13
STANDARD = "netbye-nbtp-5880"  # a 384-dot printer whose native QR follows ESC/POS (module = dots)
RASTER = "netum-nt-5890k"  # a 384-dot printer without a native QR

# (content, parameter sent, version printed, width measured on the paper in dots)
MEASURED = [(V2, 3, 3, 146), (V2, 6, 6, 206), (V2, 8, 6, 206), (V5, 3, 5, 187), (V5, 6, 6, 206), (V5, 8, 6, 206),
            (V7, 4, 7, 225)]  # fmt: skip


def needed(data: str) -> int:
    return (len(imaging.qr_matrix(data, "M", 0)) - 17) // 4


def ink_box(im) -> tuple:
    return ImageOps.invert(im.convert("L")).getbbox()


def ink_width(im) -> int:
    box = ink_box(im)
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
    fixed = p.qr_fixed()
    assert needed(data) == {V2: 2, V5: 5, V7: 7}[data]
    assert fixed.printed_version(needed(data), param) == version
    row = QRRow(data, fixed.dots, "M", version=version, param=param)
    im = preview.row_image(row, p, Emulator(p))
    assert ink_width(im) == (17 + 4 * version) * 5 and abs(ink_width(im) - measured) <= 2
    assert preview.heights([row], p) == im.height == (17 + 4 * version) * 5  # check's length: the same dots
    assert b"\x1d(k\x03\x001C" + bytes([param]) in escpos.encode([row], p)  # the parameter, not dots


def test_the_profile_holds_the_two_limits_in_one_place():
    fixed = profile.load("mtp-ii-58").qr_fixed()
    assert (fixed.dots, fixed.param_max_version, fixed.content_max_version, fixed.tested) == (5, 6, 7, (3, 9))
    assert [fixed.code(v) for v in (1, 2, 3, 5, 6, 7, 8)] == [(3, 3), (3, 3), (3, 3), (5, 5), (6, 6), (7, 7), None]
    assert profile.load(STANDARD).qr_fixed() is None


@pytest.mark.parametrize("data, param, version", [(V2, 3, 3), (V5, 5, 5), (V7, 7, 7)])
def test_bobina_sends_the_smallest_code_the_tested_range_gives(data, param, version):
    res = build(f"```qr\n{data}\n```\n")
    [row] = qrs(res)
    assert (row.module, row.param) == (5, param) and not res.nudges
    assert row.version == (3 if version == 3 else 0)  # 0: the smallest version the content fits
    assert b"\x1d(k\x03\x001C" + bytes([param]) in res.data
    assert ink_width(res.image) == (17 + 4 * version) * 5  # 145, 185, 225 dots: the paper's ~146, ~187, ~225


def test_numeric_content_takes_the_smaller_numeric_mode_as_the_firmware_does():
    # paper 16/11: 100 digits sent with parameter 4 printed version 4, 33 modules, ~165 dots. Numeric mode needs
    # version 3 (then raised to the minimum 4); alphanumeric would need 5 and bytes 6.
    digits = "1234567890" * 10
    fixed = profile.load("mtp-ii-58").qr_fixed()
    assert needed(digits) == 3 and fixed.printed_version(needed(digits), 4) == 4
    [row] = qrs(build(f"```qr\n{digits}\n```\n"))
    assert row.param == 3 and preview.heights([row], profile.load("mtp-ii-58")) == 29 * 5


def test_the_terminal_view_shows_the_printed_size():
    res = build(f"```qr\n{V2}\n```\n")
    [row] = qrs(res)
    assert len(view.lines([row], res.profile)) == -(-145 // 24)  # 29 modules × 5 dots, 24 dots per terminal line


def test_content_above_version_7_prints_as_an_image():
    for data, version in ((V8, 8), (BIG, 13)):
        for doc in (f"```qr\n{data}\n```\n", f"```qr {{render=native}}\n{data}\n```\n"):
            res = build(doc)
            assert not qrs(res) and images(res)
            [n] = q113(res)
            assert n.severity == "note" and f"version {version}" in n.message and "stops at version 7" in n.message
        assert "render=native ignored" in n.message
    # no size asked: the image keeps the printer's 5-dot modules (69 modules, 2 of quiet zone each side)
    assert ink_width(res.image) == 69 * 5


def test_an_image_too_big_for_5_dot_modules_takes_the_largest_that_fits_with_its_quiet_zone():
    huge = "https://example.com/" + "x" * 480  # version 17, 85 modules + 4 of quiet zone
    res = build(f"```qr\n{huge}\n```\n")
    assert images(res) and ink_width(res.image) == 85 * (384 // 89) and [n.code for n in res.nudges] == ["Q113"]
    box = ink_box(res.image)
    assert box[0] >= 2 * 4 and 384 - box[2] >= 2 * 4  # the quiet zone stays on the paper


def test_too_much_data_for_a_readable_image_says_less_data():
    data = "https://example.com/" + "x" * 900  # version 24: 113 + 4 modules, 3 dots at most on 384
    res = build(f"```qr\n{data}\n```\n")
    [n] = [n for n in res.nudges if n.code == "Q101"]
    assert n.suggestion.startswith("less data or ecc=L") and "module=" not in n.suggestion


def test_module_asked_prints_that_size_as_an_image_with_q113():
    res = build(f"```qr {{module=8}}\n{V2}\n```\n")
    assert not qrs(res) and ink_width(res.image) == 25 * 8
    [n] = q113(res)
    assert n.message == "this printer's own QR always has 5-dot modules: module=8 printed as an image"
    assert n.suggestion.startswith("remove module= for the printer's own code (5-dot modules)")


def test_width_asked_prints_that_width_as_an_image_silently():
    res = build(f"```qr {{width=half}}\n{V2}\n```\n")
    assert not qrs(res) and images(res) and not res.nudges
    assert ink_width(res.image) == 25 * (192 // 29)  # the largest module whose code and quiet zone fill half


def test_module_3_asked_is_a_raster_qr_with_its_rules():
    res = build(f"```qr {{module=3}}\n{V2}\n```\n")
    assert images(res) and {"Q101", "Q113"} <= {n.code for n in res.nudges}  # raster reads from module 4


def test_render_native_keeps_the_printer_code_and_says_the_size_does_nothing():
    res = build(f"```qr {{render=native module=8 width=half}}\n{V2}\n```\n")
    [row] = qrs(res)
    assert (row.module, row.param, row.version) == (5, 3, 3)
    [n] = q113(res)
    assert "render=native: module=8 width=half has no effect" in n.message
    assert n.suggestion == "remove module= and width=, or remove render=native to print that size as an image"


@pytest.mark.parametrize("module", ["5", "05"])
def test_module_5_is_what_the_printer_gives_silently(module):
    res = build(f"```qr {{module={module}}}\n{V2}\n```\n")
    assert qrs(res) and not res.nudges


def test_render_raster_is_unchanged():
    res = build(f"```qr {{render=raster}}\n{V2}\n```\n")
    assert images(res) and not res.nudges and ink_width(res.image) == 25 * 4  # profile default_module


def test_pay_and_contact_codes_take_the_same_path():
    pix = "```pay {{scheme=pix to=a@example.com name=A city=Rio amount=10{}}}\n```\n"
    res = build(pix.format(""))
    [row] = qrs(res)
    assert row.module == 5 and row.param == max(3, needed(row.data)) and not q113(res)
    res = build(pix.format(" width=full"))
    assert not qrs(res) and images(res) and not q113(res)
    res = build("```contact instagram {module=6}\nana\n```\n")
    assert not qrs(res) and images(res) and "module=6 printed as an image" in q113(res)[0].message
    [row] = qrs(build("```contact instagram\nana\n```\n"))
    assert (row.module, row.param) == (5, 3)


def test_the_pay_sign_template_prints_its_full_width_code_without_a_note():
    res = build("---\ntemplate: pay-sign\nscheme: pix\nto: ana@example.com\nname: Ana\ncity: Rio\n---\n")
    assert images(res) and not qrs(res) and not q113(res)
    box = ink_box(images(res)[0].image)
    assert box[0] > 0 and box[2] < 384  # code and quiet zone on the paper, nothing cut


def test_a_raster_width_full_keeps_its_quiet_zone_on_the_paper():
    res = build("```qr {width=full}\nhttps://example.com/full\n```\n", profile_name=RASTER)
    n = len(imaging.qr_matrix("https://example.com/full", "M", 0))
    mod = 384 // (n + 4)
    box = ink_box(res.image)
    assert box[2] - box[0] == n * mod and box[0] >= 2 * mod and 384 - box[2] >= 2 * mod


@pytest.mark.parametrize("pid", [p for p in sorted(profile.available()) if not profile.load(p).qr_fixed()])
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
    assert "qr: native 5-dot modules up to version 7 ecc M" in capsys.readouterr().out
    assert cli.main(["profile", "show", STANDARD]) == 0
    assert "qr: module 4 ecc M" in capsys.readouterr().out
