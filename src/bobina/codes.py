"""Barcodes (native GS k + exact preview) and Pix (BR Code) payloads."""

from __future__ import annotations

import re
import unicodedata

from PIL import Image, ImageDraw

GS = b"\x1d"

# type -> (GS k system, python-barcode name, firmware adds a check char the HRI does not show)
TYPES = {
    "upca": (65, "upca"),
    "upc-a": (65, "upca"),
    "upce": (66, None),
    "upc-e": (66, None),
    "ean13": (67, "ean13"),
    "ean-13": (67, "ean13"),
    "ean8": (68, "ean8"),
    "ean-8": (68, "ean8"),
    "code39": (69, "code39"),
    "code-39": (69, "code39"),
    "itf": (70, "itf"),
    "codabar": (71, "codabar"),
    "code93": (72, None),
    "code-93": (72, None),
    "code128": (73, "code128"),
    "code-128": (73, "code128"),
}
HRI = {"none": 0, "above": 1, "below": 2, "both": 3}


def native(kind: str, data: str, module: int, height: int, text: str) -> bytes:
    system, _ = TYPES[kind]
    payload = data
    if system == 73:  # CODE128 needs a code set: {B, and '{' escaped
        payload = "{B" + data.replace("{", "{{")
    d = payload.encode("ascii", "replace")
    return (
        GS
        + b"h"
        + bytes([max(1, min(255, height))])
        + GS
        + b"w"
        + bytes([module])
        + GS
        + b"H"
        + bytes([HRI.get(text, 2)])
        + GS
        + b"f\x00"
        + GS
        + b"k"
        + bytes([system, len(d)])
        + d
    )


def bars(kind: str, data: str, wide: int = 3) -> tuple[str, str]:
    """-> (pattern of '1'/'0' modules, human readable text as the firmware prints it). wide: modules of a wide
    Code39 element (python-barcode draws 3:1; the MTP-II prints 2:1, paper 09/11)."""
    import barcode

    _, name = TYPES[kind]
    if name is None:
        raise ValueError(f"no preview encoder for {kind}")
    opts = {}
    if name == "code39":
        opts["add_checksum"] = True  # N6: the firmware appends a mod-43 check char
    cls = barcode.get_barcode_class(name)
    try:
        b = cls(data, **opts)
    except TypeError:
        b = cls(data)
    pattern = b.build()[0]
    if name == "code39" and wide != 3:  # every element is 1 (narrow) or 3 (wide) modules: redraw the wide ones
        pattern = re.sub(r"(0{3}|1{3})", lambda m: m.group(0)[0] * wide, pattern)
    hri = data if name == "code39" else b.get_fullcode()  # HRI shows the data without the mod-43 char
    return pattern, hri


def image(kind: str, data: str, module: int, height: int, text: str, emulator, wide: int | None = None) -> Image.Image:
    """The barcode as an image. wide: Code39 wide-bar modules; default the printer's GS k (preview of a native
    code), 3 for a code bobina draws itself."""
    pattern, hri = bars(kind, data, emulator.p.code39_wide() if wide is None else wide)
    w = len(pattern) * module
    bar = Image.new("1", (w, height), 1)
    d = ImageDraw.Draw(bar)
    for i, b in enumerate(pattern):
        if b == "1":
            d.rectangle((i * module, 0, (i + 1) * module - 1, height - 1), fill=0)
    if text == "none":
        return bar
    from .rows import Cell

    t = emulator.line_image([Cell(ch) for ch in hri]).convert("1", dither=Image.NONE)
    parts = ([t] if text in ("above", "both") else []) + [bar] + ([t] if text in ("below", "both") else [])
    W = max(p.width for p in parts)
    out = Image.new("1", (W, sum(p.height for p in parts)), 1)
    y = 0
    for p in parts:
        out.paste(p, ((W - p.width) // 2, y))
        y += p.height
    return out


# ---------------------------------------------------------------- Pix (BR Code, EMV QRCPS)


def _tlv(tag: str, value: str) -> str:
    if len(value) > 99:
        raise ValueError(f"field {tag} longer than 99 characters")
    return f"{tag}{len(value):02d}{value}"


def _ascii(s: str, n: int) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s[:n]


def crc16(s: str) -> str:
    crc = 0xFFFF
    for b in s.encode():
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def pix_payload(
    key: str, name: str, city: str, amount: str | float | None = None, txid: str = "***", description: str = ""
) -> str:
    key = key.strip()
    if not key or len(key) > 77 or any(ord(c) < 32 for c in key):
        raise ValueError(f"key must have 1–77 printable characters (got {len(key)})")
    if amount not in (None, "", 0, "0"):
        try:
            a = float(str(amount).replace(",", "."))
        except ValueError:
            raise ValueError(f"amount '{amount}' is not a number") from None
        if not 0 < a < 10_000_000:
            raise ValueError(f"amount {a} out of range")
    txid = "".join(c for c in _ascii(txid, 25) if c.isalnum()) or "***"
    mai = _tlv("00", "br.gov.bcb.pix") + _tlv("01", key)
    if description:
        description = _ascii(description, 999)
        room = 99 - len(mai) - 4
        if len(description) > room:  # never cut: the caller learns the real room
            raise ValueError(f"description has {len(description)} characters; with this key Pix allows {max(room, 0)}")
        mai += _tlv("02", description)
    p = _tlv("00", "01") + _tlv("26", mai) + _tlv("52", "0000") + _tlv("53", "986")
    if amount not in (None, "", 0, "0"):
        p += _tlv("54", f"{float(str(amount).replace(',', '.')):.2f}")
    p += _tlv("58", "BR") + _tlv("59", _ascii(name, 25) or "N") + _tlv("60", _ascii(city, 15) or "BRASIL")
    p += _tlv("62", _tlv("05", txid))
    p += "6304"
    return p + crc16(p)
