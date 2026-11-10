"""Leftovers of the retroactive review: the file's row number in M131 after filters, typed errors from
the engine instead of matching message text, one pass over argv for the history."""

import pytest

from bobina import cli


def test_m131_names_the_row_of_the_file_after_where(tmp_path, capsys):
    data = tmp_path / "rows.csv"
    data.write_text("produto,shelf\nArroz,A\nFeijão,B\n,B\n")
    doc = tmp_path / "e.bob.md"
    doc.write_text("---\nfields:\n  produto: { required: true }\n---\n# {{ produto }}\n")
    assert cli.main(["check", str(doc), "--data", str(data), "--where", "shelf=B"]) == cli.OK
    err = capsys.readouterr().err
    assert "data row 3: required field 'produto' is empty" in err  # the 3rd data row of the file, not the 2nd kept


def test_the_row_number_is_never_a_column_or_a_field(tmp_path, capsys):
    data = tmp_path / "rows.csv"
    data.write_text("produto,qtd\nArroz,0\nFeijão,x\n")
    for source in (str(data), f"d={data}"):  # named sources copy columns as d.column: the number must not follow
        assert cli.main(["check", "# {{ prodto }}", "--data", source]) == cli.OK
        err = capsys.readouterr().err
        assert "\x00" not in err and "line" not in err, err


def test_copies_from_errors_name_the_row_of_the_file(tmp_path, capsys):
    data = tmp_path / "rows.csv"
    data.write_text("produto,qtd\nArroz,0\nFeijão,x\n")
    assert cli.main(["check", "# x", "--data", str(data), "--where", "produto=Feijão", "--copies-from", "qtd"]) != 0
    assert "row 2 has 'x'" in capsys.readouterr().err


def test_engine_errors_are_typed():
    from bobina import engine

    with pytest.raises(engine.JobTooLarge):
        engine.build_batch("x", rows_data=[{}] * 2, copies=600)
    with pytest.raises(engine.NothingToPrint):
        engine.build_batch("x", rows_data=[{"a": "1"}], row_copies=[0])


def test_history_reads_argv_once():
    from bobina import history

    typed = ["print", "--set", "pix=123.456.789-00", "Comprar pão", "https://x.example/a?t=1"]  # leak-ok: fake value
    argv, secrets = history.scan(typed)
    assert argv == ["print", "--set", "pix=***", "text", "https://x.example/…"]
    assert secrets == {"123.456.789-00", "Comprar pão", "/a?t=1"}  # leak-ok: the same fake value
    assert history.redact(typed) == argv
