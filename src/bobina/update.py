"""Is there a newer bobina, and how is this one upgraded (bobina update, and the notice at the end of a command).

The pattern of gh and npm: bobina never replaces its own files. It finds out what installed it (uv tool, pipx,
pip, Homebrew, the .deb, a git checkout) and says, or runs after asking, that installer's own upgrade command.
The newest version comes from PyPI's JSON API: one GET, a short timeout, nothing sent but the request. The
notice checks at most once a day and never speaks to agents, scripts or pipes."""

from __future__ import annotations

import json
import os
import platform
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import __version__, paths

URL = "https://pypi.org/pypi/bobina/json"
RELEASES = "https://github.com/rafaelbressan/bobina/releases"
TAP = "rafaelbressan/bobina/bobina"
TIMEOUT = 2.0
DAY = 24 * 3600
STABLE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class UpdateError(Exception):
    """PyPI could not be asked (no network, a timeout, an answer bobina cannot read)."""


def parse(version: str) -> tuple[int, int, int] | None:
    """0.1.3 -> (0, 1, 3); None for anything else (0.2.0rc1, 0.1.0.dev0, a local build): only releases count."""
    m = STABLE.fullmatch(str(version).strip())
    return tuple(int(x) for x in m.groups()) if m else None


def fetch(timeout: float = TIMEOUT) -> str:
    """The newest stable bobina on PyPI. Raises UpdateError."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(URL, headers={"User-Agent": f"bobina/{__version__}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - a fixed https URL
            data = json.loads(r.read(2_000_000))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError(f"PyPI did not answer ({getattr(e, 'reason', None) or e})") from None
    return newest(data)


def newest(data: dict) -> str:
    """The highest stable version with files that are not all yanked; PyPI's info.version when none."""
    found = []
    for v, files in (data.get("releases") or {}).items():
        if parse(v) and files and not all(f.get("yanked") for f in files if isinstance(f, dict)):
            found.append(v)
    if found:
        return max(found, key=parse)
    v = str((data.get("info") or {}).get("version") or "")
    if not parse(v):
        raise UpdateError("PyPI's answer has no bobina release")
    return v


def newer(latest: str | None, current: str | None = None) -> bool:
    a, b = parse(latest or ""), parse(__version__ if current is None else current)
    return bool(a and b and a > b)


# ---------------------------------------------------------------------------------------------- how it was installed


@dataclass
class Install:
    kind: str  # uv | pipx | pip | homebrew | deb | git | dev | unknown
    what: str  # said to the person: "uv tool", "the .deb", …
    command: list[str] | None = None  # the upgrade command, when bobina may run it (after asking)
    shown: str = ""  # the command (or steps) as said; also when it is not run (sudo, a download)
    note: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "installed_by": self.what, "command": self.shown, "runnable": bool(self.command)}


def _direct_url() -> dict | None:
    """PEP 610: how pip/uv installed bobina when it did not come from an index (a git URL, a folder)."""
    try:
        from importlib.metadata import distribution

        text = distribution("bobina").read_text("direct_url.json")
    except Exception:  # noqa: BLE001 - not installed as a distribution (a bare checkout on sys.path)
        return None
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def _deb_arch() -> str:
    m = platform.machine().lower()
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(m, m or "amd64")


def _quote(p: str) -> str:
    import shlex

    return shlex.quote(p)


def detect(latest: str | None = None, *, prefix: str | None = None, module: str | None = None) -> Install:
    """What installed the running bobina. prefix/module are for tests (sys.prefix, bobina's folder)."""
    prefix = prefix if prefix is not None else sys.prefix
    module = module if module is not None else str(Path(__file__).resolve().parent)
    p, m = Path(prefix), module.replace("\\", "/")
    version = latest or "X.Y.Z"
    if m.startswith("/usr/lib/bobina/"):  # contrib/deb/launcher.py puts /usr/lib/bobina/common first
        deb = f"bobina_{version}_{_deb_arch()}.deb"
        url = f"{RELEASES}/download/v{version}/{deb}" if latest else f"{RELEASES}/latest"
        return Install("deb", "the .deb", None, f"download {url}, then: sudo apt install ./{deb}",
                       "there is no apt repository: each release has its .deb")  # fmt: skip
    if "/Cellar/bobina/" in prefix.replace("\\", "/"):
        return Install("homebrew", "Homebrew", ["brew", "upgrade", TAP], f"brew upgrade {TAP}")
    direct = _direct_url()
    if direct and (direct.get("dir_info") or {}).get("editable"):
        return Install("dev", "an editable checkout", None, "git pull in the checkout (it runs from the source)")
    if (p / "uv-receipt.toml").exists():
        base = getattr(sys, "_base_executable", "") or sys.executable
        if direct:  # uv tool install from a git URL or a folder: upgrade would fetch the same source again
            src = direct.get("url", "a git URL or a folder")
            return Install("git", f"uv tool, from {src}", None,
                           f"uv tool install --force --python {_quote(base)} bobina   (the release on PyPI)",
                           "installed from a source, not a release")  # fmt: skip
        return Install("uv", "uv tool", ["uv", "tool", "upgrade", "bobina"], "uv tool upgrade bobina",
                       "uv keeps the same Python (the one with Bluetooth sockets)")  # fmt: skip
    if "/pipx/venvs/bobina" in prefix.replace("\\", "/"):
        if direct:
            return Install("git", f"pipx, from {direct.get('url', 'a source')}", None,
                           "pipx install --force bobina   (the release on PyPI)")  # fmt: skip
        return Install("pipx", "pipx", ["pipx", "upgrade", "bobina"], "pipx upgrade bobina")
    if direct:
        return Install("git", f"pip, from {direct.get('url', 'a source')}", None,
                       f"{_quote(sys.executable)} -m pip install --upgrade bobina   (the release on PyPI)")  # fmt: skip
    if sys.prefix != sys.base_prefix:  # a virtual environment
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "bobina"]
        return Install("pip", "pip, in a virtual environment", cmd, " ".join(_quote(c) for c in cmd))
    import site

    user = getattr(site, "getusersitepackages", lambda: "")()
    if user and m.startswith(str(Path(user).resolve()).replace("\\", "/")):
        cmd = [sys.executable, "-m", "pip", "install", "--user", "--upgrade", "bobina"]
        return Install("pip", "pip --user", cmd, " ".join(_quote(c) for c in cmd))
    return Install("unknown", "something bobina does not recognise", None,
                   f"the command of what installed it: uv tool upgrade bobina, pipx upgrade bobina, brew upgrade "
                   f"{TAP}, or the .deb of the release ({RELEASES})")  # fmt: skip


# ------------------------------------------------------------------------------------------------------ the notice


def _state() -> Path:
    return paths.state_dir() / "update.json"


def _read() -> dict:
    try:
        d = json.loads(_state().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(d: dict) -> None:
    try:
        from . import fileio

        _state().parent.mkdir(parents=True, exist_ok=True)
        fileio.write_json(_state(), d, durable=False)
    except Exception:  # noqa: BLE001 - a notice must never turn a finished command into an error
        pass


def _terminal() -> bool:
    """stderr is a person's terminal (not a pipe, a file or a captured stream)."""
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


def wanted(args, cmd: str, problem_format: str) -> bool:
    """The notice speaks to a person at a terminal only (never agents, MCP, scripts, pipes, CI, --json, -q)."""
    from . import config, config_keys

    if cmd in ("mcp", "update", "help") or not parse(__version__):
        return False
    if os.environ.get("CI") or os.environ.get("BOBINA_NONINTERACTIVE", "").strip().lower() not in (
        "",
        "0",
        "false",
        "no",
    ):
        return False
    if getattr(args, "quiet", False) or getattr(args, "json", False) or problem_format in ("json", "jsonl"):
        return False
    if not _terminal():
        return False
    try:
        return config_keys.read(config.load(), "update_check") is not False
    except Exception:  # noqa: BLE001 - a broken config.toml is said by the command itself
        return False


class Check:
    """Asks PyPI in a background thread started with the command (at most once a day): the command never waits
    for the network, and at its end the notice is said if the answer came in time."""

    def __init__(self):
        self.thread = None
        self.latest: str | None = None

    def start(self) -> None:
        import threading

        last = _read().get("checked")
        if isinstance(last, (int, float)) and 0 <= time.time() - last < DAY:
            return  # asked today (a date in the future, a changed clock: asked again)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            self.latest = fetch()
        except UpdateError:
            self.latest = None
        except Exception:  # noqa: BLE001 - a background check never surfaces
            self.latest = None
        _write({"checked": time.time(), "latest": self.latest})  # a failed check also waits a day: no retry storm

    def finish(self, wait: float = 1.0) -> str:
        """The notice line, or "" (nothing newer, no answer in time, or no check today)."""
        if self.thread is None:
            return ""
        self.thread.join(wait)
        if self.thread.is_alive() or not newer(self.latest):
            return ""
        how = detect(self.latest)
        if how.kind == "dev":  # an editable checkout: its developer pulls, a release notice would only be noise
            return ""
        how_to = how.shown if how.command else "bobina update"  # a .deb or a source: bobina update says the steps
        return f"bobina {self.latest} is available (you have {__version__}): {how_to}"
