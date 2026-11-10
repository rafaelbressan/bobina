"""Build bobina's .deb for one architecture from a bobina wheel. The release workflow runs it for amd64 and arm64.

The package runs on the distribution's own /usr/bin/python3 (it has Bluetooth sockets; uv's and Homebrew's Pythons
do not) but brings its own dependencies: Debian's python3-pil and python3-markdown-it are too old and
ppf-datamatrix is not packaged. pip downloads wheels only (nothing is compiled, so one machine builds both
architectures): pure-Python packages, bobina included, go once to /usr/lib/bobina/common, compiled ones (Pillow,
PyYAML, MarkupSafe, fonttools) once per Python version to /usr/lib/bobina/cpXY. /usr/bin/bobina
(contrib/deb/launcher.py) picks the directory of the running Python. The extras are not included.

Usage: .venv/bin/python tools/build_deb.py [--arch amd64|arm64] [--wheel dist/bobina-X-py3-none-any.whl] [--out dist]
Needs dpkg-deb, and pip in the Python that runs it. Without --wheel it builds one from this checkout.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from email.parser import Parser
from email.utils import formatdate
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHONS = ["3.11", "3.12", "3.13", "3.14"]  # from requires-python up (tests/test_install_files.py checks)
MACHINE = {"amd64": "x86_64", "arm64": "aarch64"}
GLIBC = (2, 36)  # wheels up to this glibc (Debian 12; Ubuntu 24.04 has 2.39); Depends says what they need
INDEX = "https://pypi.org/simple"
HOME = "https://github.com/rafaelbressan/bobina"
MAINTAINER = f"bobina <{HOME}/issues>"
LEGACY_MANYLINUX = {"manylinux1": (2, 5), "manylinux2010": (2, 12), "manylinux2014": (2, 17)}
# also published as a pure-Python wheel; the compiled one is only faster and 24 MB per Python: distribution: package
PURE = {"fonttools": "fontTools"}
# pip --target leaves these at the top: console scripts with pip's shebang (the launcher replaces them), data files
# (fonttools' man page) and python-barcode's docs/ and tests/
JUNK = ["bin", "share", "docs", "tests"]
# shared libraries manylinux wheels may load from the system (the rest they vendor in a .libs folder)
SYSTEM_LIBS = {
    **dict.fromkeys(["libc.so.6", "libm.so.6", "libpthread.so.0", "libdl.so.2", "librt.so.1"], "libc6"),
    **dict.fromkeys(["ld-linux-x86-64.so.2", "ld-linux-aarch64.so.1"], "libc6"),
    "libz.so.1": "zlib1g",
    "libgcc_s.so.1": "libgcc-s1",
    "libstdc++.so.6": "libstdc++6",
}

POSTINST = """#!/bin/sh
set -e
# byte-compile for the python3 installed now (the launcher never writes .pyc files); prerm removes them
if [ "$1" = configure ]; then
    tag=$(python3 -c 'import sys; print("cp%d%d" % sys.version_info[:2])') || exit 0
    if [ -d "/usr/lib/bobina/$tag" ]; then
        python3 -m compileall -q -j0 /usr/lib/bobina/common "/usr/lib/bobina/$tag" >/dev/null 2>&1 || true
    fi
fi
"""
PRERM = """#!/bin/sh
set -e
find /usr/lib/bobina -name '*.pyc' -delete 2>/dev/null || true
find /usr/lib/bobina -depth -type d -name __pycache__ -empty -delete 2>/dev/null || true
"""


def deb_version(version: str) -> str:
    """A Python version as a Debian one: 0.2.0rc1 sorts before 0.2.0 only as 0.2.0~rc1."""
    m = re.fullmatch(r"(\d+(?:\.\d+)*)(?:(a|b|rc)(\d+))?(?:\.dev(\d+))?", version)
    if not m:
        raise SystemExit(f"build_deb: no Debian version for {version!r}")
    base, pre, n, dev = m.groups()
    return base + (f"~{pre}{n}" if pre else "") + (f"~dev{dev}" if dev else "")


def platforms(arch: str) -> list[str]:
    """pip's --platform values: it takes a manylinux tag literally, not as "this glibc or older"."""
    m = MACHINE[arch]
    tags = [f"manylinux_{GLIBC[0]}_{minor}_{m}" for minor in range(GLIBC[1], 4, -1)]
    return tags + [f"{legacy}_{m}" for legacy in LEGACY_MANYLINUX]


def pip_install(wheel: Path, python: str, arch: str, target: Path) -> None:
    """bobina and its runtime dependencies as wheels for that Python and architecture, without running them."""
    pip = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-compile",
           "--index-url", INDEX, "--target", str(target), "--only-binary=:all:",
           "--python-version", python]  # fmt: skip

    def run(*args: str) -> None:
        subprocess.run([*pip, *args], check=True)
        for junk in JUNK:
            p = target / junk
            shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)

    run("--implementation", "cp", *[a for p in platforms(arch) for a in ("--platform", p)], str(wheel))
    for name, top in PURE.items():
        info = sorted(target.glob(f"{name}-*.dist-info"))
        if info:
            shutil.rmtree(info[0])
            shutil.rmtree(target / top)
            version = info[0].name[len(name) + 1 : -len(".dist-info")]
            run("--no-deps", "--implementation", "py", "--abi", "none", "--platform", "any", f"{name}=={version}")


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted([path, *path.rglob("*")]) if path.is_dir() else [path]:
        h.update(str(p.relative_to(path.parent)).encode() + (b"/" if p.is_dir() else b"\0"))
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def move_common(dirs: list[Path], common: Path) -> list[str]:
    """What is identical in every per-Python directory (the pure-Python packages) moves once to common/.

    A wheel's vendored shared libraries (pillow.libs) are found through $ORIGIN/../pillow.libs: they move too,
    and a relative symlink stays in their place."""
    common.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in sorted(p.name for p in dirs[0].iterdir()):
        paths = [d / name for d in dirs]
        if all(p.exists() for p in paths) and len({_digest(p) for p in paths}) == 1:
            shutil.move(paths[0], common / name)
            for p in paths[1:]:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
            if name.endswith(".libs"):
                for p in paths:
                    p.symlink_to(Path("..", common.name, name))
            moved.append(name)
    return moved


def glibc_needed(lib: Path) -> tuple[int, int] | None:
    """The newest glibc a bundled wheel needs: each wheel needs the oldest of its own manylinux tags."""
    need = None
    for wheel in lib.rglob("*.dist-info/WHEEL"):
        tags = [t.rsplit("-", 1)[-1] for t in re.findall(r"^Tag: (\S+)", wheel.read_text(), flags=re.M)]
        versions = [LEGACY_MANYLINUX.get(t.rsplit("_", 1)[0]) for t in tags]
        versions += [(int(a), int(b)) for t in tags for a, b in re.findall(r"^manylinux_(\d+)_(\d+)_", t)]
        versions = [v for v in versions if v]
        if versions:
            need = max(need or (0, 0), min(versions))
    return need


def elf_needed(path: Path) -> list[str]:
    """The DT_NEEDED entries of a 64-bit little-endian ELF shared object (amd64 and arm64)."""
    data = path.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01":
        return []
    shoff, shentsize, shnum = struct.unpack_from("<Q", data, 0x28)[0], *struct.unpack_from("<HH", data, 0x3A)
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, shoff + i * shentsize) for i in range(shnum)]
    needed = []
    for _, kind, _, _, offset, size, link, _, _, _ in sections:
        if kind != 6:  # SHT_DYNAMIC
            continue
        strtab = sections[link][4]
        for i in range(0, size, 16):
            tag, value = struct.unpack_from("<qQ", data, offset + i)
            if tag == 1:  # DT_NEEDED
                needed.append(data[strtab + value : data.index(b"\0", strtab + value)].decode())
    return needed


def system_depends(lib: Path) -> list[str]:
    """The Debian packages of the shared libraries the compiled modules load from the system, not from a .libs."""
    vendored = {p.name for p in lib.rglob("*.libs/*")}
    packages = set()
    for so in lib.rglob("*.so*"):
        for name in elf_needed(so) if so.is_file() else []:
            if name in vendored:
                continue
            if name not in SYSTEM_LIBS:
                raise SystemExit(f"build_deb: {so.relative_to(lib)} needs {name}: add its package to SYSTEM_LIBS")
            packages.add(SYSTEM_LIBS[name])
    return sorted(packages - {"libc6"})  # libc6 gets a version from the wheels' tags


def bundled(lib: Path) -> list[str]:
    """Name, version and license of each bundled distribution but bobina, for the copyright file."""
    found = {}
    for meta in sorted(lib.rglob("*.dist-info/METADATA")):
        m = Parser().parsestr(meta.read_text(encoding="utf-8"), headersonly=True)
        lic = m.get("License-Expression") or ""
        if not lic and len(m.get("License") or "") < 40:
            lic = m.get("License") or ""
        if not lic:
            classifiers = [c.split(" :: ")[-1] for c in m.get_all("Classifier") or [] if c.startswith("License ::")]
            lic = " / ".join(classifiers)
        if m["Name"].lower() != "bobina":
            found.setdefault(m["Name"], (set(), lic or "see its .dist-info"))[0].add(m["Version"])
    rows = sorted(found.items(), key=lambda item: item[0].lower())
    return [f"{name} {', '.join(sorted(versions))} ({lic})" for name, (versions, lic) in rows]


def copyright_text(packages: list[str]) -> str:
    lines = (ROOT / "LICENSE").read_text(encoding="utf-8").strip().splitlines()  # MIT License, Copyright…, text
    at = next(i for i, ln in enumerate(lines) if ln.lower().startswith("copyright"))
    holder = re.sub(r"^copyright\s+(\(c\)\s+)?", "", lines[at], flags=re.I)
    body = "\n".join(f" {ln}" if ln.strip() else " ." for ln in lines[at + 1 :]).lstrip(" .\n")
    comment = (
        "This package bundles these Python distributions, unmodified, each under its own license, whose text is in"
        " its .dist-info directory under /usr/lib/bobina: " + "; ".join(packages) + ". bobina's fonts are under"
        " their own licenses, in /usr/lib/bobina/common/bobina/fonts/licenses/."
    )
    wrapped = re.sub(r"(.{1,78})(?:\s+|$)", r" \1\n", comment).rstrip("\n")
    return (
        "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
        f"Upstream-Name: bobina\nUpstream-Contact: {HOME}/issues\nSource: {HOME}\n\n"
        f"Files: *\nCopyright: {holder}\nLicense: MIT\n {body}\nComment:\n{wrapped}\n"
    )


def control_text(version: str, arch: str, size_kb: int, glibc: tuple[int, int] | None, libs: list[str]) -> str:
    low, high = PYTHONS[0], PYTHONS[-1].split(".")
    depends = [f"python3 (>= {low})", f"python3 (<< {high[0]}.{int(high[1]) + 1})"]
    if glibc:
        depends.append(f"libc6 (>= {glibc[0]}.{glibc[1]})")
    depends += libs
    return (
        f"Package: bobina\nVersion: {deb_version(version)}\nArchitecture: {arch}\nMaintainer: {MAINTAINER}\n"
        f"Installed-Size: {size_kb}\nDepends: {', '.join(depends)}\nRecommends: bluez\nSection: utils\n"
        f"Priority: optional\nHomepage: {HOME}\n"
        "Description: print Markdown on thermal roll printers\n"
        " bobina prints Markdown, templates and CSV batches on ESC/POS thermal roll\n"
        " printers over Bluetooth, a file or a command, with calibrated defaults,\n"
        " previews you can trust and warnings instead of refusals.\n"
        " .\n"
        f" Its Python dependencies are bundled, for Python {low} to {PYTHONS[-1]}. The extras\n"
        " (PDF, SVG, xlsx, MCP) are not: install bobina with pipx or uv for them.\n"
    )


def changelog_gz(version: str, epoch: int) -> bytes:
    text = (
        f"bobina ({deb_version(version)}) unstable; urgency=medium\n\n"
        f"  * bobina {version}: {HOME}/blob/main/CHANGELOG.md\n\n"
        f" -- {MAINTAINER}  {formatdate(epoch)}\n"
    )
    return gzip.compress(text.encode(), compresslevel=9, mtime=0)


def _normalize(root: Path, epoch: int) -> int:
    """Modes as Debian expects (executables only where meant), mtimes clamped; returns Installed-Size in KiB."""
    kb = 0
    executable = {root / "usr/bin/bobina", root / "DEBIAN/postinst", root / "DEBIAN/prerm"}
    for p in sorted(root.rglob("*")):
        p.chmod(0o755 if p.is_dir() or p in executable else 0o644)
        if "DEBIAN" not in p.relative_to(root).parts:
            kb += 1 if p.is_dir() else -(-p.stat().st_size // 1024)
    for p in [*root.rglob("*"), root]:
        os.utime(p, (epoch, epoch), follow_symlinks=False)
    return kb


def build(wheel: Path, arch: str, out: Path) -> Path:
    version = re.match(r"bobina-([^-]+)-", wheel.name).group(1)
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH") or time.time())
    with tempfile.TemporaryDirectory(prefix="bobina-deb-") as tmp:
        root = Path(tmp) / "root"
        lib = root / "usr/lib/bobina"
        dirs = []
        for python in PYTHONS:
            d = lib / ("cp" + python.replace(".", ""))
            pip_install(wheel, python, arch, d)
            dirs.append(d)
        move_common(dirs, lib / "common")
        if not (lib / "common/bobina").is_dir():
            raise SystemExit("build_deb: bobina itself did not end up in common/: is the wheel pure Python?")
        (root / "usr/bin").mkdir(parents=True)
        shutil.copy(ROOT / "contrib/deb/launcher.py", root / "usr/bin/bobina")
        doc = root / "usr/share/doc/bobina"
        doc.mkdir(parents=True)
        (doc / "copyright").write_text(copyright_text(bundled(lib)), encoding="utf-8")
        (doc / "changelog.gz").write_bytes(changelog_gz(version, epoch))
        debian = root / "DEBIAN"
        debian.mkdir()
        (debian / "postinst").write_text(POSTINST)
        (debian / "prerm").write_text(PRERM)
        sums = [
            f"{hashlib.md5(p.read_bytes()).hexdigest()}  {p.relative_to(root)}"
            for p in sorted(root.rglob("*"))
            if p.is_file() and "DEBIAN" not in p.relative_to(root).parts
        ]
        (debian / "md5sums").write_text("\n".join(sums) + "\n")
        size = _normalize(root, epoch)
        (debian / "control").write_text(control_text(version, arch, size, glibc_needed(lib), system_depends(lib)))
        os.utime(debian / "control", (epoch, epoch))
        out.mkdir(parents=True, exist_ok=True)
        deb = out / f"bobina_{version}_{arch}.deb"  # the Python version: GitHub renames assets with a "~"
        env = {**os.environ, "SOURCE_DATE_EPOCH": str(epoch)}
        subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "-z9", "--build", str(root), str(deb)], check=True,
                       env=env, stdout=subprocess.DEVNULL)  # fmt: skip
    return deb


def _wheel(out: Path) -> Path:
    built = sorted(out.glob("bobina-*-py3-none-any.whl"), key=lambda p: p.stat().st_mtime)
    if built:
        return built[-1]
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--quiet", "--no-deps", "--index-url", INDEX, "-w", str(out),
                    str(ROOT)], check=True)  # fmt: skip
    return _wheel(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--arch", choices=sorted(MACHINE), default="amd64")
    ap.add_argument("--wheel", type=Path, help="bobina's wheel (default: the newest in --out, else built)")
    ap.add_argument("--out", type=Path, default=ROOT / "dist")
    args = ap.parse_args()
    deb = build(args.wheel or _wheel(args.out), args.arch, args.out)
    print(f"wrote {deb} ({deb.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
