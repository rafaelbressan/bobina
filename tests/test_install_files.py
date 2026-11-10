"""The installers outside Python: get.sh downloads contrib files by path from a release tag, and the Homebrew formula
lists the runtime dependencies by hand. Moving a file or adding a dependency must fail here, not on a user's machine."""

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GET = (ROOT / "get.sh").read_text(encoding="utf-8")


def test_the_contrib_files_get_sh_downloads_exist():
    names = re.search(r"for f in ([^;]+); do\n\s+fetch \"\$REPO_RAW/\$tag/contrib/\$f\"", GET)
    assert names, "get.sh no longer downloads contrib files the way this test reads"
    for name in names.group(1).split():
        assert (ROOT / "contrib" / name).is_file(), f"get.sh downloads contrib/{name}"
    unit = (ROOT / "contrib/systemd/bt-printer.service").read_text(encoding="utf-8")
    assert "ExecStart=@BOBINA_REPO@/contrib/bt-printer-up.sh" in unit and "\n[Service]\n" in unit


@pytest.mark.skipif(not shutil.which("dash"), reason="dash (a strict POSIX sh) is not installed")
def test_get_sh_is_posix_sh():
    subprocess.run(["dash", "-n", str(ROOT / "get.sh")], check=True)


def test_the_homebrew_formula_has_every_runtime_dependency():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    names = {re.split(r"[<>=!~;\[ ]", d, maxsplit=1)[0].lower().replace("_", "-") for d in deps}
    formula = (ROOT / "contrib/homebrew/bobina.rb").read_text(encoding="utf-8")
    resources = set(re.findall(r'^  resource "([^"]+)" do', formula, flags=re.M))
    assert 'depends_on "pillow"' in formula  # Homebrew's bottle, not built from source
    missing = names - resources - {"pillow"}
    assert not missing, f"run brew update-python-resources (contrib/homebrew/README.md): {sorted(missing)}"
