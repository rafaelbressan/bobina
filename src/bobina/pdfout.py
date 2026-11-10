"""A small streaming PDF writer for `preview --pages`: one 1-bit page at a time, written as soon as it is drawn.

Pillow's PDF writer needs every page in memory at once (1000 labels: ~700 MB). Each page here is an image of the
label at its real size on paper (dots / dpi), Flate-compressed 1-bit DeviceGray (1 = white, as in Pillow's
mode "1"), so the PDF prints at 1:1 and stays small.
"""

from __future__ import annotations

import zlib
from pathlib import Path


class PdfWriter:
    def __init__(self, f, dpi: int):
        self.f = f
        self.dpi = dpi
        self.offsets: list[int] = []
        self.pages: list[int] = []
        self.images: dict = {}  # key -> (object number, width, height)
        self.f.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        self._reserve()  # 1: catalog
        self._reserve()  # 2: page tree (written at the end, when the pages are known)

    def _reserve(self) -> int:
        self.offsets.append(0)
        return len(self.offsets)

    def _obj(self, n: int, body: bytes, stream: bytes | None = None) -> None:
        self.offsets[n - 1] = self.f.tell()
        self.f.write(f"{n} 0 obj\n".encode() + body)
        if stream is not None:
            self.f.write(b"\nstream\n" + stream + b"\nendstream")
        self.f.write(b"\nendobj\n")

    def add(self, im, key=None) -> None:
        """A page. Pages with the same key (copies of one label) share one image object: drawn and stored once."""
        if key is not None and key in self.images:
            img, w, h = self.images[key]
        else:
            im = im() if callable(im) else im
            im = im if im.mode == "1" else im.convert("1")
            w, h = im.size
            img = self._reserve()
            data = zlib.compress(im.tobytes(), 6)
            self._obj(
                img,
                f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceGray "
                f"/BitsPerComponent 1 /Filter /FlateDecode /Length {len(data)} >>".encode(),
                data,
            )
            if key is not None:
                self.images[key] = (img, w, h)
        pw, ph = w * 72 / self.dpi, h * 72 / self.dpi
        content, page = self._reserve(), self._reserve()
        draw = f"q {pw:.3f} 0 0 {ph:.3f} 0 0 cm /Im0 Do Q".encode()
        self._obj(content, f"<< /Length {len(draw)} >>".encode(), draw)
        self._obj(
            page,
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pw:.3f} {ph:.3f}] "
            f"/Resources << /XObject << /Im0 {img} 0 R >> >> /Contents {content} 0 R >>".encode(),
        )
        self.pages.append(page)

    def close(self) -> None:
        kids = " ".join(f"{p} 0 R" for p in self.pages)
        self._obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {len(self.pages)} >>".encode())
        self._obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
        xref = self.f.tell()
        self.f.write(f"xref\n0 {len(self.offsets) + 1}\n0000000000 65535 f \n".encode())
        for off in self.offsets:
            self.f.write(f"{off:010d} 00000 n \n".encode())
        self.f.write(f"trailer\n<< /Size {len(self.offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())


def write(path: Path, labels, dpi: int) -> int:
    """One page per label (engine Results; copies repeat a Result and are drawn once); returns the page count.
    Written like every -o output: whole or not at all (fileio.atomic_output)."""
    from . import fileio, preview

    with fileio.atomic_output(Path(path)) as f:
        w = PdfWriter(f, dpi)
        for label in labels:
            w.add(lambda label=label: preview.render(label.rows, label.profile, label.emulator), key=id(label))
        w.close()
    return len(w.pages)
