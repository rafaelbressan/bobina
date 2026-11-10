"""Two bobina commands at the same time: real processes, real files (counters, paper, history, library,
the printer). Before the locks, 20 prints of '#{{ seq.t }}' gave 100 labels with 51 distinct numbers."""

import json
import os
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor

import pytest

from bobina import fileio, history, library, paper
from bobina.nudges import Nudges
from bobina.templating import CounterStore

RUN = "import sys; from bobina.cli import main; sys.exit(main(sys.argv[1:]))"


def bobina(*argv, env=None, inp=None, timeout=120):
    return subprocess.run(
        [sys.executable, "-c", RUN, *argv],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        input=inp,
        timeout=timeout,
    )


@pytest.fixture
def sink(isolated):
    """A printer whose 'transport' is a command that logs BEGIN, waits, then END: overlapping jobs show up as
    BEGIN BEGIN in the log."""
    log = isolated / "printer.log"
    script = isolated / "sink.py"
    script.write_text(
        textwrap.dedent(f"""
        import sys, time
        data = sys.stdin.buffer.read()
        with open({str(log)!r}, "a") as f:
            f.write("BEGIN\\n"); f.flush(); time.sleep(0.15)
            f.write(f"END {{len(data)}}\\n")
        """)
    )
    cfg = isolated / "config"
    cfg.mkdir(exist_ok=True)
    (cfg / "config.toml").write_text(
        f'default_printer = "sink"\n\n[printers.sink]\ntransport = "command"\n'
        f'command = "{sys.executable} {script}"\nprofile = "mtp-ii-58"\n'
    )
    doc = isolated / "n.bob.md"
    doc.write_text("#{{ seq.t }}\n")
    return log, doc


def test_parallel_prints_never_repeat_a_number_and_never_overlap_on_the_printer(sink, isolated):
    log, doc = sink
    assert bobina("paper", "new", "15m").returncode == 0
    jobs, per_job = 8, 5
    with ThreadPoolExecutor(jobs) as ex:
        runs = list(ex.map(lambda _: bobina("print", "--yes", "--quiet", str(doc), "--repeat", str(per_job)),
                           range(jobs)))  # fmt: skip
    assert all(r.returncode == 0 for r in runs), [r.stderr for r in runs if r.returncode]
    counters = json.loads((isolated / "state" / "counters.json").read_text())
    assert counters == {"t": 1 + jobs * per_job}
    numbers = [n for rec in history.load() for n in rec["counters"]["t"]]
    assert sorted(map(int, numbers)) == list(range(1, 1 + jobs * per_job))  # each number printed once
    lines = log.read_text().splitlines()
    assert len(lines) == 2 * jobs  # one job at a time: BEGIN END BEGIN END …, never BEGIN BEGIN
    assert all(a == "BEGIN" and b.startswith("END") for a, b in zip(lines[::2], lines[1::2], strict=True))
    assert paper.get("sink")["prints"] == jobs  # the odometer counted every print
    assert len(history.load()) == jobs


def test_dry_run_and_preview_do_not_take_numbers(sink, isolated):
    _, doc = sink
    assert bobina("print", "--dry-run", str(doc), "--repeat", "3").returncode == 0
    assert bobina("preview", str(doc), "-o", str(isolated / "p.png")).returncode == 0
    assert not (isolated / "state" / "counters.json").exists()


def test_a_job_that_is_not_printed_gives_its_numbers_back(sink, isolated):
    _, doc = sink
    r = bobina("print", str(doc), "--repeat", "3")  # no terminal for the confirmation: refused (E107)
    assert r.returncode != 0 and "E107" in r.stderr
    assert json.loads((isolated / "state" / "counters.json").read_text()) == {}
    assert bobina("print", "--yes", "--quiet", str(doc)).returncode == 0
    assert history.load()[-1]["counters"] == {"t": ["1"]}  # the refused job's 1, 2, 3 came back


def test_numbers_taken_by_another_job_meanwhile_stay_skipped(isolated):
    path = isolated / "state" / "counters.json"
    a = CounterStore(None, Nudges(), reserve=True)
    assert a._next_values("t", 2) == [1, 2]
    b = CounterStore(None, Nudges(), reserve=True)
    assert b._next_values("t", 1) == [3]
    a.release()  # 1-2 cannot come back: 3 was printed after them
    assert json.loads(path.read_text()) == {"t": 4}
    b.release()  # 3 was the last: it comes back
    assert json.loads(path.read_text()) == {"t": 3}


def test_interleaved_reservations_are_never_given_back(isolated):
    path = isolated / "state" / "counters.json"
    a = CounterStore(None, Nudges(), reserve=True)
    b = CounterStore(None, Nudges(), reserve=True)
    assert a._next_values("t", 1) == [1]
    assert b._next_values("t", 1) == [2]
    assert a._next_values("t", 1) == [3]  # a's numbers are 1 and 3; b holds 2
    a.release()
    assert json.loads(path.read_text()) == {"t": 4}  # rolling back to 1 would hand out 2 again


def test_wrap_and_stop_still_work_when_reserving(isolated):
    decl = {"t": {"start": 1, "stop": 3, "wrap": True}}
    s = CounterStore(dict(decl), Nudges(), reserve=True)
    assert s._next_values("t", 5) == [1, 2, 3, 1, 2]
    s.commit()
    assert CounterStore(dict(decl), Nudges())._next_values("t", 2) == [3, 1]


def test_a_damaged_counters_file_is_an_error_and_is_kept(sink, isolated):
    _, doc = sink
    path = isolated / "state" / "counters.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"t": 4')  # cut in the middle
    r = bobina("print", "--yes", str(doc))
    assert r.returncode != 0 and "E209" in r.stderr and "counters.json" in r.stderr
    assert path.read_text() == '{"t": 4'  # not replaced by a fresh numbering
    assert bobina("preview", str(doc), "-o", str(isolated / "p.png")).returncode != 0


def test_a_damaged_paper_file_does_not_fail_a_finished_print(sink, isolated):
    log, doc = sink
    (isolated / "state").mkdir(parents=True, exist_ok=True)
    (isolated / "state" / "paper.json").write_text("{oops")
    r = bobina("print", "--yes", str(doc))
    assert r.returncode == 0 and "paper not counted" in r.stderr
    assert "END" in log.read_text()
    assert json.loads((isolated / "state" / "counters.json").read_text()) == {"t": 2}  # printed: spent


def test_paper_counts_every_parallel_print(isolated):
    paper.new_roll("a", 15000)
    paper.new_roll("b", 15000)
    code = "from bobina import paper\nfor _ in range(25): paper.add('a', 10)"
    procs = [subprocess.Popen([sys.executable, "-c", code], env=os.environ.copy()) for _ in range(4)]
    assert all(p.wait(60) == 0 for p in procs)
    assert paper.get("a")["prints"] == 100 and paper.get("a")["used_mm"] == 1000
    assert paper.get("b") is not None  # the other printer's roll survived


def test_history_keeps_every_record_while_trimming(isolated):
    cfg = isolated / "config"
    cfg.mkdir(exist_ok=True)
    (cfg / "config.toml").write_text("history_max = 20\n")
    code = (
        "import sys\nfrom bobina import history\n"
        "for i in range(40):\n"
        "    r = history.Recorder(['print', 'w' + sys.argv[1] + '-' + str(i)])\n"
        "    assert r.finish('printed', 0) is not None\n"
    )
    procs = [subprocess.Popen([sys.executable, "-c", code, str(w)], stderr=subprocess.PIPE) for w in range(4)]
    outs = [p.communicate(timeout=120)[1] for p in procs]
    assert all(p.returncode == 0 for p in procs) and not any(b"not recorded" in o for o in outs), outs
    rows = history.load()
    assert 20 <= len(rows) <= 30 and history.skipped == 0
    assert not list((isolated / "state").glob("*.tmp"))


def test_two_library_adds_at_once_keep_both(isolated):
    code = "import sys\nfrom bobina import library\nlibrary.add(sys.argv[1], 'x', '/tmp', 'f.bob.md')"
    names = [f"etq{i}" for i in range(6)]
    procs = [subprocess.Popen([sys.executable, "-c", code, n]) for n in names]
    assert all(p.wait(60) == 0 for p in procs)
    assert sorted(library.entries()) == names
    assert all(e["base"] == "/tmp" for e in library.entries().values())


def test_a_damaged_library_index_is_reported_not_wiped(isolated):
    library.add("pote", "x", "/tmp", "f.bob.md")
    (library.folder() / "index.json").write_text("[")
    with pytest.raises(library.LibraryError, match="damaged"):
        library.add("outro", "y", "/tmp", "g.bob.md")
    assert (library.folder() / "index.json").read_text() == "["


def test_status_while_a_job_prints_says_busy(sink, isolated):
    from bobina import transport

    pr = {"transport": "bluetooth", "address": "printer-under-test", "channel": 1}
    with transport.printer_lock(pr), pytest.raises(transport.PrinterBusy), transport.printer_lock(pr, timeout=0.2):
        pass
    with transport.printer_lock(pr, timeout=0.2):  # free again
        pass


def test_a_second_job_waits_for_the_printer_and_says_so(sink, isolated):
    from bobina import transport

    _, doc = sink
    pr = {"transport": "command", "command": f"{sys.executable} {isolated / 'sink.py'}"}
    with transport.printer_lock(pr):
        p = subprocess.Popen(
            [sys.executable, "-c", RUN, "print", "--yes", "--quiet", str(doc)], stderr=subprocess.PIPE, text=True
        )
        import time

        time.sleep(1.5)
        assert p.poll() is None  # waiting, not fighting for the link
    _, errout = p.communicate(timeout=60)
    assert p.returncode == 0 and "waiting for the printer" in errout


def test_config_and_last_job_are_written_whole(isolated):
    from bobina import config, state

    config.save({"default_printer": "x", "printers": {"x": {"transport": "file", "path": "/dev/null"}}})
    assert config.load()["default_printer"] == "x"
    assert not list((isolated / "config").glob(".*tmp"))
    (isolated / "config" / "config.toml").write_text("default_printer = ")
    with pytest.raises(fileio.StateError, match="not valid TOML"):
        config.load()
    from PIL import Image

    img = Image.new("1", (8, 8), 1)
    for k in range(4):
        state.save_last(f"job {k}", "/tmp", "f.bob.md", bytes([k]), img, {"length_mm": 1})
    last = state.load_last()
    assert last["source"] == "job 3" and last["data"] == bytes([3])
    assert len([d for d in state.last_dir().iterdir() if d.is_dir()]) == 2
