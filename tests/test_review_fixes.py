"""Findings of the code review of 07/11 (concurrency, memory and hangs blocks), one test each."""

import json
import os
import stat
import sys
import threading

import pytest

from bobina import fileio, sources, state
from bobina.cli import main


@pytest.fixture
def printer(isolated):
    out = isolated / "out.bin"
    cfg = isolated / "config"
    cfg.mkdir(exist_ok=True)
    (cfg / "config.toml").write_text(f'default_printer = "f"\n[printers.f]\ntransport = "file"\npath = "{out}"\n')
    doc = isolated / "n.bob.md"
    doc.write_text("#{{ seq.t }}\n")
    return out, doc


def counters(isolated):
    return json.loads((isolated / "state" / "counters.json").read_text())


def test_ctrl_c_while_sending_keeps_the_numbers_spent(printer, isolated, monkeypatch):
    from bobina import transport

    _, doc = printer

    def interrupted(data, printer, profile, log, precheck, length_mm, progress):
        progress["started"] = True
        raise KeyboardInterrupt  # halfway through the bytes

    monkeypatch.setattr(transport, "_send", interrupted)
    assert main(["print", "--yes", "--quiet", str(doc), "--repeat", "3"]) == 130
    assert counters(isolated) == {"t": 4}  # 1-3 may be on paper: never handed out again


def test_ctrl_c_before_any_byte_gives_the_numbers_back(printer, isolated, monkeypatch):
    from bobina import transport

    _, doc = printer

    def interrupted(*a, **k):
        raise KeyboardInterrupt  # still connecting / waiting for the printer

    monkeypatch.setattr(transport, "_send", interrupted)
    assert main(["print", "--yes", "--quiet", str(doc), "--repeat", "3"]) == 130
    assert counters(isolated) == {}


def test_output_to_a_pipe_nobody_reads_fails_at_once(printer, isolated):
    _, doc = printer
    fifo = isolated / "pipe.bin"
    os.mkfifo(fifo)
    assert main(["print", str(doc), "-o", str(fifo), "--force", "--quiet"]) != 0


def test_url_images_are_left_to_the_download_cache(isolated):
    from bobina import layout
    from bobina.model import Attrs

    assert layout._image_key("https://exemplo.org/a.png", str(isolated), Attrs(set(), {}), ()) is None


def test_a_send_that_fails_before_any_byte_gives_the_numbers_back(printer, isolated):
    _, doc = printer
    (isolated / "config" / "config.toml").write_text('default_printer = "nope"\n')  # E401: nothing sent
    assert main(["print", "--yes", "--quiet", str(doc), "--repeat", "3"]) != 0
    assert counters(isolated) == {}


def test_again_dry_run_never_sends(printer, isolated):
    out, doc = printer
    assert main(["print", "--yes", "--quiet", str(doc)]) == 0
    size = out.stat().st_size
    assert main(["print", "--again", "--dry-run", "--yes"]) == 0
    assert out.stat().st_size == size and counters(isolated) == {"t": 2}


def test_output_to_a_device_a_symlink_and_with_normal_permissions(printer, isolated):
    _, doc = printer
    assert main(["print", str(doc), "-o", "/dev/null", "--force", "--quiet"]) == 0  # a device: written straight
    real = isolated / "real.bin"
    real.write_bytes(b"old")
    link = isolated / "link.bin"
    link.symlink_to(real)
    assert main(["print", str(doc), "-o", str(link), "--force", "--quiet"]) == 0
    assert link.is_symlink() and real.read_bytes() != b"old"  # the target was replaced, the link kept
    fresh = isolated / "fresh.bin"
    assert main(["print", str(doc), "-o", str(fresh), "--quiet"]) == 0
    mask = os.umask(0)
    os.umask(mask)
    assert stat.S_IMODE(fresh.stat().st_mode) == 0o666 & ~mask  # not mkstemp's 0600


def test_a_damaged_counters_file_is_e209_on_every_path(printer, isolated, capsys):
    _, doc = printer
    assert main(["print", "--yes", "--quiet", str(doc)]) == 0
    (isolated / "state" / "counters.json").write_text("{")
    capsys.readouterr()
    assert main(["print", "--again", "--dry-run"]) != 0  # this path built through _build's ValueError handler
    errout = capsys.readouterr().err
    assert "E209" in errout and "E501" not in errout


def test_download_errors_keep_their_reason(monkeypatch):
    class Resp:
        status = 301

        def getheader(self, *_):
            return None

    class Conn:
        sock = None

        def __init__(self, *a):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return Resp()

        def close(self):
            pass

    monkeypatch.setattr(sources, "resolve_public", lambda *a, **k: "203.0.113.9")
    monkeypatch.setattr(sources, "_PinnedHTTPS", Conn)
    sources._CACHE.clear()
    with pytest.raises(sources.ImageError) as e:
        sources.fetch("https://exemplo.org/logo.png")
    assert e.value.code == "I106" and "redirects" in str(e.value) and e.value.hint == "use the final URL"


def test_the_deadline_flag_is_set_before_the_socket_is_cut():
    cut = threading.Event()
    seen = []

    class Sock:
        def shutdown(self, how):
            seen.append(cut.is_set())

    class Conn:
        sock = Sock()

    sources._cut(Conn(), cut)
    assert seen == [True]


def test_last_points_at_the_newest_job_when_saves_run_at_once(isolated):
    import subprocess

    code = (
        "import sys\nfrom PIL import Image\nfrom bobina import state\n"
        "state.save_last('job '+sys.argv[1], '/tmp', 'f', sys.argv[1].encode(), Image.new('1',(8,8),1), {})"
    )
    procs = [subprocess.Popen([sys.executable, "-c", code, str(k)]) for k in range(6)]
    assert all(p.wait(60) == 0 for p in procs)
    last = state.load_last()
    assert last is not None and last["source"] == "job " + last["data"].decode()
    folders = sorted(d.name for d in state.last_dir().iterdir() if d.is_dir())
    assert json.loads((isolated / "state" / "last.json").read_text())["job"] == folders[-1]


def test_pages_pdf_is_valid_and_copies_share_one_image(printer, isolated):
    pdfium = pytest.importorskip("pypdfium2")
    _, doc = printer
    out = isolated / "p.pdf"
    assert main(["preview", str(doc), "--repeat", "2", "--copies", "3", "--pages", "-o", str(out), "--quiet"]) == 0
    pdf = pdfium.PdfDocument(str(out))
    assert len(pdf) == 6
    w, h = pdf[0].get_size()
    assert abs(w - 384 * 72 / 203) < 0.5  # 1:1 on paper: 48 mm wide
    assert out.read_bytes().count(b"/Subtype /Image") == 2  # 2 distinct labels, 6 pages
    assert not list(isolated.glob(".p.pdf.*"))


def test_state_error_is_not_a_value_error():
    assert not issubclass(fileio.StateError, ValueError)


def test_last_job_survives_without_a_pointer_from_an_older_bobina(isolated):
    from PIL import Image

    old = state.last_dir()
    old.mkdir(parents=True)
    (old / "meta.json").write_text(json.dumps({"base_dir": "/tmp", "origin": "f", "stats": {}, "printed_at": "x"}))
    (old / "source.bob.md").write_text("old")
    (old / "job.bin").write_bytes(b"o")
    Image.new("1", (8, 8), 1).save(old / "preview.png")
    assert state.load_last()["source"] == "old"


def test_rules_and_table_rules_are_not_drawn_as_cut_lines(isolated, capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    doc = isolated / "r.bob.md"
    doc.write_text("# A\n\n---\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert main(["view", str(doc)]) == 0
    assert "✂" not in capsys.readouterr().out


def test_huge_percent_values_do_not_crash():
    from bobina import datasource

    class Cell:
        value, number_format = 1e30, "0%"

    assert datasource._xcell(Cell()).endswith("%")


def test_outcome_of_calibrate_and_mode_errors():
    from bobina.cli import common

    common.set_command(["calibrate", "tear"])
    assert common.stopped() == "nothing printed"
    common.set_command(["mode", "escpos"])
    assert common.stopped().startswith("nothing sent")
    common.set_command(["print"])


def test_loose_word_suggestion_keeps_punctuation_in_the_text():
    from bobina.cli.common import quote_loose

    assert quote_loose(["hello", "world."]) == '"hello world."'
    assert quote_loose(["a.bob.md", "10:30", "R$5.00"]) == 'a.bob.md "10:30 R$5.00"'
