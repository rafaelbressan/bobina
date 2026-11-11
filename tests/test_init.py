"""bobina init: the first run. Discovery is mocked (no Bluetooth scan, no USB device is opened), the printers are
files, and the interactive flow is driven by answers on stdin."""

import io
import json
import sys

import pytest

from bobina import cli, config, discover, paper, transport
from bobina.cli import common

MTP, BUDS, OTHER = "AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02", "AA:BB:CC:DD:EE:03"  # leak-ok: made-up addresses for tests


@pytest.fixture
def bt(monkeypatch, tmp_path):
    """Bluetooth works and the scan finds a headset, an MTP-II and an unknown printer; no USB printer."""
    found = [(BUDS, "Galaxy Buds"), (OTHER, "Printer001"), (MTP, "MTP-II")]
    monkeypatch.setattr(discover, "bluetooth_missing", lambda: "")
    monkeypatch.setattr(transport, "scan", lambda seconds: list(found))
    monkeypatch.setattr(discover, "USB_GLOB", str(tmp_path / "no-usb-lp*"))
    monkeypatch.setattr(discover, "known_name", lambda mac: dict((m, n) for m, n in found).get(mac, ""))
    return found


@pytest.fixture
def no_bt(monkeypatch, tmp_path):
    def never(seconds):
        raise AssertionError("no scan without Bluetooth")

    monkeypatch.setattr(discover, "bluetooth_missing", lambda: "bluetoothctl is not installed (BlueZ)")
    monkeypatch.setattr(transport, "scan", never)
    monkeypatch.setattr(discover, "USB_GLOB", str(tmp_path / "no-usb-lp*"))


def answers(monkeypatch, *lines):
    monkeypatch.setattr(sys, "stdin", io.StringIO("".join(f"{x}\n" for x in lines)))


def run(*argv):
    return cli.main(["init", *argv])


def test_yes_takes_the_known_model_says_the_roll_is_missing_and_prints_nothing(bt, capsys):
    assert run("--yes") == cli.OK
    cfg = config.load()
    assert cfg["default_printer"] == "mtp-ii"
    assert cfg["printers"]["mtp-ii"] == {"transport": "bluetooth", "address": MTP, "channel": 1,
                                         "profile": "mtp-ii-58"}  # fmt: skip
    out, e = capsys.readouterr()
    assert f"took MTP-II ({MTP}), the first of 2 printers; also found: Printer001" in out
    assert "P104" in e and "bobina paper new 30m" in e and "cannot estimate the paper left" in e
    assert "Galaxy Buds" not in out  # a headset is never taken


def test_yes_is_deterministic_whatever_the_order_of_the_scan(bt, capsys):
    bt.reverse()
    assert run("--yes") == cli.OK
    assert config.load()["default_printer"] == "mtp-ii"


def test_yes_json_matches_its_schema(bt, capsys):
    from test_schemas import _check, _schema

    assert run("--yes", "--json") == cli.OK
    doc = json.loads(capsys.readouterr().out)
    _check(doc, _schema("init"))
    assert doc["printer"]["where"] == MTP and doc["profile"]["by"] == "name" and doc["roll"]["roll_mm"] is None
    assert [p["code"] for p in doc["problems"]] == ["P104"] and doc["test_strip"] is None
    assert {d["name"]: d["printer_like"] for d in doc["found"]} == {"MTP-II": True, "Printer001": True,
                                                                    "Galaxy Buds": False}  # fmt: skip


def test_yes_with_printer_names_the_device(bt, capsys):
    assert run("--yes", "--printer", OTHER) == cli.OK
    pr = config.load()["printers"]["printer001"]
    assert pr["address"] == OTHER and pr["profile"] == "mtp-ii-58"
    assert "P402" in capsys.readouterr().err  # no profile matches its name: the default, said


def test_yes_finds_a_usb_printer_and_its_model(monkeypatch, tmp_path, no_bt, capsys):
    lp = tmp_path / "usb" / "lp0"
    lp.parent.mkdir()
    lp.write_bytes(b"")
    sysfs = tmp_path / "usbmisc" / "lp0" / "device"
    sysfs.mkdir(parents=True)
    (sysfs / "ieee1284_id").write_text("MFG:EPSON;CMD:ESCPOS;MDL:TM-T20II;CLS:PRINTER;")
    monkeypatch.setattr(discover, "USB_GLOB", str(tmp_path / "usb" / "lp*"))
    monkeypatch.setattr(discover, "USB_SYSFS", str(tmp_path / "usbmisc"))
    monkeypatch.setattr(sys, "platform", "linux")
    assert run("--yes") == cli.OK
    pr = config.load()["printers"]["epson-tm-t20ii"]
    assert pr == {"transport": "file", "path": str(lp), "profile": "epson-tm-t20ii"}
    e = capsys.readouterr().err
    assert "P401" in e and "bluetoothctl" in e  # said, and it did not wait for a scan
    assert lp.read_bytes() == b""  # nothing printed


def test_yes_without_any_printer_stops_with_e406_and_says_what_is_missing(no_bt, capsys):
    assert run("--yes") == cli.UNREACHABLE
    e = capsys.readouterr().err
    assert "E406" in e and "P401" in e and "--printer" in e
    assert "printers" not in config.load()


def test_noninteractive_behaves_like_yes(bt, monkeypatch, capsys):
    monkeypatch.setenv("BOBINA_NONINTERACTIVE", "1")
    monkeypatch.setattr(sys, "stdin", None)  # never read
    assert run() == cli.OK
    assert config.load()["default_printer"] == "mtp-ii"


def test_no_answer_on_stdin_is_e107(bt, monkeypatch, capsys):
    answers(monkeypatch)
    assert run() == cli.CONFIRM
    e = capsys.readouterr().err
    assert "E107" in e and "bobina init --yes" in e


def test_interactive_file_printer_and_test_strip(no_bt, tmp_path, monkeypatch, capsys):
    out = tmp_path / "strip.bin"
    # printer: t, its file · profile: width 58, the first · locale: kept · strip: yes
    answers(monkeypatch, "t", str(out), "", "1", "", "y")
    assert run() == cli.OK
    shown = capsys.readouterr().out
    cfg = config.load()
    assert cfg["printers"]["test"] == {"transport": "file", "path": str(out), "profile": "mtp-ii-58"}
    assert "a file printer has no roll to count" in shown
    assert "Print a test strip? (~" in shown and "the tear ruler" in shown and "feed test" not in shown
    assert out.read_bytes().count(b"\x1dv0") >= 1  # the ruler is an image
    assert "no calibration questions" in shown and "first print: bobina print" in shown


def test_interactive_roll_package_code_and_calibration_answers(bt, tmp_path, monkeypatch, capsys):
    sink = tmp_path / "printer.bin"
    sent = []
    monkeypatch.setattr(transport, "send", lambda data, pr, prof, **k: (sent.append(data), sink.write_bytes(data)))
    # printer 1 (the MTP-II) · profile netum (not measured, so the feed test is on the strip) · locale fr-CA ·
    # roll: a bare number (the unit is asked), then 57x30 and "metres" · strip: yes · touching · 15
    answers(monkeypatch, "1", "n", "58", "netum-nt-5890k", "fr-CA", "30", "57x30", "m", "y", "touching", "15")
    assert run() == cli.OK
    shown = capsys.readouterr().out
    assert "looks like a Goldensky MTP-II, 58 mm paper, measured on paper: right?" in shown
    assert "give the unit" in shown and "is 30 the length in metres (m) or the outer diameter in mm" in shown
    assert "the feed test and the tear ruler" in shown
    cfg = config.load()
    pr = cfg["printers"]["mtp-ii"]
    assert pr["profile"] == "netum-nt-5890k" and pr["tear_mm"] == 15 and pr["blank_rows_after_raster"] is True
    assert cfg["locale"] == "fr-CA"
    roll = paper.get("mtp-ii")
    assert roll["roll_mm"] == 30000 and roll["width_mm"] == 57 and roll["used_mm"] > 0  # the strip was counted
    assert b"\x1bJ" in sent[0]  # the feed test's ESC J


def test_rerun_asks_what_to_change_and_keeps_the_rest(bt, tmp_path, monkeypatch, capsys):
    assert cli.main(["printer", "add", "loja", "--path", str(tmp_path / "loja.bin")]) == cli.OK
    capsys.readouterr()
    answers(monkeypatch, "3", "pt-BR")
    assert run() == cli.OK
    shown = capsys.readouterr().out
    assert "What to change?" in shown and "1 printer   loja" in shown
    cfg = config.load()
    assert cfg["locale"] == "pt-BR" and list(cfg["printers"]) == ["loja"]


def test_rerun_with_yes_keeps_the_printer_and_does_not_scan(no_bt, tmp_path, capsys):
    assert cli.main(["printer", "add", "loja", "--path", str(tmp_path / "loja.bin")]) == cli.OK
    capsys.readouterr()
    assert run("--yes", "--json") == cli.OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["printer"]["name"] == "loja" and doc["printer"]["found_by"] == "config" and doc["changed"] == []


def test_dry_run_writes_nothing(bt, capsys):
    before = config.path().read_text()
    assert run("--yes", "--dry-run") == cli.OK
    assert config.path().read_text() == before
    assert "dry run: nothing saved" in capsys.readouterr().out


def test_command_printer_for_another_machine(no_bt, capsys):
    assert run("--yes", "--command", "ssh tower bobina send --yes -") == cli.OK
    assert config.load()["printers"]["tower"]["command"] == "ssh tower bobina send --yes -"


def test_the_same_device_keeps_its_name_and_its_calibration(bt, capsys):
    assert run("--yes") == cli.OK
    config.update(lambda cfg: cfg["printers"]["mtp-ii"].__setitem__("tear_mm", 7.0))
    assert run("--yes", "--printer", MTP) == cli.OK
    pr = config.load()["printers"]
    assert list(pr) == ["mtp-ii"] and pr["mtp-ii"]["tear_mm"] == 7.0


@pytest.mark.parametrize(
    "name,profile",
    [("MTP-II", "mtp-ii-58"), ("PT-210_A1B2", "mtp-ii-58"), ("EPSON TM-T20III", "epson-tm-t20iii"),
     ("TM-T20II", "epson-tm-t20ii"), ("ZJ-5870", "zijiang-zj-5870"), ("Galaxy Buds", None)],
)  # fmt: skip
def test_the_profile_a_name_suggests(name, profile):
    assert discover.match_profile(name) == profile


def test_bluetooth_missing_is_said_not_waited_for(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    found, notes = discover.bluetooth(8)
    assert found == [] and notes[0][0] == "P401" and "Linux" in notes[0][1]


def test_counts_paper_is_the_rule_for_the_roll_step():
    assert not common.counts_paper({"transport": "file", "path": "out.bin"})
