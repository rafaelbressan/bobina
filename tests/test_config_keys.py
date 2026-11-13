"""bobina config list|get|set|unset|edit and bobina printer show|set|unset: every setting of config.toml from the
command line, one table behind them (bobina.config_keys), and a bad value in the file never stops a print."""

import json
import re
from pathlib import Path

import pytest

from bobina import cli, config, config_keys
from bobina.cli import common

SRC = Path(__file__).resolve().parents[1] / "src" / "bobina"
NOT_BOBINA = {"model"}  # ai.py reads Codex's own ~/.codex/config.toml


def run(*argv):
    return cli.main(list(argv))


def out_json(capsys):
    return json.loads(capsys.readouterr().out)


# --------------------------------------------------------------- the table


def test_every_key_the_code_reads_is_in_the_table():
    code = "\n".join(p.read_text(encoding="utf-8") for p in SRC.rglob("*.py"))
    top = set(re.findall(r'(?:cfg|config\.load\(\))\.get\("([a-z_]+)"', code))
    top |= set(re.findall(r'cfg\["([a-z_]+)"\]', code)) | set(re.findall(r'set_value\("([a-z_]+)"', code))
    top |= set(re.findall(r'config_keys\.read\([^)]*?"([a-z_]+)"', code))
    top |= set(re.findall(r'_setting\(args, cfg, "([a-z_]+)"', code))
    missing = top - set(config_keys.KEYS) - NOT_BOBINA
    assert not missing, f"read from config.toml but not in config_keys.KEYS: {sorted(missing)}"
    printer = set(re.findall(r'\b(?:pr|printer)\.get\("([a-z_]+)"', code))
    printer |= set(re.findall(r'\b(?:pr|printer)\["([a-z_]+)"\]', code))
    assert printer - set(config_keys.PRINTER_KEYS) == set()


def test_defaults_in_the_table_are_the_ones_the_code_uses():
    from bobina import chat
    from bobina.cli import chat as cli_chat
    from bobina.paper import parse_length

    k = config_keys.KEYS
    assert k["chat_paper_style"].default == cli_chat.DEFAULT_STYLE
    assert parse_length(k["chat_limit"].default, None) == chat.DEFAULT_LIMIT_MM
    assert config_keys.PRINTER_KEYS["tear_margin_mm"].default == common.TEAR_MARGIN_MM
    assert k["chat_layout"].default == chat.LAYOUTS[0]


def test_values_are_checked_with_what_is_accepted():
    k = config_keys.KEYS
    assert config_keys.parse(k["step"], "Off") is False and config_keys.parse(k["step"], "yes") is True
    assert config_keys.parse(k["history_max"], "200") == 200
    assert config_keys.parse(k["locale"], "fr_ca") == "fr-CA"
    with pytest.raises(config_keys.KeyError_, match="did you mean both"):
        config_keys.parse(k["marks"], "bth")
    with pytest.raises(config_keys.KeyError_, match="1 or more"):
        config_keys.parse(k["history_max"], "0")
    with pytest.raises(config_keys.KeyError_, match="from 1.5cm to 1m"):
        config_keys.parse(k["chat_limit"], "5mm")
    with pytest.raises(config_keys.KeyError_, match="did you mean step"):
        config_keys.find("stpe")


# --------------------------------------------------------------- bobina config


def test_list_shows_every_setting_with_its_source(capsys):
    assert run("config", "set", "marks", "both") == cli.OK
    capsys.readouterr()
    assert run("config", "list") == cli.OK
    text = capsys.readouterr().out
    assert re.search(r"marks\s+both\n", text) and re.search(r"step\s+on \(default\)", text)
    assert "history_max" not in text and "more: --all" in text
    assert run("config") == cli.OK  # list is the default
    assert run("config", "list", "--all") == cli.OK
    assert "history_max" in capsys.readouterr().out


def test_set_get_unset(capsys):
    cfgfile = config.path()
    cfgfile.write_text('# mine\nlocale = "en-US"\n')
    assert run("config", "set", "step", "off") == cli.OK
    assert "step = off saved in config.toml" in capsys.readouterr().out
    assert config.load()["step"] is False and cfgfile.read_text().startswith("# mine\n")
    assert run("config", "get", "step") == cli.OK
    assert "step = off (config.toml)" in capsys.readouterr().out
    assert run("config", "unset", "step") == cli.OK
    assert "back to the default (on)" in capsys.readouterr().out
    assert "step" not in config.load() and cfgfile.read_text().startswith("# mine\n")
    assert run("config", "unset", "step") == cli.OK
    assert "was not set" in capsys.readouterr().out


def test_folders_take_several_values_and_a_multi_line_value_unsets(capsys):
    assert run("config", "set", "image_dirs", "a", "b c") == cli.OK
    assert config.load()["image_dirs"] == ["a", "b c"]
    config.path().write_text('locale = "en-US"\nimage_dirs = [\n  "x",\n  "y",\n]\nstep = false\n')
    assert run("config", "unset", "image_dirs") == cli.OK
    assert config.load() == {"locale": "en-US", "step": False}


def test_wrong_keys_values_and_keys_other_commands_own(capsys):
    assert run("config", "set", "marks", "bth") == cli.USAGE
    assert "did you mean both?" in capsys.readouterr().err
    assert run("config", "get", "stpe") == cli.USAGE
    assert "did you mean step?" in capsys.readouterr().err
    assert run("config", "set", "ai", "claude") == cli.USAGE
    assert "bobina ai use NAME" in capsys.readouterr().err
    assert run("config", "set", "default_printer", "x") == cli.USAGE
    assert "bobina printer use NAME" in capsys.readouterr().err
    assert run("config", "set", "chat", "x") == cli.USAGE
    assert run("config", "set", "chat_name", "Ana", "Maria") == cli.USAGE  # two values for one: quote it
    assert "quote it" in capsys.readouterr().err
    assert run("config", "set", "step") == cli.USAGE
    assert "on or off" in capsys.readouterr().err


def test_the_old_forms_are_gone():
    for argv in (["config", "locale", "pt-BR"], ["config", "step", "off"]):
        with pytest.raises(SystemExit) as e:
            run(*argv)
        assert e.value.code == cli.USAGE


def test_json_of_list_get_and_printer_show_match_the_schema(capsys):
    from test_schemas import _check, _schema

    config.path().write_text('locale = "en-US"\nmarks = "bth"\nstpe = 1\n')
    assert run("printer", "add", "loja", "--path", "o.bin", "--quiet") == cli.OK
    capsys.readouterr()
    assert run("config", "list", "--json") == cli.OK
    doc = out_json(capsys)
    _check(doc, _schema("config"))
    assert {p["message"] for p in doc["problems"]} >= {"stpe: not a bobina setting (did you mean step?)"}
    assert "loja" in doc["printers"]
    assert run("config", "get", "marks", "--json") == cli.OK
    doc = out_json(capsys)
    _check(doc, _schema("config"))
    assert doc["value"] == "bth" and doc["problems"][0]["code"] == "E304"
    assert run("printer", "show", "loja", "--json") == cli.OK
    _check(out_json(capsys), _schema("config"))


def test_a_bad_value_in_the_file_never_stops_a_print(tmp_path, capsys):
    config.path().write_text('locale = "en-US"\nmarks = "always"\nstep = "maybe"\n')
    assert run("print", "Oi", "-o", str(tmp_path / "o.bin")) == cli.OK
    err = capsys.readouterr().err
    assert "config.toml: marks = 'always': use none, cut, tear, both; none is used" in err
    assert err.count("marks = 'always'") == 1  # said once


def test_edit_opens_the_editor_and_checks_the_file(monkeypatch, capsys):
    from bobina import editor

    def bad_edit(path, flag, cfg):
        Path(path).write_text('locale = "en-US"\nmarks = "bth"\nstpe = 1\n\n[printers.x]\npath = "o"\nchanel = 2\n')
        return 0

    monkeypatch.setattr(editor, "open_file", bad_edit)
    assert run("config", "edit") == cli.OK
    err = capsys.readouterr().err
    assert "line 2" in err and "did you mean both?" in err and "did you mean step?" in err
    assert "printers.x.chanel: not a printer setting (did you mean channel?)" in err

    monkeypatch.setattr(editor, "open_file", lambda p, f, c: Path(p).write_text("marks = [\n") and 0)
    assert run("config", "edit") == cli.USAGE
    assert "is not valid TOML now" in capsys.readouterr().err

    monkeypatch.setattr(editor, "open_file", lambda p, f, c: Path(p).write_text("step = false\n") and 0)
    assert run("config", "edit") == cli.OK
    assert "every setting is fine" in capsys.readouterr().out


def test_edit_creates_the_file_and_names_a_missing_editor(monkeypatch, capsys):
    config.path().unlink()
    monkeypatch.setenv("VISUAL", "no-such-editor-here")
    assert run("config", "edit") == cli.USAGE
    assert "cannot open the editor 'no-such-editor-here'" in capsys.readouterr().err
    assert "bobina config list" in config.path().read_text()  # the commented example, for the next try


# --------------------------------------------------------------- bobina printer


def test_printer_show_set_unset(capsys):
    assert run("printer", "add", "loja", "--path", "o.bin", "--quiet") == cli.OK
    capsys.readouterr()
    assert run("printer", "set", "loja", "tear_margin_mm", "4") == cli.OK
    assert config.load()["printers"]["loja"]["tear_margin_mm"] == 4.0
    assert run("printer", "show", "loja") == cli.OK
    text = capsys.readouterr().out
    assert re.search(r"tear_margin_mm\s+4 ", text) and re.search(r"busy_timeout\s+300 \(default\)", text)
    assert "blank_rows_after_raster" not in text  # advanced and not set
    assert run("printer", "unset", "loja", "tear_margin_mm") == cli.OK
    assert "tear_margin_mm" not in config.load()["printers"]["loja"]
    assert run("printer", "set", "loja", "chanel", "2") == cli.USAGE
    assert "did you mean channel?" in capsys.readouterr().err
    assert run("printer", "set", "loja", "transport", "bluetooth") == cli.USAGE  # it would have no address
    assert "needs address" in capsys.readouterr().err
    assert config.load()["printers"]["loja"]["transport"] == "file"  # nothing written
    assert run("printer", "set", "nope", "timeout", "5") == cli.USAGE


def test_a_key_without_its_verb_says_which_verb(capsys):
    with pytest.raises(SystemExit):
        run("config", "locale", "pt-BR")
    assert "bobina config get locale, or bobina config set locale VALUE" in capsys.readouterr().err


# --------------------------------------------------------------- review fixes


def test_unset_on_a_file_that_is_not_toml_is_an_error_not_a_crash(capsys):
    config.path().write_text("locale = \n")
    assert run("config", "unset", "step") == cli.USAGE
    assert "E209" in capsys.readouterr().err


def test_image_dirs_is_checked_as_sandbox_reads_it(capsys):
    config.path().write_text('locale = "en-US"\nimage_dirs = "~/Pictures"\n')
    assert run("config", "list") == cli.OK
    assert "a list of folders" in capsys.readouterr().out
    assert run("config", "set", "image_dirs", "") == cli.USAGE


def test_bare_numbers_are_read_as_their_readers_do():
    k = config_keys.KEYS
    assert config_keys.parse(k["paper_roll"], "15") == "15"  # bobina paper new reads 15 as metres
    assert config_keys.parse(k["chat_limit"], "10") == "10"  # bobina chat reads 10 as cm
    with pytest.raises(config_keys.KeyError_):
        config_keys.parse(k["chat_limit"], "1")  # 1 cm is too little


def test_a_profile_file_is_a_profile(tmp_path):
    own = tmp_path / "mine.toml"
    own.write_text("")
    assert config_keys.parse(config_keys.KEYS["profile"], str(own)) == str(own)
    with pytest.raises(config_keys.KeyError_, match="no such file"):
        config_keys.parse(config_keys.KEYS["profile"], str(tmp_path / "nope.toml"))


def test_words_for_on_and_off_act_as_they_are_shown():
    from bobina import history

    config.path().write_text('locale = "en-US"\nhistory = "off"\nkeep_last = "no"\n')
    assert history.enabled() is False
    assert config_keys.read(config.load(), "keep_last") is False


def test_list_reports_printer_and_chat_problems(capsys):
    config.path().write_text('locale = "en-US"\n\n[printers.x]\npath = "o"\ntear_margn_mm = 4\nbusy_timeout = "x"\n')
    assert run("config", "list", "--json") == cli.OK
    msgs = " ".join(p["message"] for p in out_json(capsys)["problems"])
    assert "tear_margn_mm: not a printer setting (did you mean tear_margin_mm?)" in msgs and "busy_timeout" in msgs


def test_printer_keys_point_at_printer_show_and_share_the_json_rows(capsys):
    assert run("printer", "add", "loja", "--path", "o.bin", "--quiet") == cli.OK
    assert run("printer", "set", "loja", "margin", "4") == cli.USAGE
    assert "all of them: bobina printer show loja" in capsys.readouterr().err
    assert run("printer", "show", "loja", "--json") == cli.OK
    row = out_json(capsys)["keys"][0]
    assert {"problem", "default_shown", "choices", "accepts"} <= set(row)
    assert run("printer", "set", "loja", "tear_margin_mm", "3") == cli.OK
    assert "until then loja feeds the profile's distance" in capsys.readouterr().err


def test_print_edit_names_a_missing_editor_instead_of_crashing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("VISUAL", "no-such-editor-xyz")
    monkeypatch.delenv("EDITOR", raising=False)
    (tmp_path / "d.bob.md").write_text("hi\n")
    assert cli.main(["edit", str(tmp_path / "d.bob.md")]) == cli.USAGE
    assert "cannot open the editor 'no-such-editor-xyz'" in capsys.readouterr().err
