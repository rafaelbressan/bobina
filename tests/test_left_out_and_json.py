"""A job that went out without its payment code says so in the exit code (9), and --json never swallows a warning:
the commands that write JSON put the problems in it, the others say --json does nothing (devex review 09/11)."""

import json

from bobina import cli

BAD_PAY = '# Order 42\n\n```pay {scheme=pix to="ze@example.com" name="A shop with a name far too long"}\n```\n'


def run(*argv):
    return cli.main(list(argv))


def test_a_payment_code_left_out_exits_9_and_the_rest_is_saved(tmp_path, capsys):
    out = tmp_path / "r.bin"
    assert run("print", BAD_PAY, "-o", str(out)) == cli.LEFT_OUT
    assert out.stat().st_size > 0  # the order itself was saved: a warning, not a block
    assert "Q111" in capsys.readouterr().err
    assert run("check", BAD_PAY) == cli.LEFT_OUT
    assert run("print", BAD_PAY, "--dry-run") == cli.LEFT_OUT


def test_allow_q111_gives_exit_0_back(tmp_path):
    assert run("check", BAD_PAY, "--allow", "Q111") == cli.OK
    assert run("print", BAD_PAY, "-o", str(tmp_path / "r.bin"), "--allow", "Q111") == cli.OK


def test_quiet_still_says_why_the_exit_is_9(capsys):
    assert run("check", BAD_PAY, "-q") == cli.LEFT_OUT
    assert "Q111" in capsys.readouterr().err


def test_print_json_carries_the_warning_instead_of_dropping_it(tmp_path, capsys):
    assert run("print", BAD_PAY, "-o", str(tmp_path / "r.bin"), "--json") == cli.LEFT_OUT
    io = capsys.readouterr()
    doc = json.loads(io.out)
    assert doc["outcome"] == "saved" and doc["exit"] == cli.LEFT_OUT and doc["saved_to"].endswith("r.bin")
    assert [p["code"] for p in doc["problems"]] == ["Q111"]


def test_preview_json_lists_the_files(tmp_path, capsys):
    assert run("preview", "hello", "-o", str(tmp_path / "p.png"), "--json") == cli.OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["files"] == [str(tmp_path / "p.png")] and doc["problems"] == []


def test_commands_without_json_say_so_and_keep_their_warnings(capsys):
    assert run("view", BAD_PAY, "--json") == cli.LEFT_OUT
    err = capsys.readouterr().err
    assert "--json does nothing in bobina view" in err and "Q111" in err


def test_paper_json_without_a_known_roll(tmp_path, capsys):
    assert run("printer", "add", "loja", "--path", str(tmp_path / "p.bin")) == cli.OK
    capsys.readouterr()
    assert run("paper", "--json") == cli.OK
    assert json.loads(capsys.readouterr().out) == {"printer": "loja", "roll_mm": None, "left_mm": None}


def test_help_json_lists_exit_9(capsys):
    assert run("help", "--json") == cli.OK
    assert "9" in json.loads(capsys.readouterr().out)["exit_codes"]


def _file_printer(tmp_path):
    sink = tmp_path / "printer.bin"
    assert run("printer", "add", "loja", "--path", str(sink)) == cli.OK
    return sink


def test_again_with_yes_shows_the_warning_and_strict_stops_it(tmp_path, capsys):
    sink = _file_printer(tmp_path)
    assert run("print", BAD_PAY, "-o", str(tmp_path / "first.bin")) == cli.LEFT_OUT
    run("print", BAD_PAY, "--yes")  # the last job
    size = sink.stat().st_size
    capsys.readouterr()
    assert run("print", "--again", "--yes") == cli.LEFT_OUT
    assert "Q111" in capsys.readouterr().err
    assert run("print", "--again", "--yes", "--strict") == cli.STRICT
    assert sink.stat().st_size == 2 * size  # the strict run sent nothing


def test_a_strict_stop_never_reports_a_saved_file(tmp_path, capsys):
    _file_printer(tmp_path)
    run("print", BAD_PAY, "--yes")
    capsys.readouterr()
    out = tmp_path / "x.bin"
    assert run("print", "--again", "-o", str(out), "--strict", "--json") == cli.STRICT
    doc = json.loads(capsys.readouterr().out)
    assert doc["saved_to"] is None and doc["outcome"] != "saved" and not out.exists()


def test_last_reprints_still_say_the_payment_code_is_missing(tmp_path, capsys):
    _file_printer(tmp_path)
    assert run("print", BAD_PAY, "--yes") == cli.LEFT_OUT
    capsys.readouterr()
    assert run("print", "--last", "--yes", "--json") == cli.LEFT_OUT
    assert [p["code"] for p in json.loads(capsys.readouterr().out)["problems"]] == ["Q111"]


def test_json_and_output_on_stdout_cannot_share_it():
    assert run("print", "hello", "-o", "/dev/stdout", "--json") == cli.USAGE


def test_a_subcommand_without_json_says_so(tmp_path, capsys):
    assert run("printer", "add", "t", "--path", str(tmp_path / "o.bin"), "--json") == cli.OK
    assert "--json does nothing in bobina printer add" in capsys.readouterr().err


def test_last_applies_this_runs_allow_and_strict(tmp_path, capsys):
    sink = _file_printer(tmp_path)
    assert run("print", BAD_PAY, "--yes") == cli.LEFT_OUT
    size = sink.stat().st_size
    assert run("print", "--last", "--yes", "--allow", "Q111") == cli.OK
    assert run("print", "--last", "--yes", "--strict") == cli.STRICT
    assert sink.stat().st_size == 2 * size  # the strict reprint sent nothing


def test_last_keeps_its_problems_in_the_history(tmp_path, capsys):
    _file_printer(tmp_path)
    run("print", BAD_PAY, "--yes")
    assert run("print", "--last", "--yes") == cli.LEFT_OUT
    capsys.readouterr()
    assert run("history", "--json") == cli.OK
    rows = json.loads(capsys.readouterr().out)
    newest = max(rows, key=lambda r: r["id"])
    assert newest["exit"] == cli.LEFT_OUT and [p["code"] for p in newest["problems"]] == ["Q111"]


def test_a_failed_print_still_answers_json(capsys, monkeypatch):
    monkeypatch.setattr(cli.common, "open_tty", lambda: None)
    assert run("print", "hello", "--json") == cli.CONFIRM  # no terminal, no --yes
    doc = json.loads(capsys.readouterr().out)
    assert doc["outcome"] == "failed" and doc["exit"] == cli.CONFIRM and doc["problems"][0]["code"] == "E107"


def test_edit_with_yes_says_why_it_exits_9(tmp_path, capsys):
    _file_printer(tmp_path)
    doc = tmp_path / "ed.bob.md"
    doc.write_text(BAD_PAY)
    assert run("edit", str(doc), "--editor", "true", "--yes") == cli.LEFT_OUT
    assert "Q111" in capsys.readouterr().err


def test_dash_is_a_file_name_for_o(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run("print", "hello", "-o", "-", "--json") == cli.OK
    assert (tmp_path / "-").exists()


def test_edit_yes_strict_stops_before_printing(tmp_path, capsys):
    sink = _file_printer(tmp_path)
    doc = tmp_path / "ed.bob.md"
    doc.write_text(BAD_PAY)
    assert run("edit", str(doc), "--editor", "true", "--yes", "--strict") == cli.STRICT
    assert not sink.exists()


def test_an_allow_of_the_first_print_does_not_stick_to_last(tmp_path):
    _file_printer(tmp_path)
    assert run("print", BAD_PAY, "--yes", "--allow", "Q111") == cli.OK
    assert run("print", "--last", "--yes") == cli.LEFT_OUT  # the same bytes still lack the code


def test_a_failed_print_json_keeps_the_jobs_warnings(capsys, monkeypatch):
    monkeypatch.setattr(cli.common, "open_tty", lambda: None)
    assert run("print", BAD_PAY, "--json") == cli.CONFIRM
    doc = json.loads(capsys.readouterr().out)
    assert [p["code"] for p in doc["problems"]] == ["Q111", "E107"] and doc["stats"]["length_mm"] > 0


def test_last_keeps_the_documents_own_allow(tmp_path):
    _file_printer(tmp_path)
    doc = "---\nallow: [Q111]\n---\n" + BAD_PAY
    assert run("print", doc, "--yes", "--strict") == cli.OK  # the document allowed it
    assert run("print", "--last", "--yes", "--strict") == cli.OK


def test_last_keeps_a_batch_warning_once(tmp_path, capsys):
    _file_printer(tmp_path)
    rows = tmp_path / "rows.csv"
    rows.write_text("n\n1\n2\n3\n")
    doc = tmp_path / "b.bob.md"
    doc.write_text(BAD_PAY + "\n{{ n }}\n")
    assert run("print", str(doc), "--data", str(rows), "--yes") == cli.LEFT_OUT
    capsys.readouterr()
    assert run("print", "--last", "--yes", "--json") == cli.LEFT_OUT
    assert [p["code"] for p in json.loads(capsys.readouterr().out)["problems"]] == ["Q111"]


def test_interactive_edit_with_strict_stops_before_the_screen(tmp_path, monkeypatch):
    import io

    sink = _file_printer(tmp_path)
    doc = tmp_path / "ed.bob.md"
    doc.write_text(BAD_PAY)
    monkeypatch.setattr(cli.common, "open_tty", lambda: io.StringIO("p\n"))
    assert run("edit", str(doc), "--editor", "true", "--strict") == cli.STRICT
    assert not sink.exists()


def test_the_documents_allow_survives_a_matching_command_line_allow(tmp_path):
    _file_printer(tmp_path)
    doc = "---\nallow: [Q111]\n---\n" + BAD_PAY
    assert run("print", doc, "--yes", "--allow", "Q111") == cli.OK
    assert run("print", "--last", "--yes", "--strict") == cli.OK


def test_a_parts_command_line_allow_does_not_stick(tmp_path):
    _file_printer(tmp_path)
    assert run("print", "hello", "--then", BAD_PAY, "--allow", "Q111", "--yes") == cli.OK
    assert run("print", "--last", "--yes") == cli.LEFT_OUT


def test_strict_refuses_p_after_an_edit_brings_a_warning(tmp_path, monkeypatch, capsys):
    import io

    sink = _file_printer(tmp_path)
    doc = tmp_path / "ed.bob.md"
    doc.write_text("hello\n")

    def editor(path, *a, **k):
        if editor.calls:
            path.write_text(BAD_PAY)
        editor.calls += 1

    editor.calls = 0
    monkeypatch.setattr(cli.common.editor, "open_file", editor)
    monkeypatch.setattr(cli.common, "open_tty", lambda: io.StringIO("e\np\nq\n"))
    assert run("edit", str(doc), "--strict") == cli.CONFIRM
    assert not sink.exists()


def test_a_one_code_allow_in_front_matter_works():
    assert run("check", "---\nallow: Q111\n---\n" + BAD_PAY) == cli.OK
    assert run("check", "---\nallow: Q111, L105\n---\n" + BAD_PAY) == cli.OK


def test_allow_all_counts_for_last(tmp_path):
    _file_printer(tmp_path)
    run("print", BAD_PAY, "--yes")
    assert run("print", "--last", "--yes", "--allow-all", "Q111") == cli.OK


def test_a_failure_keeps_the_jobs_warnings_in_the_history(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.common, "open_tty", lambda: None)
    assert run("print", BAD_PAY) == cli.CONFIRM
    capsys.readouterr()
    assert run("history", "--json") == cli.OK
    row = max(json.loads(capsys.readouterr().out), key=lambda r: r["id"])
    assert {p["code"] for p in row["problems"]} == {"Q111", "E107"}
