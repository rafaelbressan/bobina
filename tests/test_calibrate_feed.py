"""bobina calibrate feed: does this printer obey ESC J right after an image? The answer turns the safe mode
(white raster rows for feeds after images) off or on for that printer."""

from bobina import cli, config


def run(*argv):
    return cli.main(list(argv))


def _printer(tmp_path):
    sink = tmp_path / "printer.bin"
    assert run("printer", "add", "loja", "--path", str(sink)) == cli.OK
    return sink


def _printer_cfg():
    return config.load()["printers"]["loja"]


def test_the_test_strip_has_raster_gap_then_esc_j_gap(tmp_path):
    sink = _printer(tmp_path)
    assert run("calibrate", "feed", "--yes") == cli.OK
    data = sink.read_bytes()
    gap = data.index(b"\x1dv0\x00" + bytes([48, 0, 80, 0]))  # A–B: 80 white raster rows = 10 mm, exact
    after_b = data.index(b"\x1bJ\x50", gap)  # B–C: ESC J 80, right after line B, whatever the safe mode says
    assert data[after_b - 3 * 48 - 8 : after_b - 3 * 48 - 4] == b"\x1dv0\x00"  # line B is right before it


def test_touching_lines_keep_the_safe_mode(tmp_path):
    _printer(tmp_path)
    assert run("calibrate", "feed", "touching") == cli.OK
    assert _printer_cfg()["blank_rows_after_raster"] is True


def test_apart_lines_turn_the_safe_mode_off(tmp_path, capsys):
    _printer(tmp_path)
    assert run("calibrate", "feed", "apart") == cli.OK
    assert _printer_cfg()["blank_rows_after_raster"] is False
    assert "white rows" in capsys.readouterr().out  # says what changes


def test_an_unknown_answer_is_a_usage_error(tmp_path):
    _printer(tmp_path)
    assert run("calibrate", "feed", "maybe") == cli.USAGE


def test_without_a_terminal_the_strip_needs_yes(tmp_path, monkeypatch):
    _printer(tmp_path)
    monkeypatch.setattr(cli.common, "open_tty", lambda: None)
    assert run("calibrate", "feed") == cli.CONFIRM


def test_a_bare_mac_cannot_store_a_calibration(tmp_path, capsys):
    _printer(tmp_path)
    for argv in (("feed", "apart"), ("tear", "5")):
        assert run("--printer", "AA:BB:CC:DD:EE:FF", "calibrate", *argv) == cli.USAGE
    assert "printer add" in capsys.readouterr().err
    assert "blank_rows_after_raster" not in _printer_cfg() and "tear_mm" not in _printer_cfg()


def test_an_answer_with_dry_run_is_not_saved(tmp_path):
    _printer(tmp_path)
    assert run("calibrate", "feed", "apart", "--dry-run") == cli.OK
    assert "blank_rows_after_raster" not in _printer_cfg()


def test_the_strip_ends_past_the_measured_tear_bar(tmp_path):
    sink = _printer(tmp_path)
    assert run("calibrate", "tear", "16") == cli.OK
    assert run("calibrate", "feed", "--yes") == cli.OK
    data = sink.read_bytes()
    rows = 0
    # the white bands at the end: 16 + 6 mm of them
    import re

    for m in re.finditer(rb"\x1dv0\x00\x30\x00(.)(.)", data):
        h = m.group(1)[0] + 256 * m.group(2)[0]
        payload = data[m.end() : m.end() + 48 * h]
        rows = rows + h if not any(payload) else 0
    assert rows >= round(22 * 203 / 25.4)


def test_answers_and_strips_have_json(tmp_path, capsys):
    import json

    _printer(tmp_path)
    capsys.readouterr()
    assert run("calibrate", "feed", "touching", "--json") == cli.OK
    assert json.loads(capsys.readouterr().out) == {"printer": "loja", "blank_rows_after_raster": True, "dry_run": False}
    assert run("calibrate", "feed", "--dry-run", "--json") == cli.OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["printed"] is False and doc["next"][0] == "bobina calibrate feed touching"
    assert run("calibrate", "tear", "5", "--dry-run", "--json") == cli.OK
    assert json.loads(capsys.readouterr().out)["tear_mm"] == 5.0


def test_a_dry_run_needs_no_printer(capsys):
    assert run("calibrate", "feed", "--dry-run") == cli.OK
    assert "lines A, B, C" in capsys.readouterr().out


def test_any_answer_but_p_says_not_printed(tmp_path, monkeypatch, capsys):
    import io

    sink = _printer(tmp_path)
    monkeypatch.setattr(cli.common, "open_tty", lambda: io.StringIO("y\n"))
    assert run("calibrate", "feed") == cli.CONFIRM
    assert "not printed" in capsys.readouterr().err and not sink.exists()


def test_tear_takes_mm_with_a_unit_and_refuses_nonsense(tmp_path):
    _printer(tmp_path)
    assert run("calibrate", "tear", "16mm") == cli.OK
    assert _printer_cfg()["tear_mm"] == 16.0
    for bad in ("nan", "0", "abc", "500"):
        assert run("calibrate", "tear", bad) == cli.USAGE
    assert _printer_cfg()["tear_mm"] == 16.0


def test_a_dry_run_takes_a_bare_mac():
    assert run("--printer", "AA:BB:CC:DD:EE:FF", "calibrate", "feed", "--dry-run") == cli.OK
