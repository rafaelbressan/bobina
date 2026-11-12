"""config.toml rewrites (printer add, calibrate…): every value and table read back the same, or no rewrite."""

import datetime as dt
import tomllib

import pytest

from bobina import config, fileio

TEXT = """locale = "pt-BR"
note = "two\\nlines, a \\"quote\\", a tab\\t and a bell \\u0007"
when = 2026-11-11T20:30:00-03:00
day = 2026-11-11
at = 07:30:00
sizes = [1, 2.5, "x"]
nan_free = inf

[printers.mtp]
transport = "bluetooth"
address = "AA:BB:CC:DD:EE:FF"

[printers."odd name"]
transport = "file"
path = "out.bin"

[chat.colors]
you = "#ff8700"

[[jobs]]
name = "first"
tags = ["a", "b"]

[jobs.extra]
deep = true

[[jobs]]
name = "second"
inline = [{x = 1}, {x = 2}]
"""


def test_a_rewrite_reads_back_the_same():
    cfg = tomllib.loads(TEXT)
    assert isinstance(cfg["when"], dt.datetime) and cfg["note"].count("\n") == 1
    text = config.dumps(cfg)
    assert tomllib.loads(text) == cfg
    config.path().write_text(TEXT)
    config.update(lambda c: c["printers"].update(new={"transport": "file", "path": "n.bin"}))
    again = config.load()
    assert again["note"] == cfg["note"] and again["jobs"] == cfg["jobs"] and again["when"] == cfg["when"]
    assert again["printers"]["new"] == {"transport": "file", "path": "n.bin"}


def test_a_value_toml_cannot_hold_refuses_the_rewrite():
    config.path().write_text('locale = "en-US"\n')
    before = config.path().read_text()
    with pytest.raises(fileio.StateError, match="was not rewritten"):
        config.update(lambda c: c.update(odd={1, 2}))
    assert config.path().read_text() == before  # untouched
