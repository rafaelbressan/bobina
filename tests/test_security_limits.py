"""The limits docs/SECURITY.md promises, checked one by one: each test names the promise it keeps.

Nothing here reaches the network (fake DNS, fake openers) or a printer (-o, check, preview, a file printer)."""

import ipaddress
import json
import os
import socket
import threading
import time

import openpyxl
import pytest

from bobina import cli, datasource, export, fileio, library, sources, templating
from bobina.engine import build
from bobina.nudges import SecurityError
from bobina.templating import Tainted


def refused(src, code="M313", **kw):
    with pytest.raises(SecurityError) as e:
        build(src, **kw)
    assert e.value.nudge.code == code, e.value.nudge.message
    return e.value.nudge.message


def rendered(res):
    return res.rendered.resolve(res.rendered.text)


# -- templates: 2000 loop iterations, 2 MB, no endless recursion -------------------------------------------


@pytest.mark.parametrize(
    "src",
    [
        '{% for c in "a" * 3000 %}{% endfor %}',  # a loop over a string, not range()
        "{% for c in [1, 2, 3] * 1000 %}{% endfor %}",  # over a list
        '{% for a in "x" * 100 %}{% for b in "x" * 100 %}{% endfor %}{% endfor %}',  # nested: 10 100 steps
        "{% for x in [[1]] recursive %}{{ loop([[1]]) }}{% endfor %}",  # a recursive loop that never ends
        "{{ range(10 ** 9) | list | length }}",  # every step of a range spends, wherever it is taken
    ],
)
def test_every_loop_spends_the_budget(src):
    assert "loop iterations" in refused(src) or "too deeply" in refused(src)


def test_loops_over_data_are_counted_too():
    refused("{% for a in d %}{% for b in d %}{% endfor %}{% endfor %}", fields={"d": Tainted("x" * 60)})


def test_usual_loops_still_work():
    res = build(
        "{% for i in range(1, 1990) %}{% endfor %}"
        "{% for k, v in {'a': 1, 'b': 2}.items() %}{{ k }}{{ v }}{{ loop.length }} {% endfor %}"
        "{{ range(5) | reverse | list }} {{ range(10)[2:4] | list }} {{ 3 in range(5) }} {{ range(10 ** 9) | length }}"
    )
    assert rendered(res) == "a12 b22 [4, 3, 2, 1, 0] [2, 3] True 1000000000"
    assert rendered(build("{% for n in seq.t.take(1500) %}{% endfor %}ok")) == "ok"  # taken numbers: paid once


def test_numbers_taken_once_are_free_once():
    refused(
        "{% set l = seq.t.take(1000) %}{% for a in l %}{% endfor %}{% for a in l %}{% endfor %}"
        "{% for a in l %}{% endfor %}"
    )


@pytest.mark.parametrize(
    "src",
    [
        "{% macro f(n) %}{{ f(n) }}{% endmacro %}{{ f(1) }}",  # Python's RecursionError, as M313
        "{% macro f(n) %}{% if n %}{{ f(n - 1) }}{{ f(n - 1) }}{% endif %}{% endmacro %}{{ f(40) }}",  # 2**40 calls
    ],
)
def test_macros_cannot_run_forever(src):
    refused(src)


@pytest.mark.parametrize(
    "src",
    [
        '{{ ("a" * 10000000000) | length }}',  # 10 GB, refused before it is made
        '{{ "ab" * 2000000 }}',
        "{{ [0] * 10000000000 }}",
        "{{ 2 ** 10000000 }}",
        '{{ "a" | center(10000000000) }}',
        '{{ "a\n" | indent(10000000000) }}',
        '{{ "a".ljust(10000000000) }}',
        '{{ "1".zfill(10000000000) }}',
        '{{ "%10000000000d" | format(1) }}',
        '{{ "%.10000000000f" % 1 }}',
        '{{ "{:>10000000000}".format(1) }}',
        '{{ "{:{}}".format(1, 10000000000) }}',
        '{% set n = namespace(s="ab") %}{% for i in range(40) %}{% set n.s = n.s ~ n.s %}{% endfor %}',
        '{% set n = namespace(s="ab") %}{% for i in range(40) %}{% set n.s = n.s + n.s %}{% endfor %}',
        '{% macro d(s, n) %}{% if n %}{{ d(s ~ s, n - 1) }}{% endif %}{% endmacro %}{{ d("ab", 40) }}',
        '{{ ("a" * 1000).join(("b" * 1000000) | list) }}',
        '{{ ("b" * 1000000) | list | join("a" * 1000) }}',
        '{{ "ab" | replace("a", "a" * 10000) | replace("a", "a" * 10000) }}',
        # ~ and set, block assignments, macro bodies
        '{% set b = "x" * 1900000 %}{{ (b ~ b) | length }}',
        '{% set n = namespace(s="ab") %}{% for i in range(40) %}{% set n.s = [n.s, n.s] | join %}{% endfor %}',
        '{% set b = "x" * 1900000 %}{% set s %}{{ b }}{{ b }}{% endset %}{{ s }}',
        '{% set b = "x" * 1900000 %}{% macro m() %}{{ b }}{{ b }}{% endmacro %}{{ m() }}',
        '{% set b = "x" * 1900000 %}{% for i in range(1500) %}{{ b }}{% endfor %}',  # 2.8 GB once resolved
        # numbers
        "{% set n = namespace(x=3) %}{% for i in range(40) %}{% set n.x = n.x * n.x %}{% endfor %}",
        # filters and methods that expand a small input
        "{{ [1] | slice(1000000000) | list | length }}",
        '{{ [1] | batch(1000000000, "x") | list | length }}',
        '{{ ("a\n" * 1000000) | indent("x" * 1000) }}',
        '{{ ("a" * 1000000).replace("a", "b" * 1000) }}',
        '{{ ("a" * 1000000) | replace("a", "b" * 1000) }}',
        '{{ ("a " * 900000) | wordwrap(1, wrapstring="x" * 1000) }}',
        '{{ ["x" * 1000000, "y" * 1000000, "z" * 1000000] | join }}',
        # widths from the arguments
        '{{ "%*d" % (10000000000, 1) }}',
        '{{ "%.*f" % (10000000000, 1.0) }}',
        '{{ "{:{w}}".format(1, w=10000000000) }}',
        '{{ "{:{w}}".format_map({"w": 10000000000}) }}',
        # review round 3: lazy joins, widths from strings, floats, items and rows, translate, expandtabs, replace
        '{{ ("b" * 1000000) | map("upper") | join("a" * 1000) }}',
        '{{ ("a" * 1000).join(("b" * 1000000) | map("upper")) }}',
        '{{ ("a" * 1000).join(("b" * 1000000) | select) }}',
        '{{ "{:{w}}".format(1, w="10000000000") }}',
        '{{ "{:{w}}".format(1, w=10000000000.0) }}',
        '{{ "{0:{1[0]}}".format(1, ["10000000000"]) }}',
        '{{ "{a:{w}}".format_map({"a": 1, "w": "10000000000"}) }}',
        '{{ ("a" * 1000000).translate({97: "b" * 1000}) }}',
        '{{ ("\\t" * 1000000).expandtabs(1000) }}',
        '{{ (["a"] * 100000) | replace("a", "b" * 1000) }}',
    ],
)
def test_no_value_grows_beyond_the_output_limit(src):
    start = time.monotonic()
    refused(src)
    assert time.monotonic() - start < 5  # refused before the memory is taken, not after


@pytest.mark.parametrize(
    "src",
    [
        '{% for i in range(100) %}{{ "a" | upper }}{% endfor %}',
        "{% for i in range(100) %}{% set x = i * i %}{% endfor %}",  # arithmetic ticks too
        "{% for i in range(100) %}{{ 'a' ~ i }}{% endfor %}",
        "{{ ('a' * 1000) | map('upper') | list | length }}",  # a lazy result is drawn with the clock ticking
    ],
)
def test_a_render_has_a_deadline(monkeypatch, src):
    monkeypatch.setattr(templating, "MAX_SECONDS", 1e-9)
    assert "s to render" in refused(src)


@pytest.mark.parametrize("n", [0, -1, -100000])
def test_taking_no_numbers_or_fewer_is_an_error_and_gives_no_loop_steps_back(n):
    with pytest.raises(ValueError, match="take at least 1"):
        build(f"{{% for i in range(1990) %}}{{{{ seq.t.take({n}) }}}}{{% endfor %}}")


def test_the_new_checks_leave_usual_templates_alone():
    res = build(
        "{{ 'a' ~ 1 ~ 'b' }} {% set s %}hi {{ 2 }}{% endset %}{{ s }} {{ 'aaa bbb' | wordwrap(4) }} "
        "{{ 'a\\nb' | indent(2, true) }} {{ [1, 2, 3] | batch(2, 0) | list }} {{ [1, 2, 3] | slice(2) | list }} "
        "{{ ['a', 'b'] | map('upper') | join(',') }} {{ 'x'.replace('x', 'yy') }} {{ 12 * 3 - 1 }} {{ 7 // 2 }} "
        "{{ '%5.1f' % 2.25 }} {{ '{:>4}'.format('a') }}"
    )
    assert rendered(res) == "a1b hi 2 aaa\nbbb   a\n  b [[1, 2], [3, 0]] [[1, 2], [3]] A,B yy 35 3   2.2    a"


def test_waiting_for_the_counters_file_is_not_the_templates_time(monkeypatch):
    monkeypatch.setattr(templating, "MAX_SECONDS", 0.2)
    real = templating.CounterStore._next_values

    def slow(self, name, n):
        time.sleep(0.3)  # another print holds the counters file
        return real(self, name, n)

    monkeypatch.setattr(templating.CounterStore, "_next_values", slow)
    assert rendered(build("{{ seq.ticket }} {% for n in seq.box.take(2) %}{{ n }}{% endfor %}")) == "1 12"


@pytest.mark.parametrize("src", ["{{ lipsum() }}", "{{ 1 / 0 }}", "{{ 10.0 ** 400 }}"])
def test_template_mistakes_are_errors_not_crashes(src, tmp_path, capsys):
    with pytest.raises(ValueError, match="template error"):
        build(src)
    (tmp_path / "t.bob.md").write_text(src + "\n")
    assert cli.main(["check", str(tmp_path / "t.bob.md")]) == cli.DOC
    assert "template error" in capsys.readouterr().err


def test_sandbox_globals_and_private_attributes(tmp_path):
    for src in ("{{ cycler }}", "{{ joiner }}", "{{ dict }}"):  # Jinja's default globals are cleared
        assert "M130" in {n.code for n in build(src).nudges}
    for src in ("{{ seq._store }}", "{{ now.__class__ }}", "{{ label.__class__ }}", "{{ range(3)._r }}"):
        refused(src, "M311")
    for src in ("{% set l = [] %}{{ l.append(1) }}", "{{ {}.update(a=1) }}"):  # immutable sandbox
        refused(src, "M311")


def test_template_symlink_out_of_the_document_folder_is_refused(tmp_path):
    outside = tmp_path / "outside.bob.md"
    outside.write_text("secret")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "t.bob.md").symlink_to(outside)
    refused("---\ntemplate: t.bob.md\n---\n", "M315", base_dir=str(docs))


# -- data files: size, unpacked size, rows ------------------------------------------------------------------

DEV_ZERO = pytest.mark.skipif(not os.path.exists("/dev/zero"), reason="no /dev/zero here")
FIFO = pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no named pipes here")


def test_a_data_file_is_read_up_to_its_limit_only(tmp_path, monkeypatch):
    (tmp_path / "d.csv").write_text("name\n" + "x\n" * 100)
    monkeypatch.setattr(datasource, "MAX_FILE", 50)
    with pytest.raises(datasource.DataError, match="larger than"):
        datasource.read_rows(str(tmp_path / "d.csv"))
    assert fileio.read_capped(tmp_path / "d.csv", 10) is None
    assert fileio.read_capped(tmp_path / "d.csv", 1000).startswith(b"name\n")


def test_reading_a_regular_file_never_changes_its_blocking_mode(tmp_path, monkeypatch):
    def refuse(fd, blocking):  # Windows has no blocking mode for files: it must never be asked
        raise AssertionError("set_blocking called on a regular file")

    monkeypatch.setattr(fileio.os, "set_blocking", refuse, raising=False)
    (tmp_path / "a.png").write_bytes(b"png")
    assert fileio.read_capped(tmp_path / "a.png", 10) == b"png"
    assert fileio.read_capped(tmp_path / "a.png", 10, pipes=True) == b"png"


@DEV_ZERO
def test_a_device_as_data_is_refused_before_it_is_read(tmp_path):
    for dev in ("/dev/zero", "/dev/tty", str(tmp_path)):  # endless, waits for a person, a folder
        if os.path.exists(dev):
            with pytest.raises(datasource.DataError, match="not a regular file"):
                datasource.read_rows(dev)


@FIFO
def test_a_pipe_named_with_data_waits_for_its_writer_as_before(tmp_path, monkeypatch):
    fifo = tmp_path / "rows.csv"
    os.mkfifo(fifo)

    def write_later():
        time.sleep(0.3)  # the reader is already waiting: --data opens a FIFO in blocking mode
        fifo.write_text("name\nRice\n")

    writer = threading.Thread(target=write_later)
    writer.start()
    assert datasource.read_rows(str(fifo)) == [{"name": "Rice"}]
    writer.join(5)
    monkeypatch.setattr(datasource, "MAX_FILE", 10)
    writer = threading.Thread(target=lambda: fifo.write_text("name\n" + "x\n" * 100))
    writer.start()
    with pytest.raises(datasource.DataError, match="larger than"):  # and it is still read up to the limit
        datasource.read_rows(str(fifo))
    writer.join(5)
    os.mkfifo(tmp_path / "s.xlsx")
    with pytest.raises(datasource.DataError, match="not a regular file"):  # a zip needs a file it can seek
        datasource.read_rows(str(tmp_path / "s.xlsx"))


def test_rows_beyond_max_read_are_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(datasource, "MAX_READ", 3)
    (tmp_path / "d.csv").write_text("n\n" + "".join(f"{i}\n" for i in range(10)))
    (tmp_path / "d.json").write_text(json.dumps([{"n": i} for i in range(10)]))
    wb = openpyxl.Workbook()
    wb.active.append(["n"])
    for i in range(10):
        wb.active.append([i])
    wb.save(tmp_path / "d.xlsx")
    for f in ("d.csv", "d.json", "d.xlsx"):
        assert [r["n"] for r in datasource.read_rows(str(tmp_path / f))] == ["0", "1", "2"], f


def test_a_spreadsheet_that_unpacks_too_large_is_refused(tmp_path, monkeypatch):
    wb = openpyxl.Workbook()
    wb.active.append(["n"])
    wb.save(tmp_path / "s.xlsx")
    monkeypatch.setattr(datasource, "MAX_UNPACKED", 1000)  # a zip bomb, in small
    with pytest.raises(datasource.DataError, match="unpacks to more than"):
        datasource.read_rows(str(tmp_path / "s.xlsx"))


@pytest.mark.parametrize(
    "name,content,why",
    [
        ("deep.json", "[" * 100_000 + "]" * 100_000, "nested too deeply"),
        ("big.json", '[{"n": ' + "9" * 5000 + "}]", "invalid JSON"),
        ("long.csv", "a,b\n" + "x" * 200_000 + ",y\n", "field larger"),
    ],
)
def test_hostile_data_files_are_errors_not_crashes(tmp_path, name, content, why):
    (tmp_path / name).write_text(content)
    with pytest.raises(datasource.DataError, match=why):
        datasource.read_rows(str(tmp_path / name))


def test_library_names_are_names_not_paths():
    for name in ("../x", "a/b", "..", ".hidden", "~x", "x.bob.md", "a\\b", ""):
        with pytest.raises(library.LibraryError):
            library.check_name(name)
    with pytest.raises(library.LibraryError):
        library.get("../config")


# -- images from files: size cap, devices -------------------------------------------------------------------


@DEV_ZERO
def test_an_image_path_to_a_device_or_a_pipe_is_refused_before_it_is_opened(tmp_path):
    paths = [p for p in ("/dev/zero", "/dev/tty") if os.path.exists(p)]
    if hasattr(os, "mkfifo"):
        os.mkfifo(tmp_path / "pipe.png")
        paths.append(str(tmp_path / "pipe.png"))
    for p in paths:
        with pytest.raises(sources.ImageError, match="not a regular file"):
            sources.load(p, "/")
    with pytest.raises(fileio.NotAFile):  # the open file is checked too: a path swapped after stat() is refused
        fileio.read_capped("/dev/zero", 10)


def test_image_files_over_the_limit_and_folders_are_refused(tmp_path, monkeypatch):
    (tmp_path / "big.png").write_bytes(b"x" * 2000)
    monkeypatch.setattr(sources, "MAX_FILE_BYTES", 1000)
    for src in ("big.png", "."):
        with pytest.raises(sources.ImageError):
            sources.load(src, str(tmp_path))


# -- SVG and PDF: never rendered taller than MAX_RENDER_DOTS, even on the way to a refusal -----------------


def tall_svg(height: int) -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 {height}" width="1" height="{height}">'
        f'<rect width="1" height="{height}"/></svg>'
    ).encode()


@pytest.mark.parametrize("height", [21, 5000, 10_000_000])  # 384 x 1.9 M dots: 5.8 GB of pixels before
def test_a_tall_svg_is_refused_without_being_drawn(height):
    start = time.monotonic()
    with pytest.raises(sources.ImageError, match="taller than"):
        sources.render_svg(tall_svg(height), 384)
    assert time.monotonic() - start < 5


def test_an_svg_drawn_taller_than_asked_is_still_refused(monkeypatch):
    import io

    from PIL import Image

    def tall(**kw):  # a renderer that ignores the height it was given
        buf = io.BytesIO()
        Image.new("L", (kw["width"], sources.MAX_RENDER_DOTS + 1), 255).save(buf, format="PNG")
        return buf.getvalue()

    resvg = pytest.importorskip("resvg_py")
    monkeypatch.setattr(resvg, "svg_to_bytes", tall)
    with pytest.raises(sources.ImageError, match="taller than"):
        sources.render_svg(tall_svg(10), 384)


def test_an_svg_at_the_height_limit_still_renders():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="1000"><rect width="48" height="1000"/></svg>'
    assert sources.render_svg(svg, 384).size == (384, 8000)


def test_a_tall_pdf_page_is_refused_before_it_is_rendered(tmp_path):
    from PIL import Image

    Image.new("L", (10, 10_000), 0).save(tmp_path / "tall.pdf")  # 10 x 10 000 pt: 384 000 dots at 384 wide
    with pytest.raises(sources.ImageError, match="taller than"):
        sources.render_pdf((tmp_path / "tall.pdf").read_bytes(), 384)


# -- images by URL: --allow-net, https, public addresses only, the checked address, no redirects, 10 MB / time


MAPPED_CGNAT = "::ffff:" + str(ipaddress.IPv4Address((100 << 24) | (64 << 16) | 1))  # the shared space of tailnets


def fake_dns(monkeypatch, *addrs):
    calls = []

    def getaddrinfo(host, port, *a, **k):
        calls.append(host)
        return [(socket.AF_INET6 if ":" in x else socket.AF_INET, socket.SOCK_STREAM, 6, "", (x, port)) for x in addrs]

    monkeypatch.setattr(sources.socket, "getaddrinfo", getaddrinfo)
    sources._CACHE.clear()
    return calls


@pytest.mark.parametrize(
    "addr",
    [
        "0.0.0.0", "224.0.0.1", "255.255.255.255", "198.18.0.1", "192.0.0.8", "240.0.0.1", "::",
        "::127.0.0.1", "::7f00:1",  # IPv4-compatible IPv6: deprecated, never public
        "64:ff9b::7f00:1", "64:ff9b::c0a8:101",  # NAT64 of loopback and of a LAN address
        "2002:c0a8:101::1",  # 6to4 of a LAN address
        "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo
        "fec0::1", "fe80::1", "ff02::1", MAPPED_CGNAT,
        "::ffff:0:7f00:1", "::ffff:0:c0a8:101",  # IPv4-translated (SIIT)
        "64:ff9b:1::808:808",  # a local NAT64 prefix
        "2606:4700::5efe:7f00:1", "2606:4700::200:5efe:c0a8:101",  # ISATAP around loopback, a LAN address
    ],
)  # fmt: skip
def test_addresses_that_reach_this_machine_or_its_network_are_refused(monkeypatch, addr):
    fake_dns(monkeypatch, addr)
    with pytest.raises(sources.ImageError) as e:
        sources.fetch("https://looks-public.example/logo.png")
    assert e.value.code == "I106"


def test_ipv4_inside_ipv6_of_a_public_address_is_public():
    for a in ("8.8.8.8", "64:ff9b::808:808", "::ffff:0:808:808", "2606:4700::5efe:808:808", "2606:4700::1111"):
        assert sources._public(a), a


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b"", wait=None):
        self.status, self.headers, self.body, self.wait = status, headers or {}, body, wait

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, n):
        if self.wait is not None:
            self.wait.wait(5)  # until the deadline shuts the socket down
        return self.body[:n]


def fake_https(monkeypatch, response):
    seen = {}

    class Conn:
        def __init__(self, host, ip, port, timeout):
            seen.update(host=host, ip=ip, port=port)
            self.raw_sock = self

        def request(self, method, path, headers):
            seen.update(method=method, path=path)

        def getresponse(self):
            return response

        def shutdown(self, how):
            if response.wait is not None:
                response.wait.set()

        def close(self):
            pass

    monkeypatch.setattr(sources, "_PinnedHTTPS", Conn)
    return seen


def test_the_connection_goes_to_the_address_that_was_checked(monkeypatch):
    calls = fake_dns(monkeypatch, "93.184.215.14")
    seen = fake_https(monkeypatch, FakeResponse(headers={"Content-Type": "image/png"}, body=b"\x89PNG"))
    assert sources.fetch("https://example.com/a.png?x=1") == (b"\x89PNG", "example.com")
    assert seen == {"host": "example.com", "ip": "93.184.215.14", "port": 443, "method": "GET", "path": "/a.png?x=1"}
    assert calls == ["example.com"]  # one lookup: no second answer (rebinding) between the check and the connection


@pytest.mark.parametrize(
    "response,why",
    [
        (FakeResponse(302, {"Location": "https://127.0.0.1/"}), "redirects are not followed"),
        (FakeResponse(200, {"Content-Type": "text/html"}, b"<html>"), "not an image"),
        (FakeResponse(200, {"Content-Type": "image/png", "Content-Length": "999999999"}), "larger than"),
        (FakeResponse(200, {"Content-Type": "image/png"}, b"x" * 2000), "larger than"),  # no length, too long
    ],
)
def test_redirects_other_types_and_large_downloads_are_refused(monkeypatch, response, why):
    monkeypatch.setattr(sources, "MAX_BYTES", 1000)
    fake_dns(monkeypatch, "93.184.215.14")
    fake_https(monkeypatch, response)
    with pytest.raises(sources.ImageError, match=why):
        sources.fetch("https://example.com/a.png")


def test_a_download_that_drips_is_cut_at_the_deadline(monkeypatch):
    monkeypatch.setattr(sources, "DEADLINE_S", 0.2)
    fake_dns(monkeypatch, "93.184.215.14")
    fake_https(monkeypatch, FakeResponse(headers={"Content-Type": "image/png"}, body=b"part", wait=threading.Event()))
    start = time.monotonic()
    with pytest.raises(sources.ImageError, match="did not finish"):
        sources.fetch("https://example.com/a.png")
    assert time.monotonic() - start < 3


def test_a_document_cannot_turn_the_network_on(monkeypatch):
    def never(url):
        raise AssertionError(f"fetched {url}")

    monkeypatch.setattr(sources, "fetch", never)
    for fm in ("allow_net: true", "allow: [I103, net]", "net: true"):
        res = build(f"---\n{fm}\n---\n![](https://example.com/logo.png)\n")
        assert not [r for r in res.rows if getattr(r, "kind", None) == "image"]


# -- -o with {column}: a data value never places a file outside the folder chosen ------------------------

HOSTILE_NAMES = ["../../x", "/abs/x", "~", "~root", "~/x", "a\\..\\b", "C:x", "..", "...", "a\x00b", " . ", ""]


@pytest.mark.parametrize("pattern", ["{name}.bin", "{name}/label.bin", "labels-{name|slug}/{name}-{n}.bin"])
def test_values_in_output_names_stay_in_the_folder(tmp_path, monkeypatch, pattern):
    folder = tmp_path / "out"
    folder.mkdir()
    monkeypatch.chdir(folder)  # a relative -o that starts with the value: '~' there was the home folder
    for v in HOSTILE_NAMES:  # one label each: two of them cleaned alike would be refused as the same name
        (p,) = export.names(pattern, [{"n": 1, "i": 1, "part": 1, "file": "doc", "fields": {"name": v}}])
        assert not p.is_absolute(), p
        p = folder / p
        assert p.resolve().is_relative_to(folder.resolve()), p
        assert all(part not in ("..", ".") and not part.startswith("~") for part in p.relative_to(folder).parts), p


def test_output_names_from_a_spreadsheet_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "doc.bob.md").write_text("{{ name }}\n")
    (tmp_path / "d.csv").write_text("name\n" + "".join(f'"{v}"\n' for v in HOSTILE_NAMES[:7]))
    code = cli.main(["print", "doc.bob.md", "--data", "d.csv", "-o", "out/{name}-{n}.bin"])
    assert code == cli.OK
    written = [p for p in tmp_path.rglob("*.bin")]
    assert len(written) == 7 and all(p.parent == tmp_path / "out" for p in written), written


def test_windows_device_names_are_never_output_names(monkeypatch):
    monkeypatch.setattr(export, "WINDOWS", True)
    assert [export.clean(v) for v in ("NUL", "con", "Com1.txt", "lpt9", "console")] == [
        "_NUL",
        "_con",
        "_Com1.txt",
        "_lpt9",
        "console",
    ]


# -- text going to the printer: C0/C1 controls never reach the stream ---------------------------------------

CONTROLS = [chr(c) for c in [*range(0, 9), *range(11, 32), 0x7F, *range(0x80, 0xA0)]]  # not \t, \n
PLACES = [
    "{{ d }}", "# {{ d }}", "### {{ d }}", "- {{ d }}", "1. {{ d }}", "- [ ] {{ d }}", "> {{ d }}",
    "| a | b |\n|---|---|\n| {{ d }} | x |", "```text\n{{ d }}\n```", "`{{ d }}`", "**{{ d }}**",
    "[{{ d }}](https://example.com)", "{{ d | markdown }}", "{{ d | upper }}", "[{{ d }}]{.invert}",
    "::: {size=small}\n{{ d }}\n:::",
]  # fmt: skip


@pytest.mark.parametrize("profile", [None, "epson-tm-t88v"])  # UTF-8 text, and a printer with code pages
@pytest.mark.parametrize("src", PLACES)
def test_control_characters_never_reach_the_printer_from_any_block(src, profile):
    """Text reaches the stream only as the characters of TextRow cells (escpos.text_row; raster rows are pixels):
    none of them may be a control, and no raw row may appear."""
    from bobina.rows import RawRow, TextRow

    payload = " ".join(f"Z{c}Q" for c in CONTROLS) + " é ß"
    for fields, text in (
        ({"d": Tainted(payload)}, src),
        ({"d": payload}, src),
        (None, src.replace("{{ d }}", payload)),
    ):
        res = build(text, fields=fields, profile_name=profile)  # data, a value of the author, the author's own text
        if fields is None and "{{" in text:
            continue  # {{ d | upper }}: only as a value
        cells = [cell.ch for r in res.rows if isinstance(r, TextRow) for cell in r.cells]
        assert "Z" in cells and not set(cells) & set(CONTROLS), src
        assert not [r for r in res.rows if isinstance(r, RawRow)]


def test_no_code_page_turns_a_letter_into_a_control_byte():
    """Native text goes out in the profile's code pages: no character any profile can send becomes a byte below
    0x20 or 0x7F (they would be printer commands)."""
    import tomllib
    from importlib import resources

    from bobina.layout import CTRL
    from bobina.profile import plain_ascii

    codecs = set()
    for f in (resources.files("bobina") / "profiles").iterdir():
        if f.name.endswith(".toml"):
            codecs |= set(tomllib.loads(f.read_text(encoding="utf-8")).get("codepages") or {})
    assert codecs, "no profile with code pages: the test would prove nothing"
    chars = [
        chr(c) for c in range(0x80, 0x10000) if not (CTRL.match(chr(c)) or plain_ascii(chr(c)) or 0xD800 <= c < 0xE000)
    ]
    for codec in sorted(codecs):
        for ch in chars:
            try:
                b = ch.encode(codec)
            except UnicodeEncodeError:
                continue
            assert all(x >= 0x20 and x != 0x7F for x in b), (codec, hex(ord(ch)), b)


# -- the --command printer and the MCP server: argv entries, never a shell ----------------------------------


def test_a_command_printer_runs_without_a_shell(tmp_path):
    import shlex
    import sys

    out, pwned = tmp_path / "job.bin", tmp_path / "pwned"
    copy = f"import sys; open({str(out)!r}, 'wb').write(sys.stdin.buffer.read())"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(copy)} ; touch {shlex.quote(str(pwned))} $(id)"
    assert cli.main(["printer", "add", "cmd", "--command", command]) == cli.OK
    assert cli.main(["print", "hello", "--yes", "--printer", "cmd"]) == cli.OK
    assert b"hello" in out.read_bytes()
    assert not pwned.exists()  # ';', 'touch' and '$(id)' were arguments of python, not shell syntax


def test_mcp_tool_arguments_are_single_argv_entries_and_text_goes_on_stdin(monkeypatch):
    anyio = pytest.importorskip("anyio")
    pytest.importorskip("mcp")
    from bobina import mcp_server

    runs = []

    async def run(argv, stdin=None, timeout=mcp_server.TIMEOUT):
        runs.append((argv, stdin))
        return mcp_server.Run(argv, 0, "{}", "")

    monkeypatch.setattr(mcp_server, "run", run)
    s = mcp_server.Server()
    evil = "x; touch /tmp/pwned $(id) `id` | rm -rf ~ --yes"
    doc = "# hi\n--yes\n$(id)"
    anyio.run(lambda: s.print(text=doc, set_={"a": evil}, data=f"d={evil}.csv", printer=evil, profile=evil))
    argv, stdin = runs[-1]
    assert stdin == doc and doc not in argv and argv[1] == "-"
    assert "--dry-run" in argv and "--yes" not in argv  # no confirm: true
    for entry in (f"--set=a={evil}", f"--data=d={evil}.csv", f"--printer={evil}", f"--profile={evil}"):
        assert entry in argv


def test_mcp_children_are_started_from_a_list_never_a_shell(monkeypatch):
    anyio = pytest.importorskip("anyio")
    import sys

    from bobina import mcp_server

    started = []

    async def open_process(command, **kw):
        started.append((command, kw))
        raise OSError("not started in tests")

    monkeypatch.setattr(anyio, "open_process", open_process)
    with pytest.raises(OSError):
        anyio.run(mcp_server.run, ["check", "-", "--set=a=$(id)"], "text")
    (command, kw) = started[0]
    assert command == [sys.executable, "-m", "bobina", "check", "-", "--set=a=$(id)"]
    assert "shell" not in kw
