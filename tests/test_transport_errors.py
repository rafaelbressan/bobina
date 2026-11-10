"""Sending failures are coded errors (E402), recorded in the history; a job cut in the middle uses its
seq numbers so they are not printed twice (decided 07/11)."""

import sys

from bobina import cli, config, history, transport


def printer(**kw):
    cfg = config.load()
    cfg.setdefault("printers", {})["p"] = {"transport": "command", **kw}
    cfg["default_printer"] = "p"
    config.save(cfg)


def test_missing_command_is_e402_and_recorded(tmp_path, capsys):
    printer(command="no-such-binary-xyz")
    assert cli.main(["print", "hello", "--yes", "--printer", "p"]) == cli.UNREACHABLE
    assert "[E402]" in capsys.readouterr().err
    assert history.load()[-1]["outcome"] == "failed"


def test_command_timeout(tmp_path, capsys):
    printer(command=f"{sys.executable} -c 'import time; time.sleep(5)'", timeout=0.5)
    assert cli.main(["print", "x", "--yes", "--printer", "p"]) == cli.UNREACHABLE
    assert "did not finish" in capsys.readouterr().err


def test_partial_send_consumes_the_numbers(tmp_path, monkeypatch, capsys):
    printer(command="true")

    def cut(data, *a, **k):
        raise transport.SendFailed("link lost after 10 of 100 bytes", 10)

    real_send = transport.send
    monkeypatch.setattr(transport, "send", cut)
    assert cli.main(["print", "#{{ seq.t }}", "--yes", "--printer", "p"]) == cli.UNREACHABLE
    err = capsys.readouterr().err
    assert "part of the job may have printed" in err and "will not repeat" in err
    monkeypatch.setattr(transport, "send", real_send)  # not undo(): that would also drop the isolated dirs
    out = tmp_path / "o.bin"
    cli.main(["print", "#{{ seq.t }}", "-o", str(out)])
    assert b"#2" in out.read_bytes()  # 1 was used by the cut job


def test_a_failed_send_says_the_printer_has_no_paper(monkeypatch, capsys):
    from bobina import cli, transport
    from bobina.cli import common

    cli.main(["printer", "add", "mtp", "AA:BB:CC:DD:EE:FF"])

    def fail(*a, **k):
        raise transport.SendFailed("the Bluetooth link failed after 20480 of 20634 bytes (timed out)", 20480)

    monkeypatch.setattr(transport, "send", fail)
    monkeypatch.setattr(common, "printer_status", lambda pr, **k: {"answered": True, "paper_out": True})
    assert cli.main(["print", "oi", "--yes"]) == cli.UNREACHABLE
    e = capsys.readouterr().err
    assert "no paper" in e and "cover" in e and "bobina paper new" in e


def test_no_bluetooth_sockets_says_what_to_do_on_each_system(monkeypatch):
    """uv's and Homebrew's Pythons have no AF_BLUETOOTH: on Linux the fix is the system Python; elsewhere there are
    no RFCOMM sockets at all, so the way out is a command or device printer."""
    import socket

    import pytest

    monkeypatch.delattr(socket, "AF_BLUETOOTH", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(transport.PrinterUnreachable, match=r"--python /usr/bin/python3"):
        transport._bt_connect("AA:BB:CC:DD:EE:FF", 1)
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(transport.PrinterUnreachable, match=r"need Linux.*--command.*--path"):
        transport._bt_connect("AA:BB:CC:DD:EE:FF", 1)
