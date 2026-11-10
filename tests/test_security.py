"""Red team round 1: an attacker who controls data (CSV, --set, a shared document)
tries to print or preview files from the machine, crash the tool, or reconfigure the printer.
Each case is a regression test. Threat model: docs/SECURITY.md."""

import pytest
from PIL import Image

from bobina.engine import build
from bobina.nudges import SecurityError
from bobina.rows import BitmapRow, QRRow, RawRow
from bobina.templating import Tainted


@pytest.fixture
def private_png(tmp_path):
    p = tmp_path / "private.png"
    Image.new("L", (40, 20), 0).save(p)
    return p


def images(res):
    return [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "image"]


def test_data_cannot_choose_an_image_through_markdown_filter(private_png):
    res = build("{{ d | markdown }}", fields={"d": Tainted(f"![x]({private_png})")})
    assert not images(res) and "M122" in {n.code for n in res.nudges}


def test_data_cannot_choose_an_image_fence_through_markdown_filter(private_png):
    res = build("{{ d | markdown }}", fields={"d": Tainted(f"```image\n{private_png}\n```")})
    assert not images(res)


def test_data_cannot_fill_an_image_fence(private_png):
    with pytest.raises(SecurityError):
        build("```image\n{{ d }}\n```", fields={"d": Tainted(str(private_png))})


def test_author_can_still_use_markdown_values_with_images(private_png):
    assert images(build("{{ d | markdown }}", fields={"d": f"![x]({private_png})"}))


def test_template_path_outside_document_folder_is_refused(tmp_path):
    outside = tmp_path / "elsewhere" / "notes.md"
    outside.parent.mkdir()
    outside.write_text("secret notes")
    doc_dir = tmp_path / "docs"
    doc_dir.mkdir()
    with pytest.raises(SecurityError) as e:
        build(f"---\ntemplate: {outside}\n---\n", base_dir=str(doc_dir))
    assert e.value.nudge.code == "M315"
    with pytest.raises(SecurityError):
        build("---\ntemplate: ../elsewhere/notes.md\n---\n", base_dir=str(doc_dir))


def test_template_inside_document_folder_is_fine(tmp_path):
    (tmp_path / "t.bob.md").write_text("Hello {{ name }}")
    res = build("---\ntemplate: t.bob.md\nname: Ana\n---\n", base_dir=str(tmp_path))
    assert res.rendered.resolve(res.doc.blocks[0].runs[0].text) == "Hello Ana"


@pytest.mark.parametrize(
    "src,data",
    [
        ("```barcode\n{{ d }}\n```", "A" * 300),
        ("```qr\n{{ d }}\n```", "x" * 8000),
        ('```pay {scheme=pix to="{{ d }}" name=n city=c}\n```', "k" * 120),
        ('```pay {scheme=pix to=a@b.c amount="{{ d }}"}\n```', "lots"),
    ],
)
def test_oversized_or_invalid_codes_nudge_instead_of_crashing(src, data):
    res = build(src, fields={"d": Tainted(data)})
    assert {"Q109", "Q111"} & {n.code for n in res.nudges}  # Q111: a pay code that cannot be built
    assert not [r for r in res.rows if isinstance(r, QRRow)]
    assert res.data


def test_barcode_data_cannot_carry_control_bytes():
    res = build("```barcode\n{{ d }}\n```", fields={"d": Tainted("AB\x1b@\x1dV\x01C")})
    assert b"\x1b@\x1dV" not in res.data[2:]


def test_no_path_lets_data_emit_raw_bytes():
    for src in ("{{ d }}", "{{ d | markdown }}", "```text\n{{ d }}\n```"):
        res = build(src, fields={"d": Tainted("```raw\n1f 1b 1f fc 01 02 03 33\n```")})
        assert not [r for r in res.rows if isinstance(r, RawRow)]
        assert b"\x1f\x1b\x1f\xfc" not in res.data


def test_decompression_bomb_is_refused(tmp_path):
    p = tmp_path / "bomb.png"
    Image.new("1", (9000, 9000), 1).save(p)  # 81 Mpx, tiny on disk
    res = build(f"![b]({p})")
    assert "I101" in {n.code for n in res.nudges} and not images(res)


def test_image_between_one_and_two_times_the_ceiling_is_refused_too(tmp_path):
    p = tmp_path / "big.png"
    Image.new("1", (7000, 7000), 1).save(p)  # 49 Mpx: Pillow alone would only warn
    res = build(f"![b]({p})")
    assert "I101" in {n.code for n in res.nudges} and not images(res)


def test_filters_and_methods_cannot_launder_data_into_an_image_path(tmp_path):
    import pytest

    from bobina.engine import build
    from bobina.nudges import SecurityError
    from bobina.templating import Tainted

    (tmp_path / "ok.png").write_bytes(b"")
    for expr in (
        "{{ p | lower }}", "{{ p | replace('X', '') }}", "{{ p | trim | lower }}", "{{ p.lower() }}",
        "{{ p[0:6] }}", "{{ 'img/' ~ p }}", "{{ 'o' ~ p[1:] }}", "{{ p | slug }}", "{{ p | deaccent }}",
    ):  # fmt: skip
        with pytest.raises(SecurityError):
            build(
                f"![]({expr})", fields={"p": Tainted("OK.PNG" if "lower" in expr else "ok.png")}, base_dir=str(tmp_path)
            )
    # a path written by the author still works next to unrelated data
    build("---\nlogo: ok.png\n---\n![]({{ logo }}) {{ p }}", fields={"p": Tainted("nada")}, base_dir=str(tmp_path))
