"""The confirmation screen and --ask open the real terminal (/dev/tty). Tested under a real pseudo-terminal:
the simulated terminals of the other tests cannot catch a tty that fails to open."""

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="needs a Linux pseudo-terminal")


def run_in_pty(code: str, answers: list[str], env: dict | None = None) -> tuple[str, int]:
    """-> (what the terminal showed, the child's exit code). The exit code is the real one: a crash is 99."""
    import pty
    import select
    import time

    pid, fd = pty.fork()
    if pid == 0:  # child: a session whose controlling terminal is the pty
        status = 0
        try:
            os.environ.update(env or {})
            exec(code, {})
        except SystemExit as e:
            status = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        except BaseException:  # noqa: BLE001 - reported to the parent as 99
            import traceback

            traceback.print_exc()
            status = 99
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(status)
    out = b""
    for a in [*answers, None]:
        end = time.time() + 2
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.1)
            if not r:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            if a is not None and out.rstrip().endswith((b":", b">")):
                break
        if a is not None:
            os.write(fd, (a + "\n").encode())
    _, st = os.waitpid(pid, 0)
    return out.decode("utf-8", "replace").replace("\r", ""), os.waitstatus_to_exitcode(st)


def test_open_tty_works_on_a_real_terminal():
    out, code = run_in_pty(
        "import os\nfrom bobina.cli import common\nt = common.open_tty()\n"
        "os.write(1, f'TTY {t is not None}\\n'.encode())\n"
        "os.write(1, f'ANS {common.ask(t, \"go? [y/N] \")}\\n'.encode())",
        ["y"],
    )
    assert "TTY True" in out and "ANS y" in out and code == 0


def test_ask_on_a_real_terminal(tmp_path):
    doc = tmp_path / "d.bob.md"
    doc.write_text("Oi {{ nome }}\n")
    out, code = run_in_pty(
        f"from bobina import cli\nimport sys\nsys.exit(cli.main(['print', '--ask', r'{doc}', '-o', r'{tmp_path}/o.bin']))",
        ["Rafa"],
    )
    assert "nome:" in out and code == 0
    assert b"Oi Rafa" in (tmp_path / "o.bin").read_bytes()


def _printer(tmp_path):
    out = tmp_path / "printer.bin"
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "config.toml").write_text(f'default_printer = "f"\n[printers.f]\ntransport = "file"\npath = "{out}"\n')
    doc = tmp_path / "d.bob.md"
    doc.write_text("Oi #{{ seq.t }}\n")
    env = {"BOBINA_CONFIG_DIR": str(cfg), "BOBINA_STATE_DIR": str(tmp_path / "st"), "NO_COLOR": "1"}
    return out, doc, env


def test_confirmation_screen_p_prints_and_records(tmp_path):
    out, doc, env = _printer(tmp_path)
    shown, code = run_in_pty(
        f"from bobina import cli\nimport sys\nsys.exit(cli.main(['print', r'{doc}']))", ["", "p"], env
    )
    assert "[p] print" in shown and "Enter alone never prints" in shown and code == 0
    assert b"Oi #1" in out.read_bytes()
    import json

    rec = json.loads((tmp_path / "st" / "history.jsonl").read_text().splitlines()[-1])
    assert rec["outcome"] == "printed"


def test_confirmation_screen_q_prints_nothing_and_gives_the_number_back(tmp_path):
    out, doc, env = _printer(tmp_path)
    shown, code = run_in_pty(f"from bobina import cli\nimport sys\nsys.exit(cli.main(['print', r'{doc}']))", ["q"], env)
    assert "not printed" in shown and code == 7  # CONFIRM
    assert not out.exists()
    import json

    assert json.loads((tmp_path / "st" / "counters.json").read_text()) == {}
    rec = json.loads((tmp_path / "st" / "history.jsonl").read_text().splitlines()[-1])
    assert rec["outcome"] == "cancelled"
