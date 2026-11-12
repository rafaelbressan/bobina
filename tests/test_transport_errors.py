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
    assert "→ is the printer behind it on? Try it with an empty job: printf '' | sh -c 'echo boom >&2; exit 3'" in err
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


SSH = "ssh -p 2222 -i ~/.ssh/key me@tower ~/.local/bin/bobina send --yes -"


def test_ssh_255_says_why_from_what_ssh_said():
    cases = {
        b"ssh: connect to host tower port 2222: No route to host": "tower did not answer: is it on and on the network?"
        " Try: ssh -p 2222 -i ~/.ssh/key me@tower true",
        b"me@tower: Permission denied (publickey).": "ssh reached tower but was not let in",
        b"Host key verification failed.": "tower's host key is not known here, or changed",
        b"ssh: Could not resolve hostname tower: Name or service not known": "the name tower is not known here",
        b"ssh: connect to host tower port 2222: Connection refused": "no ssh server listens there",
        b"ssh: connect to host tower port 2222: Connection timed out": "tower did not answer",
        b"kex_exchange_identification: read: Connection reset by peer": "is tower on and on the network? Try:",
    }
    for said, hint in cases.items():
        e = transport.command_failed(SSH, 255, said + b"\n")
        assert str(e) == f"ssh to tower failed (exit 255): {said.decode()}" and hint in e.hint, said


def test_ssh_127_does_not_guess_the_program_and_uses_the_remote_path_given():
    e = transport.command_failed(SSH, 127, b"bash: line 1: ~/.local/bin/bobina: No such file or directory\n")
    assert (
        str(e)
        == "a program was not found on tower (exit 127): bash: line 1: ~/.local/bin/bobina: No such file or directory"
    )
    assert e.hint.endswith("Try: ssh -p 2222 -i ~/.ssh/key me@tower '~/.local/bin/bobina --version'")  # ~ over there
    other = transport.command_failed("ssh tower 'lp -d label'", 127, b"sh: lp: not found\n")
    assert str(other).startswith("a program was not found on tower (exit 127): sh: lp: not found")
    assert "bobina" not in other.hint and "installed on tower" in other.hint


def test_a_failure_on_the_other_side_points_to_the_remote_bobina_as_given():
    off = transport.command_failed(SSH, 4, b"x [E402] printer unreachable: AA did not answer\n")
    assert str(off) == "the command on tower exited with 4: x [E402] printer unreachable: AA did not answer"
    assert off.hint.endswith("ssh -p 2222 -i ~/.ssh/key me@tower '~/.local/bin/bobina status' asks it")
    other = transport.command_failed("ssh tower lp -d label", 1, b"lp: printer not found\n")
    assert other.hint.endswith("printf '' | ssh tower lp -d label")  # never a command left waiting on stdin


def test_a_signal_is_said_as_stopped_here():
    e = transport.command_failed("ssh tower bobina send --yes -", -9, b"")
    assert str(e) == "the command was stopped on this machine by SIGKILL: nothing on stderr"
    assert "tower" not in str(e)


def test_run_by_hand_suggestions_never_wait_on_stdin():
    for code in (1, 3, 127):
        hint = transport.command_failed("nc printer.local 9100", code, b"x").hint
        assert "printf '' | nc printer.local 9100" in hint
    assert "printf '' | COMMAND" in transport.command_failed("x " * 80, 1, b"").hint


def test_a_file_printer_in_a_folder_that_is_not_there_says_to_check_the_path(tmp_path, capsys):
    cli.main(["printer", "add", "out", "--path", str(tmp_path / "no-dir" / "job.bin")])
    assert cli.main(["print", "x", "--yes", "--printer", "out"]) == cli.UNREACHABLE
    err = capsys.readouterr().err
    assert "[E402] printer 'out': cannot write to" in err and "→ its folder does not exist" in err
    assert "plugged in" not in err


def test_device_hints_follow_the_error():
    import errno

    assert transport.device_hint("/dev/usb/lp0", errno.ENOENT).startswith("is the printer plugged in and on?")
    assert transport.device_hint("COM3", errno.EACCES).startswith("this user may not write to it")
    assert transport.device_hint("/tmp/out.bin", errno.ENOSPC).startswith("the disk is full")
    assert transport.device_hint("/tmp", errno.EISDIR).startswith("that is a folder")
    assert transport.device_hint("/dev/usb/lp0", errno.EIO).startswith("an input/output error")
    assert "plugged in" not in transport.device_hint("/tmp/out.bin", errno.EPERM)


def test_a_folder_as_printer_file_says_it_is_a_folder(tmp_path, capsys):
    cli.main(["printer", "add", "dir", "--path", str(tmp_path)])
    assert cli.main(["print", "x", "--yes", "--printer", "dir"]) == cli.UNREACHABLE
    assert "→ that is a folder" in capsys.readouterr().err


def test_a_write_that_fails_half_way_keeps_the_part_may_have_printed_warning(capsys):
    import os

    import pytest

    if not os.path.exists("/dev/full"):  # opens, then every write fails with ENOSPC (Linux)
        pytest.skip("no /dev/full here")
    cli.main(["printer", "add", "full", "--path", "/dev/full"])
    assert cli.main(["print", "x", "--yes", "--printer", "full"]) == cli.UNREACHABLE
    err = capsys.readouterr().err
    assert "[E402] printer 'full': cannot write to /dev/full" in err
    assert "part of the job may have printed" in err and "the disk is full" in err


def test_the_remote_status_keeps_the_options_that_pick_the_printer_there():
    import shlex

    def status(cmd):
        return transport.remote_bobina_command(shlex.split(cmd), "status")

    assert status("ssh pi@kiosk ~/.local/bin/bobina send --yes --printer goldensky -") == (
        "ssh pi@kiosk '~/.local/bin/bobina status --printer goldensky'"
    )
    assert status("ssh tower 'bobina send --yes --printer=gold --profile mtp-ii-58 -'") == (
        "ssh tower 'bobina status --printer=gold --profile mtp-ii-58'"
    )
    assert status("ssh tower lp -d label") == "" and status("nc printer 9100") == ""
    hint = transport.command_failed("ssh tower bobina send --printer gold -", 4, b"x").hint
    assert hint.endswith("ssh tower 'bobina status --printer gold' asks it")


def test_com_ports_are_devices_with_a_roll():
    from bobina.cli import common

    for path in ("COM3", "\\\\.\\COM10", "/dev/usb/lp0"):
        assert transport.is_device(path) and common.counts_paper({"transport": "file", "path": path}), path
    assert not common.counts_paper({"transport": "file", "path": "out.bin"})
