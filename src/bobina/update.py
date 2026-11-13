"""Is there a newer bobina, and how is this one upgraded (bobina update, and the notice at the end of a command).

The pattern of gh and npm: bobina never replaces its own files. It finds out what installed it (uv tool, pipx,
pip, Homebrew, the .deb, a git checkout) and says, or runs after asking, that installer's own upgrade command.
The newest version comes from PyPI's JSON API: one GET, a short timeout, nothing sent but the request. The
notice asks PyPI at most once a day, speaks at most once a day, and never to agents, scripts or pipes."""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
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
    """The newest stable bobina on PyPI. Raises UpdateError, whatever went wrong on the way."""
    import urllib.request

    req = urllib.request.Request(URL, headers={"User-Agent": f"bobina/{__version__}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - a fixed https URL
            data = json.loads(r.read(2_000_000))
    except Exception as e:  # noqa: BLE001 - URLError, OSError, http.client errors, bad JSON: all "no answer"
        raise UpdateError(f"PyPI did not answer ({getattr(e, 'reason', None) or e})") from None
    return newest(data)


def newest(data) -> str:
    """The highest stable version with files that are not all yanked; PyPI's info.version when none."""
    if not isinstance(data, dict):
        raise UpdateError("PyPI's answer is not what bobina expects")
    releases = data.get("releases")
    found = []
    for v, files in (releases if isinstance(releases, dict) else {}).items():
        yanked = isinstance(files, list) and all(isinstance(f, dict) and f.get("yanked") for f in files)
        if parse(v) and isinstance(files, list) and files and not yanked:
            found.append(v)
    if found:
        return max(found, key=parse)
    info = data.get("info")
    v = str((info if isinstance(info, dict) else {}).get("version") or "")
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
    command: list[str] | None = None  # the upgrade command bobina may run (after asking); None: it never runs one
    line: str = ""  # a command to copy into a shell ("" when the way is not one command: a download, git pull)
    steps: str = ""  # what to do, in words, when it is not one command
    note: str = ""

    @property
    def shown(self) -> str:
        return self.line or self.steps

    def as_dict(self) -> dict:
        return {"kind": self.kind, "installed_by": self.what, "command": self.line, "steps": self.steps,
                "runnable": bool(self.command)}  # fmt: skip


def _direct_url() -> dict | None:
    """PEP 610: how pip/uv installed bobina when it did not come from an index (a git URL, a folder)."""
    try:
        from importlib.metadata import distribution

        text = distribution("bobina").read_text("direct_url.json")
    except Exception:  # noqa: BLE001 - not installed as a distribution (a bare checkout on sys.path)
        return None
    try:
        d = json.loads(text) if text else None
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def _deb_arch() -> str:
    m = platform.machine().lower()
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(m, m or "amd64")


def _join(cmd: list[str]) -> str:
    return " ".join(shlex.quote(c) for c in cmd)


def _norm(p: str) -> str:
    return str(p).replace("\\", "/")


def detect(latest: str | None = None, *, prefix: str | None = None, module: str | None = None) -> Install:
    """What installed the running bobina, from markers each installer leaves (not from where it happens to be
    reached through: Homebrew runs it through an opt/ symlink, pipx may live under any PIPX_HOME). prefix/module
    are for tests (sys.prefix, bobina's folder)."""
    prefix = prefix if prefix is not None else sys.prefix
    module = module if module is not None else str(Path(__file__).resolve().parent)
    p = Path(prefix)
    real = _norm(p.resolve()) if p.exists() else _norm(prefix)
    m = _norm(module)
    version = latest or "X.Y.Z"
    if m.startswith("/usr/lib/bobina/"):  # contrib/deb/launcher.py puts /usr/lib/bobina/common first
        deb = f"bobina_{version}_{_deb_arch()}.deb"
        url = f"{RELEASES}/download/v{version}/{deb}" if latest else f"{RELEASES}/latest"
        return Install("deb", "the .deb", steps=f"download {url}, then: sudo apt install ./{deb}",
                       note="there is no apt repository: each release has its .deb")  # fmt: skip
    if "/Cellar/bobina/" in real or "/Cellar/bobina/" in m:
        return Install("homebrew", "Homebrew", ["brew", "upgrade", TAP], f"brew upgrade {TAP}")
    direct = _direct_url()
    if direct and (direct.get("dir_info") or {}).get("editable"):
        return Install("dev", "an editable checkout", steps="git pull in the checkout (it runs from the source)")
    src = (direct or {}).get("url", "a source")
    if (p / "uv-receipt.toml").exists():
        if direct:  # uv tool install from a git URL or a folder: upgrade would fetch the same source again
            base = getattr(sys, "_base_executable", "") or sys.executable
            return Install("git", f"uv tool, from {src}", None,
                           _join(["uv", "tool", "install", "--force", "--python", base, "bobina"]),
                           note="installed from a source: this command moves it to the release on PyPI")  # fmt: skip
        return Install("uv", "uv tool", ["uv", "tool", "upgrade", "bobina"], "uv tool upgrade bobina",
                       note="uv keeps the same Python (the one with Bluetooth sockets)")  # fmt: skip
    if (p / "pipx_metadata.json").exists() or "/pipx/venvs/bobina" in real:
        if direct:
            return Install("git", f"pipx, from {src}", None, "pipx install --force bobina",
                           note="installed from a source: this command moves it to the release on PyPI")  # fmt: skip
        return Install("pipx", "pipx", ["pipx", "upgrade", "bobina"], "pipx upgrade bobina")
    pip = [sys.executable, "-m", "pip", "install", "--upgrade", "bobina"]
    if direct:
        return Install("git", f"pip, from {src}", None, _join(pip),
                       note="installed from a source: this command moves it to the release on PyPI")  # fmt: skip
    if sys.prefix != sys.base_prefix:  # a virtual environment of its own
        return Install("pip", "pip, in a virtual environment", pip, _join(pip))
    import site

    user = getattr(site, "getusersitepackages", lambda: "")()
    if user and m.startswith(_norm(Path(user).resolve())):
        cmd = [sys.executable, "-m", "pip", "install", "--user", "--upgrade", "bobina"]
        return Install("pip", "pip --user", cmd, _join(cmd))
    return Install("unknown", "something bobina does not recognise",
                   steps=f"the upgrade of what installed it: uv tool upgrade bobina, pipx upgrade bobina, brew upgrade "
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
    """A person's terminal on both stdout and stderr: `bobina history | less` or `x=$(bobina status)` is a script."""
    try:
        return sys.stdout.isatty() and sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


def _fresh(ts) -> bool:
    """A time within the last day (one in the future, from a changed clock, is not)."""
    return isinstance(ts, (int, float)) and 0 <= time.time() - ts < DAY


def wanted(args, cmd: str, problem_format: str) -> bool:
    """The notice speaks to a person at a terminal only (never agents, MCP, scripts, pipes, CI, --json, -q)."""
    from . import config, config_keys
    from .cli.common import noninteractive

    if cmd in ("mcp", "update", "help") or not parse(__version__):
        return False
    if os.environ.get("CI") or noninteractive():
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
    """Asks PyPI in a background thread started with the command, when the last answer is older than a day: the
    command never waits for the network (at most WAIT at its end). The answer is kept in update.json, so a check
    that ended after the command still tells the next one. The notice is said at most once a day."""

    WAIT = 1.0

    def __init__(self):
        self.thread = None
        self.latest: str | None = None

    def start(self) -> None:
        import threading

        st = _read()
        self.latest = st.get("latest") if isinstance(st.get("latest"), str) else None
        if _fresh(st.get("checked")):
            return
        # the attempt is written first: a check cut off when bobina exits (slow DNS, a captive portal) waits a day
        # too, instead of slowing every command down by WAIT
        _write({**st, "checked": time.time()})
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            latest = fetch()
        except Exception:  # noqa: BLE001 - a background check never surfaces
            return
        self.latest = latest
        _write({**_read(), "checked": time.time(), "latest": latest})

    def finish(self) -> str:
        """The notice line, or "" (nothing newer, said today already, or an editable checkout)."""
        if self.thread is not None:
            try:
                self.thread.join(self.WAIT)
            except KeyboardInterrupt:  # Ctrl-C while waiting for PyPI: the command itself had ended
                return ""
        if not newer(self.latest):
            return ""
        st = _read()
        if _fresh(st.get("said")):
            return ""
        how = detect(self.latest)
        if how.kind == "dev":  # an editable checkout: its developer pulls, a release notice would only be noise
            return ""
        _write({**st, "said": time.time()})
        how_to = how.line if how.command else "bobina update"  # a .deb or a source: bobina update says the steps
        return f"bobina {self.latest} is available (you have {__version__}): {how_to}"
