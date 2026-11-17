"""Data rendered as Markdown (`{{ value | markdown }}` on a --data/--set value) never enters the document's source:
it is a placeholder there, like every value, and once the document is parsed the value, parsed alone, is spliced
in with text markup only (paragraphs, emphasis, inline code, links as text, headings, lists, quotes, tables,
rules). It never sets attributes, defines links, opens or closes a block, or meets the template's text. Data stays
data through every operation of the template, and never carries bobina's reserved characters (SECURITY.md,
FORMAT §7.4)."""

import time

import pytest
from PIL import Image

from bobina import view
from bobina.engine import build
from bobina.model import Div, Fence, Heading, ListBlock, Paragraph, Quote, Table
from bobina.nudges import SecurityError
from bobina.rows import BitmapRow, QRRow, RawRow
from bobina.templating import Tainted

T = Tainted
RAW = "x\n```raw\n1b 40\n```\n"  # each probe would send ESC @ (reset) if it became a raw block
BOX = "x\n::: {.box title=HACK}\ny"


def codes(res) -> set[str]:
    return {n.code for n in res.nudges}


def said(res, code: str) -> list:
    return [n for n in res.nudges if n.code == code]


def raws(res) -> list[bytes]:
    return [r.data for r in res.rows if isinstance(r, RawRow)]


def images(res) -> list:
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "image"]


def walk(blocks):
    for b in blocks:
        yield b
        if isinstance(getattr(b, "children", None), list):
            yield from walk(b.children)
        for it in getattr(b, "items", []):
            yield from walk(it.children)


def divs(res) -> list[Div]:
    return [b for b in walk(res.doc.blocks) if isinstance(b, Div)]


def fences(res) -> list[Fence]:
    return [b for b in walk(res.doc.blocks) if isinstance(b, Fence)]


def printed(res) -> str:
    return "\n".join(view.lines(res.rows, res.profile))


def md(template: str, **values):
    return build(template, fields={k: T(v) for k, v in values.items()})


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "secret.png"
    Image.new("L", (40, 20), 0).save(p)
    return str(p)


# --- data stays data through every operation of the template ------------------------------------------------------


EXPRS = [
    "d", "(d ~ '')", "('' ~ d)", "('%s' % d)", "('%.400s' % d)", "('{}'.format(d))", "('%s' | format(d))",
    "(d * 1)", "d[0:]", "d | upper | lower", "d.replace('Q', 'Q')", "d | trim", "[d] | join", "d | list | join",
    "{'k': d}.k", "d | replace('Q', 'Q')", "d | map('lower') | join",
]  # fmt: skip


@pytest.mark.parametrize("expr", EXPRS)
def test_whatever_the_template_does_with_data_it_brings_no_raw_image_or_box(expr, photo):
    for value, code in ((RAW, "M121"), (f"![x]({photo})", "M122"), (BOX, "M123")):
        res = md("{{ " + expr + " | markdown }}\nafter\n", d=value)
        assert not raws(res) and not images(res) and not divs(res) and code in codes(res), (expr, value)


@pytest.mark.parametrize("crlf", ["\r\n", "\r"])
def test_line_breaks_of_any_kind(crlf):
    for expr in ("d", "('%s' % d)", "('{}'.format(d))"):
        res = md("{{ " + expr + " | markdown }}\n", d=RAW.replace("\n", crlf))
        assert not raws(res) and len(said(res, "M121")) == 1


def test_loops_and_namespaces_keep_data_data(photo):
    for src in (
        "{% for c in d %}{{ c | markdown }}{% endfor %}\n",
        "{% for x in [d, 'ok'] %}{{ x | markdown }}{% endfor %}\n",
        "{% set ns = namespace(x=d) %}{{ ns.x | markdown }}\n",
        "{% set x = d %}{{ x | replace(x[0], x[0]) | markdown }}\n",
    ):
        for value in (RAW, f"![x]({photo})"):
            res = md(src, d=value)
            assert not raws(res) and not images(res) and not fences(res), src


def test_bytes_cannot_launder_data():
    with pytest.raises(SecurityError):
        md("{{ d.encode().decode() | markdown }}\n", d=RAW)


def test_data_column_names_are_data_too(photo):
    res = build("{% for k in row %}{{ k | markdown }}{% endfor %}\n", fields={"row": {T(f"![x]({photo})"): T("v")}})
    assert not images(res) and "M122" in codes(res)


# --- only text markup, said at the document's line, once ---------------------------------------------------------


@pytest.mark.parametrize(
    "value, code",
    [
        ("x\n```raw\n1b 40\n", "M121"),  # never closed
        ("x\n```raw\n1b 40\n`````\n", "M121"),  # closed by a longer fence
        ("x\n> ```raw\n> 1b 40\n> ```\n", "M121"),  # in a quote
        ("x\n- ```raw\n  1b 40\n  ```\n", "M121"),  # in a list item
        ("x\n~~~raw\n1b 40\n~~~\n", "M121"),
        ("```qr\nhttps://evil.example\n```", "M123"),  # data does not make objects
        ('```pay {scheme=pix to="x@y.z" name=A city=B}\n```', "M123"),
        ("```barcode\n123\n```", "M123"),
        ("```contact whatsapp\n+55 11 90000-0000\n```", "M123"),
        ("```\nplain code\n```", "M123"),
        ("para\n\n    indented code\n", "M123"),
        ("x\n::: {.box}\ny\n:::", "M123"),
        ("one\n:::\ntwo", "M123"),
        ("[logo]: /etc/passwd\n", "M123"),
        ('[logo]:\n  /etc/passwd\n  "title"\n', "M123"),  # a definition over lines
    ],
)
def test_blocks_data_may_not_bring_are_refused_at_the_documents_line_once(value, code):
    res = md("intro\n\n{{ d | markdown }}\n", d=value)
    assert not raws(res) and not fences(res) and not divs(res)
    (refusal,) = said(res, code)
    assert refusal.line == 3


def test_text_markup_from_data_works():
    value = "# Title\n\n**bold** and *it* ~~old~~ `code` [link](https://x.example)\n\n- a\n- b\n\n> q\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n---"  # noqa: E501
    res = md("{{ d | markdown }}\n", d=value)
    kinds = {type(b) for b in walk(res.doc.blocks)}
    assert {Heading, Paragraph, ListBlock, Quote, Table} <= kinds and codes(res) == {"M120"}
    assert "`code`" not in printed(res) and "code" in printed(res)  # no escape ever printed


def test_data_never_sets_attributes():
    res = md("```qr\nhttps://shop.example\n```\n{{ d | markdown }}\n", d="{module=1 width=10 .left}")
    assert isinstance(res.doc.blocks[0], Fence) and not res.doc.blocks[0].attrs.kv
    assert "{module=1 width=10 .left}" in printed(res)
    res = md("# Sale {{ d | markdown }}\n", d="now {.invert size=huge}")
    heading = res.doc.blocks[0]
    assert not heading.attrs.classes and "{.invert size=huge}" in "".join(r.text for r in heading.runs)


def test_a_payment_cannot_be_rewritten_by_data():
    tpl = '```pay {scheme=pix to="shop@example.com" name=Shop city=Rio amount=10.00}\n```\n{{ d | markdown }}\n'
    res = md(tpl, d="{amount=500 to=thief@example.com}")
    (pay,) = fences(res)
    assert pay.attrs.kv["amount"] == "10.00" and pay.attrs.kv["to"] == "shop@example.com"


def test_data_never_defines_a_link_the_document_uses(photo, tmp_path):
    logo = tmp_path / "logo.png"
    Image.new("L", (40, 20), 255).save(logo)
    for value in (f"[logo]: {photo}", f"[logo]:\n  {photo}", f"\\[x]\n[logo]: {photo}"):
        res = md(f"![logo][logo]\n\n[logo]: {logo}\n\n{{{{ d | markdown }}}}\n", d=value)
        assert [b.src for b in res.doc.blocks if type(b).__name__ == "Image"] == [str(logo)]
        assert "M123" in codes(res) or value.startswith("\\")  # after a paragraph line it is only text
    res = md(f"{{{{ d | markdown }}}}: {photo}\n\n![logo][logo]\n", d="[logo]")  # [label] then the document's
    assert not images(res)


def test_two_values_on_one_line_never_join_into_markup(photo):
    for a, b in (("```", "raw\n1b 40\n```"), (":", ":: {.box title=HACK}\ny"), ("!", f"[x]({photo})"),
                 ("``", "`raw\n1b 40\n```"), ("[logo]", ": /etc/passwd")):  # fmt: skip
        res = md("{{ a | markdown }}{{ b | markdown }}\nz\n\n![logo][logo]\n", a=a, b=b)
        assert not raws(res) and not divs(res) and not images(res) and not fences(res), (a, b)


def test_in_the_documents_code_the_value_is_plain_text_with_no_escapes():
    value = "x\n```\n~~~\n::: {.box title=HACK}\nq\n```"
    res = md("~~~\n{{ d | markdown }}\n~~~\nend `{{ d | markdown }}`\n", d=value)
    (fence,) = fences(res)
    assert res.rendered.resolve(fence.content) == value + "\n" and not divs(res)
    assert "\\" not in printed(res) and isinstance(res.doc.blocks[-1], Paragraph)


@pytest.mark.parametrize("value", ["x\n```\n", "x\n~~~\n", "x\n````", "one\n:::\ntwo", "one\r:::\rtwo",
                                   "one\n> :::\ntwo", "one\n- :::\ntwo"])  # fmt: skip
def test_data_never_swallows_or_closes_the_documents_box(value):
    res = md("::: {.box}\n{{ d | markdown }}\n\nmine\n:::\nend\n", d=value)
    (box,) = divs(res)
    assert box.closed and isinstance(box.children[-1], Paragraph) and isinstance(res.doc.blocks[-1], Paragraph)
    assert "M105" not in codes(res)


def test_the_documents_raw_block_never_takes_data_and_its_image_block_never_a_path(photo):
    with pytest.raises(SecurityError):
        md("```raw\n{{ d | markdown }}\n```\n", d="1b 40")
    with pytest.raises(SecurityError):
        md("```image\n{{ d | markdown }}\n```\n", d=photo)


def test_data_never_chooses_a_code_blocks_kind():
    res = md("```{{ lang | markdown }}\n1b 40\n```\n", lang="raw")
    (fence,) = fences(res)
    assert fence.kind == "text" and fence.content == "1b 40\n" and not raws(res) and "M123" in codes(res)


def test_the_documents_box_title_and_qr_caption_may_come_from_data():
    res = md('::: {.box title="{{ t | markdown }}"}\nx\n:::\n', t="**TABLE** 4")
    assert divs(res) and "**TABLE** 4" in printed(res)
    res = md('```qr {caption="{{ c | markdown }}"}\nhttps://shop.example\n```\n', c="Menu *today*")
    (qr,) = fences(res)
    assert qr.kind == "qr" and qr.attrs.kv["caption"] and "M123" not in codes(res)
    assert [r for r in res.rows if isinstance(r, (QRRow, BitmapRow))]


def test_a_long_chain_of_tildes_prints_quickly_and_says_it():
    start = time.perf_counter()
    res = md("{{ d | markdown }}\n", d="~~~\n" * 1000)
    assert time.perf_counter() - start < 5 and "M123" in codes(res) and "M313" not in codes(res)


def test_a_big_document_with_data_costs_about_what_it_costs_without():
    body = "Line of the document with some *text* in it.\n\n" * 9000  # ~400 KB
    value = ("- item **bold**\n" * 200) + RAW

    def took(src):
        start = time.perf_counter()
        build(src, fields={"d": T(value)})
        return time.perf_counter() - start

    plain = took(body + "{{ d }}\n")
    marked = took(body + "{{ d | markdown }}\n")
    assert marked < plain * 1.5 + 0.2


# --- no false positives ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("data", ["for", "Shop", "secret", "100"])
def test_data_that_appears_in_the_authors_own_text_changes_nothing(data, tmp_path):
    folder = tmp_path / "secret-shop-for-100"
    folder.mkdir()
    logo = folder / "logo.png"
    Image.new("L", (40, 20), 0).save(logo)
    mine = f"::: {{.box title=Shop}}\nfor 100 :fragile:\n:::\n\n![logo]({logo})\n"
    front = "---\nv: |\n" + "".join(f"  {ln}\n" for ln in mine.splitlines()) + "---\n"  # the author's own value
    res = build(front + "{{ v | markdown }}\n\n{{ d }}\n", fields={"d": T(data)})
    assert divs(res) and images(res) and not codes(res) - {"P301", "I109"}


def test_plain_values_are_unchanged_and_the_authors_markdown_keeps_everything():
    res = md("{{ d }}\n", d="::: {.box}\n```raw\n1b 40\n```")
    assert [type(b) for b in res.doc.blocks] == [Paragraph] and not raws(res) and not codes(res)
    for src in (
        '---\nv: "::: {.box}\\n```qr\\nhi\\n```\\n:::"\n---\n{{ v | markdown }}\n',  # front matter
        '{{ "::: {.box}\\n```qr\\nhi\\n```\\n:::" | markdown }}\n',
    ):  # a literal of the template
        res = build(src)
        assert divs(res) and fences(res) and "M123" not in codes(res), src
    res = build("{{ v | markdown }}\n", fields={"v": "::: {.box}\n```qr\nhi\n```\n:::"})  # handed in: data
    assert not divs(res) and not fences(res) and "M123" in codes(res)


# --- data never carries bobina's reserved characters -------------------------------------------------------------


def test_a_value_with_a_placeholder_character_cannot_show_another_values_text():
    res = md("A={{ a }}\n\nB={{ b }}\n", a="SECRET", b="\ue0000\ue001")
    assert printed(res).count("SECRET") == 1 and "M124" in codes(res)
    res = build("A={{ a }}\n\nB={{ b[0] }}\n", fields={"a": "SECRET", "b": ["\ue0000\ue001"]})  # in a list too
    assert printed(res).count("SECRET") == 1 and "M124" in codes(res)
    res = build("{% for k in row %}{{ k }}{% endfor %}\n", fields={"row": {T("\ue0000\ue001"): T("v")}})  # a key
    assert "M124" in codes(res)


def test_ordinary_data_is_untouched_and_not_copied():
    fields = {"d": T("Café 10:30 · R$ 4,50"), "rows": [{"a": T("1")}]}
    from bobina.nudges import Nudges
    from bobina.templating import clean_data

    assert clean_data(fields, Nudges()) is fields
    res = build("{{ d }}\n", fields=fields)
    assert "Café 10:30 · R$ 4,50" in printed(res) and "M124" not in codes(res)


# --- only the author's own values get all of Markdown ------------------------------------------------------------


@pytest.mark.parametrize(
    "src",
    [
        "{% for v in row.values() %}{{ v | markdown }}{% endfor %}\n",
        "{% for k in row.keys() %}{{ k | markdown }}{% endfor %}\n",
        "{% for k, v in row.items() %}{{ k | markdown }}{{ v | markdown }}{% endfor %}\n",
        "{% set ns = namespace(x=row['k']) %}{{ ns.x | markdown }}\n",
        "{{ (row['k'] | string)[0:] | markdown }}\n",
        "{{ row['k'] | replace('Q', '\\n') | markdown }}\n",
        "{{ [row['k']] | first | markdown }}\n",
    ],
)
def test_values_inside_containers_and_computed_strings_are_never_the_authors(src, photo):
    for value in (RAW, f"![x]({photo})", BOX, "{.invert}"):
        for row in ({T(value): T(value), "k": T(value)}, {value: value, "k": value}):  # tainted or plain
            res = build(src, fields={"row": row})
            assert not raws(res) and not images(res) and not divs(res) and not fences(res), (src, value)
            assert not any(b.attrs.classes for b in walk(res.doc.blocks)), (src, value)


def test_an_image_path_from_data_is_refused_through_assignments():
    src = "{% set a = d %}{% set b = [a] %}{% set c = b | first %}![x]({{ c }})\n"
    with pytest.raises(SecurityError) as err:
        md(src, d="/etc/secret.png")
    assert err.value.nudge.code == "M312"


def test_the_authors_front_matter_may_name_a_code_blocks_kind():
    res = build("---\nk: python\n---\n```{{ k }}\nx = 1\n```\n")
    assert "M102" in codes(res) and "M123" not in codes(res)  # an unknown kind, printed as text


def test_refusals_are_said_at_the_line_the_value_is_written_on():
    res = md("intro\nsecond line {{ d | markdown }}\n", d="![x](p.png)")
    assert [n.line for n in said(res, "M122")] == [2]
    res = md("| a | b |\n|---|---|\n| 1 | 2 |\n| x | {{ d | markdown }} |\n", d="![x](p.png)")
    assert [n.line for n in said(res, "M122")] == [4]


@pytest.mark.parametrize("tail", [" {.center}", "\n{.center}"])
def test_the_authors_attributes_after_a_value_apply_to_its_blocks(tail):
    res = md("{{ d | markdown }}" + tail + "\n", d="# Title\n\nline one\n\nline two")
    assert [type(b) for b in res.doc.blocks] == [Heading, Paragraph, Paragraph]
    assert all(b.attrs.has("center") for b in res.doc.blocks)


def test_escaped_braces_in_data_print_as_braces():
    res = md("{{ d | markdown }}\n", d="\\{x} and {y}")
    assert "".join(r.text for r in res.doc.blocks[0].runs) == "{x} and {y}"


def test_two_documents_built_at_once_keep_their_own_values():
    import threading

    results = {}

    def one(name):
        res = md("{{ d | markdown }}\n", d=f"**{name}**")
        results[name] = "".join(r.text for b in res.doc.blocks for r in b.runs)

    threads = [threading.Thread(target=one, args=(f"N{k}",)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == {f"N{k}": f"N{k}" for k in range(8)}


# --- the last review's proofs of concept -------------------------------------------------------------------------

LETTERS = "'#*![]()abcdefghijklmnopqrstuvwxyz.:/ '"


@pytest.mark.parametrize("step", ["'{}{}'.format(ns.s, a)", "ns.s ~ a", "'%s%s' % (ns.s, a)"])
def test_data_rebuilt_from_the_templates_own_letters_is_not_the_authors(step):
    src = ("{% set ns = namespace(s='') %}{% for c in d %}{% for a in " + LETTERS + " %}{% if c == a %}"
           "{% set ns.s = " + step + " %}{% endif %}{% endfor %}{% endfor %}{{ ns.s | markdown }}\n")  # fmt: skip
    res = md(src, d="![x](/etc/passwd)")
    assert not images(res) and "M122" in codes(res)


def test_an_operation_on_the_authors_text_is_not_the_authors():
    from bobina.templating import Trusted, carry

    assert type(carry(Trusted("{}{}"), (Trusted("{}{}"), "x"))) is str
    res = build("---\na: '**x**'\n---\n{{ '{}{}'.format(a, '![i](p.png)') | markdown }}\n")
    assert not images(res) and "M122" in codes(res)


@pytest.mark.parametrize("expr", ["d | striptags", "(d ~ '') | striptags", "d | replace('&', '&') | striptags"])
def test_entities_in_data_never_become_a_placeholder(expr):
    res = md("{{ a | markdown }}\n\n{{ " + expr + " }}\n", a="SECRET", d="&#57344;0&#57345; {.invert size=4}")
    assert printed(res).count("SECRET") == 1
    assert not any(b.attrs.classes for b in res.doc.blocks)


@pytest.mark.parametrize(
    "src",
    [
        "```{{ 'qr' }}\nhi\n```\n",
        "{% set k = 'qr' %}```{{ k }}\nhi\n```\n",
        "---\nkind: qr\n---\n```{{ kind }}\nhi\n```\n",
        "---\nkind: qr\n---\n```{{ kind | default('text') }}\nhi\n```\n",
        "---\nkinds: [qr]\n---\n```{{ kinds | first }}\nhi\n```\n",
        "---\nkinds: [qr]\n---\n```{{ kinds[0] }}\nhi\n```\n",
    ],
)
def test_the_authors_own_value_names_a_code_blocks_kind(src):
    res = build(src)
    (fence,) = fences(res)
    assert fence.kind == "qr" and [r for r in res.rows if isinstance(r, (QRRow, BitmapRow))]
    assert not codes(res) & {"M102", "M123"}


def test_an_unknown_kind_from_the_author_is_said_without_private_characters():
    res = build("---\nk: python\n---\n```{{ k }}\nx = 1\n```\n")
    (note,) = said(res, "M102")
    assert "python" in note.message and not any("\ue000" <= c <= "\ue004" for c in note.message)


def test_a_refusal_is_said_once_per_value_even_in_a_loop():
    res = md("{% for i in range(50) %}{{ d | markdown }}\n\n{% endfor %}", d="![x](p.png)")
    assert len(said(res, "M122")) == 1


def test_the_refusals_say_the_value_is_not_the_authors_own():
    res = build("{% set p = 'p.png' %}{{ ('![i](' ~ p ~ ')') | markdown }}\n")  # computed: no --data in sight
    (refusal,) = said(res, "M122")
    assert "not the author's own" in refusal.message and "--data" not in refusal.message


# --- the review after it -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["# Head {.invert}", "```raw\n1b 40\n```", "::: {.box title=HACK}\ny\n:::"])
def test_filter_blocks_are_refused(value):
    with pytest.raises(SecurityError) as err:
        md("{% filter replace('X', d) %}X{% endfilter %}\n", d=value)
    assert err.value.nudge.code == "M311"


@pytest.mark.parametrize("index", ["0", "9"])
def test_numbers_never_make_a_placeholder(index):
    fields = {"o": T("57344"), "c": T("57345"), "a": T("SECRET")}
    res = build("{{ a }}\n\n{{ '%c" + index + "%c' % (o|int, c|int) }}\n", fields=fields)
    assert printed(res).count("SECRET") == 1 and "M124" in codes(res)
    assert len(said(res, "M124")) == 1


def test_the_authors_value_through_an_identity_filter_keeps_all_of_markdown(tmp_path):
    logo = tmp_path / "logo.png"
    Image.new("L", (40, 20), 0).save(logo)
    res = build(f"---\nlogo: '![i]({logo})'\n---\n{{{{ logo | default('') | markdown }}}}\n")
    assert images(res) and "M122" not in codes(res)


# --- what a template may be made of ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src, code, said",
    [
        ("{% macro m(v) %}{{ v }}{% endmacro %}{{ m(d) }}", "M311", "{% macro %} is not allowed"),
        ("{% macro m() %}{{ caller() }}{% endmacro %}{% call m() %}{{ d }}{% endcall %}", "M311", "{% macro %}"),
        ("{% call(x) range(1) %}{{ d }}{% endcall %}", "M311", "{% call %} is not allowed"),
        ("{% filter upper %}{{ d }}{% endfilter %}", "M311", "{% filter %} is not allowed"),
        ("{% set x %}{{ d }}{% endset %}{{ x }}", "M311", "{% set x %}…{% endset %} is not allowed"),
        ("{% block b %}x{% endblock %}", "M311", "{% block %} is not allowed"),
        ("{% extends 'x' %}", "M311", "{% extends %} is not allowed"),
        ("{% autoescape true %}{{ d }}{% endautoescape %}", "M311", "{% autoescape %} is not allowed"),
        ("{% include 'x' %}", "M310", "templates cannot read files"),
        ("{% import 'x' as y %}", "M310", "templates cannot read files"),
        ("{% from 'x' import y %}", "M310", "templates cannot read files"),
    ],
)
def test_a_construct_outside_the_allowlist_is_refused_before_it_runs(src, code, said):
    with pytest.raises(SecurityError) as err:
        md(src + "\n", d="```raw\n1b 40\n```")
    assert err.value.nudge.code == code and said in err.value.nudge.message


@pytest.mark.parametrize(
    "payload",
    ["```raw\n1b 40\n```", "```qr\nhttps://evil.example\n```", "::: {.box title=HACK}\ny\n:::", "x {.invert}",
     "![x](/etc/secret.png)"],
)  # fmt: skip
def test_call_blocks_cannot_write_data_into_the_document(payload):
    src = "{% macro m() %}{{ caller() }}{% endmacro %}{% call m() %}{{ d }}{% endcall %}\n"
    with pytest.raises(SecurityError) as err:
        md(src, d=payload)
    assert err.value.nudge.code == "M311"


def test_the_allowed_constructs_work():
    src = ("{% set ns = namespace(n=0) %}{% for x in [1, 2, 3] if x > 1 %}{% set ns.n = ns.n + x %}"
           "{% else %}none{% endfor %}{% with y = ns.n * 2 %}{% if y > 5 and not false %}{{ y }}"
           "{% elif y %}{{ -y }}{% endif %}{% endwith %} {{ {'a': (1, 2)}['a'][0:1] | first }} "
           "{{ 'a' ~ ('b' if true else 'c') }} {{ 7 // 2 }}{{ 7 % 4 }}{{ 2 ** 3 }}")  # fmt: skip
    res = build(src + "\n")
    assert res.rendered.resolve(res.rendered.text).strip() == "10 1 ab 338"


def test_a_field_default_keeps_the_authors_markdown_and_its_data_stays_data():
    src = '---\nfields:\n  v: {default: "**{{ d }}** _x_"}\n---\n{{ v }}\n'
    res = md(src, d="Ana {.invert} ![i](p.png)")
    runs = res.doc.blocks[0].runs
    assert any(r.bold for r in runs) and any(r.italic for r in runs)
    assert "Ana {.invert} ![i](p.png)" in printed(res) and not images(res)
    assert not res.doc.blocks[0].attrs.classes


@pytest.mark.parametrize("expr", ["ns.x", "row.values() | first", "row.items() | list | first | last"])
def test_defaults_built_from_hidden_data_stay_data(expr):
    src = ('---\nfields:\n  v: {default: "{{ ' + expr + ' }}"}\n---\n{% set ns = namespace(x=row["k"]) %}'
           "{{ v | markdown }}\n")  # fmt: skip
    res = build(src, fields={"row": {"k": T("```raw\n1b 40\n```")}})
    assert not raws(res) and not fences(res)


def test_a_huge_value_is_refused_without_taking_memory():
    import tracemalloc

    tracemalloc.start()
    try:
        with pytest.raises(SecurityError):
            build('{% set b = "x" * 1900000 %}{% for i in range(1500) %}{{ b }}{% endfor %}')
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 64 * 2**20


def test_two_thousand_distinct_values_as_markdown_build_in_time():
    start = time.perf_counter()
    res = md("{% for i in range(1999) %}{{ (d ~ i) | markdown }}\n\n{% endfor %}", d="**x** ")
    assert time.perf_counter() - start < 10 and len(res.doc.blocks) == 1999


# --- the review of the allowlist ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src",
    [
        "{% set t = '**{}**' | markdown %}{{ t.format(d) }}\n",
        "{% set t = '{x}' | markdown %}{{ t.format_map({'x': d}) }}\n",
        "{% set t = '**%s**' | markdown %}{{ t | format(d) }}\n",
    ],
)
def test_formatting_the_authors_markdown_with_data_gives_data(src):
    for value in (RAW, "::: {.box title=HACK}\nyo\n:::"):
        res = md(src, d=value)
        assert not raws(res) and not divs(res) and not fences(res), (src, value)


def test_no_wrapper_hides_str_format_from_the_sandbox():
    from jinja2.sandbox import SandboxedEnvironment

    from bobina.templating import MdData, MdSafe, Trusted

    jinja = SandboxedEnvironment()  # it wraps a bound str.format/format_map it can see: none may be hidden from it
    for kind in (T, Trusted, MdSafe, MdData):
        for name in ("format", "format_map"):
            assert jinja.wrap_str_format(getattr(kind("{}"), name)) is not None, (kind, name)


def test_a_default_with_data_is_its_text_in_expressions_and_the_authors_markdown_in_the_document():
    front = "---\nfields:\n  k:\n    default: '{{ name }}!'\n  b:\n    default: '**{{ name }}**'\n---\n"
    res = md(front + "{{ k | upper }}|{{ k }}|{{ k | length }}|{% if k == 'Bob!' %}eq{% endif %}|{{ k[0:2] }}\n\n"
             "{{ other | default(b) }}\n", name="Bob")  # fmt: skip
    assert "BOB!|Bob!|4|eq|Bo" in printed(res) and not codes(res)
    assert any(r.bold for r in res.doc.blocks[1].runs)  # the author's ** around the data, which prints as text


def test_a_default_without_data_is_the_authors_markdown_in_both():
    res = build("---\nfields:\n  k:\n    default: '**{{ 2 + 2 }}**'\n---\n{{ k }}\n\n{{ k | upper }}\n")
    assert res.doc.blocks[0].runs[0].bold and "**4**" in printed(res)


def test_a_raw_block_in_the_authors_default_never_reaches_the_printer():
    res = md('---\nfields:\n  k:\n    default: "```raw\\n1b 40\\n```\\n{{ name }}"\n---\n{{ k }}\n', name="Bob")
    assert not raws(res)


def test_the_authors_own_objects_are_not_data(tmp_path):
    res = build("![](img/{{ seq.n }}.png)\n", base_dir=str(tmp_path))
    assert "I101" in codes(res)  # looked for, not refused as a path from data
    res = build("---\nx:\n  a: '**b**'\n---\n{% for k, v in x.items() | list %}{{ v | markdown }}{% endfor %}\n")
    assert res.doc.blocks[0].runs[0].bold and "M120" not in codes(res)
    res = build("{% set ns = namespace(x='**a**') %}{{ ns.x | markdown }} {{ self }}\n")
    assert "M120" not in codes(res)


def test_a_refused_construct_is_said_at_its_document_line_or_in_its_field_or_template(tmp_path):
    with pytest.raises(SecurityError) as err:
        build("---\na: 1\nb: 2\nc: 3\n---\nline1\nline2\n{% macro m() %}x{% endmacro %}\n")
    assert err.value.nudge.line == 8
    with pytest.raises(SecurityError) as err:
        build("---\nfields:\n  k:\n    default: '{% macro m() %}x{% endmacro %}{{ 1 }}'\n---\n{{ k }}\n")
    assert "default of field 'k'" in err.value.nudge.message
    (tmp_path / "t.bob.md").write_text("one\n{% filter upper %}x{% endfilter %}\n")
    with pytest.raises(SecurityError) as err:
        build("---\ntemplate: t.bob.md\n---\n", base_dir=str(tmp_path))
    assert "template t.bob.md, line 2" in err.value.nudge.message and err.value.nudge.line is None
