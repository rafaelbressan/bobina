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


def test_a_failed_command_says_the_printer_its_exit_code_its_stderr_and_what_to_do(capsys):
    printer(command="sh -c 'echo boom >&2; exit 3'")
    assert cli.main(["print", "hello", "--yes", "--printer", "p"]) == cli.UNREACHABLE
    err = capsys.readouterr().err
    assert "[E402] printer 'p': the command exited with 3: boom" in err
    assert "→ is the printer behind it on? Run it by hand to see why: sh -c 'echo boom >&2; exit 3'" in err
    assert history.load()[-1]["outcome"] == "failed"


def test_the_failed_command_in_json_has_message_and_suggestion(capsys):
    import json

    printer(command="sh -c 'echo boom >&2; exit 3'")
    assert cli.main(["print", "hello", "--yes", "--printer", "p", "--problems", "json"]) == cli.UNREACHABLE
    (problem,) = json.loads(capsys.readouterr().err.strip().splitlines()[-1])["problems"]
    assert problem["code"] == "E402" and "exited with 3: boom" in problem["message"]
    assert problem["suggestion"].startswith("is the printer behind it on?")


def test_only_the_end_of_stderr_is_shown_cleaned_and_bounded():
    noise = "".join(f"\x1b[31mline {i} " + "x" * 300 + "\x1b[0m\r\n" for i in range(50))
    tail = transport.stderr_tail(noise.encode() + b"\x07last words\n\n")
    assert tail.count(" | ") == 2 and tail.endswith(" | last words")
    assert tail.startswith("line 48 ") and "line 47" not in tail
    assert "\x1b" not in tail and "\x07" not in tail and len(tail) <= 3 * transport.STDERR_CHARS + 6


def test_ssh_failures_say_which_side_failed():
    cmd = "ssh -p 2222 -i ~/.ssh/key me@tower bobina send --yes -"
    down = transport.command_failed(cmd, 255, b"ssh: connect to host tower port 2222: No route to host\n")
    assert str(down) == "ssh could not reach tower (exit 255): ssh: connect to host tower port 2222: No route to host"
    assert down.hint == "is tower on and on the network? Try it by hand: ssh -p 2222 -i ~/.ssh/key me@tower true"
    gone = transport.command_failed(cmd, 127, b"bash: line 1: bobina: command not found\n")
    assert str(gone).startswith("bobina was not found on tower (exit 127)") and "command -v bobina" in gone.hint
    off = transport.command_failed(cmd, 4, b"x [E402] printer unreachable: AA did not answer\n")
    assert str(off) == "the command on tower exited with 4: x [E402] printer unreachable: AA did not answer"
    assert off.hint.endswith("ssh -p 2222 -i ~/.ssh/key me@tower bobina status asks it")
    quiet = transport.command_failed("sh -c 'kill -9 $$'", -9, b"")
    assert str(quiet) == "the command was stopped by signal 9: nothing on stderr"


def test_ssh_options_with_values_are_not_the_host():
    def host(cmd):
        return (transport.ssh_target(cmd.split()) or (None,))[0]

    assert host("ssh -p 22 -o ConnectTimeout=5 tower x") == "tower"
    assert host("ssh -p22 -tt tower x") == host("ssh -vp 22 tower") == host("ssh -- tower") == "tower"
    assert host("ssh -p 22") is None and host("nc tower 9100") is None


def test_command_timeout_shows_what_it_said(tmp_path, capsys):
    printer(command="sh -c 'echo still connecting >&2; sleep 5'", timeout=0.5)
    assert cli.main(["print", "x", "--yes", "--printer", "p"]) == cli.UNREACHABLE
    err = capsys.readouterr().err
    assert "printer 'p': the command did not finish in 0.5 s: still connecting" in err
    assert "raise timeout = SECONDS" in err


def test_a_device_that_is_not_there_says_to_plug_it_in(tmp_path, capsys):
    cli.main(["printer", "add", "usb", "--path", str(tmp_path / "no-dir" / "lp0")])
    assert cli.main(["print", "x", "--yes", "--printer", "usb"]) == cli.UNREACHABLE
    err = capsys.readouterr().err
    assert "[E402] printer 'usb': cannot write to" in err and "→ is the printer plugged in and on?" in err


def test_a_bluetooth_printer_that_does_not_answer_says_so_with_its_name(monkeypatch, capsys):
    cli.main(["printer", "add", "mtp", "AA:BB:CC:DD:EE:FF"])

    def down(mac, channel, timeout=15):
        raise OSError(112, "Host is down")

    monkeypatch.setattr(transport, "_bt_connect", down)
    monkeypatch.setattr(transport, "_bluetoothctl", lambda *a: None)  # never the real Bluetooth stack
    assert cli.main(["print", "oi", "--yes", "--printer", "mtp"]) == cli.UNREACHABLE
    err = capsys.readouterr().err
    assert "[E402] printer 'mtp': AA:BB:CC:DD:EE:FF did not answer: [Errno 112] Host is down" in err
    assert "→ is it on (steady yellow LED) and in range?" in err
