#!/usr/bin/env python3
"""Record what the site shows of bobina: terminal casts and tickets, from real commands on real files.

Runs the released bobina (from PyPI, in site/.capture-venv; the version of site/.release/release.json) on the
site's examples (site/examples/) and the release's own (examples/). Writes src/captures/captures.json (each cast:
the command lines, their output as HTML and their exit codes), public/captures/*.png (each ticket: `bobina preview`
of a file shown next to it) and capture/lock.txt (every package that made them, pinned). Nothing is drawn by hand.

    cd site && npm run capture          # = node scripts/release.mjs && python3 capture/capture.py
    python3 capture/capture.py --locked # the packages of lock.txt: the same bytes again (what CI compares)

A release records them by itself (.github/workflows/release-commit.yml). It stops, writing nothing, when a command
exits with another code than expected, when an output shows the capture folder or a temporary path, or when
tools/leakscan.py finds personal data in it."""

from __future__ import annotations

import argparse
import html
import json
import os
import pty
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]
ROOT = SITE.parent
OUT_JSON = SITE / "src" / "captures" / "captures.json"
OUT_PNG = SITE / "public" / "captures"
LOCK = SITE / "capture" / "lock.txt"
ENV_DIR = SITE / ".capture-venv"
NOW = "2026-11-05T09:49:00"  # the date the docs' examples use
COLUMNS = 64

# A cast is one or more commands run in a folder holding the example files; `tty` gives them a terminal (the
# confirmation screen), `keys` are typed when the command waits, `expect` is its exit code.
CASTS = [
    {
        "id": "print",
        "title": "Print, after the confirmation screen",
        "steps": [{"cmd": "bobina print receipt.bob.md", "tty": True, "keys": "p\r", "expect": 0}],
    },
    {
        "id": "nudges",
        "title": "Nudges, not blocks",
        "steps": [{"cmd": "bobina check price-tag.bob.md", "expect": 0}],
    },
    {
        "id": "agents",
        "title": "An agent without a terminal",
        "steps": [
            {"cmd": "bobina print receipt.bob.md", "expect": 7},
            {"cmd": "bobina help E107", "expect": 0},
            {"cmd": "bobina print receipt.bob.md --yes", "expect": 0},
        ],
    },
    {
        "id": "batch",
        "title": "One label per row",
        "steps": [
            {"cmd": "bobina check jar-label.bob.md --data pantry.csv", "expect": 0},
            {"cmd": "bobina preview jar-label.bob.md --data pantry.csv -o 'labels/{product}.png'", "expect": 0},
        ],
    },
]

# Tickets: (id, file in the work folder, extra arguments). The gallery adds every examples/templates/*.bob.md.
TICKETS = [("receipt", "receipt.bob.md", []), ("price-tag", "price-tag.bob.md", [])]

TEMPORARY = re.compile(r"/(?:tmp|var/folders|private/var)/")  # personal data is tools/leakscan.py's job


def fail(msg: str) -> None:
    sys.exit(f"capture: {msg}")


def release() -> dict:
    path = SITE / ".release" / "release.json"
    if not path.exists():
        fail("no .release/release.json: run `node scripts/release.mjs` first (npm run capture does both)")
    info = json.loads(path.read_text())
    info["dir"] = (SITE / info["root"]).resolve()
    return info


def python_of(bobina: Path) -> Path:
    """The interpreter a bobina script runs on: its shebang (a venv, pipx, uv tool), else the python next to it."""
    try:
        first = bobina.read_bytes()[:256].split(b"\n")[0].decode()
    except (OSError, UnicodeDecodeError):
        first = ""
    if first.startswith("#!") and Path(first[2:].strip().split()[0]).is_file():
        return Path(first[2:].strip().split()[0])
    return bobina.parent / "python"


def bobina_for(version: str, locked: bool) -> tuple[Path, str]:
    """bobina VERSION from PyPI in a venv of its own: the newest packages that fit, or exactly those of lock.txt.
    Returns the executable and the pinned list of what is installed."""
    if locked:
        if not LOCK.exists():
            fail(f"--locked: no {LOCK.relative_to(ROOT)}")
        spec = LOCK.read_text()
        if f"bobina=={version}\n" not in spec:
            fail(f"--locked: {LOCK.relative_to(ROOT)} is not for bobina {version}; record without --locked")
    else:
        spec = f"bobina=={version}\n"
    marker = ENV_DIR / "capture-spec.txt"
    exe = ENV_DIR / "bin" / "bobina"  # POSIX only, like the pseudo-terminal the casts need
    if not (exe.exists() and marker.exists() and marker.read_text() == spec):
        shutil.rmtree(ENV_DIR, ignore_errors=True)  # a fresh venv: no package left from another version
        venv.create(ENV_DIR, with_pip=True)
        req = ENV_DIR / "requirements.txt"
        req.write_text(spec)
        pip = [str(ENV_DIR / "bin" / "python"), "-m", "pip", "install", "--quiet", "--no-cache-dir"]
        pip += ["--index-url", "https://pypi.org/simple", "-r", str(req)] + (["--no-deps"] if locked else [])
        for _ in range(20):  # PyPI's CDN can miss an upload for a few minutes (a release run starts at once)
            if subprocess.run(pip).returncode == 0:
                break
            time.sleep(30)
        else:
            fail(f"could not install {spec.strip()!r} from PyPI")
        marker.write_text(spec)
    freeze = subprocess.run([ENV_DIR / "bin" / "python", "-m", "pip", "freeze"], capture_output=True, text=True,
                            check=True).stdout  # fmt: skip
    return exe, "".join(sorted(line + "\n" for line in freeze.splitlines() if "==" in line))


def ansi_to_html(text: str) -> str:
    """SGR colours and weights become <span class>; every other escape sequence is dropped."""
    text = re.sub(
        r"\x1b\[\?[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[=>]", "", text.replace("\r\n", "\n").replace("\r", "")
    )
    out, state = [], set()
    pos = 0
    for m in re.finditer(r"\x1b\[([0-9;:]*)m", text):
        chunk = text[pos : m.start()]
        if chunk:
            esc = html.escape(chunk, quote=False)
            out.append(f'<span class="{" ".join(sorted(state))}">{esc}</span>' if state else esc)
        pos = m.end()
        codes = [int(c) if c.isdigit() else 0 for c in re.split(r"[;:]", m.group(1) or "0")]
        i = 0
        while i < len(codes):
            n = codes[i]
            if n in (38, 48, 58):  # 256 colours (5;n) or RGB (2;r;g;b): one unit, dropped (the site is 1-bit)
                i += (
                    3
                    if i + 1 < len(codes) and codes[i + 1] == 5
                    else 5
                    if i + 1 < len(codes) and codes[i + 1] == 2
                    else 1
                )
                if n == 38:
                    state = {s for s in state if not s.startswith("c")}
                continue
            if n == 0:
                state.clear()
            elif n in (1, 2, 3, 4, 7):
                state.add({1: "b", 2: "d", 3: "i", 4: "u", 7: "r"}[n])
            elif n == 22:
                state -= {"b", "d"}
            elif n in (23, 24, 27):
                state.discard({23: "i", 24: "u", 27: "r"}[n])
            elif 30 <= n <= 37 or 90 <= n <= 97:
                state = {s for s in state if not s.startswith("c")} | {f"c{n % 10}"}
            elif n == 39:
                state = {s for s in state if not s.startswith("c")}
            i += 1
    chunk = text[pos:]
    out.append(html.escape(chunk, quote=False))
    return re.sub(r"\x1b\[[0-9;:]*[A-Za-z]", "", "".join(out)).rstrip("\n")


def one_cell(html_text: str, covered: set[int]) -> str:
    """A character the site's terminal fonts (Terminus, Spleen) lack comes from another font, with another width, and
    breaks the columns of a box: such characters are wrapped to take exactly one cell (CSS class g)."""
    return "".join(f'<span class="g">{c}</span>' if ord(c) > 127 and ord(c) not in covered else c for c in html_text)


def terminus_chars(python: Path) -> set[int]:
    """The characters of the site's terminal fonts, Terminus then Spleen (both one cell wide, both bundled with
    bobina), read with bobina's fontTools."""
    code = (
        "from fontTools.ttLib import TTFont; from bobina.paths import fonts_dir; "
        "print(' '.join(str(c) for f in ('TerminusTTF-4.49.3.ttf', 'spleen-12x24.otf') "
        "for c in TTFont(fonts_dir() / f).getBestCmap()))"
    )
    out = subprocess.run([python, "-c", code], capture_output=True, text=True, check=True).stdout
    return {int(x) for x in out.split()}


def plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;:?]*[A-Za-z]", "", text.replace("\r\n", "\n").replace("\r", "")).rstrip("\n")


def run_tty(argv: list[str], cwd: Path, env: dict, keys: str | None) -> tuple[str, int]:
    pid, fd = pty.fork()
    if pid == 0:  # the child: never return into this script, whatever happens
        try:
            os.chdir(cwd)
            os.execvpe(argv[0], argv, env)
        except BaseException as e:
            os.write(2, f"capture: cannot run {argv[0]}: {e}\n".encode())
        finally:
            os._exit(127)
    buf, sent, status, deadline = b"", False, None, time.time() + 60
    while time.time() < deadline:  # read until the terminal closes (EOF, or EIO on Linux)
        ready, _, _ = select.select([fd], [], [], 0.5)
        if ready:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            buf += data
        elif keys and not sent and buf:
            os.write(fd, keys.encode())  # quiet with output on screen: the command waits for an answer
            sent = True
    while status is None and time.time() < deadline:  # then wait for the exit, which may come a moment later
        done, st = os.waitpid(pid, os.WNOHANG)
        if done:
            status = st
        else:
            time.sleep(0.05)
    os.close(fd)
    if status is None:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        fail(f"{shlex.join(argv)}: still running after 60 s")
    return buf.decode("utf-8", "replace"), os.waitstatus_to_exitcode(status)


def run(step: dict, bobina: Path, cwd: Path, env: dict, covered: set[int]) -> dict:
    argv = shlex.split(step["cmd"])
    argv[0] = str(bobina)
    if step.get("tty"):
        output, code = run_tty(argv, cwd, env, step.get("keys"))
    else:
        r = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=60)  # fmt: skip
        output, code = r.stdout.decode("utf-8", "replace"), r.returncode
    if code != step["expect"]:
        fail(f"`{step['cmd']}` exited {code}, expected {step['expect']}:\n{plain(output)}")
    return {"cmd": step["cmd"], "exit": code, "text": plain(output), "html": one_cell(ansi_to_html(output), covered)}


def check_staged(staged: Path, work: Path) -> None:
    """What would be written: no path of the capture folder or of a temporary folder, and no personal data."""
    for f in (x for x in staged.rglob("*") if x.is_file()):
        data = f.read_bytes()
        if str(work).encode() in data:
            fail(f"{f.name}: shows the capture folder")
        if f.suffix != ".png" and (m := TEMPORARY.search(data.decode("utf-8", "replace"))):
            fail(f"{f.name}: a temporary path ({m.group(0)}) in the output")
    scan = subprocess.run([sys.executable, str(ROOT / "tools" / "leakscan.py"), str(staged)])
    if scan.returncode != 0:
        fail("tools/leakscan.py found personal data in the captures (above)")


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--locked", action="store_true", help="install exactly the packages of capture/lock.txt")
    ap.add_argument("--bobina", help="use this bobina executable instead of the release from PyPI (a test run)")
    a = ap.parse_args()
    info = release()
    tree: Path = info["dir"]
    if a.bobina:
        bobina, lock = Path(shutil.which(a.bobina) or a.bobina).resolve(), None
        if not bobina.is_file():
            fail(f"--bobina: {a.bobina} is not a file")
    else:
        bobina, lock = bobina_for(info["version"], a.locked)
    python = python_of(bobina)
    version = subprocess.run([bobina, "--version"], capture_output=True, text=True, check=True).stdout.split()[-1]

    work = Path(tempfile.mkdtemp(prefix="bobina-capture-"))
    try:
        sources = {}
        for f in sorted((SITE / "examples").glob("*.bob.md")):
            sources[f.name] = ("site/examples/" + f.name, f)
        for rel in ("examples/batch/jar-label.bob.md", "examples/batch/pantry.csv"):
            sources[Path(rel).name] = (rel, tree / rel)
        gallery = sorted((tree / "examples" / "templates").glob("*.bob.md"))
        for f in gallery:
            sources[f.name] = ("examples/templates/" + f.name, f)
        for name, (_, src) in sources.items():
            shutil.copy(src, work / name)

        env = {
            "PATH": f"{bobina.parent}{os.pathsep}/usr/bin:/bin",
            "HOME": str(work / "home"),
            "BOBINA_CONFIG_DIR": str(work / "config"),
            "BOBINA_STATE_DIR": str(work / "state"),
            "BOBINA_NOW": NOW,
            "LANG": "C.UTF-8",
            "TERM": "xterm-256color",
            "COLUMNS": str(COLUMNS),
        }
        (work / "home").mkdir()
        # a file printer that keeps nothing: the casts really print, and no path of this machine shows up
        subprocess.run([bobina, "printer", "add", "test", "--path", "/dev/null"], env=env, cwd=work, check=True,
                       capture_output=True)  # fmt: skip

        covered = terminus_chars(python)
        casts = [
            {"id": c["id"], "title": c["title"], "steps": [run(s, bobina, work, env, covered) for s in c["steps"]]}
            for c in CASTS
        ]

        staged = work / "out"  # nothing is written into the site before every check passed
        (staged / "png").mkdir(parents=True)
        tickets = []

        def keep(tid: str, png: Path, group: str, file: str | None, label: str) -> None:
            dest = staged / "png" / f"{tid}.png"
            shutil.copy(png, dest)
            w, h = png_size(dest)
            tickets.append({"id": tid, "group": group, "png": f"/captures/{tid}.png", "width": w, "height": h,
                            "file": file, "label": label})  # fmt: skip

        todo = [(tid, name, args, "site") for tid, name, args in TICKETS]
        todo += [(f.name.removesuffix(".bob.md"), f.name, [], "gallery") for f in gallery]
        for tid, name, args, group in todo:
            out = work / "png" / f"{tid}.png"
            out.parent.mkdir(exist_ok=True)
            r = subprocess.run([bobina, "preview", name, *args, "-o", str(out)], cwd=work, env=env, capture_output=True)
            if r.returncode != 0:
                fail(f"bobina preview {name}: exit {r.returncode}\n{r.stderr.decode()}")
            keep(tid, out, group, name, name)

        for png in sorted((work / "labels").glob("*.png")):  # written by the batch cast
            tid = "label-" + re.sub(r"[^a-z0-9]+", "-", png.stem.lower()).strip("-")
            keep(tid, png, "batch", "jar-label.bob.md", f"labels/{png.name}")

        data = {
            "about": "Written by site/capture/capture.py from real bobina runs; do not edit.",
            "bobina": version,
            "release": info["ref"],
            "now": NOW,
            "files": {
                name: {"path": rel, "text": (work / name).read_text(encoding="utf-8")}
                for name, (rel, _) in sources.items()
            },
            "casts": casts,
            "tickets": tickets,
        }
        (staged / "captures.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        check_staged(staged, work)

        if OUT_PNG.exists():
            shutil.rmtree(OUT_PNG)
        shutil.copytree(staged / "png", OUT_PNG)
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(staged / "captures.json", OUT_JSON)
        if lock is not None and not a.locked:
            LOCK.write_text(
                f"# The packages that recorded the captures (capture.py writes it, --locked reads it)\n{lock}"
            )
        print(f"capture: bobina {version} ({info['ref']}): {len(casts)} casts, {len(tickets)} tickets")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
