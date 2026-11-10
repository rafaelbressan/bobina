"""Getting bytes to the printer: Bluetooth RFCOMM, a file, or a command (e.g. ssh to the host
that has the printer)."""

from __future__ import annotations

import contextlib
import errno
import re
import shlex
import socket
import subprocess
import sys
import time


class SendFailed(Exception):
    """The link failed after part of the job was sent: some of it may be on paper."""

    def __init__(self, message: str, sent: int):
        super().__init__(message)
        self.sent = sent


class PrinterUnreachable(Exception):
    pass


def _bt_connect(mac: str, channel: int, timeout: float = 15):
    if not hasattr(socket, "AF_BLUETOOTH"):
        raise PrinterUnreachable(
            "this Python has no Bluetooth sockets (WSL, macOS, or a Python built without them, like uv's and"
            " Homebrew's: reinstall bobina with the system Python, see docs/INSTALL.md) — or use a 'command'"
            " printer via ssh"
        )
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.settimeout(timeout)
    s.connect((mac, channel))
    return s


STATUS_QUERIES = [b"\x10\x04\x01", b"\x10\x04\x02", b"\x10\x04\x03", b"\x10\x04\x04"]


def _connect(mac: str, channel: int, log=None, full: bool = True, timeout: float = 15):
    """An RFCOMM link, recovering a stale one: a job that failed (paper out, out of range) can leave the link busy
    (EBUSY) until it is dropped. full (prints): any failure also tries bluetoothctl connect. Not full (status
    queries): only EBUSY is recovered, so a printer that is off fails after one timeout, not after a minute."""
    try:
        return _bt_connect(mac, channel, timeout)
    except OSError as e:
        busy = e.errno == errno.EBUSY
        if not (full or busy):
            raise PrinterUnreachable(f"printer {mac} unreachable: {e}. Is it on (steady yellow LED)?") from e
        if log:
            log(f"connection failed ({e}); recovering Bluetooth…", file=sys.stderr)
        if busy:  # stale ACL link right after another connection (never another bobina job: the lock is held)
            _bluetoothctl("disconnect", mac, 10)
            time.sleep(3)
        if full:
            _bluetoothctl("connect", mac, 20)
        try:
            return _bt_connect(mac, channel, timeout)
        except OSError as e2:
            raise PrinterUnreachable(f"printer {mac} unreachable: {e2}. Is it on (steady yellow LED)?") from e2


def _ask(s, q: bytes, timeout: float = 1.5):
    s.settimeout(timeout)
    s.sendall(q)
    try:
        return s.recv(16)
    except OSError:
        return None


STALL_S = 20.0  # the queue did not shrink for this long: the printer stopped taking bytes (off, jammed, no paper)
MAX_DRAIN_S = 600.0  # a bound even for a queue that keeps creeping


def _unsent(s) -> int | None:
    """Bytes of this socket still queued in the kernel, or None when the kernel cannot tell. For Bluetooth sockets
    TIOCOUTQ is the FREE space of the send buffer (bt_sock_ioctl), not the queued bytes as for TCP: idle, it equals
    SO_SNDBUF (checked on the tower 08/11: 50800 and 50800)."""
    if getattr(s, "family", None) != getattr(socket, "AF_BLUETOOTH", object()):
        return None  # TIOCOUTQ means queued bytes elsewhere (TCP): this reading is only right for Bluetooth
    try:
        import fcntl
        import struct
        import termios

        free = struct.unpack("i", fcntl.ioctl(s.fileno(), termios.TIOCOUTQ, b"\0\0\0\0"))[0]
        return max(0, s.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF) - free)
    except (OSError, AttributeError, ValueError, ImportError):
        return None


GS_V0 = b"\x1dv0"
TAIL_MAX = 128  # bytes after the last image that count as the end of the job (feeds, a --marks line, status)


def _split_tail(data: bytes) -> tuple[bytes, bytes]:
    """(job, tail): the few commands after the last raster block (GS v 0), when the job ends with an image.

    The MTP-II drops what arrives while it prints a big image: the final feed after a 29 KB strip never happened,
    and a status request after it was never answered, while the same feed sent once the image had printed worked
    (08/11, tests with 1 to 3 bands). So the end of such a job is sent only when the printer is idle again.
    With escpos.blank_rows_after_raster the final feed is itself white raster bands: then there is no tail, and none
    is needed, since what got lost were commands that are not images (ESC J, GS r)."""
    end, i = None, data.find(GS_V0)
    while i != -1 and i + 8 <= len(data):
        w, h = data[i + 4] + 256 * data[i + 5], data[i + 6] + 256 * data[i + 7]
        if h > 1:  # a 1-row block is a --marks line inside the final feed: part of the end, not the image
            end = i + 8 + w * h
        i = data.find(GS_V0, i + 8 + w * h)
    if end is None or end > len(data) or not 0 < len(data) - end <= TAIL_MAX:  # no image, a truncated one, or more
        return data, b""  # than a few commands after it: sent as one stream
    return data[:end], data[end:]


def _wait_idle(s, max_s: float) -> bool:
    """Asks GS r 1 until it is answered: while printing an image the MTP-II drops the request (no answer, no side
    effect), once idle it answers at once. The wait between asks doubles from 0.5 s to 4 s, so a printer that never
    answers gets a handful of requests, not one every half second. A closed link is an error, not 'idle'."""
    t0 = time.monotonic()
    wait = 0.5
    while time.monotonic() - t0 < max_s:
        s.settimeout(wait)
        s.sendall(b"\x1dr\x01")
        wait = min(4.0, wait * 2)
        try:
            reply = s.recv(16)
        except TimeoutError:
            continue
        if not reply:
            raise ConnectionResetError("the printer closed the link while printing the image")
        _flush_input(s)  # a printer that answers late instead of dropping: later answers must not pass as the
        return True  # confirmation of the end of the job
    return False


def _flush_input(s, limit: int = 32) -> None:
    s.settimeout(0.2)
    with contextlib.suppress(OSError):
        for _ in range(limit):
            if not s.recv(64):
                break


def _drain(s) -> bool | None:
    """Waits while the queue of the socket keeps moving. True: everything left the computer. False: it stopped
    moving (or took absurdly long). None: the kernel cannot tell."""
    t0 = last_move = time.monotonic()
    left = _unsent(s)
    while left:
        now = time.monotonic()
        if now - last_move > STALL_S or now - t0 > MAX_DRAIN_S:
            return False
        time.sleep(0.25)
        now_left = _unsent(s)
        if now_left is None:
            return None
        if now_left < left:
            last_move = time.monotonic()
        left = now_left
    return None if left is None else True


def bluetooth(
    data: bytes,
    mac: str,
    channel: int = 1,
    chunk: int = 4096,
    pause: float = 0.0,
    log=print,
    precheck=None,
    print_s: float = 0.0,
    progress: dict | None = None,
    idle_before_tail: bool = False,
):
    """Sends `data`. `precheck(replies)` runs on the same connection (one link: no EBUSY) and may raise.

    The link stays open until the printer has processed the whole job. Closing early dropped the tail twice: right
    after sendall() (05/11), and after a fixed wait (08/11): the kernel send buffer holds ~50 KB, so sendall() of a
    big raster returns at once and the bytes cross only as fast as the printer prints. So: wait until the queue in
    the kernel is empty (as long as it keeps moving), then ask GS r 1, which is answered in order, after the job;
    close with SO_LINGER so nothing still queued is thrown away. If it answers too early (firmware treating it as
    real-time), the estimated print time is waited instead."""
    s = _connect(mac, channel, log)
    try:
        if precheck:
            precheck([_ask(s, q) for q in STATUS_QUERIES])
            s.settimeout(15)
        sent = 0
        if progress is not None:
            progress["started"] = True
        job, tail = _split_tail(data) if idle_before_tail else (data, b"")
        drained = None
        try:
            for i in range(0, len(job), chunk):
                s.sendall(job[i : i + chunk])
                sent = min(len(job), i + chunk)
                if pause:
                    time.sleep(pause)
            if tail:  # the end of a job that ends with an image: only once the image is on paper (see _split_tail)
                drained = _drain(s)
                if drained is not False:  # a stuck queue: the tail would only queue behind it (raised below)
                    if not _wait_idle(s, 30 + 2 * print_s):
                        log("note: the printer stayed busy; sending the end of the job anyway", file=sys.stderr)
                    s.settimeout(15)
                    s.sendall(tail)
                    sent = len(data)
        except OSError as e:
            raise SendFailed(f"the Bluetooth link failed after {sent} of {len(data)} bytes ({e})", sent) from e
        if drained is not False:
            drained = _drain(s)
        if drained is False:  # not "printed on …": part of the job never left the computer
            left = _unsent(s)  # of what was handed to the socket: the tail may never have been
            took = max(0, sent - left) if left is not None else sent
            with contextlib.suppress(OSError, AttributeError):  # a few seconds more for whatever is still queued
                import struct

                s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 10))
            about = "" if left is not None else "at most "
            raise SendFailed(f"the printer stopped taking the job after {about}{took} of {len(data)} bytes", took)
        t0 = time.monotonic()
        try:  # GS r 1 is answered after the job is processed; asked again while busy printing an image (dropped)
            confirmed = _wait_idle(s, 10 + 2 * print_s)
        except OSError:
            confirmed = False
        if not confirmed:
            log("note: the printer did not confirm the end of the job; check the paper", file=sys.stderr)
        if time.monotonic() - t0 < print_s:  # an early (real-time) answer: the printer may still hold the job
            time.sleep(print_s - (time.monotonic() - t0))
        time.sleep(0.5)
        with contextlib.suppress(OSError, AttributeError):  # only on success: after Ctrl-C close() must not block
            import struct

            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 10))
    finally:
        s.close()


def _bluetoothctl(action: str, mac: str, timeout: float) -> None:
    """Best effort, bounded: a hung bluetoothd must not hang the print."""
    try:
        subprocess.run(
            ["bluetoothctl", action, mac],
            check=False,
            timeout=timeout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _write_device(path: str, data: bytes, timeout: float, progress: dict | None = None) -> None:
    """Writes to a device file (/dev/usb/lp0, /dev/rfcomm0 …). An offline printer can block open() or write()
    forever: they run in a daemon thread that is abandoned after `timeout`."""
    import threading

    box: dict = {}

    def run():
        try:
            with open(path, "ab") as f:
                box["opened"] = True  # from here, bytes may reach the printer
                if progress is not None:
                    progress["started"] = True
                f.write(data)
                box["done"] = True
        except OSError as e:
            box["err"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        # some bytes may already be in the kernel buffer and still print: count it as maybe printed (the numbers
        # are spent, never reused)
        if not box.get("opened"):  # still opening: nothing reached the printer
            raise SendFailed(f"{path} did not open in {timeout:.0f} s (printer off or offline?)", 0)
        raise SendFailed(f"{path} did not take the whole job in {timeout:.0f} s (printer off or offline?)", len(data))
    if "err" in box:
        e = box["err"]
        raise PrinterUnreachable(f"cannot write to {path}: {e.strerror or e}") from e


def query(
    mac: str, channel: int, requests: list[bytes], timeout: float = 2.0, connect_timeout: float = 15
) -> list[bytes | None]:
    """Sends status requests (DLE EOT n, GS r n) and collects one reply each (a stale, busy link is recovered)."""
    s = _connect(mac, channel, full=False, timeout=connect_timeout)
    s.settimeout(timeout)
    out = []
    try:
        for q in requests:
            s.sendall(q)
            try:
                out.append(s.recv(16))
            except OSError:
                out.append(None)
    finally:
        s.close()
    return out


class PrinterBusy(PrinterUnreachable):
    pass


def printer_key(printer: dict) -> str:
    t = printer.get("transport", "bluetooth")
    target = printer.get("address") or printer.get("path") or printer.get("command") or "?"
    return re.sub(r"[^A-Za-z0-9._-]", "_", f"{t}-{target}")[:80]


@contextlib.contextmanager
def printer_lock(printer: dict, log=print, timeout: float | None = None):
    """One bobina job at a time per printer: a second job waits instead of fighting for the Bluetooth link (the
    EBUSY recovery below disconnects the link, which cut the first job in half) or interleaving bytes on a
    device file. `busy_timeout` (seconds, printer config, default 300) bounds the wait."""
    from . import fileio, paths

    timeout = float(printer.get("busy_timeout", 300)) if timeout is None else timeout
    path = paths.state_dir() / "printers" / printer_key(printer)

    def waiting():
        log("waiting for the printer: another bobina job is using it…", file=sys.stderr)

    try:
        with fileio.locked(path, timeout=timeout, on_wait=waiting):
            yield
    except fileio.LockTimeout:
        raise PrinterBusy(f"the printer is still busy with another bobina job after {timeout:.0f} s") from None


def send(data: bytes, printer: dict, profile, log=print, precheck=None, length_mm: float = 0.0, progress=None):
    """progress (a dict) gets "started" = True once bytes may have reached the printer: an interruption after
    that point spends the job's seq numbers, one before it gives them back."""
    with printer_lock(printer, log):
        _send(data, printer, profile, log, precheck, length_mm, progress)


def _send(data: bytes, printer: dict, profile, log=print, precheck=None, length_mm: float = 0.0, progress=None):
    progress = {} if progress is None else progress
    t = printer.get("transport", "bluetooth")
    if t == "file":
        _write_device(printer["path"], data, float(printer.get("timeout", 120)), progress)
    elif t == "command":
        cmd = shlex.split(printer["command"])
        timeout = float(printer.get("timeout", 120))
        progress["started"] = True  # the command gets the bytes at once
        try:
            r = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout)
        except FileNotFoundError:
            raise PrinterUnreachable(f"command not found: {cmd[0]}") from None
        except subprocess.TimeoutExpired:
            raise SendFailed(
                f"the command did not finish in {timeout:.0f} s (printer timeout = …)", len(data)
            ) from None
        except OSError as e:
            raise PrinterUnreachable(f"cannot run {cmd[0]}: {e.strerror}") from e
        if r.returncode:
            raise PrinterUnreachable(f"command failed ({r.returncode}): {r.stderr.decode(errors='replace').strip()}")
    else:
        bluetooth(
            data,
            printer["address"],
            int(printer.get("channel", 1)),
            int(profile.get("transport.chunk_bytes", 4096)),
            float(profile.get("transport.pause_s", 0.0)),
            log,
            precheck,
            length_mm / float(profile.get("transport.print_mm_per_s", 40)),
            progress,
            bool(profile.get("transport.idle_before_tail", True)),  # safe by default (08/11)
        )


def scan(seconds: int = 8) -> list[tuple[str, str]]:
    """Paired and nearby Bluetooth devices via bluetoothctl."""
    found = {}
    try:
        subprocess.run(
            ["bluetoothctl", "--timeout", str(seconds), "scan", "on"], capture_output=True, timeout=seconds + 5
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        r = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            parts = line.split(" ", 2)
            if len(parts) == 3 and parts[0] == "Device":
                found[parts[1]] = parts[2]
    except (OSError, subprocess.TimeoutExpired):
        raise PrinterUnreachable("bluetoothctl not available") from None
    return sorted(found.items(), key=lambda kv: kv[1])
