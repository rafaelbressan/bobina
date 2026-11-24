"""Asterisks as decoration: four or more in a row print as written (receipts frame text with them), M106 says so,
***text*** stays bold italic with M107, and literal_asterisks (front matter, config.toml) turns it off."""

import pytest

from bobina import cli
from bobina.engine import build
from bobina.nudges import Nudges
from bobina.parser import parse


def runs(src: str, **kw) -> tuple[list[tuple[str, bool, bool]], list]:
    n = Nudges()
    doc = parse(src, n, **kw)
    return [(r.text, r.bold, r.italic) for r in doc.blocks[0].runs if r.text != "\n"], list(n)


def text(src: str, **kw) -> str:
    return "".join(t for t, _b, _i in runs(src, **kw)[0])


def codes(problems) -> list[str]:
    return [p.code for p in problems]


@pytest.mark.parametrize(
    "src",
    ["****EXTRATO PARA SIMPLES CONFERENCIA****", "*****AGUARDE O CUPOM DE FECHAMENTO*****", "a ****** b"],
)
def test_four_or_more_print_as_written_and_never_bold(src):
    got, problems = runs(src)
    assert "".join(t for t, _b, _i in got) == src
    assert not any(b or i for _t, b, i in got)
    assert codes(problems) == ["M106"]


def test_m106_once_with_the_other_lines_named():
    _got, problems = runs("****A****\n*****B***** {.center}\n\nx\n\n****C****\n")
    (n,) = problems
    assert n.code == "M106" and n.line == 1
    assert n.message == "****A**** printed as asterisks, not bold (also lines 2, 6)"
    assert "literal_asterisks: false" in n.suggestion


def test_bold_and_italic_still_work_and_say_nothing():
    got, problems = runs("**bold** and *italic* and ** spaced **")
    assert ("bold", True, False) in got and ("italic", False, True) in got
    assert not problems


def test_three_stars_are_bold_italic_with_a_note_that_shows_the_escape():
    got, problems = runs("***TOTAL***")
    assert got == [("TOTAL", True, True)]
    (n,) = problems
    assert n.code == "M107" and n.line == 1
    assert n.message == "***TOTAL*** prints TOTAL in bold italic, without the asterisks"
    assert n.suggestion == "to print the asterisks, write \\*\\*\\*TOTAL\\*\\*\\*"


def test_three_stars_with_spaces_and_escapes_stay_text_without_notes():
    assert runs("*** MESA 008 ***") == ([("*** MESA 008 ***", False, False)], [])
    got, problems = runs("\\*\\*\\*\\*A\\*\\*\\*\\*")
    assert "".join(t for t, _b, _i in got) == "****A****" and not problems


def test_code_tables_and_dividers():
    n = Nudges()
    doc = parse("`****x****`\n\n****\n\n| | |\n|---|--:|\n| ****TOTAL**** | 9,00 |\n", n)
    kinds = [type(b).__name__ for b in doc.blocks]
    assert kinds == ["Paragraph", "Divider", "Table"]  # a line of stars alone is still a divider
    assert doc.blocks[0].runs[0].text == "****x****"
    assert "".join(r.text for r in doc.blocks[2].rows[0][0]) == "****TOTAL****"
    assert [(p.code, p.line) for p in n] == [("M106", 7)]  # code says nothing


def test_off_reads_them_as_markdown():
    got, problems = runs("****A****", literal_asterisks=False)
    assert got == [("A", True, False)] and not problems


@pytest.mark.parametrize("src", ["***a* b**", "***[site](https://example.com)***", "***R$ **9**,00***"])
def test_m107_only_for_one_plain_text_closed_together(src):
    assert "M107" not in codes(runs(src)[1])  # its hint would change what the author wrote


def test_m106_quotes_the_run_not_the_sentence():
    _got, problems = runs("Obrigado pela preferencia, volte sempre ****FIM**** {.center}")
    assert problems[0].message == "****FIM**** printed as asterisks, not bold"


def test_front_matter_wins_and_a_wrong_value_is_m101():
    res = build("---\nliteral_asterisks: false\n---\n****A****\n")
    assert "M106" not in codes(res.nudges)
    res = build("---\nliteral_asterisks: talvez\n---\n****A****\n")
    m101 = [n for n in res.nudges if n.code == "M101"]
    assert m101[0].line == 2 and "write true or false" in m101[0].message
    assert "M106" in codes(res.nudges)  # the default stays
    assert "M106" not in codes(build("****A****\n", literal_asterisks=False).nudges)


def test_config_toml_turns_it_off_and_the_document_turns_it_back_on(tmp_path, capsys):
    doc = tmp_path / "d.bob.md"
    doc.write_text("****A****\n")
    assert cli.main(["config", "set", "literal_asterisks", "off"]) == 0
    capsys.readouterr()
    cli.main(["check", str(doc)])
    assert "M106" not in capsys.readouterr().err
    doc.write_text("---\nliteral_asterisks: true\n---\n****A****\n")
    cli.main(["check", str(doc)])
    assert "M106" in capsys.readouterr().err


def test_a_wrong_value_from_a_template_names_the_template(tmp_path):
    (tmp_path / "t.bob.md").write_text("---\nliteral_asterisks: talvez\n---\n****A****\n")
    res = build("---\ntemplate: ./t.bob.md\n---\n", base_dir=str(tmp_path))
    (m101,) = [n for n in res.nudges if n.code == "M101"]
    assert m101.message.startswith("template ./t.bob.md: literal_asterisks: 'talvez'") and m101.line is None
