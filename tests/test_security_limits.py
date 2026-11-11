"""The limits docs/SECURITY.md promises, checked one by one: each test names the promise it keeps.

Nothing here reaches the network (fake DNS, fake openers) or a printer (-o, check, preview, a file printer)."""

import time

import pytest

from bobina import cli, templating
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
