"""Printed marks: none by default; --marks cut|tear|both prints a fine dashed line (1 dot, 4 on / 4 off) where one
label or order ends and the next begins: between --compact labels (cut) and on the tear bar (tear)."""

import json

from bobina import cli

GS_V0 = b"\x1dv0"


def run(*argv):
    return cli.main(list(argv))


def _job(tmp_path, *extra):
    rows = tmp_path / "rows.csv"
    rows.write_text("nome\nArroz\nFeijão\n")
    doc = tmp_path / "e.bob.md"
    doc.write_text("# {{ nome }}\n")
    out = tmp_path / "job.bin"
    assert run("print", str(doc), "--data", str(rows), "-o", str(out), "--force", *extra) == cli.OK
    return out.read_bytes()


def _rasters(data):
    """(offset, width_bytes, rows, payload) of every GS v 0 block."""
    out, i = [], data.find(GS_V0)
    while i != -1:
        w, h = data[i + 4] + 256 * data[i + 5], data[i + 6] + 256 * data[i + 7]
        out.append((i, w, h, data[i + 8 : i + 8 + w * h]))
        i = data.find(GS_V0, i + 8 + w * h)
    return out


def _moved_after(data, offset):
    """Dots of paper moved by what follows `offset`: white raster bands plus ESC J feeds, parsed (not grepped)."""
    i, dots = offset, 0
    while i < len(data):
        if data[i : i + 3] == GS_V0:
            w, h = data[i + 4] + 256 * data[i + 5], data[i + 6] + 256 * data[i + 7]
            assert not any(data[i + 8 : i + 8 + w * h]), "only white rows may follow the mark"
            dots, i = dots + h, i + 8 + w * h
        elif data[i : i + 2] == b"\x1bJ":
            dots, i = dots + data[i + 2], i + 3
        elif data[i : i + 2] == b"\x1ba":
            i += 3
        else:
            raise AssertionError(f"unexpected byte after the mark at {i}: {data[i : i + 4]!r}")
    return dots


def _is_fine_dash_line(block):
    _, w, h, payload = block
    return h == 1 and payload == bytes([0xF0]) * w  # 4 dots on, 4 off, across the paper


def test_no_marks_by_default(tmp_path):
    for compact in ((), ("--compact",)):
        assert not any(_is_fine_dash_line(b) for b in _rasters(_job(tmp_path, *compact)))


def test_compact_without_marks_prints_no_cut_line(tmp_path):
    assert _rasters(_job(tmp_path, "--compact")) == []  # native text only: the cut is just space


def test_marks_cut_prints_the_fine_line_between_compact_labels(tmp_path):
    lines = [b for b in _rasters(_job(tmp_path, "--compact", "--marks", "cut")) if _is_fine_dash_line(b)]
    assert len(lines) == 1  # 2 labels glued: one cut, and no tear mark (not asked)


def test_marks_tear_lands_on_the_tear_bar(tmp_path):
    from bobina.profile import load

    data = _job(tmp_path, "--marks", "tear")
    lines = [b for b in _rasters(data) if _is_fine_dash_line(b)]
    assert len(lines) == 2  # each label ends on the tear bar
    prof = load("mtp-ii-58")
    tear = prof.get("margins.tear_dots")
    last = lines[-1]
    assert _moved_after(data, last[0] + 8 + last[1]) == tear - 1  # then exactly the distance to the tear bar


def test_marks_both(tmp_path):
    lines = [b for b in _rasters(_job(tmp_path, "--compact", "--marks", "both")) if _is_fine_dash_line(b)]
    assert len(lines) == 2  # the cut between the glued labels + the tear mark at the end of the strip


def test_marks_do_not_change_the_paper_length(tmp_path, capsys):
    doc = tmp_path / "e.bob.md"
    doc.write_text("# Oi\n")
    lengths = []
    for marks in ("none", "both"):
        assert run("check", str(doc), "--json", "--marks", marks) == cli.OK
        lengths.append(json.loads(capsys.readouterr().out)["stats"]["length_mm"])
    assert lengths[0] == lengths[1]


def test_the_preview_shows_the_tear_mark_where_it_prints(tmp_path):
    from PIL import Image

    from bobina.profile import load

    doc = tmp_path / "e.bob.md"
    doc.write_text("# Oi\n")
    png = tmp_path / "p.png"
    assert run("preview", str(doc), "--marks", "tear", "-o", str(png)) == cli.OK
    im = Image.open(png).convert("1")
    y = im.height - load("mtp-ii-58").get("margins.tear_dots")
    row = [im.getpixel((x, y)) for x in range(16)]
    assert row[:4] == [0] * 4 and row[4:8] == [255] * 4


def test_the_screen_says_which_marks_go_on_paper(tmp_path, capsys):
    doc = tmp_path / "e.bob.md"
    doc.write_text("# Oi\n")
    assert run("print", str(doc), "-n", "--marks", "tear") == cli.OK
    assert "marks on paper" in capsys.readouterr().out


def test_config_sets_the_default_and_rejects_unknown_values(tmp_path):
    from bobina import config

    path = config.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('marks = "cut"\n')
    lines = [b for b in _rasters(_job(tmp_path, "--compact")) if _is_fine_dash_line(b)]
    assert len(lines) == 1
    path.write_text('marks = "always"\n')
    doc = tmp_path / "e.bob.md"
    assert run("check", str(doc)) == cli.USAGE


def test_an_unknown_marks_value_is_a_usage_error(tmp_path):
    import pytest

    doc = tmp_path / "e.bob.md"
    doc.write_text("# Oi\n")
    with pytest.raises(SystemExit) as e:
        run("check", str(doc), "--marks", "sempre")
    assert e.value.code == cli.USAGE


def test_the_tear_mark_never_falls_past_the_end_of_the_feed(tmp_path):
    from bobina.engine import build

    res = build("# Oi\n", overrides={"marks": "tear", "margins.tear_dots": 0})
    feed = res.rows[-1]
    assert feed.tear_at == feed.dots - 1  # at least 1 dot of feed after the line: no extra paper


def test_the_screen_names_cut_marks_only_when_the_job_has_cuts(tmp_path, capsys):
    doc = tmp_path / "e.bob.md"
    doc.write_text("# Oi\n")
    assert run("print", str(doc), "-n", "--marks", "both") == cli.OK
    out = capsys.readouterr().out
    assert "tear bar" in out and "cut lines" not in out


def test_feeds_after_a_raster_are_blank_raster_rows_on_the_mtp_ii(tmp_path):
    """The MTP-II ignores an ESC J that comes right after a GS v 0 image (08/11: a 10 mm ESC J between two raster
    lines printed nothing, the lines touched; a tear mark stopped 3 mm short whatever the feed after it). Blank
    raster rows do move the paper, so feeds after an image are sent that way."""
    from bobina.profile import load

    data = _job(tmp_path, "--marks", "tear")
    last = [b for b in _rasters(data) if _is_fine_dash_line(b)][-1]
    after = data[last[0] + 8 + last[1] :]
    assert _moved_after(data, last[0] + 8 + last[1]) == load("mtp-ii-58").get("margins.tear_dots") - 1
    assert not any(after[i : i + 2] == b"\x1bJ" for i in range(len(after) - 1))  # all of it as white rows


def test_feeds_after_native_text_stay_esc_j(tmp_path):
    data = _job(tmp_path)  # native text only: no image, nothing to work around
    assert _rasters(data) == [] and b"\x1bJ" in data


def test_safe_by_default_for_a_profile_that_does_not_say(tmp_path):
    from bobina.engine import build
    from bobina.escpos import encode

    res = build(
        "![x](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNgAAAAAgABc3UBGAAAAABJRU5ErkJggg==)\n"
    )
    res.profile.data.get("escpos", {}).pop("blank_rows_after_raster", None)  # an unknown printer
    data = encode(res.rows, res.profile)
    assert not data.endswith(b"\x1bJ" + bytes([res.rows[-1].dots]))  # the final feed went as white rows


def test_a_calibrated_printer_can_turn_the_safe_mode_off():
    from bobina.cli import common

    over = common.printer_overrides({"tear_mm": 5.0, "blank_rows_after_raster": False, "idle_before_tail": False})
    assert over["escpos.blank_rows_after_raster"] is False and over["transport.idle_before_tail"] is False
    assert "escpos.blank_rows_after_raster" not in common.printer_overrides({"tear_mm": 5.0})  # unmeasured: profile


def test_a_feed_after_a_native_qr_goes_as_white_rows(tmp_path):
    from bobina.engine import build
    from bobina.escpos import encode
    from bobina.rows import QRRow

    res = build("```qr\nhttps://example.com\n```\n")
    assert any(isinstance(r, QRRow) for r in res.rows)  # the native QR of the profile
    data = encode(res.rows, res.profile)
    assert not data.endswith(b"\x1bJ" + bytes([res.rows[-1].dots]))  # a QR is a graphic: white rows after it
