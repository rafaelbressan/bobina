"""Safe writes for bobina's own files (counters, paper, history, library, config, last job).

Two bobina commands can run at the same time (two terminals, a script, the tower over ssh). Every state file
is therefore written whole or not at all (atomic_write: temp file in the same folder + os.replace) and every
read-modify-write runs under a file lock (locked / locked_update), so one command never loses the other's
change. A damaged file is an error (StateError), never silently replaced by an empty one: an empty counters
file would restart the numbering and print repeated numbers.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path


class StateError(Exception):  # not a ValueError: document-error handlers must not swallow it
    """A bobina state file exists but cannot be read."""

    code = "E209"


class LockTimeout(TimeoutError):
    pass


def atomic_write(
    path: Path, data: bytes | str, durable: bool = True, encoding: str = "utf-8", mode: int | None = None
) -> None:
    """Readers see the old content or the new one, never a part. durable=False skips fsync (still atomic for
    other processes; only a power cut can lose the write). mode: permissions of the result (default 0600,
    right for bobina's own state; files the user asked for use public_mode)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = data.encode(encoding) if isinstance(data, str) else data
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        if mode is not None:
            os.chmod(tmp, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            if durable:
                f.flush()
                os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _read_umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


_UMASK = _read_umask()  # read once, at import (single-threaded): os.umask is process-wide


def public_mode(path: Path) -> int:
    """The permissions a normal write would give: the existing file's, or 0666 minus the umask."""
    import stat

    try:
        return stat.S_IMODE(Path(path).stat().st_mode)
    except OSError:
        return 0o666 & ~_UMASK


@contextlib.contextmanager
def atomic_output(path: Path):
    """A file the user asked for (-o), as a binary file object: written to a temporary file in the same folder,
    synced and renamed over the target only when the block ends without error (else removed). A symlink is
    followed (its target is replaced, the link stays); permissions are those of a normal write."""
    path = Path(path).expanduser()
    target = path.resolve() if path.is_symlink() else path
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        os.chmod(tmp, public_mode(target))
        with os.fdopen(fd, "wb") as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def write_output(path: Path, data: bytes) -> None:
    """-o FILE. A device (/dev/stdout, a printer) is written straight. A FIFO is written only when something
    reads it (never a wait forever). A regular file is written whole or not at all (atomic_output)."""
    import errno
    import stat

    path = Path(path).expanduser()
    try:
        st = path.stat()
    except OSError:
        st = None
    if st is not None and stat.S_ISFIFO(st.st_mode):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as e:
            if e.errno == errno.ENXIO:
                raise OSError(errno.ENXIO, "nothing is reading this pipe", str(path)) from None
            raise
        os.set_blocking(fd, True)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return
    if st is not None and not stat.S_ISREG(st.st_mode):
        with open(path, "wb") as f:
            f.write(data)
        return
    with atomic_output(path) as f:
        f.write(data)


def fsync_file(path: Path) -> None:
    with contextlib.suppress(OSError), open(path, "rb+") as f:
        os.fsync(f.fileno())


def _try_lock(f) -> bool:
    if sys.platform == "win32":
        import msvcrt

        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _unlock(f) -> None:
    if sys.platform == "win32":
        import msvcrt

        with contextlib.suppress(OSError):
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def lock_path(path: Path) -> Path:
    path = Path(path)
    return path.with_name(path.name + ".lock")


@contextlib.contextmanager
def locked(path: Path, timeout: float | None = 30.0, on_wait=None):
    """Exclusive lock on PATH.lock (the data file itself is replaced by atomic_write, so it cannot hold the lock).
    on_wait() is called once if another process holds it; LockTimeout after `timeout` seconds (None: wait)."""
    lp = lock_path(path)
    lp.parent.mkdir(parents=True, exist_ok=True)
    with open(lp, "a+b") as f:
        if not _try_lock(f):
            if on_wait:
                on_wait()
            deadline = None if timeout is None else time.monotonic() + timeout
            while not _try_lock(f):
                if deadline is not None and time.monotonic() > deadline:
                    raise LockTimeout(f"{path.name} is held by another bobina command for more than {timeout:.0f} s")
                time.sleep(0.05)
        try:
            yield
        finally:
            _unlock(f)


def read_json(path: Path, default):
    """The file's JSON, `default` when it does not exist; StateError when it exists but is damaged."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except OSError as e:
        raise StateError(f"cannot read {path}: {e.strerror or e}") from e
    try:
        data = json.loads(text)
    except ValueError as e:
        raise StateError(f"{path} is damaged ({e.__class__.__name__}: {e})") from e
    if not isinstance(data, type(default)):
        raise StateError(f"{path} is damaged (expected a JSON {type(default).__name__})")
    return data


def write_json(path: Path, data, durable: bool = True) -> None:
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False), durable=durable)


def locked_update(path: Path, fn, default=None, durable: bool = True):
    """Reads PATH (JSON) under its lock, lets fn(data) change it in place, writes it atomically and returns what
    fn returned. A damaged file raises StateError before fn runs: nothing is overwritten."""
    with locked(path):
        data = read_json(path, {} if default is None else default)
        out = fn(data)
        write_json(path, data, durable=durable)
        return out
