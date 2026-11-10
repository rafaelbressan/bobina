"""Which editor opens: --editor > config `editor` > $VISUAL > $EDITOR > nano > vi (Notepad on Windows).
GUI editors return immediately unless told to wait; known ones get the flag automatically."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess

WAIT_FLAGS = {
    "code": "--wait",
    "code-insiders": "--wait",
    "cursor": "--wait",
    "codium": "--wait",
    "windsurf": "--wait",
    "subl": "-w",
    "zed": "--wait",
    "mate": "-w",
    "gedit": "--wait",
}


def resolve(flag: str | None, cfg: dict) -> list[str]:
    cmd = flag or cfg.get("editor") or os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not cmd:
        for c in ("nano", "vi"):
            if shutil.which(c):
                cmd = c
                break
        else:
            cmd = "notepad" if os.name == "nt" else "vi"
    argv = shlex.split(cmd)
    base = os.path.basename(argv[0]).removesuffix(".exe").removesuffix(".cmd")
    flag_ = WAIT_FLAGS.get(base)
    if flag_ and flag_ not in argv:
        argv.append(flag_)
    return argv


def open_file(path, flag: str | None, cfg: dict) -> int:
    argv = resolve(flag, cfg) + [str(path)]
    try:
        tty = open("/dev/tty", "r+") if os.name != "nt" else None  # noqa: SIM115 - closed in finally below
    except OSError:
        tty = None
    try:
        return subprocess.call(argv, stdin=tty, stdout=tty) if tty else subprocess.call(argv)
    finally:
        if tty:
            tty.close()


RULER = (
    "<!-- ruler, 32 columns of the native font (other fonts: trust the preview):\n"
    "----+----1----+----2----+----3--\n"
    "-->\n"
)
