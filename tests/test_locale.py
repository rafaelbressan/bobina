"""One locale per job: the document's locale:, else the machine's (config.toml; inferred from the time zone on the
first run and saved, said once), else English. Never the user's real config: conftest points it at tmp_path."""

import json

import pytest

from bobina import cli, config, locales
from bobina.engine import build

LABEL = 'USE BY {{ today | add(days=4) | date("short") }}\n\n2 x 12.45 = {{ 24.9 | currency("BRL") }}\n'


def _text(res) -> str:
    return "".join(c.ch for r in res.rows for c in getattr(r, "cells", [])).replace("\xa0", " ")


@pytest.fixture
def fresh(isolated):
    """A machine where bobina never chose a locale (conftest seeds en-US for the other tests)."""
    (isolated / "config" / "config.toml").unlink()
    return isolated


def _check(capsys, doc=LABEL) -> list:
    assert cli.main(["check", doc, "--json"]) == cli.OK
    return [(p["code"], p["message"], p["suggestion"]) for p in json.loads(capsys.readouterr().out)["problems"]]


@pytest.mark.parametrize(
    "zone,lang,want",
    [
        ("America/Sao_Paulo", "en", "pt-BR"),
        ("America/Belem", "en", "pt-BR"),
        ("America/Toronto", "fr", "fr-CA"),
        ("America/Toronto", "en", "en-CA"),
        ("Asia/Kolkata", "en", "en-IN"),
        ("Asia/Calcutta", "en", "en-IN"),  # an old name of the same zone
        ("Asia/Bangkok", "en", "th-TH"),  # the language of the zone's country when LANG's is not official there
        ("Etc/UTC", "en", None),
        ("UTC", "pt", None),
        (None, "en", None),
    ],
)
def test_the_locale_a_time_zone_gives(zone, lang, want):
    assert locales.infer(zone, lang) == want


def test_the_first_run_saves_the_zones_locale_and_says_so_once(fresh, capsys):
    notes = _check(capsys)
    assert notes == [("M203", "locale pt-BR (from the time zone America/Sao_Paulo), saved in config.toml",
                      "change it: bobina config locale en-US")]  # fmt: skip
    assert config.load()["locale"] == "pt-BR"
    assert _check(capsys) == []  # said once
    assert cli.main(["view", LABEL, "--no-color"]) == cli.OK
    out = capsys.readouterr().out
    assert "USE BY 09/11/2026" in out and "R$ 24,90" in out  # not 11/9/26 next to R$ 24,90


def test_it_stays_when_the_machine_travels(fresh, capsys, monkeypatch):
    _check(capsys)
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    assert _check(capsys) == [] and config.load()["locale"] == "pt-BR"


def test_one_locale_for_dates_numbers_and_money():
    res = build("{{ 24.9 | currency('USD') }} · {{ today | date('short') }} · {{ 1234.5 | number }}\n", locale="pt-BR")
    assert "US$ 24,90 · 05/11/2026 · 1.234,5" in _text(res)
    res = build("---\nlocale: en-US\n---\n{{ 24.9 | currency('BRL') }} · {{ today | date('short') }}\n", locale="pt-BR")
    assert "R$24.90 · 11/5/26" in _text(res)  # the document's locale wins, for the money too


def test_a_set_locale_reads_typed_prices_in_it_and_payments_still_refuse_guesses():
    assert "R$ 1.890,00" in _text(build('{{ "1.890" | currency }}\n', locale="pt-BR"))
    res = build('```pay {scheme=pix to="a@b.c" amount=1.890}\n```\n', locale="pt-BR")
    assert any(n.code == "Q111" and "1890 or 1.89" in n.message for n in res.nudges)


def test_no_country_is_english_said_once_and_not_saved(fresh, capsys, monkeypatch):
    monkeypatch.setenv("TZ", "Etc/UTC")
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    notes = _check(capsys, LABEL + '{{ "1.890" | currency }}\n')
    assert ("M204", "no country in the time zone Etc/UTC: dates, numbers and money in English (en)",
            "set yours: bobina config locale pt-BR") in notes  # fmt: skip
    assert "M202" in [c for c, *_ in notes]  # English is a fallback: 1.890 is not read as 1.89
    assert "locale" not in config.load()
    assert _check(capsys) == []
    assert cli.main(["view", LABEL, "--no-color"]) == cli.OK
    out = capsys.readouterr().out
    assert "USE BY 11/9/26" in out and "R$24.90" in out  # English for all of it, never mixed


def test_no_time_zone_at_all(fresh, capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("TZ")
    monkeypatch.setattr(locales, "LOCALTIME", str(tmp_path / "none"))
    monkeypatch.setattr(locales, "TIMEZONE_FILE", str(tmp_path / "none"))
    assert [c for c, m, _ in _check(capsys) if "no time zone on this machine" in m] == ["M204"]


def test_a_script_bobina_cannot_draw_prints_english_words_with_the_countrys_formats(fresh, capsys, monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Bangkok")
    codes = [c for c, *_ in _check(capsys)]
    assert codes == ["M203", "F304"] and config.load()["locale"] == "th-TH"  # the hook keeps what was inferred
    assert _check(capsys) == []  # said once
    assert locales.tag(locales.printable(locales.parse("th-TH"))) == "en-TH"
    assert cli.main(["view", '{{ today | date("short") }} {{ today | date("long") }}', "--no-color"]) == cli.OK
    assert "5/11/26" in capsys.readouterr().out  # Thai order (d/M/yy), English words
    res = build("---\nlocale: th\n---\n{{ today | date('medium') }}\n")  # a document's: said on each check
    assert "5 Nov 2026" in _text(res) and [n.code for n in res.nudges] == ["F304"]
    assert locales.printable(locales.parse("he-IL")) == locales.parse("en-IL")  # right to left: not yet either


def test_a_language_with_another_country():
    loc = locales.parse("en-BR")  # no such CLDR locale: English words, Brazilian formats
    assert locales.tag(loc) == "en-BR"
    assert "Thursday, November 5" not in _text(build("{{ today | date('short') }} {{ 1234.5 | number }}\n", locale=loc))
    assert "05/11/2026 1.234,5" in _text(build("{{ today | date('short') }} {{ 1234.5 | number }}\n", locale="en-BR"))
    assert locales.parse("klingon") is None and locales.parse("C.UTF-8") is None
    assert "11/5/26" in _text(build("---\nlocale: [pt]\n---\n{{ today | date('short') }}\n"))  # not a tag: English


def test_config_locale_shows_saves_and_answers_json(fresh, capsys):
    (fresh / "config" / "config.toml").write_text('# mine\ndefault_printer = "x"\n\n[printers.x]\npath = "o.bin"\n')
    assert cli.main(["config", "locale"]) == cli.OK
    assert "the first print, check or preview saves pt-BR" in capsys.readouterr().out
    assert "locale" not in config.load()  # showing writes nothing
    assert cli.main(["config", "locale", "fr_ca"]) == cli.OK
    assert "locale fr-CA saved" in capsys.readouterr().out
    text = (fresh / "config" / "config.toml").read_text()
    assert text.startswith('# mine\ndefault_printer = "x"\nlocale = "fr-CA"\n') and "[printers.x]" in text
    assert cli.main(["config", "locale", "--json"]) == cli.OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "bobina.config/1" and doc["value"] == "fr-CA" and doc["source"] == "config"
    assert {k: v.replace("\xa0", " ") for k, v in doc["example"].items()} == {
        "date": "2026-11-05", "number": "1 234,5", "money": "1 234,50 $"}  # fmt: skip
    assert _check(capsys) == []  # set by hand: nothing to say


def test_config_locale_refuses_an_unknown_tag(capsys):
    assert cli.main(["config", "locale", "xx-YY-zz"]) == cli.USAGE
    assert "E304" in capsys.readouterr().err
    assert config.load()["locale"] == "en-US"


def test_config_locale_of_a_script_not_drawable_says_what_prints(capsys):
    assert cli.main(["config", "locale", "ja-JP"]) == cli.OK
    io = capsys.readouterr()
    assert "locale ja-JP saved" in io.out and "F304" in io.err and "en-JP" in io.err


def test_an_unknown_locale_in_config_is_english_and_said(isolated, capsys):
    (isolated / "config" / "config.toml").write_text('locale = "elvish"\n')
    assert [c for c, *_ in _check(capsys)] == ["M204"]
    assert config.load()["locale"] == "elvish"  # never overwritten


def test_printer_add_chooses_the_locale_too(fresh, capsys):
    assert cli.main(["printer", "add", "test", "--path", str(fresh / "o.bin")]) == cli.OK
    assert "M203" in capsys.readouterr().err
    cfg = config.load()
    assert cfg["locale"] == "pt-BR" and cfg["printers"]["test"]["transport"] == "file"
    assert cli.main(["printer", "use", "test"]) == cli.OK and config.load()["locale"] == "pt-BR"  # kept by save()


def test_not_saved_still_prints_in_it_and_says_why(fresh, capsys, monkeypatch):
    def fail(*a):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(config, "set_value", fail)
    ((code, msg, hint),) = _check(capsys)
    assert code == "M203" and "not saved: Permission denied" in msg and hint == "set it: bobina config locale pt-BR"


def test_plain_text_and_the_engine_alone_never_infer(fresh):
    build("# {{ today | date('long') }}\n")  # no Machine: English, nothing written
    assert not (fresh / "config" / "config.toml").exists()
    assert cli.main(["check", "--plain", "hello"]) == cli.OK
    assert not (fresh / "config" / "config.toml").exists()


def test_lc_all_wins_over_lang(monkeypatch):
    monkeypatch.setenv("LC_ALL", "fr_CA.UTF-8")
    assert locales.system_language() == ("fr", "fr-CA")
    monkeypatch.setenv("LC_ALL", "C")
    assert locales.system_language() == (None, None)
