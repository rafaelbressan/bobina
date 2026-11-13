"""bobina history export (JSONL or CSV for log and audit systems) and --log FILE / log_file (each run's problems
appended as JSON lines): stable formats, the history's masking, and a log that never fails a command."""

import csv
import io
import json

from test_schemas import _check, _schema

from bobina import cli, history


def run(*argv):
    return cli.main(list(argv))


def _jobs(tmp_path):
    assert run("print", "Olá {{ nome }}", "--set", "nome=Ana", "-o", str(tmp_path / "a.bin"), "-q") == cli.OK
    assert run("print", "Pedido 42", "--dry-run", "-q") == cli.OK
    return history.load()


def test_export_jsonl_is_the_stored_lines_oldest_first(tmp_path, capsys):
    rows = _jobs(tmp_path)
    capsys.readouterr()
    assert run("history", "export") == cli.OK
    out = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert out == rows and len(out) == 2
    for r in out:
        _check(r, _schema("history"))
    assert "Ana" not in json.dumps(out)  # --set values stay masked, as stored


def test_export_csv_has_the_documented_columns_in_order(tmp_path, capsys):
    _jobs(tmp_path)
    capsys.readouterr()
    assert run("history", "export", "--format", "csv", "--outcome", "saved") == cli.OK
    table = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    assert table[0] == list(history.CSV_COLUMNS)
    assert table[0][:4] == ["id", "time", "command", "outcome"] and "labels_printed" in table[0]
    assert len(table) == 2 and table[1][3] == "saved"
    row = dict(zip(table[0], table[1], strict=True))
    assert row["exit"] == "0" and row["labels"] == "1" and "nome=***" in row["argv"]


def test_export_to_a_file_and_filters(tmp_path, capsys):
    _jobs(tmp_path)
    out = tmp_path / "jobs.jsonl"
    assert run("history", "export", "--since", "today", "-o", str(out)) == cli.OK
    assert len(out.read_text().splitlines()) == 2
    assert "wrote 2 jobs" in capsys.readouterr().err
    assert run("history", "export", "--outcome", "failed") == cli.OK
    assert capsys.readouterr().out == ""
    assert run("history", "export", "--format", "xml") == cli.USAGE


def test_export_takes_every_job_unless_limit_says(tmp_path, capsys):
    for i in range(23):
        assert run("print", f"job {i}", "--dry-run", "-q") == cli.OK
    capsys.readouterr()
    assert run("history", "export") == cli.OK
    assert len(capsys.readouterr().out.splitlines()) == 23  # list shows 20; export is for systems: all of them
    assert run("history", "export", "--limit", "5") == cli.OK
    assert len(capsys.readouterr().out.splitlines()) == 5
    assert run("history") == cli.OK
    assert len(capsys.readouterr().out.splitlines()) == 20


# --------------------------------------------------------------- --log FILE


def log_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_log_appends_the_problems_of_each_run_with_the_job_id(tmp_path, capsys):
    log = tmp_path / "problems.jsonl"
    assert run("print", "Olá {{ nome }}", "-o", str(tmp_path / "a.bin"), "-q", "--log", str(log)) == cli.OK
    assert run("check", "x {{ y }}", "--log", str(log)) == cli.OK
    rows = log_lines(log)
    printed = [r for r in rows if r["command"] == "print"]
    checked = [r for r in rows if r["command"] == "check"]
    assert printed and printed[0]["job"] == history.load()[-1]["id"]  # -q hides them, the log keeps them
    assert checked and checked[0]["job"] is None and checked[0]["code"] == "M130"
    assert {r["code"] for r in printed} >= {"M130"}
    for r in rows:
        _check(r, _schema("log"))
        assert r["exit"] == 0


def test_log_masks_values_like_the_history(tmp_path):
    log = tmp_path / "p.jsonl"
    doc = "```ean13\n{{ code }}\n```\n\nfone {{ fone | date }}"
    run("check", doc, "--set", "code=segredo", "--set", "fone=11 91234-5678", "--log", str(log))
    text = log.read_text()
    assert text and "segredo" not in text and "91234" not in text


def test_log_file_in_config_logs_every_run(tmp_path):
    log = tmp_path / "always.jsonl"
    assert run("config", "set", "log_file", str(log)) == cli.OK
    assert run("check", "x {{ y }}") == cli.OK
    assert [r["code"] for r in log_lines(log)] == ["M130"]


def test_a_log_that_cannot_be_written_never_fails_the_command(tmp_path, capsys):
    bad = tmp_path / "no-such-folder" / "p.jsonl"
    assert run("check", "x {{ y }}", "--log", str(bad)) == cli.OK
    assert "were not logged" in capsys.readouterr().err


def test_a_run_without_problems_writes_nothing_and_errors_are_logged(tmp_path):
    log = tmp_path / "p.jsonl"
    assert run("check", "# ok", "--log", str(log)) == cli.OK
    assert not log.exists()
    assert run("print", "--last", "--log", str(log), "--yes") == cli.USAGE  # nothing printed yet: E105
    rows = log_lines(log)
    assert rows[-1]["code"] == "E105" and rows[-1]["severity"] == "error" and rows[-1]["exit"] == cli.USAGE


def test_log_value_is_kept_on_the_stored_command_line(tmp_path):
    log = tmp_path / "p.jsonl"
    assert run("print", "Pedido 42", "--dry-run", "-q", "--log", str(log)) == cli.OK
    assert history.load()[-1]["argv"][-2:] == ["--log", str(log)]


# --------------------------------------------------------------- review fixes


def test_log_after_then_is_a_job_option(tmp_path):
    log = tmp_path / "chain.jsonl"
    assert run("print", "a {{ y }}", "--dry-run", "-q", "--then", "b", "--log", str(log)) == cli.OK
    assert "M130" in {r["code"] for r in log_lines(log)}


def test_a_home_that_does_not_exist_is_a_note_not_a_crash(capsys):
    assert run("check", "x {{ y }}", "--log", "~no-such-user-xyz/p.jsonl") == cli.OK
    assert "were not logged" in capsys.readouterr().err


def test_export_to_a_named_file_guesses_csv_from_its_name(tmp_path, capsys):
    _jobs(tmp_path)
    out = tmp_path / "jobs.csv"
    assert run("history", "export", str(out)) == cli.OK
    assert out.read_text().splitlines()[0].split(",") == list(history.CSV_COLUMNS)
    assert run("history", "export", str(out), "-o", str(tmp_path / "x")) == cli.USAGE
    assert run("history", "--format", "csv") == cli.USAGE  # only export takes it


def test_export_with_json_says_nothing_about_json(tmp_path, capsys):
    _jobs(tmp_path)
    capsys.readouterr()
    assert run("history", "export", "--json") == cli.OK
    assert "--json does nothing" not in capsys.readouterr().err


def test_export_says_when_damaged_lines_are_left_out(tmp_path, capsys):
    _jobs(tmp_path)
    with history.path().open("a") as f:
        f.write("{not json\n")
    capsys.readouterr()
    assert run("history", "export") == cli.OK
    assert "1 damaged line(s)" in capsys.readouterr().err


def test_a_relative_log_file_is_beside_config_toml(tmp_path, monkeypatch):
    from bobina import config

    assert run("config", "set", "log_file", "problems.jsonl") == cli.OK
    monkeypatch.chdir(tmp_path)
    assert run("check", "x {{ y }}") == cli.OK
    assert (config.path().parent / "problems.jsonl").exists() and not (tmp_path / "problems.jsonl").exists()


def test_each_recorded_job_writes_its_problems_at_once(tmp_path):
    from bobina import problem_log
    from bobina.nudges import Nudge

    log = tmp_path / "p.jsonl"
    problem_log.start(["chat"], "chat", str(log))
    problem_log.add([Nudge("F304", "a font for Thai was downloaded")])
    rec = history.Recorder(["chat"])
    rec.finish("printed", 0, [])
    rows = log_lines(log)  # written when the job was recorded, not when the session ends
    assert [r["job"] for r in rows] == [history.LAST_ID] and rows[0]["code"] == "F304"
    problem_log.write(0, None)
    assert len(log_lines(log)) == 1  # nothing is written twice
    problem_log.start([], "", None)  # no log for the tests that follow


def test_without_a_log_nothing_is_collected():
    from bobina import problem_log

    assert run("check", "x {{ y }}") == cli.OK
    assert not problem_log.active() and not problem_log._seen
