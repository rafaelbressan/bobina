"""Terminal preview marks (decided 08/11: symbols only), plurals and the outcome of an error per command."""

from bobina.cli import main


def _two(isolated):
    (isolated / "a.bob.md").write_text("# Arroz\n")
    (isolated / "b.bob.md").write_text("# Feijão\n")
    return str(isolated / "a.bob.md"), str(isolated / "b.bob.md")


def test_tear_and_cut_marks(isolated, capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    a, b = _two(isolated)
    assert main(["print", "--dry-run", a, b]) == 0
    out = capsys.readouterr().out
    assert out.count("⟶") == 2 + 1  # two tear feeds drawn + the summary line
    assert "⠐⠐" not in out
    assert main(["print", "--dry-run", a, b, "--compact"]) == 0
    out = capsys.readouterr().out
    assert "✂ ┄" in out and "1 cut line ✂, 1 feed to the tear bar" in out


def test_plurals(isolated, capsys):
    (isolated / "a.bob.md").write_text("one line\n")
    assert main(["print", "--dry-run", str(isolated / "a.bob.md")]) == 0
    out = capsys.readouterr().out
    assert "1 native row," in out and "1 native rows" not in out


def test_the_outcome_of_an_error_follows_the_command(isolated, capsys):
    missing = str(isolated / "nope.bob.md")
    main(["print", missing])
    assert "nothing printed" in capsys.readouterr().err
    main(["preview", missing])
    assert "nothing saved" in capsys.readouterr().err
    main(["check", missing])
    assert "nothing" not in capsys.readouterr().err
    main(["--printer", "x", "preview", missing])  # a global option's value is not the command
    assert "nothing saved" in capsys.readouterr().err
