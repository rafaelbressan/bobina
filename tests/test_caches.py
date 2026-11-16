"""A batch decodes the same logo once and encodes each QR once; a changed file is read again."""

import os
import time

from PIL import Image

from bobina import imaging, layout
from bobina.cli import main


def _logo(path, color=0):
    Image.new("L", (600, 300), color).save(path)


def test_the_same_logo_is_decoded_once_per_batch(isolated, monkeypatch):
    layout._IMAGES.clear()
    _logo(isolated / "logo.png")
    doc = isolated / "pote.bob.md"
    doc.write_text("![](logo.png)\n\n# Pote {{ seq.t }}\n")
    calls = []
    real = imaging.open_image
    monkeypatch.setattr(imaging, "open_image", lambda *a, **k: calls.append(a[0]) or real(*a, **k))
    assert main(["print", "--dry-run", "--quiet", str(doc), "--repeat", "20"]) == 0
    assert calls == ["logo.png"]


def test_a_changed_file_is_read_again(isolated):
    layout._IMAGES.clear()
    logo = isolated / "logo.png"
    _logo(logo, 0)
    doc = isolated / "d.bob.md"
    doc.write_text("![](logo.png)\n")
    out = isolated / "p.png"
    assert main(["preview", str(doc), "-o", str(out), "--quiet"]) == 0
    black = Image.open(out).convert("L").getextrema()
    _logo(logo, 255)  # same name, new content
    os.utime(logo, ns=(time.time_ns(), time.time_ns() + 10**9))
    assert main(["preview", str(doc), "-o", str(out), "--quiet", "--force"]) == 0
    assert Image.open(out).convert("L").getextrema() != black


def test_each_qr_is_encoded_once(isolated):
    imaging.qr_matrix.cache_clear()
    doc = isolated / "q.bob.md"
    doc.write_text("```qr\nhttps://exemplo.org/{{ seq.t }}\n```\n")
    assert main(["preview", str(doc), "--repeat", "5", "-o", str(isolated / "q.png"), "--quiet"]) == 0
    info = imaging.qr_matrix.cache_info()
    assert info.misses == 5 and info.hits >= 5  # layout, heights and drawing share one encoding per label


def test_a_big_jpeg_is_decoded_reduced_but_wide_enough(isolated):
    Image.new("RGB", (4000, 3000), "gray").save(isolated / "f.jpg")
    im = imaging.open_image(str(isolated / "f.jpg"), str(isolated), width=384)
    assert 384 <= im.width < 4000 and im.height >= 384


def test_font_sizes_are_clamped_with_a_warning(isolated):
    from bobina import engine

    res = engine.build('# Big {font="Atkinson Hyperlegible" size=5000px}\n')
    codes = [n.code for n in res.nudges]
    assert "F205" in codes


def test_font_caches_are_bounded():
    from bobina import rasterfont

    assert rasterfont.load.cache_info().maxsize == 64
    assert rasterfont.resolve.cache_info().maxsize == 64


def test_url_cache_is_bounded_by_bytes_and_expires(monkeypatch):
    from bobina import sources

    sources._CACHE.clear()
    monkeypatch.setattr(sources, "CACHE_BYTES", 1000)
    for k in range(10):
        sources._keep(f"https://x/{k}", b"z" * 200, "x")
    assert sum(len(v[0]) for v in sources._CACHE.values()) <= 1000
    assert "https://x/9" in sources._CACHE and "https://x/0" not in sources._CACHE
    monkeypatch.setattr(sources, "CACHE_TTL_S", -1)
    assert sources._cached("https://x/9") is None  # expired: fetched again
    sources._CACHE.clear()
