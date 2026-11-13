"""The problem policy in config.toml: problems.allow, problems.error, problems.strict, problems.format, how they rank
against the command line and the document, and resetting the whole group (bobina config unset problems)."""

import json
import tomllib

import pytest

from bobina import cli, config
from bobina.cli import common


class FakeTTY:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.shown = []

    def write(self, s):
        self.shown.append(s)

    def flush(self):
        pass

    def readline(self):
        return (self.answers.pop(0) + "\n") if self.answers else ""

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def run(*argv):
    return cli.main(list(argv))


def toml():
    return tomllib.loads(config.path().read_text())


@pytest.fixture
def doc(tmp_path):
    """A document with an empty blank: warning M130 (a field with no value)."""
    p = tmp_path / "d.bob.md"
    p.write_text("# {{ product }}\n")
    return str(p)


@pytest.fixture
def no_tty(monkeypatch):
    monkeypatch.setattr(common, "open_tty", lambda: None)


def test_set_get_and_list_the_policy(capsys):
    assert run("config", "set", "problems.allow", "L102,F301") == cli.OK
    assert toml()["problems"]["allow"] == ["L102", "F301"]
    assert run("config", "set", "problems.error", "m130", "M131") == cli.OK  # spaces and lower case too
    assert toml()["problems"]["error"] == ["M130", "M131"]
    assert run("config", "set", "problems.strict", "on") == cli.OK
    capsys.readouterr()
    assert run("config", "get", "problems.allow") == cli.OK
    assert "problems.allow = L102, F301 (config.toml)" in capsys.readouterr().out
    assert run("config", "list", "--json") == cli.OK
    keys = {r["key"]: r for r in json.loads(capsys.readouterr().out)["keys"]}
    assert keys["problems.strict"]["value"] is True and keys["problems.format"]["source"] == "default"


def test_an_unknown_code_is_kept_with_a_note_and_a_malformed_one_is_refused(capsys):
    assert run("config", "set", "problems.allow", "L109") == cli.OK  # no such code: kept, said
    err = capsys.readouterr().err
    assert "L109 is not a bobina problem code" in err and "did you mean" in err
    assert run("config", "set", "problems.allow", "abc") == cli.USAGE
    assert "'ABC' is not a problem code" in capsys.readouterr().err
    assert toml()["problems"]["allow"] == ["L109"]


def test_a_table_written_by_hand_is_kept_and_emptied_tables_go(capsys):
    config.path().write_text(config.path().read_text() + '\n# my policy\n[problems]\nallow = ["L102"]\n')
    assert run("config", "set", "problems.strict", "on") == cli.OK
    text = config.path().read_text()
    assert "# my policy" in text and "[problems]" in text and "problems.strict" not in text
    assert toml()["problems"] == {"allow": ["L102"], "strict": True}
    assert run("config", "unset", "problems.allow") == cli.OK
    assert run("config", "unset", "problems.strict") == cli.OK
    assert "problems" not in toml() and "[problems]" not in config.path().read_text()


def test_allow_in_config_silences_and_the_document_and_command_line_still_add(doc, capsys):
    assert run("check", doc) == cli.OK
    assert "M130" in capsys.readouterr().err
    assert run("config", "set", "problems.allow", "M130") == cli.OK
    capsys.readouterr()
    assert run("check", doc) == cli.OK
    assert "M130" not in capsys.readouterr().err


def test_error_codes_stop_and_allow_on_the_command_line_beats_them(doc, capsys):
    assert run("config", "set", "problems.error", "M130") == cli.OK
    capsys.readouterr()
    assert run("check", doc) == cli.STRICT
    assert "(problems.error: M130)" in capsys.readouterr().err
    assert run("check", doc, "--allow", "M130") == cli.OK
    doc_allowed = doc.replace("d.bob.md", "e.bob.md")
    with open(doc_allowed, "w") as f:
        f.write("---\nallow: M130\n---\n# {{ product }}\n")
    assert run("check", doc_allowed) == cli.OK  # the document beats the config too


def test_strict_in_config_and_no_strict_for_one_run(doc, capsys):
    assert run("config", "set", "problems.strict", "on") == cli.OK
    capsys.readouterr()
    assert run("check", doc) == cli.STRICT
    assert "(problems.strict)" in capsys.readouterr().err
    assert run("check", doc, "--no-strict") == cli.OK


def test_format_ranks_below_the_environment_and_the_option(doc, capsys, monkeypatch):
    assert run("config", "set", "problems.format", "plain") == cli.OK
    capsys.readouterr()
    run("check", doc)
    assert capsys.readouterr().err.startswith("warning M130:")  # plain: one line per problem
    monkeypatch.setenv("BOBINA_PROBLEMS", "json")  # the MCP server sets it: its tools keep JSON
    run("check", doc)
    assert json.loads(capsys.readouterr().err)
    run("check", doc, "--problems", "pretty")
    err = capsys.readouterr().err
    assert "M130" in err and not err.startswith(("{", "warning M130:"))


def test_a_security_refusal_can_never_be_allowed(tmp_path, capsys):
    p = tmp_path / "x.bob.md"
    p.write_text('{% include "other.bob.md" %}\n')
    assert run("config", "set", "problems.allow", "M310") == cli.OK
    assert run("check", str(p)) == cli.SECURITY


def test_a_bad_value_in_the_file_never_stops_a_command(doc, capsys):
    config.path().write_text(config.path().read_text() + '\n[problems]\nstrict = "maybe"\nformat = "fancy"\n')
    assert run("check", doc) == cli.OK
    err = capsys.readouterr().err
    assert "problems.strict" in err and "M130" in err


# --------------------------------------------------------------- bobina config unset problems


def set_policy():
    assert run("config", "set", "problems.allow", "L102,F301") == cli.OK
    assert run("config", "set", "problems.strict", "on") == cli.OK


def test_unset_group_asks_and_yes_removes_and_says_how_to_restore(monkeypatch, capsys):
    set_policy()
    tty = FakeTTY("y")
    monkeypatch.setattr(common, "open_tty", lambda: tty)
    capsys.readouterr()
    assert run("config", "unset", "problems") == cli.OK
    out = capsys.readouterr().out
    assert "remove problems.allow L102,F301 and problems.strict on? [y/n]" in "".join(tty.shown)
    assert "problems.allow L102,F301 and problems.strict on removed: back to the defaults" in out
    restore = "bobina config set problems.allow L102,F301 && bobina config set problems.strict on"
    assert f"to restore them: {restore}" in out
    assert "problems" not in toml()
    for cmd in restore.split(" && "):  # the restore command sets it back exactly
        assert run(*cmd.split()[1:]) == cli.OK
    assert toml()["problems"] == {"allow": ["L102", "F301"], "strict": True}


def test_unset_group_answered_no_changes_nothing(monkeypatch, capsys):
    set_policy()
    monkeypatch.setattr(common, "open_tty", lambda: FakeTTY("n"))
    assert run("config", "unset", "problems") == cli.CONFIRM
    assert "nothing removed" in capsys.readouterr().err
    assert toml()["problems"] == {"allow": ["L102", "F301"], "strict": True}


def test_unset_group_without_a_terminal_needs_yes(no_tty, capsys):
    set_policy()
    assert run("config", "unset", "problems") == cli.CONFIRM
    err = capsys.readouterr().err
    assert "E107" in err and "--yes" in err and "nothing changed" in err
    assert toml()["problems"] == {"allow": ["L102", "F301"], "strict": True}
    assert run("config", "unset", "problems", "--yes", "--json") == cli.OK
    out = json.loads(capsys.readouterr().out)
    assert out["removed"] == {"problems.allow": ["L102", "F301"], "problems.strict": True}
    assert out["restore"].startswith("bobina config set problems.allow L102,F301")
    assert "problems" not in toml()


def test_unset_group_with_nothing_set_and_one_key_never_asks(no_tty, capsys):
    assert run("config", "unset", "problems") == cli.OK
    assert "nothing to remove" in capsys.readouterr().out
    set_policy()
    assert run("config", "unset", "problems.allow") == cli.OK  # one key: no question
    assert toml()["problems"] == {"strict": True}


# --------------------------------------------------------------- review fixes


def test_dry_run_writes_nothing(no_tty, capsys):
    set_policy()
    before = config.path().read_text()
    assert run("config", "set", "problems.format", "plain", "--dry-run") == cli.OK
    assert run("config", "unset", "problems.allow", "--dry-run") == cli.OK
    assert run("config", "unset", "problems", "--dry-run") == cli.OK
    assert "would be removed (dry run" in capsys.readouterr().out
    assert config.path().read_text() == before


def test_a_string_or_odd_list_in_the_file_still_gives_a_working_restore(no_tty, capsys):
    config.path().write_text(config.path().read_text() + '\n[problems]\nallow = "L102,F301"\nerror = [130]\n')
    assert run("config", "unset", "problems", "--yes") == cli.OK
    out = capsys.readouterr().out
    assert "bobina config set problems.allow L102,F301" in out and "problems.error 130" in out


def test_multi_line_values_and_comments_in_the_table_are_kept():
    config.path().write_text(
        config.path().read_text()
        + '\n[problems]\n# silence long prints at work\nallow = [\n  "L102",\n]\n# end\n\n[printers.a]\npath = "x"\n'
    )
    assert run("config", "set", "problems.error", "M130") == cli.OK
    assert toml()["problems"] == {"allow": ["L102"], "error": ["M130"]}
    assert run("config", "set", "problems.allow", "F301") == cli.OK  # its old value spanned three lines
    assert toml()["problems"]["allow"] == ["F301"]
    assert run("config", "unset", "problems.allow") == cli.OK
    assert run("config", "unset", "problems.error") == cli.OK
    text = config.path().read_text()
    assert "# silence long prints at work" in text and "# end" in text  # comments keep their table
    assert toml().get("problems", {}) == {}
    assert toml()["printers"]["a"]["path"] == "x"


def test_quiet_still_shows_the_note_that_stopped_the_job(doc, capsys):
    assert run("config", "set", "problems.error", "M130") == cli.OK
    capsys.readouterr()
    assert run("check", doc, "-q") == cli.STRICT
    assert "M130" in capsys.readouterr().err


def test_a_code_both_allowed_and_an_error_in_config_stops(doc, capsys):
    assert run("config", "set", "problems.allow", "M130") == cli.OK
    assert run("config", "set", "problems.error", "M130") == cli.OK
    capsys.readouterr()
    assert run("check", doc) == cli.STRICT
