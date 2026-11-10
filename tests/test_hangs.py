"""Places that could wait forever: a terminal nobody answers, stdin, DNS, a dripping download, an offline device."""

import os
import socket
import subprocess
import sys
import threading
import time

import pytest

from bobina import sources, transport

RUN = "import sys; from bobina.cli import main; sys.exit(main(sys.argv[1:]))"


def bobina(*argv, env=None, inp=None, timeout=30):
    return subprocess.run(
        [sys.executable, "-c", RUN, *argv], capture_output=True, text=True, input=inp, timeout=timeout,
        env={**os.environ, **(env or {})},
    )  # fmt: skip


def test_noninteractive_never_asks(isolated):
    doc = isolated / "f.bob.md"
    doc.write_text("---\nfields:\n  nome: {required: true}\n---\n# {{ nome }}\n")
    r = bobina("print", "--ask", "--dry-run", str(doc), env={"BOBINA_NONINTERACTIVE": "1"})
    assert r.returncode != 0 and "E107" in r.stderr
    r = bobina("print", str(doc), "--set", "nome=x", env={"BOBINA_NONINTERACTIVE": "1"})
    assert "E107" in r.stderr  # the confirmation is refused at once, not waited for


def test_stdin_has_a_size_limit(isolated, monkeypatch):
    from bobina.cli import common

    monkeypatch.setattr(common, "STDIN_MAX", 100)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("# x\n" * 100))
    from bobina.cli import main

    assert main(["check", "-"]) != 0


def test_dns_that_never_answers_gives_up(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: release.wait(10))
    t0 = time.monotonic()
    with pytest.raises(sources.ImageError, match="no answer"):
        sources._getaddrinfo("example.org", 443, 0.3)
    assert time.monotonic() - t0 < 2
    release.set()  # the abandoned thread ends (no stray threads for later fork-based tests)


def test_the_download_deadline_wakes_a_blocked_read():
    a, b = socket.socketpair()

    class Conn:
        sock = a

    timer = threading.Timer(0.3, sources._cut, [Conn()])
    timer.start()
    t0 = time.monotonic()
    assert a.recv(10) == b""  # the server sends nothing; the deadline ends the wait
    assert time.monotonic() - t0 < 2
    a.close()
    b.close()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs a FIFO")
def test_a_device_that_never_takes_the_bytes_fails_in_time(isolated):
    fifo = isolated / "lp0"
    os.mkfifo(fifo)  # nobody reads it: open() blocks, like an offline printer
    t0 = time.monotonic()
    with pytest.raises(transport.SendFailed, match="did not open") as e:
        transport._write_device(str(fifo), b"x", 0.3)
    assert e.value.sent == 0  # never opened: nothing reached the printer, no paper counted
    assert time.monotonic() - t0 < 2
    with open(fifo, "rb") as f:  # let the abandoned writer finish
        f.read()


def test_bluetoothctl_that_hangs_is_bounded(monkeypatch):
    calls = []

    def fake(cmd, **kw):
        calls.append(kw.get("timeout"))
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(subprocess, "run", fake)
    transport._bluetoothctl("disconnect", "printer", 10)  # no exception: best effort
    assert calls == [10]
