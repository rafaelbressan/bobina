"""A print of several labels stops after each one so it can be torn off: when it stops, what the keys do,
the seq numbers of a job stopped part way, --last, and when it never stops (agents, --yes, files, --compact)."""

import json
import shlex

import pytest

from bobina import cli, state
from bobina.cli import args as A
from bobina.cli import common, steps


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

    @property
    def text(self):
        return "".join(self.shown)


def run(*argv):
    return cli.main(list(argv))


@pytest.fixture
def printer(tmp_path):
    """A real printer for bobina (a command, its roll counted) that writes each send to a file and counts sends."""
    sink, sends = tmp_path / "paper.bin", tmp_path / "sends"
    cmd = f"sh -c {shlex.quote(f'cat >> {shlex.quote(str(sink))}; printf x >> {shlex.quote(str(sends))}')}"
    assert run("printer", "add", "loja", "--command", cmd, "--quiet") == cli.OK

    class P:
        def sends(self):
            return len(sends.read_text()) if sends.exists() else 0

        def data(self):
            return sink.read_bytes() if sink.exists() else b""

    return P()


@pytest.fixture
def tty(monkeypatch):
    def make(*answers):
        t = FakeTTY(*answers)
        monkeypatch.setattr(common, "open_tty", lambda: t)
        monkeypatch.setattr(steps, "open_tty", lambda: t)
        return t

    return make


def jars(tmp_path, n=4, seq=False):
    rows = "\n".join(f"Jar {i}" for i in range(1, n + 1))
    (tmp_path / "jars.csv").write_text("name\n" + rows + "\n")
    body = "# {{ name }}\n" + ("\nN {{ seq.jar }}\n" if seq else "")
    front = "---\ncounters:\n  jar: { start: 1 }\n---\n" if seq else ""
    (tmp_path / "jar.bob.md").write_text(front + body)
    return str(tmp_path / "jar.bob.md"), str(tmp_path / "jars.csv")


# --------------------------------------------------------------- the options


def parsed(*argv):
    return A.parse_args(A.make_parser(), ["print", *argv])


def test_step_options_and_their_names():
    assert parsed("a.bob.md").step is None
    assert parsed("a.bob.md", "--step").step == 1
    assert parsed("a.bob.md", "--step", "3").step == 3
    assert parsed("a.bob.md", "--step=2").step == 2
    assert parsed("--step", "a.bob.md").target == ["a.bob.md"]  # a file after --step is the document
    for off in ("--no-step", "--no-steps", "--continuous", "--all-at-once", "--no-pause", "--no-pauses"):
        assert parsed("a.bob.md", off).step == 0, off
    assert parsed("a.bob.md", "--pause").step == 1
    with pytest.raises(SystemExit):
        parsed("a.bob.md", "--step=0")


def test_step_is_not_offered_in_portuguese():
    hidden = {o for a in A.COMMANDS["print"]._actions for o in a.option_strings}
    assert not {"--sem-pausa", "--passo", "--pausar"} & hidden


# --------------------------------------------------------------- stopping


def test_each_label_is_its_own_send_and_enter_prints_the_next(tmp_path, printer, tty, capsys):
    doc, data = jars(tmp_path, 3)
    t = tty("p", "", "")
    assert run("print", doc, "--data", data) == cli.OK
    assert printer.sends() == 3
    assert "3 labels: bobina stops after each label" in t.text
    assert " ✓ 1/3 printed: tear it off" in t.text and "next (2/3 · Jar 2)" in t.text
    assert "3 of 3 labels printed on loja (~" in capsys.readouterr().err


def test_all_prints_the_rest_at_once(tmp_path, printer, tty):
    doc, data = jars(tmp_path, 4)
    t = tty("p", "a")
    assert run("print", doc, "--data", data) == cli.OK
    assert printer.sends() == 2 and "[a] all 3 left" in t.text
    assert printer.data().count(b"Jar") == 4


def test_again_reprints_the_last_label_with_the_same_bytes(tmp_path, printer, tty):
    doc, data = jars(tmp_path, 2)
    tty("p", "r", "")
    assert run("print", doc, "--data", data) == cli.OK
    out = printer.data()
    assert printer.sends() == 3 and out.count(b"Jar 1") == 2 and out.count(b"Jar 2") == 1


def test_skip_leaves_a_label_out(tmp_path, printer, tty, capsys):
    doc, data = jars(tmp_path, 3)
    tty("p", "s", "")
    assert run("print", doc, "--data", data) == cli.OK
    assert b"Jar 2" not in printer.data() and b"Jar 3" in printer.data()
    assert "2 of 3 labels printed on loja (~" in (e := capsys.readouterr().err) and "cm), 1 skipped" in e


def test_stop_says_the_command_for_the_rest(tmp_path, printer, tty, capsys):
    doc, data = jars(tmp_path, 5)
    tty("p", "", "q")
    assert run("print", doc, "--data", data) == cli.OK
    err = capsys.readouterr().err
    assert "stopped: 2 of 5 labels printed on loja (~" in err and "cm), 3 not printed" in err
    assert f"to print the rest: bobina print {doc} --data {data} --rows 3-5" in err
    assert printer.sends() == 2


def test_stop_with_where_keeps_the_filter_and_names_file_rows(tmp_path, printer, tty, capsys):
    (tmp_path / "p.csv").write_text("name,shelf\nA1,a\nB1,b\nA2,a\nA3,a\n")
    (tmp_path / "t.bob.md").write_text("# {{ name }}\n")
    tty("p", "q")
    assert run("print", str(tmp_path / "t.bob.md"), "--data", str(tmp_path / "p.csv"), "--where", "shelf=a") == 0
    assert "--where shelf=a --rows 3-4" in capsys.readouterr().err  # A2 and A3: file rows 3 and 4


def test_stop_among_copies_and_repeat(tmp_path, printer, tty, capsys):
    tty("p", "q")
    assert run("print", "Hello", "--copies", "4") == cli.OK
    assert "to print the rest: bobina print Hello --copies 3" in capsys.readouterr().err
    tty("p", "", "q")
    assert run("print", "Hello", "--repeat", "5") == cli.OK
    assert "bobina print Hello --repeat 3" in capsys.readouterr().err


def test_step_n_stops_every_n_labels(tmp_path, printer, tty):
    doc, data = jars(tmp_path, 5)
    t = tty("p", "", "")
    assert run("print", doc, "--data", data, "--step", "2") == cli.OK
    assert printer.sends() == 3  # 2 + 2 + 1
    assert "stops after every 2 labels" in t.text and "next (3-4/5" in t.text


# --------------------------------------------------------------- seq numbers


def counters(tmp_path):
    return json.loads((tmp_path / "state" / "counters.json").read_text())


def test_stopped_job_gives_back_the_numbers_it_did_not_print(tmp_path, printer, tty):
    doc, data = jars(tmp_path, 4, seq=True)
    tty("p", "", "q")
    assert run("print", doc, "--data", data) == cli.OK
    assert counters(tmp_path)["jar"] == 3  # 1 and 2 printed; 3 is next
    tty("p", "a")
    assert run("print", doc, "--data", data) == cli.OK
    assert counters(tmp_path)["jar"] == 7
    assert b"N 3" in printer.data() and printer.data().count(b"N 2") == 1


def test_skipped_label_between_printed_ones_leaves_a_gap(tmp_path, printer, tty):
    doc, data = jars(tmp_path, 3, seq=True)
    tty("p", "s", "")
    assert run("print", doc, "--data", data) == cli.OK
    assert counters(tmp_path)["jar"] == 4  # 2 was skipped: never printed twice later


def test_reserved_numbers_of_another_print_are_never_given_back(tmp_path, printer, tty, monkeypatch):
    doc, data = jars(tmp_path, 3, seq=True)
    real = steps.run

    def meanwhile(labels, every, send, st):  # another job takes a number while this one waits
        from bobina import fileio

        fileio.locked_update(tmp_path / "state" / "counters.json", lambda s: s.update(jar=s["jar"] + 5))
        return real(labels, every, send, st)

    monkeypatch.setattr(steps, "run", meanwhile)
    tty("p", "q")
    assert run("print", doc, "--data", data) == cli.OK
    assert counters(tmp_path)["jar"] == 9  # 4 + 5: the gap stays


# --------------------------------------------------------------- never stopping


def test_no_step_and_config_off_print_at_once(tmp_path, printer, tty, capsys):
    doc, data = jars(tmp_path, 3)
    tty("p")
    assert run("print", doc, "--data", data, "--no-step") == cli.OK
    assert printer.sends() == 1
    assert run("config", "step", "off") == cli.OK
    assert "step off" in capsys.readouterr().out
    tty("p")
    assert run("print", doc, "--data", data) == cli.OK
    assert printer.sends() == 2
    tty("p", "", "")
    assert run("print", doc, "--data", data, "--step") == cli.OK  # one print stops again
    assert printer.sends() == 5


def test_yes_never_waits_unless_step_is_written(tmp_path, printer, tty):
    doc, data = jars(tmp_path, 3)
    tty()
    assert run("print", doc, "--data", data, "--yes") == cli.OK
    assert printer.sends() == 1
    tty("", "")
    assert run("print", doc, "--data", data, "--yes", "--step") == cli.OK
    assert printer.sends() == 4


def test_no_terminal_prints_at_once_and_step_says_why(tmp_path, printer, monkeypatch, capsys):
    monkeypatch.setattr(common, "open_tty", lambda: None)
    monkeypatch.setattr(steps, "open_tty", lambda: None)
    doc, data = jars(tmp_path, 3)
    assert run("print", doc, "--data", data, "--yes") == cli.OK
    assert "P106" not in capsys.readouterr().err
    assert run("print", doc, "--data", data, "--yes", "--step") == cli.OK
    assert "P106" in capsys.readouterr().err
    assert printer.sends() == 2


def test_compact_prints_at_once_with_a_note(tmp_path, printer, tty):
    doc, data = jars(tmp_path, 3)
    t = tty("p")
    assert run("print", doc, "--data", data, "--compact") == cli.OK
    assert printer.sends() == 1 and "P105" in t.text


def test_file_printer_and_output_never_stop(tmp_path, tty):
    doc, data = jars(tmp_path, 3)
    assert run("printer", "add", "test", "--path", str(tmp_path / "out.bin"), "--quiet") == cli.OK
    t = tty("p")
    assert run("print", doc, "--data", data) == cli.OK
    assert "tear it off" not in t.text
    assert run("print", doc, "--data", data, "-o", str(tmp_path / "x.bin")) == cli.OK


def test_one_label_never_stops(tmp_path, printer, tty):
    t = tty("p")
    assert run("print", "Hello") == cli.OK
    assert printer.sends() == 1 and "tear it off" not in t.text


# --------------------------------------------------------------- --last, --again, history


def test_last_stops_too_and_keeps_only_what_printed(tmp_path, printer, tty):
    doc, data = jars(tmp_path, 3)
    tty("p", "q")
    assert run("print", doc, "--data", data) == cli.OK
    last = state.load_last()
    assert b"Jar 1" in last["data"] and b"Jar 2" not in last["data"]  # only what printed
    tty("p")
    assert run("print", "--last") == cli.OK  # one label kept: nothing to stop between
    tty("p", "a")
    assert run("print", doc, "--data", data) == cli.OK
    t = tty("p", "", "")
    assert run("print", "--last") == cli.OK
    assert " ✓ 1/3 printed" in t.text
    assert printer.sends() == 1 + 1 + 2 + 3


def test_again_stops_between_labels(tmp_path, printer, tty):
    doc, data = jars(tmp_path, 2)
    tty("p", "")
    assert run("print", doc, "--data", data) == cli.OK
    t = tty("p", "")
    assert run("print", "--again", "--data", data) == cli.OK
    assert " ✓ 1/2 printed" in t.text


def test_history_records_a_stopped_job(tmp_path, printer, tty):
    from bobina import history

    doc, data = jars(tmp_path, 3)
    tty("p", "q")
    assert run("print", doc, "--data", data) == cli.OK
    rec = history.load()[-1]
    assert rec["outcome"] == "stopped" and rec["labels_printed"] == 1


def test_config_step_shows_and_refuses_other_values(capsys):
    assert run("config", "step") == cli.OK
    assert "step on" in capsys.readouterr().out
    assert run("config", "step", "maybe") == cli.USAGE
    assert run("config", "step", "--json") == cli.OK
    assert json.loads(capsys.readouterr().out)["value"] is True


def test_step_larger_than_the_job_prints_it_at_once(tmp_path, printer, tty):
    doc, data = jars(tmp_path, 3)
    t = tty("p")
    assert run("print", doc, "--data", data, "--step", "5") == cli.OK
    assert printer.sends() == 1 and "stops after" not in t.text and "tear it off" not in t.text


# --------------------------------------------------------------- review fixes


def test_step_in_config_as_a_word_or_a_typo_never_stops_a_print(tmp_path, printer, tty, capsys):
    cfg = tmp_path / "config" / "config.toml"
    doc, data = jars(tmp_path, 3)
    cfg.write_text('step = "off"\n' + cfg.read_text())  # top level, before the [printers] table
    tty("p")
    assert run("print", doc, "--data", data) == cli.OK
    assert printer.sends() == 1
    cfg.write_text(cfg.read_text().replace('step = "off"', 'step = "maybe"'))
    tty("p", "", "")
    assert run("print", doc, "--data", data) == cli.OK  # taken as on, with a note
    assert printer.sends() == 4 and "is not on or off" in capsys.readouterr().err


def test_history_keeps_the_step_number_but_never_typed_text():
    from bobina import history

    assert history.redact(["print", "x", "--step", "3"]) == ["print", "text", "--step", "3"]
    assert history.redact(["print", "--step=2", "x"]) == ["print", "--step=2", "text"]
    assert history.redact(["print", "--step", "buy bread"]) == ["print", "--step", "text"]


def test_a_stopped_job_is_recorded_with_what_printed(tmp_path, printer, tty, capsys):
    from bobina import history

    doc, data = jars(tmp_path, 4, seq=True)
    tty("p", "", "q")
    assert run("print", doc, "--data", data) == cli.OK
    rec = history.load()[-1]
    assert rec["outcome"] == "stopped" and rec["labels"] == 4 and rec["labels_printed"] == 2
    assert rec["counters"] == {"jar": ["1", "2"]}
    assert history.stats(history.load())["printed_labels"] == 2
    assert run("history", "--outcome", "stopped") == cli.OK
    assert "stopped" in capsys.readouterr().out


def test_a_printer_that_fails_part_way_says_what_printed_and_how_to_go_on(tmp_path, tty, capsys):
    calls = tmp_path / "calls"
    script = f"n=$(cat {calls} 2>/dev/null || echo 0); n=$((n+1)); echo $n > {calls}; cat >/dev/null; [ $n -lt 3 ]"
    assert run("printer", "add", "loja", "--command", f"sh -c {shlex.quote(script)}", "--quiet") == cli.OK
    doc, data = jars(tmp_path, 5, seq=True)
    tty("p", "", "")
    assert run("print", doc, "--data", data) != cli.OK
    err = capsys.readouterr().err
    assert "1 error — 2 of 5 labels printed" in err and "3 not printed" in err and "--rows 3-5" in err
    assert counters(tmp_path)["jar"] == 3  # the command failed: label 3 never printed, its number went back


def test_again_and_last_with_yes_and_step_say_why_they_do_not_stop(tmp_path, printer, monkeypatch, capsys):
    monkeypatch.setattr(common, "open_tty", lambda: None)
    monkeypatch.setattr(steps, "open_tty", lambda: None)
    doc, data = jars(tmp_path, 3)
    assert run("print", doc, "--data", data, "--yes") == cli.OK
    capsys.readouterr()
    assert run("print", "--again", "--data", data, "--yes", "--step") == cli.OK
    assert "P106" in capsys.readouterr().err
    assert run("print", "--last", "--yes", "--step") == cli.OK
    assert "P106" in capsys.readouterr().err


def test_a_piece_that_failed_part_way_counts_as_printed_once(tty):
    from types import SimpleNamespace

    labels = [SimpleNamespace(data=b"x", length_mm=10.0, rows=[]) for _ in range(5)]
    sent = []

    def send(data, mm):
        if len(sent) == 2:
            e = common.Fail(cli.UNREACHABLE, "link failed")
            e.partial = True
            raise e
        sent.append(data)

    tty("", "")
    st = steps.Run(5)
    with pytest.raises(common.Fail):
        steps.run(labels, 1, send, st)
    assert st.printed == {0, 1, 2} and st.next == 3
    assert steps.summary(st).startswith("stopped: 3 of 5 labels printed, 2 not printed")


# --------------------------------------------------------------- devex review


def test_p_at_the_pause_prints_the_next_one(tmp_path, printer, tty):
    doc, data = jars(tmp_path, 2)
    tty("p", "p")
    assert run("print", doc, "--data", data) == cli.OK
    assert printer.sends() == 2


def test_stop_without_an_option_for_the_rest_says_which_labels(tmp_path, printer, tty, capsys):
    doc, data = jars(tmp_path, 2)
    tty("p", "q")
    assert run("print", doc, "--data", data, "--then", doc, "--data", data) == cli.OK
    assert "not printed: labels 2-4 of this job" in capsys.readouterr().err


def test_a_bad_step_number_names_step_not_the_hidden_option(capsys):
    with pytest.raises(SystemExit) as e:
        run("print", "x", "--step=0")
    assert e.value.code == cli.USAGE
    err = capsys.readouterr().err
    assert "argument --step:" in err and "--step-every" not in err


def test_history_shows_how_many_of_a_stopped_job_printed(tmp_path, printer, tty, capsys):
    doc, data = jars(tmp_path, 3)
    tty("p", "q")
    assert run("print", doc, "--data", data) == cli.OK
    capsys.readouterr()
    assert run("history") == cli.OK
    assert "1/3 lbl" in capsys.readouterr().out
    assert run("history", "show", "last") == cli.OK
    assert "1 of 3 printed" in capsys.readouterr().out


def test_last_pause_names_the_next_label(tmp_path, printer, tty):
    doc, data = jars(tmp_path, 2)
    tty("p", "")
    assert run("print", doc, "--data", data) == cli.OK
    t = tty("p", "")
    assert run("print", "--last") == cli.OK
    assert "next (2/2 · Jar 2)" in t.text


@pytest.mark.parametrize("bad", ["-1", "0", "abc", "1.5", "2,5"])
def test_a_step_that_is_not_a_count_says_so(bad, capsys):
    for argv in (
        ["print", "--step", bad, "Hello"],
        ["print", "Hello", "--step", bad],
        ["print", f"--step={bad}", "Hi"],
    ):
        with pytest.raises(SystemExit) as e:
            run(*argv)
        assert e.value.code == cli.USAGE
        assert f"argument --step: --step N: N is how many labels between stops (1 or more), got '{bad}'" in (
            capsys.readouterr().err
        )


def test_text_with_spaces_or_a_file_after_step_is_the_document(tmp_path):
    (tmp_path / "abc").write_text("# a file called abc\n")
    assert parsed("--step", "buy bread").target == ["buy bread"]
    assert parsed("--step", str(tmp_path / "abc")).target == [str(tmp_path / "abc")]
    assert parsed("--step", "@shelf").target == ["@shelf"]
