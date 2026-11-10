"""The leak scan allows test data on purpose (tools/leak-allow.txt, `leak-ok:`) and still catches real data."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UNKNOWN_CPF = "123.456" + ".789-09"  # built at run time: this file must itself pass the scan
spec = importlib.util.spec_from_file_location("leakscan", ROOT / "tools" / "leakscan.py")
leakscan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(leakscan)


def hits(tmp_path, text, name="t.py", allow=(set(), []), private=None):
    f = leakscan.ROOT / "tests" / "_scan_probe" / name
    f.parent.mkdir(exist_ok=True)
    try:
        f.write_text(text)
        return leakscan.scan([f], leakscan.GENERIC, private, set(), allow)
    finally:
        f.unlink()
        f.parent.rmdir()


def test_an_unknown_cpf_is_caught(tmp_path):
    assert hits(tmp_path, f'x = "{UNKNOWN_CPF}"')


def test_the_fake_kit_and_reserved_domains_are_allowed(tmp_path):
    allow = leakscan.load_allow()
    assert not hits(tmp_path, 'cpf = "000.000.001-91"; tel = "+55 11 90000-0000"', allow=allow)
    assert not hits(tmp_path, 'mail = "ana@loja.test", "b@x.example", "c@example.org"')


def test_a_marked_line_needs_a_reason(tmp_path):
    assert not hits(tmp_path, f'x = "{UNKNOWN_CPF}"  # leak-ok: Pix payload from the BC manual')
    assert hits(tmp_path, f'x = "{UNKNOWN_CPF}"  # leak-ok:')


def test_private_values_are_never_excused(tmp_path):
    import re

    private = {"private pattern #1": re.compile("chave-de-verdade")}
    assert hits(tmp_path, 'k = "chave-de-verdade"  # leak-ok: looks fake', private=private)
    assert hits(tmp_path, 'k = "chave-de-verdade"', name="x.py",
                allow=(set(), ["tests/_scan_probe/*"]), private=private)  # fmt: skip


def test_fake_data_folders(tmp_path):
    assert not hits(tmp_path, f'cpf = "{UNKNOWN_CPF}"', allow=(set(), ["tests/_scan_probe/*"]))


def test_an_entry_without_a_reason_is_refused(tmp_path):
    p = tmp_path / "allow.txt"
    p.write_text("value: 1.2.3\n")
    with pytest.raises(SystemExit, match="needs a reason"):
        leakscan.load_allow(p)


def test_the_repository_is_clean():
    assert subprocess.run([sys.executable, str(ROOT / "tools" / "leakscan.py")], capture_output=True).returncode == 0
