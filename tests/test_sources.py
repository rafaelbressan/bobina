"""Images from files, PDF pages, SVG and (opt-in) https: rendering and the guards around them."""

import ipaddress
import socket

import pytest
from PIL import Image

from bobina import cli, sources
from bobina.engine import build
from bobina.rows import BitmapRow


def codes(res):
    return {n.code for n in res.nudges}


def bitmaps(res):
    return [r for r in res.rows if isinstance(r, BitmapRow)]


SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="40" height="20">'
    '<rect width="20" height="20"/>{extra}</svg>'
)


def test_svg_renders_at_paper_width(tmp_path):
    (tmp_path / "a.svg").write_text(SVG.format(extra=""))
    res = build("![](a.svg)", base_dir=str(tmp_path))
    (row,) = bitmaps(res)
    assert row.image.width == 384
    assert "I101" not in codes(res)


def test_svg_external_references_are_removed(tmp_path):
    black = tmp_path / "secret.png"
    Image.new("L", (20, 20), 0).save(black)
    for href in (str(black), f"file://{black}", "https://example.com/x.png"):
        cleaned = sources.clean_svg(SVG.format(extra=f'<image href="{href}" x="20" width="20" height="20"/>').encode())
        assert href not in cleaned
    nested = '<image xlink:href="data:image/svg+xml;base64,PHN2Zz4=" width="1" height="1"/>'
    assert "svg+xml" not in sources.clean_svg(SVG.format(extra=nested).encode())
    keep = '<use href="#r"/><image href="data:image/png;base64,iVBORw0KGgo=" width="1" height="1"/>'
    out = sources.clean_svg(SVG.format(extra=keep).encode())
    assert 'href="#r"' in out and "data:image/png" in out


def test_svg_with_entities_is_refused(tmp_path):
    (tmp_path / "e.svg").write_text('<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "x">]><svg/>')
    res = build("![](e.svg)", base_dir=str(tmp_path))
    assert "I101" in codes(res) and not bitmaps(res)


def two_page_pdf(path):
    a = Image.new("L", (200, 100), 255)
    b = Image.new("L", (200, 100), 0)
    a.save(path, save_all=True, append_images=[b])


def test_pdf_page_is_rendered_and_vector_defaults_to_threshold(tmp_path):
    two_page_pdf(tmp_path / "d.pdf")
    res = build("![](d.pdf){page=2}", base_dir=str(tmp_path))
    (row,) = bitmaps(res)
    assert row.image.width == 384
    assert row.image.convert("L").getextrema() == (0, 0)  # page 2 is black, thresholded with no speckle
    bad = build("![](d.pdf){page=9}", base_dir=str(tmp_path))
    assert "I101" in codes(bad)


def test_print_pdf_target_all_pages_and_range(tmp_path, capsys):
    two_page_pdf(tmp_path / "d.pdf")
    out = tmp_path / "o.bin"
    assert cli.main(["print", str(tmp_path / "d.pdf"), "-o", str(out)]) == cli.OK
    both = out.read_bytes()
    assert cli.main(["print", str(tmp_path / "d.pdf"), "--page", "2", "-o", str(out), "--force"]) == cli.OK
    assert len(out.read_bytes()) < len(both)
    assert cli.main(["print", str(tmp_path / "d.pdf"), "--page", "3"]) == cli.USAGE


def test_print_photo_target(tmp_path):
    Image.new("RGB", (300, 200), (120, 120, 120)).save(tmp_path / "p.jpg")
    out = tmp_path / "o.bin"
    assert cli.main(["print", str(tmp_path / "p.jpg"), "-o", str(out)]) == cli.OK
    assert b"\x1dv0" in out.read_bytes()


def test_eps_is_not_opened(tmp_path):
    (tmp_path / "x.png").write_bytes(b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n")
    res = build("![](x.png)", base_dir=str(tmp_path))
    assert "I101" in codes(res) and not bitmaps(res)


def test_other_schemes_are_refused(tmp_path):
    for src in ("file:///etc/hostname", "ftp://example.com/a.png", "javascript:alert(1)"):
        assert not bitmaps(build(f"![]({src})", base_dir=str(tmp_path)))  # never loaded (Markdown may drop it)
        with pytest.raises(sources.ImageError):
            sources.load(src, str(tmp_path))


def test_network_is_off_by_default():
    res = build("![](https://example.com/logo.png)")
    assert "I103" in codes(res) and not bitmaps(res)


CGNAT = str(ipaddress.IPv4Address((100 << 24) | (64 << 16) | 1))  # shared space used by Tailscale


def fake_dns(monkeypatch, *addrs):
    def getaddrinfo(host, port, *a, **k):
        return [(socket.AF_INET6 if ":" in x else socket.AF_INET, socket.SOCK_STREAM, 6, "", (x, port)) for x in addrs]

    monkeypatch.setattr(sources.socket, "getaddrinfo", getaddrinfo)


@pytest.mark.parametrize(
    "addr",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.10",
        CGNAT,
        "169.254.169.254",
        "::1",
        "::ffff:127.0.0.1",
        "fd00::1",
    ],
)
def test_private_addresses_are_refused(monkeypatch, addr):
    sources._CACHE.clear()
    fake_dns(monkeypatch, addr)
    with pytest.raises(sources.ImageError) as e:
        sources.fetch("https://looks-public.example/logo.png")
    assert e.value.code == "I106"


def test_mixed_public_and_private_answer_is_refused(monkeypatch):
    fake_dns(monkeypatch, "93.184.215.14", "127.0.0.1")
    with pytest.raises(sources.ImageError):
        sources.resolve_public("rebind.example", 443)


def test_http_and_credentials_are_refused():
    for url in ("http://example.com/a.png", "https://user:pw@example.com/a.png"):
        with pytest.raises(sources.ImageError) as e:
            sources.fetch(url)
        assert e.value.code == "I106"


def test_network_url_cannot_come_from_data():
    from bobina.nudges import SecurityError

    with pytest.raises(SecurityError):
        build("![]({{ logo }})", fields={"logo": cli.common.Tainted("https://example.com/a.png")}, net=True)


def test_url_target_needs_allow_net_and_explains_why(capsys):
    assert cli.main(["print", "https://example.com/logo.png", "--dry-run"]) == cli.USAGE
    e = capsys.readouterr().err
    assert "--allow-net" in e and "local network" in e


def test_unsupported_targets_are_refused_with_a_reason(tmp_path, capsys):
    (tmp_path / "doc.eps").write_text("%!PS-Adobe-3.0 EPSF-3.0\n")
    (tmp_path / "r.docx").write_bytes(b"PK\x03\x04\x00binary\xff\xfe")
    (tmp_path / "fake.png").write_text("%!PS-Adobe-3.0\n")
    for name, word in (("doc.eps", "PostScript"), ("r.docx", "export it as PDF"), ("fake.png", "supported")):
        assert cli.main(["print", str(tmp_path / name), "--dry-run"]) == cli.USAGE
        assert word in capsys.readouterr().err


def test_document_with_only_skipped_blocks_says_nothing_printable(tmp_path):
    res = build("![](missing.png)", base_dir=str(tmp_path))
    assert {"I101", "L105"} <= codes(res)
    assert "L105" not in codes(build("hello\n\n![](missing.png)", base_dir=str(tmp_path)))


def test_image_path_with_space_explains_the_angle_brackets(tmp_path):
    res = build("![](my photo.png) and text", base_dir=str(tmp_path))
    n = [x for x in res.nudges if x.code == "I107"]
    assert n and "<my photo.png>" in n[0].suggestion
    assert "I107" not in codes(build("![](<my photo.png>)", base_dir=str(tmp_path)))


def test_svg_cleaning_resists_quote_tricks_and_css(tmp_path):
    black = tmp_path / "it's.png"
    Image.new("L", (20, 20), 0).save(black)
    tricks = [
        f'<image href="{black}" width="20" height="20"/>',  # the other quote inside the value
        f"<image xlink:href='{tmp_path}/x.png' width='1' height='1'/>",
        f'<image href="  {black}" width="1" height="1"/>',
        '<image href="&#47;etc&#47;passwd" width="1" height="1"/>',  # character references
        '<style>@import url("http://evil.example/x.css"); rect { fill: url(/etc/x) }</style>',
        f'<rect width="5" height="5" style="fill: url(\'{black}\')"/>',
    ]
    for t in tricks:
        out = sources.clean_svg(SVG.format(extra=t).encode())
        assert str(tmp_path) not in out and "/etc" not in out and "evil" not in out, out
    kept = sources.clean_svg(SVG.format(extra='<rect fill="url(#g)" width="1" height="1"/>').encode())
    assert "url(#g)" in kept
    img = sources.render_svg(SVG.format(extra=tricks[0]).encode(), 40)  # renders without reading the file
    assert img.width == 40
