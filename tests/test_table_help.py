"""bobina help table: on one screen, in step with what the parser takes, the styles the layout draws, the columns a
font gives per line (measured by bobina check, L108) and the problem codes; and bobina help lists every topic."""

import json
import re

import pytest

from bobina import cli, parser, table_help
from bobina.cli import args
from bobina.engine import build
from bobina.layout import TABLE_STYLES
from bobina.nudges import CATALOG


def test_help_table_prints_on_an_80_column_terminal(capsys):
    assert cli.main(["help", "table"]) == cli.OK
    out = capsys.readouterr().out
    assert max(len(line) for line in out.splitlines()) <= 80
    out = " ".join(out.split())  # wrapped lines read as one
    for must in ("style=plain|receipt|lines|grid|header-invert|zebra", "width=", 'prefix="R$ "', "span=all",
                 "one empty cell for each column before it", "lowercase", "| | |", "docs/guides/tables.md"):  # fmt: skip
        assert must in out, must


def test_help_table_json_has_the_same_parts(capsys):
    assert cli.main(["help", "table", "--json"]) == cli.OK
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "bobina.help/1" and out["kind"] == "table"
    assert list(out["styles"]) == list(TABLE_STYLES)
    assert {c["font"] for c in out["columns_per_line"]} >= {"printer font", "Terminus 16px"}
    assert "M101" in out["problems"] and out["text"].startswith("bobina help table")


def test_the_styles_are_the_layouts():
    assert tuple(table_help.STYLES) == TABLE_STYLES


def test_the_names_are_the_parsers():
    assert {c[1:] for c in table_help.CELL_CLASSES} == parser.CELL_CLASSES
    assert {c[1:] for c in table_help.ROW_CLASSES} == parser.ROW_CLASSES
    assert {k.rstrip("=") for k in table_help.COLUMN} == set(parser.COLUMN_KEYS)


def test_every_code_is_in_the_catalog():
    assert set(table_help.PROBLEMS) <= set(CATALOG)


PAPER = {"58mm": "mtp-ii-58", "80mm": "epson-tm-t20iii"}


@pytest.mark.parametrize("font, n58, n80", table_help.COLUMNS_PER_LINE)
def test_the_columns_per_line_are_what_bobina_check_measures(font, n58, n80):
    for paper, n in (("58mm", n58), ("80mm", n80)):
        family, size = font.rsplit(" ", 1)
        attrs = "{.compact}" if font == "printer font" else f'{{font="{family}" size={size}}}'
        res = build(f"| A {{width=auto}} |\n|---|\n| x |\n{attrs}\n", profile_name=PAPER[paper])
        said = [n.message for n in res.notes if n.code == "L108"]
        assert said and re.search(rf"= \d+ of {n}\)", said[0]), (paper, said)


def test_the_example_is_clean():
    res = build(table_help.EXAMPLE)
    assert not [n.code for n in res.visible_nudges() if n.severity in ("warning", "error")]


def test_bobina_help_lists_every_topic(capsys):
    """The footer of bobina help, the help command's description and an unknown topic say the same list, made from
    TOPICS: a new topic cannot be left out of them."""
    cli.main(["help"])
    footer = capsys.readouterr().out.strip().splitlines()[-1]
    for t in ("format", "table", "data", "pay", "contact", "icons", "nudges", "aliases", "E302", "COMMAND"):
        assert f" {t}" in footer, t
    assert cli.main(["help", "tabel"]) == cli.USAGE
    err = capsys.readouterr().err
    assert "did you mean table?" in err and all(t in err for t in args.LISTED)
    assert all(t in args.COMMANDS["help"].description for t in args.LISTED)
