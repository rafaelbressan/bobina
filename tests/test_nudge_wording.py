""":name: a nudge says what is wrong and what prints instead: never only the attribute as written ('valign=up')."""

import re
from pathlib import Path

from bobina.engine import build
from bobina.nudges import not_a_value

SRC = Path(__file__).resolve().parents[1] / "src" / "bobina"
BARE = re.compile(r'\.add\(\s*"([A-Z]\d{3})",\s*f"([a-z.-]+=\{[^}]+\})"\s*,', re.S)


def test_no_nudge_message_is_only_the_attribute_as_written():
    bare = [f"{f.name}: {m.group(1)} {m.group(2)}" for f in SRC.rglob("*.py") for m in BARE.finditer(f.read_text())]
    assert not bare, "use not_a_value(key, given, what prints instead):\n" + "\n".join(bare)


def test_not_a_value_reads_as_a_sentence():
    assert not_a_value("valign", "up", "the default") == "valign=up is not a value it takes: the default"


def test_a_wrong_value_says_what_prints_instead():
    res = build("| d | v |\n|---|--:|\n| a | 1 |\n| b | 2 |\n{chart=line y-labels=vertical}\n")
    (n,) = [n for n in res.nudges if n.code == "M101"]
    assert n.message == "y-labels=vertical is not a value it takes: turned along the axis, the default"
    assert n.suggestion == "rotated (the default) or horizontal"
