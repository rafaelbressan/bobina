"""The limits docs/SECURITY.md promises, checked one by one: each test names the promise it keeps.

Nothing here reaches the network (fake DNS, fake openers) or a printer (-o, check, preview, a file printer)."""

import json
import os
import time

import openpyxl
import pytest

from bobina import cli, datasource, fileio, library, sources, templating
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
    ],
)
def test_no_value_grows_beyond_the_output_limit(src):
    start = time.monotonic()
    refused(src)
    assert time.monotonic() - start < 5  # refused before the memory is taken, not after


def test_a_render_has_a_deadline(monkeypatch):
    monkeypatch.setattr(templating, "MAX_SECONDS", 1e-9)
    assert "s to render" in refused('{% for i in range(100) %}{{ "a" | upper }}{% endfor %}')


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


def test_a_data_file_is_read_up_to_its_limit_only(tmp_path, monkeypatch):
    (tmp_path / "d.csv").write_text("name\n" + "x\n" * 100)
    monkeypatch.setattr(datasource, "MAX_FILE", 50)
    with pytest.raises(datasource.DataError, match="larger than"):
        datasource.read_rows(str(tmp_path / "d.csv"))
    assert fileio.read_capped(tmp_path / "d.csv", 10) is None
    assert fileio.read_capped(tmp_path / "d.csv", 1000).startswith(b"name\n")


@DEV_ZERO
def test_a_device_as_data_is_capped_not_read_forever(monkeypatch):
    monkeypatch.setattr(datasource, "MAX_FILE", 1_000_000)  # /dev/zero (or a pipe) has no size to check first
    with pytest.raises(datasource.DataError, match="larger than"):
        datasource.read_rows("/dev/zero")


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
def test_an_image_path_to_a_device_is_capped(monkeypatch):
    monkeypatch.setattr(sources, "MAX_FILE_BYTES", 1_000_000)
    with pytest.raises(sources.ImageError, match="larger than"):
        sources.load("/dev/zero", "/")


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


def test_an_svg_at_the_height_limit_still_renders():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="1000"><rect width="48" height="1000"/></svg>'
    assert sources.render_svg(svg, 384).size == (384, 8000)


def test_a_tall_pdf_page_is_refused_before_it_is_rendered(tmp_path):
    from PIL import Image

    Image.new("L", (10, 10_000), 0).save(tmp_path / "tall.pdf")  # 10 x 10 000 pt: 384 000 dots at 384 wide
    with pytest.raises(sources.ImageError, match="taller than"):
        sources.render_pdf((tmp_path / "tall.pdf").read_bytes(), 384)
