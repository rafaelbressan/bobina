#!/usr/bin/env python3
"""Record what the site shows of bobina: terminal casts and tickets, from real commands on real files.

Runs the released bobina (installed from PyPI into site/.capture-venv, the version of site/.release/release.json)
on the site's examples (site/examples/) and the release's own (examples/). Writes src/captures/captures.json (each
cast: the command lines, their output as HTML and their exit codes) and public/captures/*.png (each ticket:
`bobina preview` of a file shown next to it). Nothing here is drawn by hand; run it again after each release:

    cd site && npm run capture        # = node scripts/release.mjs && python3 capture/capture.py

It stops, writing nothing, when a command exits with another code than expected or when an output holds a home
folder, a temporary path or a Bluetooth address that is not the documented example. The build checks that the
captures are of the release it describes."""

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
OUT_JSON = SITE / "src" / "captures" / "captures.json"
OUT_PNG = SITE / "public" / "captures"
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

LEAKS = {
    "home folder": re.compile(r"/(?:home|Users|root)/[\w.-]+"),
    "temporary path": re.compile(r"/(?:tmp|var/folders|private)/"),
    "bluetooth address": re.compile(
        r"(?<![0-9A-Fa-f:])(?!AA:BB:CC:DD:EE:FF)[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}(?![0-9A-Fa-f:])"
    ),
}


def fail(msg: str) -> None:
    sys.exit(f"capture: {msg}")


def release() -> dict:
    path = SITE / ".release" / "release.json"
    if not path.exists():
        fail("no .release/release.json: run `node scripts/release.mjs` first (npm run capture does both)")
    info = json.loads(path.read_text())
    info["dir"] = (SITE / info["root"]).resolve()
    return info


def bobina_for(version: str, given: str | None) -> Path:
    """The bobina that the site describes: VERSION from PyPI, in a venv of its own."""
    if given:
        return Path(given)
    env_dir = SITE / ".capture-venv"
    exe = env_dir / "bin" / "bobina"  # POSIX only, like the pseudo-terminal the casts need
    current = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout if exe.exists() else ""
    if current.strip() != f"bobina {version}":
        if not exe.exists():
            venv.create(env_dir, with_pip=True)
        pip = [str(env_dir / "bin" / "python"), "-m", "pip", "install", "--quiet", "--index-url"]
        subprocess.run([*pip, "https://pypi.org/simple", f"bobina=={version}"], check=True)
    return exe


def ansi_to_html(text: str) -> str:
    """SGR colours and weights become <span class>; every other escape sequence is dropped."""
    text = re.sub(
        r"\x1b\[\?[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[=>]", "", text.replace("\r\n", "\n").replace("\r", "")
    )
    out, state = [], set()
    pos = 0
    for m in re.finditer(r"\x1b\[([0-9;]*)m", text):
        chunk = text[pos : m.start()]
        if chunk:
            esc = html.escape(chunk, quote=False)
            out.append(f'<span class="{" ".join(sorted(state))}">{esc}</span>' if state else esc)
        pos = m.end()
        for code in (m.group(1) or "0").split(";"):
            n = int(code or 0)
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
    chunk = text[pos:]
    out.append(html.escape(chunk, quote=False))
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", "".join(out)).rstrip("\n")


def one_cell(html_text: str, covered: set[int]) -> str:
    """A character the site's terminal fonts (Terminus, Spleen) lack comes from another font, with another width, and
    breaks the columns of a box: such characters are wrapped to take exactly one cell (CSS class g)."""
    return "".join(f'<span class="g">{c}</span>' if ord(c) > 127 and ord(c) not in covered else c for c in html_text)


def terminus_chars(bobina: Path) -> set[int]:
    """The characters of the site's terminal fonts, Terminus then Spleen (both one cell wide, both bundled with
    bobina), read with bobina's fontTools."""
    code = (
        "from fontTools.ttLib import TTFont; from bobina.paths import fonts_dir; "
        "print(' '.join(str(c) for f in ('TerminusTTF-4.49.3.ttf', 'spleen-12x24.otf') "
        "for c in TTFont(fonts_dir() / f).getBestCmap()))"
    )
    out = subprocess.run([bobina.parent / "python", "-c", code], capture_output=True, text=True, check=True).stdout
    return {int(x) for x in out.split()}


def plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text.replace("\r\n", "\n").replace("\r", "")).rstrip("\n")


def run_tty(argv: list[str], cwd: Path, env: dict, keys: str | None) -> tuple[str, int]:
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        os.execvpe(argv[0], argv, env)
    buf, sent, deadline = b"", False, time.time() + 60
    while time.time() < deadline:
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
            os.write(fd, keys.encode())  # the command is waiting for an answer
            sent = True
        elif os.waitpid(pid, os.WNOHANG)[0]:
            break
    done, status = os.waitpid(pid, os.WNOHANG)
    if not done:
        os.kill(pid, signal.SIGKILL)
        _, status = os.waitpid(pid, 0)
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


def check_leaks(where: str, text: str, work: Path) -> None:
    if str(work) in text:
        fail(f"{where}: shows the capture folder")
    for name, rx in LEAKS.items():
        if m := rx.search(text):
            fail(f"{where}: a {name} ({m.group(0)!r}) in the output")


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bobina", help="use this bobina executable instead of the release from PyPI (a test run)")
    a = ap.parse_args()
    info = release()
    tree: Path = info["dir"]
    bobina = bobina_for(info["version"], a.bobina)
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

        casts, covered = [], terminus_chars(bobina)
        for cast in CASTS:
            steps = [run(step, bobina, work, env, covered) for step in cast["steps"]]
            for s in steps:
                check_leaks(f"cast {cast['id']}: {s['cmd']}", s["text"], work)
            casts.append({"id": cast["id"], "title": cast["title"], "steps": steps})

        if OUT_PNG.exists():
            shutil.rmtree(OUT_PNG)
        OUT_PNG.mkdir(parents=True)
        tickets = []

        def keep(tid: str, png: Path, group: str, file: str | None, label: str) -> None:
            dest = OUT_PNG / f"{tid}.png"
            shutil.copy(png, dest)
            w, h = png_size(dest)
            tickets.append({"id": tid, "group": group, "png": f"/captures/{tid}.png", "width": w, "height": h,
                            "file": file, "label": label})  # fmt: skip

        todo = [(tid, name, args, "site") for tid, name, args in TICKETS]
        todo += [(f.name.removesuffix(".bob.md"), f.name, [], "gallery") for f in gallery]
        for tid, name, args, group in todo:
            out = work / "png" / f"{tid}.png"
            out.parent.mkdir(exist_ok=True)
            step = {"cmd": shlex.join(["bobina", "preview", name, *args, "-o", str(out)]), "expect": 0}
            r = subprocess.run([bobina, *shlex.split(step["cmd"])[1:]], cwd=work, env=env, capture_output=True)
            if r.returncode != 0:
                fail(f"{step['cmd']}: exit {r.returncode}\n{r.stderr.decode()}")
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
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        check_leaks("captures.json", OUT_JSON.read_text(encoding="utf-8"), work)
        print(f"capture: bobina {version} ({info['ref']}): {len(casts)} casts, {len(tickets)} tickets")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
