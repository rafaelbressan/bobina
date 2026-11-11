"""Finding printers for bobina init: Bluetooth (bluetoothctl) and USB (/dev/usb/lp* on Linux), and the profile
a printer's name suggests. Nothing here waits on a missing Bluetooth stack: what is missing is said (P401)."""

from __future__ import annotations

import functools
import glob
import os
import re
import shutil
import socket
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import paths, transport
from . import profile as profiles

USB_GLOB = "/dev/usb/lp*"  # module values, so tests can point them elsewhere
USB_SYSFS = "/sys/class/usbmisc"
BT_SYSFS = "/sys/class/bluetooth"
MAC = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
# words in the names printers give themselves; a phone or a headset is listed, never chosen by --yes
PRINTER_WORDS = re.compile(
    r"print|pos|thermal|receipt|label|mtp|mpt|pt-?\d|tm-|xp-|zj|nt-|rpp|bixolon|epson|citizen|star|seiko|xprinter|"
    r"zijiang|zjiang|netum|munbyn|rongta|hprt|goojprt|peripage|phomemo|metapace|yhd",
    re.I,
)


@dataclass
class Device:
    kind: str  # bluetooth | usb
    name: str  # what the printer calls itself (a Bluetooth name, a USB model), or the device path
    where: str  # Bluetooth address or device path
    profile: str | None = None  # the profile its name suggests
    printer_like: bool = False
    writable: bool = True  # False: a USB device this user cannot write to (P403)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "name": self.name, "where": self.where, "profile": self.profile,
                "printer_like": self.printer_like, "writable": self.writable}  # fmt: skip


@dataclass(frozen=True)
class Entry:
    """What bobina init needs of a profile (read once per run: catalog())."""

    id: str
    name: str
    paper_mm: float
    measured: bool
    keys: tuple


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _keys(prof) -> tuple:
    """The model names a profile answers to: its name without the brand and the notes in brackets (Epson TM-T20II
    → tmt20ii), the id, and match_names in the profile (MTP-II, PT-210)."""
    name = re.sub(r"\(.*?\)", "", prof.name).strip()
    words = name.split()
    model = " ".join(words[1:]) if len(words) > 1 else name
    keys = {_norm(model), _norm(prof.id)} | {_norm(n) for n in prof.get("match_names", []) or []}
    keys |= {_norm(w) for w in words[1:] if re.search(r"\d", w)}  # ZJ-5870 of "Zijiang ZJ-5870 Thermal Printer"
    return tuple(sorted(k for k in keys if len(k) >= 4))


def _user_profiles() -> tuple:
    d = paths.config_dir() / "profiles"
    try:
        return tuple(sorted((f.name, f.stat().st_mtime_ns) for f in d.glob("*.toml")))
    except OSError:
        return ()


def catalog() -> dict[str, Entry]:
    """Every readable profile, loaded once (until a user profile is added or changed); a broken user profile is
    left out here (bobina profile list shows it)."""
    return _catalog(str(paths.config_dir()), _user_profiles())


@functools.lru_cache(maxsize=4)
def _catalog(config_dir: str, user: tuple) -> dict[str, Entry]:
    out = {}
    for pid in profiles.available():
        try:
            p = profiles.load(pid)
        except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError):
            continue
        out[pid] = Entry(pid, p.name, float(p.get("paper_mm", 58)), p.get("measured", True) is not False, _keys(p))
    return out


def match_profiles(name: str) -> list[str]:
    """The profiles whose model name is in NAME, all with the longest match (TM-T20III is not a TM-T20II), best
    first: measured, then the shortest id (epson-tm-p80, not its 42-column mode). Several widths among them
    (Seiko RP-F10: 58 and 80 mm) mean the name does not settle the paper."""
    n = _norm(name)
    if len(n) < 4:
        return []
    scored = []
    for e in catalog().values():
        hits = [k for k in e.keys if k in n]
        if hits:
            scored.append((-max(map(len, hits)), not e.measured, len(e.id), e.id))
    if not scored:
        return []
    top = min(scored)[0]
    return [pid for length, *_, pid in sorted(scored) if length == top]


def match_profile(name: str) -> str | None:
    best = match_profiles(name)
    return best[0] if best else None


def widths(pids: list[str]) -> list[float]:
    """The paper widths of these profiles, most common first (then the narrower)."""
    cat = catalog()
    ws = [cat[p].paper_mm for p in pids if p in cat]
    return sorted(set(ws), key=lambda w: (-ws.count(w), w))


def _device(kind: str, name: str, where: str, writable: bool = True) -> Device:
    pid = match_profile(name)
    like = bool(pid) or bool(PRINTER_WORDS.search(name)) or kind == "usb"
    return Device(kind, name, where, pid, like, writable)


def _usb_model(dev: str) -> str:
    """The model of a USB printer from sysfs (IEEE 1284 id: MFG:EPSON;MDL:TM-T20II;), or ""."""
    base = Path(USB_SYSFS) / Path(dev).name / "device"
    try:
        ident = (base / "ieee1284_id").read_text(errors="replace")
        fields = dict(f.split(":", 1) for f in ident.split(";") if ":" in f)
        mfg = fields.get("MFG") or fields.get("MANUFACTURER") or ""
        mdl = fields.get("MDL") or fields.get("MODEL") or ""
        if mdl:
            return f"{mfg} {mdl}".strip()
    except OSError:
        pass
    for f in ("../product", "../../product"):
        try:
            return (base / f).read_text(errors="replace").strip()
        except OSError:
            continue
    return ""


def usb() -> tuple[list[Device], list[tuple[str, str, str]]]:
    """USB printers bobina can write to, and notes (code, message, suggestion)."""
    if sys.platform.startswith("linux"):
        found, notes = [], []
        for dev in sorted(glob.glob(USB_GLOB)):
            ok = os.access(dev, os.W_OK)
            found.append(_device("usb", _usb_model(dev) or dev, dev, ok))
            if not ok:
                notes.append(("P403", f"{dev} is a USB printer this user cannot write to",
                              "sudo usermod -aG lp $USER, then log out and in again"))  # fmt: skip
        return found, notes
    what = "the printer queue of Windows" if os.name == "nt" else "USB printers on this system"
    return [], [("P401", f"bobina cannot look for {what} yet",
                 "print through a Linux machine (bobina init --command 'ssh HOST bobina send --yes -'), or give the"
                 " device: bobina init --printer DEVICE")]  # fmt: skip


def bluetooth_missing() -> str:
    """Why Bluetooth printers cannot be looked for here, or "" when they can."""
    if not sys.platform.startswith("linux"):
        return "Bluetooth printers need Linux (BlueZ)"
    if not shutil.which("bluetoothctl"):
        return "bluetoothctl is not installed (BlueZ: sudo apt install bluez)"
    if os.path.isdir("/sys/class") and not glob.glob(os.path.join(BT_SYSFS, "hci*")):
        return "no Bluetooth adapter (none, or blocked: rfkill unblock bluetooth)"
    return ""


def bluetooth(seconds: int) -> tuple[list[Device], list[tuple[str, str, str]]]:
    """Bluetooth devices nearby or paired (each marked printer-like or not), and notes."""
    missing = bluetooth_missing()
    if missing:
        return [], [("P401", f"Bluetooth printers were not looked for: {missing}",
                     "a USB printer, a printer on another machine (ssh) or a file printer still work")]  # fmt: skip
    try:
        found = [_device("bluetooth", name, mac) for mac, name in transport.scan(seconds)]
    except transport.PrinterUnreachable as e:
        return [], [("P401", f"Bluetooth scan failed: {e}", "is bluetoothd running? systemctl status bluetooth")]
    notes = []
    if found and not hasattr(socket, "AF_BLUETOOTH"):
        notes.append(("P401", "found Bluetooth devices, but this Python cannot print over Bluetooth",
                      transport.no_bluetooth_sockets()))  # fmt: skip
    return found, notes


def known_name(mac: str) -> str:
    """The name of a paired or seen Bluetooth device (bluetoothctl devices, no scan), or ""."""
    if bluetooth_missing():
        return ""
    try:
        r = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in r.stdout.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[0] == "Device" and parts[1].upper() == mac.upper():
            return parts[2]
    return ""


def ranked(devices: list[Device]) -> list[Device]:
    """Printers first, in an order that does not depend on the scan: USB, then a known model, then a printer-like
    name, then the rest; by name and address within each."""

    def rank(d: Device):
        usb = d.kind == "usb"
        order = (0 if d.profile else 1) if usb else 2 if d.profile else 3 if d.printer_like else 4
        return order, d.name.lower(), d.where

    return sorted(devices, key=rank)
