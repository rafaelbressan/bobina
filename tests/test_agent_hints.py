"""Hints at the places where agents got stuck in the agent-eval runs (help, status, data columns, counters)."""

import sys

from bobina import cli


def run(*argv):
    return cli.main(list(argv))


def test_status_on_a_file_printer_says_where_the_bytes_go(tmp_path, capsys):
    sink = tmp_path / "printer.bin"
    run("printer", "add", "loja", "--path", str(sink))
    assert run("status") == cli.USAGE
    e = capsys.readouterr().err
    assert "E404" in e and str(sink) in e


def test_help_data_is_a_topic(capsys):
    assert run("help", "data") == cli.OK
    out = capsys.readouterr().out
    for flag in ("--data", "--sheet", "--where", "--copies-from", "--join", "--on", "{column}"):
        assert flag in out


def test_undefined_variable_with_data_lists_the_columns(tmp_path, capsys):
    rows = tmp_path / "rows.csv"
    rows.write_text("produto,qtd\nArroz,2\n")
    assert run("check", "# {{ product }}", "--data", str(rows)) == cli.OK
    e = capsys.readouterr().err
    assert "M130" in e and "produto" in e and "qtd" in e


def test_counter_format_error_shows_a_valid_format(capsys):
    run("check", '---\ncounters:\n  t: { format: "{}" }\n---\n{{ seq.t }}')
    assert '"{:d}"' in capsys.readouterr().err


def test_no_roll_length_nudge_on_a_file_printer(tmp_path, capsys):
    run("printer", "add", "loja", "--path", str(tmp_path / "printer.bin"))
    capsys.readouterr()
    assert run("print", "oi", "--yes") == cli.OK
    assert "roll length" not in capsys.readouterr().err


def test_dry_run_with_yes_shows_the_paper_line_once(tmp_path, capsys):
    sink = tmp_path / "sink.bin"
    cmd = f"{sys.executable} -c \"import sys; open(r'{sink}','ab').write(sys.stdin.buffer.read())\""
    run("printer", "add", "pipe", "--command", cmd)
    capsys.readouterr()
    assert run("print", "oi", "-n", "--yes") == cli.OK
    cap = capsys.readouterr()
    assert (cap.out + cap.err).count("paper:") == 1


def test_empty_required_field_is_one_warning(capsys):
    run("check", "---\nfields:\n  produto: { required: true }\n---\n# {{ produto }}")
    e = capsys.readouterr().err
    assert "M131" in e and "M130" not in e


def test_a_device_path_printer_still_counts_paper(tmp_path, monkeypatch):
    from bobina.cli import common

    counted = []
    monkeypatch.setattr(common, "_count_paper", lambda name, mm: counted.append(name))
    assert common.counts_paper({"transport": "file", "path": "/dev/usb/lp0"})
    assert not common.counts_paper({"transport": "file", "path": str(tmp_path / "out.bin")})
    assert common.counts_paper({"transport": "bluetooth", "address": "AA:BB:CC:DD:EE:FF"})


def test_status_on_a_device_printer_does_not_call_it_a_file(tmp_path, capsys):

    run("printer", "add", "usb", "--path", "/dev/usb/lp9")
    assert run("status") == cli.USAGE
    e = capsys.readouterr().err
    assert "appended" not in e and "/dev/usb/lp9" in e


def test_the_end_of_a_label_clears_the_tear_bar_with_room_to_spare():
    from bobina.cli import common
    from bobina.profile import load

    mm = 203 / 25.4
    assert load("mtp-ii-58").get("margins.feed_after_dots") >= round(11 * mm)  # tear bar ~5 mm + 6 mm to spare
    assert common.printer_overrides({"tear_mm": 5.0}) == {
        "margins.tear_mm": 5.0,
        "margins.tear_margin_mm": 6.0,
    }
    custom = common.printer_overrides({"tear_mm": 5.0, "tear_margin_mm": 2})
    assert custom["margins.tear_margin_mm"] == 2  # per printer, for whoever wants less paper


def test_a_real_column_called_row_is_listed_by_m130(tmp_path, capsys):
    rows = tmp_path / "shelves.csv"
    rows.write_text("row,item\nA3,rice\n")
    assert run("check", "# {{ rwo }}", "--data", str(rows)) == cli.OK
    e = capsys.readouterr().err
    assert "row" in e.split("give:")[-1] and "item" in e
