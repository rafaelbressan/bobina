"""The installers outside Python: get.sh downloads contrib files by path from a release tag, the Homebrew formula
lists the runtime dependencies by hand, the .deb picks its packages by Python version. Moving a file or adding a
dependency must fail here, not on a user's machine."""

import importlib.util
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
    formula = (ROOT / "Formula/bobina.rb").read_text(encoding="utf-8")
    resources = set(re.findall(r'^  resource "([^"]+)" do', formula, flags=re.M))
    assert 'depends_on "pillow"' in formula  # Homebrew's bottle, not built from source
    missing = names - resources - {"pillow"}
    assert not missing, f"run brew update-python-resources (CONTRIBUTING.md, Homebrew): {sorted(missing)}"


def test_get_sh_runs_nothing_until_its_last_line():
    """curl | sh runs what has arrived: a download cut short must not run half of the installer."""
    lines = [ln for ln in GET.splitlines() if ln.strip()]
    assert lines[-1].startswith('main "$@"')
    assert [ln for ln in lines if ln.startswith("main ")] == [lines[-1]]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deb = _load("build_deb", "tools/build_deb.py")
launcher = _load("deb_launcher", "contrib/deb/launcher.py")


def test_the_deb_launcher_picks_the_directory_of_the_running_python(tmp_path):
    for d in ("common", "cp311", "cp312", "cp314"):
        (tmp_path / d).mkdir()
    assert launcher.lib_dirs(str(tmp_path), (3, 12)) == [str(tmp_path / "cp312"), str(tmp_path / "common")]
    with pytest.raises(SystemExit) as no:
        launcher.lib_dirs(str(tmp_path), (3, 15))
    msg = str(no.value)
    assert "Python 3.15" in msg and "3.11, 3.12, 3.14" in msg and "pipx install bobina" in msg


def test_the_deb_launcher_runs_on_the_system_python():
    assert (ROOT / "contrib/deb/launcher.py").read_text(encoding="utf-8").startswith("#!/usr/bin/python3 -I\n")


def test_the_deb_has_packages_for_every_python_bobina_supports():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    low = re.fullmatch(r">=\s*(3\.\d+)", project["requires-python"]).group(1)
    minors = [int(v.split(".")[1]) for v in deb.PYTHONS]
    assert deb.PYTHONS[0] == low and minors == list(range(minors[0], minors[-1] + 1))
    control = deb.control_text("0.2.0rc1", "arm64", 1000, (2, 28), ["zlib1g"])
    assert "Version: 0.2.0~rc1\n" in control and "Architecture: arm64\n" in control
    assert f"Depends: python3 (>= {low}), python3 (<< 3.{minors[-1] + 1}), libc6 (>= 2.28), zlib1g\n" in control


def test_the_deb_copyright_file_is_machine_readable():
    text = deb.copyright_text(["segno 1.6.6 (BSD License)"])
    lines = text.splitlines()
    assert lines[0] == "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/"
    assert "\nLicense: MIT\n Permission is hereby granted" in text and text.count("Copyright") == 1
    assert "segno 1.6.6 (BSD License)" in text and lines[-1].endswith("fonts/licenses/.")
    assert all(not ln or ln.startswith(" ") or re.match(r"[A-Z][\w-]*:", ln) for ln in lines)  # fields, continuations
    assert max(map(len, lines)) <= 80


@pytest.mark.parametrize(("python", "debian"), [("0.1.0", "0.1.0"), ("0.2.0rc1", "0.2.0~rc1"), ("1.0.0b2", "1.0.0~b2")])
def test_deb_versions_sort_like_python_ones(python, debian):
    assert deb.deb_version(python) == debian
    if shutil.which("dpkg"):
        subprocess.run(["dpkg", "--compare-versions", debian, "lt", "1.0.0"], check=True)
        if "~" in debian:
            subprocess.run(["dpkg", "--compare-versions", debian, "lt", debian.split("~")[0]], check=True)


def test_the_deb_shares_what_is_the_same_for_every_python(tmp_path):
    dirs = [tmp_path / "cp311", tmp_path / "cp312"]
    for d in dirs:
        (d / "segno").mkdir(parents=True)
        (d / "segno/__init__.py").write_text("pure")
        (d / "PIL").mkdir()
        (d / "PIL/_imaging.so").write_text(f"compiled for {d.name}")
        (d / "pillow.libs").mkdir()
        (d / "pillow.libs/libjpeg.so.62").write_text("vendored, the same")
    assert deb.move_common(dirs, tmp_path / "common") == ["pillow.libs", "segno"]
    assert (tmp_path / "common/segno/__init__.py").is_file() and (dirs[1] / "PIL/_imaging.so").is_file()
    for d in dirs:  # PIL finds them through $ORIGIN/../pillow.libs
        assert not (d / "segno").exists() and (d / "pillow.libs").is_symlink()
        assert (d / "pillow.libs/libjpeg.so.62").read_text() == "vendored, the same"


def test_the_deb_depends_on_the_glibc_its_wheels_need(tmp_path):
    for name, tags in {"a": ["cp311-cp311-manylinux_2_17_x86_64", "cp311-cp311-manylinux2014_x86_64"],
                       "b": ["cp311-cp311-manylinux_2_27_x86_64", "cp311-cp311-manylinux_2_28_x86_64"],
                       "c": ["py3-none-any"]}.items():  # fmt: skip
        info = tmp_path / f"{name}-1.dist-info"
        info.mkdir()
        (info / "WHEEL").write_text("Wheel-Version: 1.0\n" + "".join(f"Tag: {t}\n" for t in tags))
    assert deb.glibc_needed(tmp_path) == (2, 27)
    tags = deb.platforms("arm64")  # pip takes each tag literally: every glibc up to GLIBC
    assert tags[0] == "manylinux_2_36_aarch64" and "manylinux_2_17_aarch64" in tags and "manylinux2014_aarch64" in tags


def test_the_deb_reads_which_system_libraries_a_compiled_module_needs():
    pil = Path(importlib.util.find_spec("PIL._imaging").origin)
    if pil.read_bytes()[:6] != b"\x7fELF\x02\x01":
        pytest.skip("not a 64-bit little-endian ELF (the .deb architectures)")
    needed = deb.elf_needed(pil)
    assert "libc.so.6" in needed
    if shutil.which("readelf"):
        out = subprocess.run(["readelf", "-d", str(pil)], capture_output=True, text=True, check=True).stdout
        assert needed == re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", out)


@pytest.mark.skipif(not shutil.which("dash"), reason="dash (a strict POSIX sh) is not installed")
@pytest.mark.parametrize("script", ["POSTINST", "PRERM"])
def test_the_deb_maintainer_scripts_are_posix_sh(script, tmp_path):
    (tmp_path / "script").write_text(getattr(deb, script))
    subprocess.run(["dash", "-n", str(tmp_path / "script")], check=True)
    subprocess.run(["dash", "-n", str(ROOT / "contrib/deb/test-in-container.sh")], check=True)
