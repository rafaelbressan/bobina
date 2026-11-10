"""-o with {placeholders}: one file per label (bytes for print, images for preview); --pages: one PDF page each."""

import pytest
from PIL import Image

from bobina import cli, export


@pytest.fixture
def kit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.bob.md").write_text("A\n")
    (tmp_path / "b.bob.md").write_text("B\n")
    (tmp_path / "pote.bob.md").write_text("Pote {{ item }}\n")
    (tmp_path / "c.csv").write_text("item\narroz\n../../etc/passwd\ncafé\n")
    return tmp_path


def run(*argv):
    return cli.main(list(argv))


def test_numbered_images_without_data(kit):
    assert run("preview", "a.bob.md", "b.bob.md", "-o", "saida-{n}.png") == cli.OK
    assert Image.open(kit / "saida-1.png").size[0] == 384 and (kit / "saida-2.png").exists()


def test_file_part_and_i_restart_per_document(kit):
    assert (
        run("preview", "a.bob.md", "--then", "pote.bob.md", "--data", "c.csv", "-o", "out/{part}-{file}-{i:02}.jpg")
        == 0
    )
    made = sorted(p.name for p in (kit / "out").iterdir())
    assert made == ["1-a-01.jpg", "2-pote-01.jpg", "2-pote-02.jpg", "2-pote-03.jpg"]


def test_column_values_are_cleaned(kit):
    assert run("preview", "pote.bob.md", "--data", "c.csv", "-o", "tag-{item}.png") == cli.OK
    assert sorted(p.name for p in kit.glob("tag-*")) == ["tag-___etc_passwd.png", "tag-arroz.png", "tag-café.png"]
    assert not (kit.parent / "etc").exists()


def test_bytes_per_label_are_each_printable(kit):
    assert run("print", "pote.bob.md", "--data", "c.csv", "-o", "p-{n}.bin") == cli.OK
    for k in (1, 2, 3):
        data = (kit / f"p-{k}.bin").read_bytes()
        assert data.startswith(b"\x1b@") and data.endswith(b"\x1bJX")  # init … tear feed: a whole job each


def test_collisions_unknown_names_and_existing_files(kit, capsys):
    assert run("preview", "pote.bob.md", "--data", "c.csv", "-o", "x-{file}.png") == cli.USAGE
    assert "would both be saved" in capsys.readouterr().err
    assert run("preview", "pote.bob.md", "--data", "c.csv", "-o", "x-{cor}.png") == cli.USAGE
    assert "available: n, i, part, file, item" in capsys.readouterr().err
    assert run("preview", "a.bob.md", "-o", "s-{n}.png") == cli.OK
    assert run("preview", "a.bob.md", "-o", "s-{n}.png") == cli.USAGE
    assert run("preview", "a.bob.md", "-o", "s-{n}.png", "--force") == cli.OK
    assert run("preview", "a.bob.md", "b.bob.md", "-o", "s-{n}.svg") == cli.USAGE


def test_pages_pdf(kit):
    assert run("preview", "pote.bob.md", "--data", "c.csv", "--pages", "-o", "lote.pdf") == cli.OK
    assert run("preview", "a.bob.md", "--pages", "-o", "x.png") == cli.USAGE
    pdfium = pytest.importorskip("pypdfium2")  # last: skipping it skips nothing else
    assert len(pdfium.PdfDocument(str(kit / "lote.pdf"))) == 3  # pages read by a PDF library, not a regex


def test_strict_stops_the_export(kit):
    (kit / "f.bob.md").write_text("F\n\n![](missing.png)\n")
    assert run("print", "f.bob.md", "--strict", "-o", "q-{n}.bin") == cli.STRICT
    assert not (kit / "q-1.bin").exists()


def test_clean():
    assert "/" not in export.clean("../../x") and ".." not in export.clean("../../x")
    assert export.clean("a:b*c") == "a_b_c" and export.clean("") == "_"


def test_case_in_placeholders(kit):
    assert (
        run("preview", "pote.bob.md", "--data", "c.csv", "--where", "item!=../../etc/passwd", "-o", "{item|upper}.png")
        == 0
    )
    assert sorted(p.name for p in kit.glob("*.png")) == ["ARROZ.png", "CAFÉ.png"]
    assert run("preview", "pote.bob.md", "--data", "c.csv", "--where", "item=café", "-o", "{item|slug}-{n}.png") == 0
    assert (kit / "cafe-1.png").exists()
    assert run("preview", "a.bob.md", "-o", "{file|nope}.png") == cli.USAGE


def test_single_outputs_need_force_and_never_replace_inputs(kit, capsys):
    from PIL import Image

    Image.new("RGB", (30, 20), (200, 0, 0)).save(kit / "foto.png")
    before = (kit / "foto.png").read_bytes()
    assert run("preview", "foto.png") == cli.OK and (kit / "foto.preview.png").exists()
    assert run("preview", "foto.png", "-o", "foto.png", "--force") == cli.USAGE  # an input, even with --force
    assert (kit / "foto.png").read_bytes() == before
    assert run("print", "a.bob.md", "-o", "x.bin") == cli.OK
    assert run("print", "a.bob.md", "-o", "x.bin") == cli.USAGE
    assert "use --force" in capsys.readouterr().err
    assert run("print", "a.bob.md", "-o", "x.bin", "--force") == cli.OK


def test_force_and_pages_work_from_any_part_and_export_checks_folders_first(kit, capsys):
    assert run("preview", "a.bob.md", "--then", "b.bob.md", "-o", "o/{file}.png") == cli.OK
    assert run("preview", "a.bob.md", "--then", "b.bob.md", "-o", "o/{file}.png", "--force") == cli.OK
    assert run("preview", "a.bob.md", "--then", "b.bob.md", "--pages", "-o", "all.pdf") == cli.OK
    assert (kit / "all.pdf").exists()
    (kit / "cafe").write_text("I am a file")
    (kit / "d.csv").write_text("item\nmel\ncafe\n")
    capsys.readouterr()
    assert run("print", "pote.bob.md", "--data", "d.csv", "-o", "{item}/l.bin") == cli.USAGE
    assert "nothing written" in capsys.readouterr().err and not (kit / "mel").exists()


def test_file_names_keep_their_dotted_parts():
    from bobina.cli.common import file_stem

    assert file_stem("jar.v1.bob.md") == "jar.v1" and file_stem("jar.v2.bob.md") == "jar.v2"
    assert file_stem("dir/foto.jpg") == "foto" and file_stem("@pote") == "pote"
    assert file_stem("notes.md") == "notes" and file_stem("stdin") == "stdin"


def test_loose_words_suggestion_quotes_only_the_words(tmp_path, monkeypatch):
    from bobina.cli.common import quote_loose

    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.bob.md").write_text("x")
    assert quote_loose(["a.bob.md", "hello", "world"]) == 'a.bob.md "hello world"'
    assert quote_loose(["hello", "a.bob.md", "bye"]) == '"hello" a.bob.md "bye"'
