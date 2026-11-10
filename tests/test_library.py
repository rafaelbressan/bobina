"""Saved labels: bobina library add/list/show/rm and bobina print @NAME."""

from PIL import Image

from bobina import cli, library


def run(*argv):
    return cli.main(list(argv))


def test_add_print_and_remove(tmp_path, capsys):
    src = tmp_path / "shelf.bob.md"
    src.write_text("---\nfields:\n  item: { required: true }\n---\n# {{ item }}\n\n![](logo.png)\n")
    Image.new("L", (40, 40), 0).save(tmp_path / "logo.png")
    assert run("library", "add", "shelf", str(src), "--note", "pantry") == cli.OK
    src.unlink()  # the library keeps a snapshot
    capsys.readouterr()
    assert run("library", "list") == cli.OK
    out = capsys.readouterr().out
    assert "@shelf" in out and "pantry" in out and "fields: item" in out
    o = tmp_path / "o.bin"
    assert run("print", "@shelf", "--set", "item=Arroz", "-o", str(o)) == cli.OK
    data = o.read_bytes()
    assert b"Arroz" in data and b"\x1dv0" in data  # the image still resolves from the original folder
    assert run("library", "rm", "shelf") == cli.OK
    assert run("print", "@shelf", "-o", str(o)) == cli.USAGE


def test_inline_text_entry_and_replace(tmp_path):
    assert run("library", "add", "bread", "# PAO") == cli.OK
    assert run("library", "add", "bread", "# PAO 2") == cli.USAGE
    assert run("library", "add", "bread", "# PAO 2", "--force") == cli.OK
    assert library.get("bread")[0] == "# PAO 2"


def test_names_cannot_be_paths(tmp_path):
    for bad in ("../x", "a/b", ".hidden", "x.bob.md", ""):
        assert run("library", "add", bad, "# X") == cli.USAGE
    o = tmp_path / "o"
    assert run("print", "@../etc", "-o", str(o)) == cli.OK  # not a library name: printed as plain text
    assert b"@../etc" in o.read_bytes()
