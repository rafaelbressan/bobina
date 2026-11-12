"""Where images come from: a file, a data: URI or (opt-in) an https URL; PDF pages and SVG are rendered
straight at the paper width.

Every byte here may be hostile (a shared template, a downloaded file, a web page), so:
- https only when the command line says --allow-net; a document cannot turn it on by itself;
- the host must resolve to public addresses only (no loopback, private, link-local, CGNAT/tailnet,
  multicast); the connection goes to the address that was checked (no second DNS lookup), redirects are
  not followed, and the body is capped in size and time;
- SVG: external references are removed before rendering (resvg would read absolute local paths);
  DOCTYPE/ENTITY declarations are refused;
- PDF: only the requested page is rendered, with a cap on the output size.
"""

from __future__ import annotations

import base64
import http.client
import ipaddress
import re
import socket
import ssl
import stat
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 10_000_000  # downloads and embedded data: URIs
MAX_FILE_BYTES = 50_000_000  # local files
TIMEOUT_S = 10  # per network operation
DEADLINE_S = 20  # the whole download (a server dripping one byte at a time cannot hold the job)
MAX_RENDER_DOTS = 8000  # tallest PDF/SVG render, in printer dots (1 m of paper at 8 dots/mm)
NET_TYPES = ("image/", "application/pdf")
NET_WHY = (
    "fetching shows the server when and where you print, and a shared document could use it to reach your local network"
)
NET_HINT = "trust this URL? add --allow-net (https, public hosts only); or download the file and print it"


class ImageError(ValueError):
    """A source that cannot be used; code is the nudge to report (I101, I103, I105, I106)."""

    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code, self.hint = code, hint


@dataclass
class Source:
    data: bytes
    kind: str  # raster | pdf | svg
    origin: str  # file | data | net
    host: str = ""


def sniff(data: bytes) -> str:
    head = data[:1024].lstrip()
    if head.startswith(b"%PDF"):
        return "pdf"
    low = head.lower()
    if low.startswith(b"<svg") or (low.startswith(b"<?xml") and b"<svg" in low) or b"<svg" in low[:300]:
        return "svg"
    return "raster"


def load(src: str, base_dir: str, *, allow_net: bool = False, confine=None) -> Source:
    """confine: folders (resolved Paths) a local file must be in, wherever its path or symlinks point
    (--sandbox, MCP); None: anywhere. Decided here, with the same scheme test that picks a file at all."""
    if src.startswith("data:"):
        head, _, payload = src.partition(",")
        if ";base64" not in head:
            raise ImageError("I101", "only base64 data: URIs are supported")
        if len(payload) > MAX_BYTES * 4 // 3 + 4:
            raise ImageError("I101", "embedded image larger than 10 MB")
        try:
            data = base64.b64decode(payload, validate=True)
        except ValueError:
            raise ImageError("I101", "the data: URI is not valid base64") from None
        return Source(data, sniff(data), "data")
    scheme = urllib.parse.urlsplit(src).scheme.lower()
    if scheme in ("http", "https"):
        if not allow_net:
            raise ImageError("I103", "images from the network are off: " + NET_WHY, NET_HINT)
        data, host = fetch(src)
        return Source(data, sniff(data), "net", host)
    if scheme and len(scheme) > 1:  # file:, ftp:, javascript:, ... (a Windows drive letter is one char)
        raise ImageError("I101", f"'{scheme}:' sources are not supported", "use a path or an https URL")
    p = Path(src).expanduser()
    if not p.is_absolute():
        p = Path(base_dir) / p
    if confine is not None:
        p = _confined(p, src, confine)
    try:
        st = p.stat()
    except OSError as e:
        raise ImageError(
            "I101", f"{e.strerror or 'cannot read'}: {src[:60]}", "paths are relative to the document"
        ) from None
    size = st.st_size
    if stat.S_ISDIR(st.st_mode):
        raise ImageError("I101", f"{src[:60]} is a folder, not an image")
    if not stat.S_ISREG(st.st_mode):  # /dev/tty, a FIFO, a device: reading could wait forever or never end
        raise ImageError("I101", f"{src[:60]} is not a regular file")
    from .fileio import read_capped

    try:
        data = read_capped(p, MAX_FILE_BYTES) if size <= MAX_FILE_BYTES else None
    except OSError as e:
        raise ImageError("I101", f"{e.strerror or 'cannot read'}: {src[:60]}") from None
    if data is None:  # also a device or a pipe (/dev/zero has no size)
        raise ImageError("I101", f"file larger than {MAX_FILE_BYTES // 1_000_000} MB")
    return Source(data, sniff(data), "file")


def _confined(p: Path, src: str, folders) -> Path:
    try:
        real = p.resolve()
    except (OSError, RuntimeError):  # a symlink loop
        real = None
    if real is not None and any(real.is_relative_to(d) for d in folders):
        return real  # read what was checked
    import json

    folder = (real.parent if real is not None else p.parent).as_posix()  # forward slashes: valid TOML on Windows
    raise ImageError(
        "I108",
        "outside the document folder and image_dirs: not read (--sandbox)",
        f"trust that folder? add it to config.toml: image_dirs = [{json.dumps(folder)}]",
    )


# -- network -----------------------------------------------------------------------------------------


_NAT64 = ipaddress.ip_network("64:ff9b::/96")  # DNS64 answers for IPv4 hosts on IPv6-only networks
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")  # a translator of one network's own choosing
_TRANSLATED = ipaddress.ip_network("::ffff:0:0:0/96")  # SIIT: ::ffff:0:a.b.c.d
_COMPATIBLE = ipaddress.ip_network("::/96")  # ::a.b.c.d, deprecated (and ::, ::1)


def _low_ipv4(ip: ipaddress.IPv6Address) -> str:
    return str(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))


def _public(addr: str) -> bool:
    """A public internet address. IPv6 forms that carry an IPv4 address are judged by that address (mapped,
    translated, NAT64, 6to4, ISATAP); IPv4-compatible, site-local, Teredo and local NAT64 addresses are never
    public."""
    ip = ipaddress.ip_address(addr)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip in _TRANSLATED:
            ip = ipaddress.IPv4Address(_low_ipv4(ip))
        elif ip in _NAT64:  # 64:ff9b::192.168.1.1 reaches the LAN behind the translator
            return _public(_low_ipv4(ip))
        else:
            if ip in _COMPATIBLE or ip in _NAT64_LOCAL or ip.is_site_local or ip.teredo is not None:
                return False
            embedded = [str(ip.sixtofour)] if ip.sixtofour is not None else []
            if (int(ip) >> 32) & 0xFDFFFFFF == 0x5EFE:  # ISATAP: the interface id is [02]00:5efe:a.b.c.d
                embedded.append(_low_ipv4(ip))
            if not all(_public(e) for e in embedded):
                return False
    return ip.is_global and not ip.is_multicast


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to a fixed, already-checked address; certificate and SNI still use the host name."""

    def __init__(self, host: str, ip: str, port: int, timeout: float):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.raw_sock = sock  # visible to the deadline (_cut) during the TLS handshake too
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _getaddrinfo(host: str, port: int, timeout: float):
    """getaddrinfo has no timeout of its own: it runs in a daemon thread that is abandoned after `timeout`."""
    box: dict = {}

    def run():
        try:
            box["ok"] = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as e:
            box["err"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise ImageError("I101", f"cannot resolve {host}: no answer in {timeout:.0f} s")
    if "err" in box:
        raise ImageError("I101", f"cannot resolve {host}")
    return box["ok"]


def resolve_public(host: str, port: int, timeout: float = TIMEOUT_S) -> str:
    infos = _getaddrinfo(host, port, timeout)
    addrs = sorted({i[4][0] for i in infos})
    blocked = [a for a in addrs if not _public(a)]
    if not addrs or blocked:
        raise ImageError(
            "I106",
            f"{host} points to a local or private address ({', '.join(blocked or addrs)})",
            "bobina only fetches from public internet hosts",
        )
    return addrs[0]


def _cut(conn, cut: threading.Event | None = None) -> None:
    """Deadline reached: shutting the socket down wakes the blocked read up. The event is set first, so a read
    that returns because of the shutdown always sees it."""
    if cut is not None:
        cut.set()
    sock = getattr(conn, "raw_sock", None) or getattr(conn, "sock", None)
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


_CACHE: dict[str, tuple[bytes, str, float]] = {}  # url -> (data, host, fetched at); oldest first
CACHE_BYTES = 32_000_000  # a batch fetches its logo once; a long-running caller does not keep 32 x 10 MB
CACHE_TTL_S = 600  # an image updated on the server is fetched again after 10 minutes


def _cached(url: str):
    hit = _CACHE.get(url)
    if hit and time.monotonic() - hit[2] < CACHE_TTL_S:
        return hit[0], hit[1]
    _CACHE.pop(url, None)
    return None


def _keep(url: str, data: bytes, host: str) -> None:
    if len(data) > CACHE_BYTES // 4:
        return
    while _CACHE and sum(len(v[0]) for v in _CACHE.values()) + len(data) > CACHE_BYTES:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[url] = (data, host, time.monotonic())


def fetch(url: str) -> tuple[bytes, str]:
    if (hit := _cached(url)) is not None:  # a batch of 1000 labels fetches the logo once
        return hit
    u = urllib.parse.urlsplit(url)
    if u.scheme.lower() != "https":
        raise ImageError("I106", "only https URLs are fetched", "plain http can be altered on the way")
    if u.username or u.password:
        raise ImageError("I106", "URLs with credentials are refused")
    host, port = u.hostname or "", u.port or 443
    if not host:
        raise ImageError("I101", "URL without a host")
    start = time.monotonic()  # DEADLINE_S covers everything: DNS, connection, headers, body
    ip = resolve_public(host, port, min(TIMEOUT_S, DEADLINE_S))
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    conn = _PinnedHTTPS(host, ip, port, TIMEOUT_S)
    cut = threading.Event()
    watchdog = threading.Timer(max(0.1, DEADLINE_S - (time.monotonic() - start)), _cut, [conn, cut])
    watchdog.daemon = True
    watchdog.start()
    try:
        conn.request("GET", path, headers={"User-Agent": "bobina", "Accept": "image/*, application/pdf"})
        r = conn.getresponse()
        if 300 <= r.status < 400:
            raise ImageError("I106", f"{host} redirects ({r.status}); redirects are not followed", "use the final URL")
        if r.status != 200:
            raise ImageError("I101", f"{host} answered {r.status}")
        ctype = (r.getheader("Content-Type") or "").split(";")[0].strip().lower()
        if not ctype.startswith(NET_TYPES):
            raise ImageError("I106", f"{host} sent '{ctype or 'no type'}', not an image or PDF")
        length = r.getheader("Content-Length")
        if length and length.isdigit() and int(length) > MAX_BYTES:
            raise ImageError("I106", f"download larger than {MAX_BYTES // 1_000_000} MB")
        data = r.read(MAX_BYTES + 1)
        if cut.is_set():  # cut by the deadline: what arrived is a part, never use it as the image
            raise ImageError("I101", f"{host}: the download did not finish in {DEADLINE_S} s")
        if len(data) > MAX_BYTES:
            raise ImageError("I106", f"download larger than {MAX_BYTES // 1_000_000} MB")
    except ImageError:
        raise  # the specific reason (redirect, type, size, status) and its hint reach the user as they are
    except (OSError, http.client.HTTPException, ValueError) as e:
        if cut.is_set():
            raise ImageError("I101", f"{host}: the download did not finish in {DEADLINE_S} s") from None
        raise ImageError("I101", f"{host}: {e.__class__.__name__}") from None
    finally:
        watchdog.cancel()
        conn.close()
    _keep(url, data, host)
    return data, host


# -- vector rendering ----------------------------------------------------------------------------------

_DATA_RASTER = re.compile(r"(?i)^\s*data:image/(?:png|jpe?g|gif|webp)[;,]")  # not svg+xml: nested SVG skips cleaning
_CSS_URL = re.compile(r"""(?i)url\(\s*(?!['"]?\s*#)[^)]*\)""")
_CSS_IMPORT = re.compile(r"(?i)@import[^;]*;?")
SVG_NS = "http://www.w3.org/2000/svg"


def clean_svg(data: bytes) -> str:
    """Parses the SVG (a real XML parser, not a regex) and removes every reference to something outside it:
    href/xlink:href that is not #fragment or inline PNG/JPEG/GIF/WebP, url(...) that is not #fragment in any
    attribute or <style>, and CSS @import. DOCTYPE/ENTITY declarations are refused before parsing."""
    import xml.etree.ElementTree as ET

    text = data.decode("utf-8", errors="replace")
    if re.search(r"(?i)<!DOCTYPE|<!ENTITY", text):
        raise ImageError("I101", "SVG with DOCTYPE/ENTITY declarations is refused")
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ImageError("I101", f"SVG is not valid XML ({e})") from None
    for el in root.iter():
        for key in list(el.attrib):
            local = key.rsplit("}", 1)[-1]
            value = el.attrib[key]
            if local == "href" and not (value.strip().startswith("#") or _DATA_RASTER.match(value)):
                del el.attrib[key]
            elif "url(" in value.lower():
                el.attrib[key] = _CSS_URL.sub("none", value)
        if el.tag.rsplit("}", 1)[-1] == "style" and el.text:
            el.text = _CSS_URL.sub("none", _CSS_IMPORT.sub("", el.text))
    return ET.tostring(root, encoding="unicode")


def render_svg(data: bytes, width: int):
    import io

    from PIL import Image

    try:
        import resvg_py
    except ImportError:
        raise ImageError("I105", "SVG support is not installed", "pip install 'bobina[svg]'") from None
    try:  # fitted into width x MAX_RENDER_DOTS: a tall SVG is never drawn at full size (gigabytes) to be refused
        png = resvg_py.svg_to_bytes(svg_string=clean_svg(data), width=width, height=MAX_RENDER_DOTS, background="white")
    except Exception as e:  # noqa: BLE001 - resvg reports parse errors as generic exceptions
        raise ImageError("I101", f"SVG: {str(e)[:80]}") from None
    im = Image.open(io.BytesIO(bytes(png)))
    if im.width < width or im.height > MAX_RENDER_DOTS:  # narrower: the height limit set the scale
        raise ImageError("I101", f"SVG renders taller than {MAX_RENDER_DOTS} dots")
    return im


def pdf_pages(data: bytes) -> int:
    pdf = _open_pdf(data)
    try:
        return len(pdf)
    finally:
        pdf.close()


def _open_pdf(data: bytes):
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise ImageError("I105", "PDF support is not installed", "pip install 'bobina[pdf]'") from None
    try:
        return pdfium.PdfDocument(data)
    except Exception as e:  # noqa: BLE001
        raise ImageError("I101", f"PDF: {str(e)[:80]}") from None


def render_pdf(data: bytes, width: int, page: int = 1):
    pdf = _open_pdf(data)
    try:
        n = len(pdf)
        if not 1 <= page <= n:
            raise ImageError("I101", f"PDF has {n} page(s), page={page} asked")
        pg = pdf[page - 1]
        w_pt, h_pt = pg.get_size()
        scale = width / w_pt if w_pt else 1
        if h_pt * scale > MAX_RENDER_DOTS:
            raise ImageError("I101", f"PDF page renders taller than {MAX_RENDER_DOTS} dots")
        im = pg.render(scale=scale, fill_color=(255, 255, 255, 255)).to_pil()
        pg.close()
        return im
    finally:
        pdf.close()
