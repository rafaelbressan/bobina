"""Hints at the places where agents got stuck in the agent-eval runs (help, status, data columns, counters)."""

import sys

from bobina import cli


def run(*argv):
    return cli.main(list(argv))


def test_status_on_a_file_printer_says_where_the_bytes_go(tmp_path, capsys):
    """Agents read E404 here as a broken printer: a file printer simply has no live status (exit 0, no problem)."""
    sink = tmp_path / "printer.bin"
    run("printer", "add", "loja", "--path", str(sink))
    capsys.readouterr()
    assert run("status") == cli.OK
    o = capsys.readouterr()
    assert "no live status" in o.out and "printing works the same" in o.out and str(sink) in o.out
    assert o.err == "" and "E404" not in o.out


def test_status_of_a_command_printer_says_how_to_ask_the_printer_over_there(capsys):
    import json

    run("printer", "add", "tower", "--command", "ssh -p 2222 tower ~/.local/bin/bobina send --yes -")
    capsys.readouterr()
    assert run("status", "--json") == cli.OK
    out = json.loads(capsys.readouterr().out)
    assert out["live_status"] is False and out["transport"] == "command"
    assert out["status_there"] == "ssh -p 2222 tower '~/.local/bin/bobina status'"  # ~ expands over there
    run("printer", "add", "lp", "--command", "lp -d label")
    assert run("status", "--printer", "lp") == cli.OK
    o = capsys.readouterr().out
    assert "a command printer: no live status" in o and "runs lp -d label" in o and "other machine" not in o


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
    capsys.readouterr()
    assert run("status") == cli.OK
    o = capsys.readouterr().out
    assert o.startswith("usb: a device printer: no live status") and "file printer" not in o and "/dev/usb/lp9" in o


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


def test_problems_help_says_they_go_to_stderr():
    """An agent sent stdout to a file and got the summary, not the problems."""
    from bobina.cli import args

    assert args.COMMANDS
    for name, p in args.COMMANDS.items():
        text = " ".join(p.format_help().split())
        if "--problems" in text:
            assert "always to stderr (stdout keeps the command's own output" in text, name


def test_check_lists_the_data_columns_usable_in_braces(tmp_path, capsys):
    import json

    prices, catalog = tmp_path / "prices.csv", tmp_path / "catalog.json"
    prices.write_text("name,Unit Price\nRice,5\n")
    catalog.write_text('[{"name": "Rice", "id": "7"}]')
    assert run("check", "x", "--data", str(prices)) == cli.OK
    assert "data columns (prices.csv): name, unit_price" in capsys.readouterr().out  # 'Unit Price': row['…'] only
    assert run("check", "x", "--data", f"a={prices}", "--join", f"b={catalog}", "--on", "name", "--json") == cli.OK
    (src,) = json.loads(capsys.readouterr().out)["data_columns"]
    assert src["part"] == 1 and src["data"] == [f"a={prices}", f"b={catalog}"]
    assert {"a.name", "b.id", "unit_price"} <= set(src["columns"]) and not any(" " in c for c in src["columns"])
    assert run("check", "x") == cli.OK and "data columns" not in capsys.readouterr().out


def test_an_unclosed_block_is_placed_where_it_opens(capsys):
    doc = "---\nx: 1\n---\n# Title\n{% set y %}a{% endset %}{% set z = 1 %}\n{% if x %}\n{% for i in [1] %}{{ i }}{% endfor %}\nend\n"
    assert run("check", doc) == cli.DOC
    e = capsys.readouterr().err
    assert "[E501] line 6: {% if %} is not closed: add {% endif %} where the block ends" in e
    assert run("check", "a\n{% for i in [1] %}\n{% if i %}x{% endif %}\nb") == cli.DOC
    assert "line 2: {% for %} is not closed" in capsys.readouterr().err


def test_an_unclosed_block_that_cannot_be_placed_says_to_look_for_it(monkeypatch, capsys):
    from bobina import templating

    monkeypatch.setattr(templating, "unclosed_block", lambda env, body, tag: None)
    assert run("check", "a\n{% if x %}\nb") == cli.DOC
    e = capsys.readouterr().err
    assert "an {% if %} opened earlier is not closed (look for the {% if %} without {% endif %})" in e


def test_status_json_has_one_shape_for_every_printer(tmp_path, monkeypatch, capsys):
    import json

    from test_schemas import _check, _schema

    from bobina.cli import device

    run("printer", "add", "test", "--path", str(tmp_path / "t.bin"))
    run("printer", "add", "tower", "--command", "ssh tower bobina send --yes --printer gold -")
    run("printer", "add", "mtp", "AA:BB:CC:DD:EE:FF")
    monkeypatch.setattr(device, "printer_status", lambda pr: {"answered": True, "online": True, "paper_out": False})
    capsys.readouterr()
    shapes = {}
    for name in ("test", "tower", "mtp"):
        assert run("status", "--printer", name, "--json") == cli.OK
        doc = json.loads(capsys.readouterr().out)
        _check(doc, _schema("status"))
        shapes[name] = (doc["kind"], doc["live_status"], doc["where"])
    assert shapes["mtp"] == ("a Bluetooth printer", True, "AA:BB:CC:DD:EE:FF")
    assert shapes["test"] == ("a file printer (a test printer)", False, str(tmp_path / "t.bin"))
    assert shapes["tower"][:2] == ("a command printer", False)


def test_data_columns_per_part_of_a_job_with_then(tmp_path, capsys):
    import json

    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("name,price\nRice,5\n")
    b.write_text("code\n7\n")
    assert run("check", "x", "--data", str(a), "--then", "y", "--then", "z", "--data", str(b)) == cli.OK
    out = capsys.readouterr().out
    assert "data columns, part 1 (x: a.csv): name, price" in out and "data columns, part 3 (z: b.csv): code" in out
    assert "part 2" not in out
    assert run("check", "x", "--data", str(a), "--then", "z", "--data", str(b), "--json") == cli.OK
    doc = json.loads(capsys.readouterr().out)
    assert [(d["part"], d["columns"]) for d in doc["data_columns"]] == [(1, ["name", "price"]), (2, ["code"])]


def test_jinja_words_are_not_listed_as_names(tmp_path, capsys):
    rows = tmp_path / "k.csv"
    rows.write_text("name,if,None,true,loop\nRice,1,2,3,4\n")
    assert run("check", "{{ row['if'] }}", "--data", str(rows)) == cli.OK
    assert "data columns (k.csv): name\n" in capsys.readouterr().out
