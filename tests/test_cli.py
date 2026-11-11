import sys

import pytest

from bobina import cli


def run(*argv):
    return cli.main(list(argv))


def test_no_terminal_requires_confirmation(monkeypatch, capsys):
    monkeypatch.setattr(cli.common, "open_tty", lambda: None)
    assert run("print", "hello") == cli.CONFIRM
    assert "--yes" in capsys.readouterr().err


def test_output_writes_bytes_without_printing(tmp_path):
    out = tmp_path / "job.bin"
    assert run("print", "hello", "-o", str(out)) == cli.OK
    assert out.read_bytes().startswith(b"\x1b@")


def test_missing_file_is_usage_error():
    assert run("print", "missing.bob.md") == cli.USAGE


def test_security_error_exit_code():
    assert run("check", "{% include 'x' %}") == cli.SECURITY


def test_strict_turns_warnings_into_exit_3():
    assert run("check", "x" * 40, "--strict") == cli.STRICT


def test_alias_and_global_option_before_command(tmp_path):
    out = tmp_path / "a.bin"
    assert run("--quiet", "p", "hi", "-o", str(out)) == cli.OK


def test_inline_newline_escape(tmp_path):
    out = tmp_path / "a.bin"
    run("print", "# T\\n- [ ] milk", "-o", str(out))
    assert b"milk" not in out.read_bytes()  # checkbox line is raster
    assert b"T\n" in out.read_bytes()


def test_yes_without_printer_is_unreachable(monkeypatch):
    assert run("print", "hello", "--yes") == cli.UNREACHABLE


def test_printer_add_list(capsys):
    assert run("printer", "add", "mtp", "AA:BB:CC:DD:EE:FF") == cli.OK
    run("printer", "list")
    assert "AA:BB:CC:DD:EE:FF" in capsys.readouterr().out


def test_print_through_command_transport(tmp_path, monkeypatch):
    sink = tmp_path / "sink.bin"
    run(
        "printer",
        "add",
        "pipe",
        "--command",
        f"{sys.executable} -c \"import sys; open(r'{sink}','wb').write(sys.stdin.buffer.read())\"",
    )
    assert run("print", "hello", "--yes", "--quiet") == cli.OK
    assert sink.read_bytes().startswith(b"\x1b@")
    assert run("print", "--last", "--dry-run") == cli.OK


def test_help_topics(capsys):
    for t in ("format", "nudges", "problems", "data", "aliases", "print"):
        assert run("help", t) == cli.OK


def test_fonts_test_goes_through_confirmation(monkeypatch):
    monkeypatch.setattr(cli.common, "open_tty", lambda: None)
    assert run("fonts", "test", "Atkinson Hyperlegible") == cli.CONFIRM


def test_fonts_mark_changes_the_minimum(capsys):
    from bobina.engine import build

    assert run("fonts", "mark", "Barlow Condensed", "28") == cli.OK
    res = build("---\nfonts: {body: Barlow Condensed}\n---\ntext {size=24px}")
    assert any(n.code == "F201" and "you marked" in n.message for n in res.nudges)


def test_long_inline_text_is_not_mistaken_for_a_path(tmp_path):
    out = tmp_path / "a.bin"
    assert run("print", "word " * 400, "-o", str(out)) == cli.OK


def test_paper_odometer(tmp_path, capsys, monkeypatch):
    import sys

    from bobina import paper

    sink = tmp_path / "sink.bin"
    run(
        "printer",
        "add",
        "pipe",
        "--command",
        f"{sys.executable} -c \"import sys; open(r'{sink}','wb').write(sys.stdin.buffer.read())\"",
    )
    assert run("paper", "new", "1.2m") == cli.OK
    assert run("print", "hello", "--yes", "--quiet") == cli.OK
    used = paper.get("pipe")["used_mm"]
    assert 10 < used < 40 and paper.get("pipe")["prints"] == 1
    capsys.readouterr()
    run("print", "x\n" * 200, "--yes")  # ~ 60+ cm on a roll with ~1.2 m
    err = capsys.readouterr().err
    assert "P101" in err or "P102" in err
    prints = paper.get("pipe")["prints"]
    before = paper.get("pipe")["used_mm"]
    assert run("paper", "used", "+30cm") == cli.OK  # adds, does not count a print
    assert paper.get("pipe")["used_mm"] == round(before + 300, 1)
    assert paper.get("pipe")["prints"] == prints
    assert run("paper", "used", "5m") == cli.OK  # sets the total
    assert paper.get("pipe")["used_mm"] == 5000
    capsys.readouterr()
    run("print", "hello", "--yes")
    assert "P102" in capsys.readouterr().err


def test_roll_length_from_diameter():
    from bobina import paper

    assert 18_000 < paper.from_diameter(40, 12, 0.06) < 20_000  # ~19 m: typical 57x40 roll


def test_roll_sizes_as_they_are_written_around_the_world():
    from bobina import paper

    assert paper.parse_length("50ft") == paper.parse_length("50'") == paper.parse_length("50 feet") == 15240
    assert paper.parse_length("50′") == 15240 and round(paper.parse_width("2 1/4″"), 2) == 57.15  # prime marks
    assert paper.parse_length("1,5m") == 1500 and paper.parse_length("15") == 15000  # bare: metres (terminal)
    assert round(paper.parse_width('2 1/4"'), 2) == 57.15 and paper.parse_width("80") == 80
    with pytest.raises(ValueError, match="use 15m"):
        paper.parse_length("30", None)
    for zero in ("0m", "0", "0,0cm"):
        with pytest.raises(ValueError, match="more than 0"):
            paper.parse_length(zero)
    assert paper.parse_length("0m", zero=True) == 0  # paper used 0m: nothing used yet
    for code in ("57x30", "80 x 40", "57 × 40 × 12"):  # never guessed: metres (Brazil) or diameter (Europe)?
        advice = paper.code_advice(code, cli=True)
        assert "--diameter" in advice and "m --width" in advice
        with pytest.raises(ValueError, match="package code") as e:  # other commands: only refused
            paper.parse_length(code)
        assert "paper new" not in str(e.value)
    assert "--core 12mm" in paper.code_advice("57x40x12", cli=True)
    us = paper.code_advice("2 1/4 x 50")  # inches x feet: only the feet reading is asked
    assert "feet?" in us and 'length "50ft"' in us and "diameter" not in us


@pytest.mark.parametrize(
    "code, split",
    [
        ("57mm x 30m", 'length "30m", width "57mm"'),
        ("3 1/8 x 70m", 'length "70m", width "3 1/8in"'),  # a unit the user wrote is kept: never 70ft
        ("2 1/4 x 40mm", 'diameter "40mm", width "2 1/4in"'),  # … nor 40ft
        ("57 x 30m", 'length "30m", width "57mm"'),  # the second number says it: nothing to ask
        ("57mm x 40mm x 12", 'diameter "40mm", core "12mm", width "57mm"'),
        ("57 x 30m x 12", 'length "30m", width "57mm"'),  # a core means nothing with a length
    ],
)
def test_a_package_code_with_a_unit_on_the_second_number_is_split_as_written(code, split):
    from bobina import paper

    advice = paper.code_advice(code)
    assert advice == f"'{code}' is a package code: give its parts as {split}"
    assert "Ask" not in advice and "?" not in advice


def test_the_suggested_commands_quote_every_value():
    import shlex

    from bobina import paper

    cmd = paper.code_advice("2 1/4 x 1 1/2in x 1/2in", cli=True).split("run ", 1)[1]
    assert shlex.split(cmd) == ["bobina", "paper", "new", "--diameter", "1 1/2in", "--core", "1/2in", "--width",
                                "2 1/4in"]  # fmt: skip


def test_paper_used_and_calibrate_tear_never_suggest_paper_new(capsys):
    run("printer", "add", "pipe", "--command", f'{sys.executable} -c "import sys; sys.stdin.buffer.read()"')
    for argv in (("paper", "used", "57x30"), ("paper", "used", "+57x30"), ("calibrate", "tear", "57x30")):
        assert run(*argv) == cli.USAGE
        assert "paper new" not in capsys.readouterr().err  # it would reset the roll


def test_a_roll_of_zero_in_the_state_file_is_unknown_not_a_crash(capsys):
    from bobina import fileio, paper

    run("printer", "add", "pipe", "--command", f'{sys.executable} -c "import sys; sys.stdin.buffer.read()"')
    assert run("paper", "new", "0m") == cli.USAGE
    fileio.locked_update(paper._path(), lambda d: d.update(pipe={"roll_mm": 0, "used_mm": 0.0, "loaded": "x"}))
    capsys.readouterr()
    assert run("paper") == cli.OK and "roll length unknown" in capsys.readouterr().out
    assert "unknown" in paper.check("pipe", 100, [])
    assert run("print", "hello", "--yes", "--quiet") == cli.OK


def test_paper_new_warns_when_the_roll_is_not_the_printers_width(capsys):
    import json

    from bobina import paper

    run("printer", "add", "pipe", "--command", f'{sys.executable} -c "import sys; sys.stdin.buffer.read()"')
    assert run("paper", "new", "30m", "--width", "57mm") == cli.OK
    assert "P103" not in capsys.readouterr().err  # 57 mm rolls are the 58 mm printers' rolls
    assert run("paper", "new", "40m", "--width", "80mm") == cli.OK  # a nudge: recorded anyway
    out = capsys.readouterr()
    assert "P103" in out.err and "takes 58 mm paper" in out.err and "80 mm wide" in out.out
    assert paper.get("pipe")["roll_mm"] == 40000 and paper.get("pipe")["width_mm"] == 80
    assert run("paper", "new", "40m", "--width", "80mm", "--allow", "P103") == cli.OK
    assert "P103" not in capsys.readouterr().err
    assert run("paper", "new", "20m", "--width", "80mm", "--strict") == 3  # --strict: not recorded
    assert "P103" in capsys.readouterr().err and paper.get("pipe")["roll_mm"] == 40000
    assert run("paper", "new", "20m", "--width", "80mm", "--strict", "--json") == 3  # … and the JSON still comes
    got = json.loads(capsys.readouterr().out)
    assert got["roll_mm"] == 40000 and [p["code"] for p in got["problems"]] == ["P103"]
    assert run("paper", "new", "20m", "--width", "80mm", "--profile", "epson-tm-t70-sa") == cli.OK  # an 80 mm one
    assert "P103" not in capsys.readouterr().err
    assert run("paper", "new", "57x30") == cli.USAGE
    assert "package code" in capsys.readouterr().err and paper.get("pipe")["roll_mm"] == 20000


def test_paper_default_roll(tmp_path):
    import sys

    from bobina import paper

    run("printer", "add", "pipe", "--command", f'{sys.executable} -c "import sys; sys.stdin.buffer.read()"')
    assert run("paper", "new", "10m", "--remember") == cli.OK
    assert run("paper", "new") == cli.OK
    assert paper.get("pipe")["roll_mm"] == 10000


def test_tear_calibration_sets_feed(capsys):
    from bobina import config
    from bobina.cli import printer_overrides
    from bobina.engine import build

    run("printer", "add", "mtp", "AA:BB:CC:DD:EE:FF")
    assert run("calibrate", "tear", "16") == cli.OK
    _, pr = config.printer(config.load(), None)
    res = build("x", overrides=printer_overrides(pr))
    assert res.rows[-1].dots == round((16 + 6) * 203 / 25.4)  # measured tear bar + 6 mm to spare


def test_config_keeps_numbers_as_numbers():
    from bobina import config

    run("printer", "add", "mtp", "AA:BB:CC:DD:EE:FF")
    run("calibrate", "tear", "5")
    assert "tear_mm = 5.0" in config.path().read_text()


def test_the_version_comes_from_pyproject():
    import tomllib
    from pathlib import Path

    import bobina

    meta = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert bobina.__version__ == meta["project"]["version"]
