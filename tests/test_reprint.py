"""print --last / --again: -o saves instead of printing, and a reprint says where it went."""

from bobina import cli


def run(*argv):
    return cli.main(list(argv))


def _printed_once(tmp_path):
    sink = tmp_path / "printer.bin"
    assert run("printer", "add", "loja", "--path", str(sink)) == cli.OK
    assert run("print", "Pedido 42", "--yes", "--quiet") == cli.OK
    return sink, sink.read_bytes()


def test_last_with_output_saves_the_identical_bytes_and_prints_nothing(tmp_path, capsys):
    sink, first = _printed_once(tmp_path)
    out = tmp_path / "again.bin"
    assert run("print", "--last", "-o", str(out), "--yes") == cli.OK
    assert out.read_bytes() == first
    assert sink.read_bytes() == first  # nothing more reached the printer
    assert "nothing printed" in capsys.readouterr().err


def test_last_with_output_needs_no_confirmation(tmp_path, monkeypatch):
    sink, first = _printed_once(tmp_path)
    monkeypatch.setattr(cli.common, "open_tty", lambda: None)
    out = tmp_path / "again.bin"
    assert run("print", "--last", "-o", str(out)) == cli.OK  # saving a file is not printing
    assert out.read_bytes() == first


def test_last_with_a_name_pattern_is_refused(tmp_path):
    _printed_once(tmp_path)
    assert run("print", "--last", "-o", str(tmp_path / "{n}.bin"), "--yes") == cli.USAGE


def test_again_with_output_saves_without_printing(tmp_path):
    sink, first = _printed_once(tmp_path)
    out = tmp_path / "again.bin"
    assert run("print", "--again", "-o", str(out), "--yes") == cli.OK
    assert b"Pedido 42" in out.read_bytes()
    assert sink.read_bytes() == first


def test_reprint_says_where_it_went(tmp_path, capsys):
    sink, first = _printed_once(tmp_path)
    capsys.readouterr()
    assert run("print", "--last", "--yes") == cli.OK
    assert sink.read_bytes() == first * 2
    assert "reprinted on loja" in capsys.readouterr().err


def test_again_says_where_it_went(tmp_path, capsys):
    _printed_once(tmp_path)
    capsys.readouterr()
    assert run("print", "--again", "--yes") == cli.OK
    assert "printed on loja" in capsys.readouterr().err


def test_quiet_reprint_says_nothing(tmp_path, capsys):
    _printed_once(tmp_path)
    capsys.readouterr()
    assert run("print", "--last", "--yes", "--quiet") == cli.OK
    assert "reprinted" not in capsys.readouterr().err


def _history(tmp_path):
    import json

    from bobina import history

    return [json.loads(line) for line in history.path().read_text().splitlines()]


def test_a_reprint_is_recorded_with_its_labels_printer_and_hash(tmp_path):
    _printed_once(tmp_path)
    assert run("print", "--last", "--yes", "--quiet") == cli.OK
    last = _history(tmp_path)[-1]
    assert last["outcome"] == "reprinted" and last["printer"] == "loja"
    assert last["labels"] == 1 and last["bytes_sha256"] == _history(tmp_path)[-2]["bytes_sha256"]


def test_last_output_with_dry_run_saves_like_a_normal_print(tmp_path):
    _printed_once(tmp_path)
    out = tmp_path / "again.bin"
    assert run("print", "--last", "-o", str(out), "--dry-run") == cli.OK
    assert out.exists()  # print doc -o f --dry-run saves too: the history's "saved" is true
    assert _history(tmp_path)[-1]["saved_to"] == str(out)


def test_again_output_honours_strict(tmp_path):
    sink = tmp_path / "printer.bin"
    run("printer", "add", "loja", "--path", str(sink))
    doc = tmp_path / "d.bob.md"
    doc.write_text("# {{ nome }}\n")
    assert run("print", str(doc), "--set", "nome=x", "--yes", "--quiet") == cli.OK
    assert run("print", "--again", "-o", str(tmp_path / "x.bin"), "--strict") == cli.STRICT
    assert not (tmp_path / "x.bin").exists()


def test_reprint_output_never_replaces_the_document_of_the_last_job(tmp_path):
    sink = tmp_path / "printer.bin"
    run("printer", "add", "loja", "--path", str(sink))
    doc = tmp_path / "d.bob.md"
    doc.write_text("# Oi\n")
    assert run("print", str(doc), "--yes", "--quiet") == cli.OK
    for flag in ("--again", "--last"):
        assert run("print", flag, "-o", str(doc), "--force") == cli.USAGE
    assert doc.read_text() == "# Oi\n"


def test_a_print_to_a_file_printer_says_which_file(tmp_path, capsys):
    sink = tmp_path / "printer.bin"
    run("printer", "add", "loja", "--path", str(sink))
    capsys.readouterr()
    assert run("print", "oi", "--yes") == cli.OK
    assert f"printed on loja (file {sink})" in capsys.readouterr().err
