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


def no_font(monkeypatch, state="none", downloads=True):
    """scriptfonts as on a machine where non-Latin scripts are STATE (ready | download | none); never the network."""
    from bobina import scriptfonts

    monkeypatch.setattr(scriptfonts, "support", lambda t: "ready" if locales.parse(t).language in LATIN else state)
    monkeypatch.setattr(scriptfonts, "downloads_on", lambda: downloads)


LATIN = {"en", "pt", "fr", "de", "es"}


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


def test_only_the_documents_locale_settles_an_amount_that_reads_two_ways():
    doc = '{{ "1.890" | currency }}\n'
    res = build(doc, locale="pt-BR")  # the machine's locale was not chosen for this document: never a guess
    assert _text(res) == "1.890" and [n.code for n in res.nudges] == ["M202"]
    assert "R$ 1.890,00" in _text(build("---\nlocale: pt-BR\n---\n" + doc, locale="en-US"))
    for loc in ("pt-BR", None):
        res = build('```pay {scheme=pix to="a@b.c" amount=1.890}\n```\n', locale=loc)
        assert any(n.code == "Q111" and "1890 or 1.89" in n.message for n in res.nudges)
    res = build('---\nlocale: pt-BR\n---\n{{ "1.890" | paymoney("pix") }}\n')  # a payment, even then
    assert "M202" in [n.code for n in res.nudges]


def test_a_saved_or_inferred_locale_never_settles_it_on_the_command_line(fresh, capsys):
    for _ in range(2):  # the run that infers pt-BR, and the next one that reads it from config.toml
        assert "M202" in [c for c, *_ in _check(capsys, '{{ "1.890" | currency }}\n')]


def test_no_country_takes_the_system_locale_when_it_is_not_english(fresh, capsys, monkeypatch):
    monkeypatch.setenv("TZ", "Etc/UTC")
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")  # a container with LANG set and no zone
    assert _check(capsys) == [("M203", "locale pt-BR (from LANG=pt_BR.UTF-8; no country in the time zone Etc/UTC), "
                               "saved in config.toml", "change it: bobina config locale en-US")]  # fmt: skip
    assert config.load()["locale"] == "pt-BR" and _check(capsys) == []


def test_lc_all_then_lc_time_then_lang(fresh, monkeypatch):
    monkeypatch.setenv("TZ", "Etc/UTC")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LC_TIME", "de_DE.UTF-8")
    assert locales.Machine().peek().value == "de-DE"
    monkeypatch.setenv("LC_ALL", "C")  # LC_ALL wins, and C names no locale: English
    assert locales.Machine().peek().source == "default"


def test_no_country_is_english_said_once_and_not_saved(fresh, capsys, monkeypatch):
    monkeypatch.setenv("TZ", "Etc/UTC")
    monkeypatch.setenv("LANG", "en_GB.UTF-8")  # English: nothing to take from it
    notes = _check(capsys, LABEL + '{{ "1.890" | currency }}\n')
    assert ("M204", "no country in the time zone Etc/UTC, and LC_ALL, LC_TIME, LANG name no other language: dates, "
            "numbers and money in English (en)", "set yours: bobina config locale en-GB") in notes  # fmt: skip
    assert "M202" in [c for c, *_ in notes]  # English is a fallback: 1.890 is not read as 1.89
    assert "locale" not in config.load()
    assert _check(capsys) == []
    assert cli.main(["view", LABEL, "--no-color"]) == cli.OK
    out = capsys.readouterr().out
    assert "USE BY 11/9/26" in out and "R$24.90" in out  # English for all of it, never mixed


def test_no_time_zone_at_all(fresh, capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("TZ")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setattr(locales, "LOCALTIME", str(tmp_path / "none"))
    monkeypatch.setattr(locales, "TIMEZONE_FILE", str(tmp_path / "none"))
    assert [c for c, m, _ in _check(capsys) if "no time zone on this machine" in m] == ["M204"]


def test_a_script_bobina_cannot_draw_prints_english_words_with_the_countrys_formats(fresh, capsys, monkeypatch):
    no_font(monkeypatch, "none")
    monkeypatch.setenv("TZ", "Asia/Bangkok")
    codes = [c for c, *_ in _check(capsys)]
    assert codes == ["M203", "F306"] and config.load()["locale"] == "th-TH"  # the hook keeps what was inferred
    assert _check(capsys) == []  # said once
    assert locales.tag(locales.printable(locales.parse("th-TH"))) == "en-TH"
    assert cli.main(["view", '{{ today | date("short") }} {{ today | date("long") }}', "--no-color"]) == cli.OK
    assert "5/11/26" in capsys.readouterr().out  # Thai order (d/M/yy), English words
    res = build("---\nlocale: th\n---\n{{ today | date('medium') }}\n")  # a document's: said on each check
    assert "5 Nov 2026" in _text(res) and [n.code for n in res.nudges] == ["F306"]


@pytest.mark.parametrize(
    "state,downloads,prints,hint",
    [
        ("ready", True, "th-TH", None),  # a font here: the language itself
        ("ready", False, "th-TH", None),
        ("download", True, "th-TH", None),  # fetched on first use, with the fonts code's own notice (F304)
        ("download", False, "en-TH", "bobina fonts get th (or font_downloads = true in config.toml)"),
        ("none", True, "en-TH", "choose another locale: bobina config locale TAG"),
    ],
)
def test_the_printed_form_follows_the_fonts_bobina_has(monkeypatch, state, downloads, prints, hint):
    no_font(monkeypatch, state, downloads)
    loc = locales.parse("th-TH")
    assert locales.tag(locales.printable(loc)) == prints
    res = build("---\nlocale: th-TH\n---\n{{ today | date('medium') }}\n")
    notes = [n for n in res.nudges if n.code == "F306"]
    assert [hint in n.suggestion for n in notes] == ([True] if hint else [])


def test_the_saved_locale_stays_the_persons_when_it_falls_back(fresh, capsys, monkeypatch):
    no_font(monkeypatch, "download", downloads=False)
    monkeypatch.setenv("TZ", "Asia/Bangkok")
    notes = _check(capsys)
    assert [c for c, *_ in notes] == ["M203", "F306"] and "bobina fonts get th" in notes[1][2]
    assert config.load()["locale"] == "th-TH"  # only the printed form is en-TH
    no_font(monkeypatch, "ready")  # after bobina fonts get th
    assert cli.main(["view", '{{ today | date("long") }}', "--no-color"]) == cli.OK
    assert "พฤศจิกายน" in capsys.readouterr().out  # Thai, now that the font is here


def test_right_to_left_scripts_print_in_their_language_now():
    assert locales.printable(locales.parse("he-IL")) == locales.parse("he-IL")  # Hebrew: a bundled font


def test_font_downloads_in_config_is_kept(isolated, capsys):
    p = isolated / "config" / "config.toml"
    p.write_text("font_downloads = false\n")
    assert cli.main(["printer", "add", "t", "--path", "o.bin"]) == cli.OK
    assert cli.main(["config", "locale", "fr-CA"]) == cli.OK
    cfg = config.load()
    assert cfg["font_downloads"] is False and cfg["locale"] == "fr-CA" and "t" in cfg["printers"]


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


def test_config_locale_of_a_script_not_drawable_says_what_prints(capsys, monkeypatch):
    no_font(monkeypatch, "none")
    assert cli.main(["config", "locale", "ja-JP"]) == cli.OK
    io = capsys.readouterr()
    assert "locale ja-JP saved" in io.out and "F306" in io.err and "en-JP" in io.err


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


# ---------------------------------------------------------------- review fixes


def test_config_locale_names_where_an_undrawable_locale_comes_from(fresh, capsys, monkeypatch):
    no_font(monkeypatch, "none")
    monkeypatch.setenv("TZ", "Asia/Bangkok")
    assert cli.main(["config", "locale"]) == cli.OK
    err = capsys.readouterr().err
    assert "F306" in err and "from the time zone Asia/Bangkok" in err and "config.toml" not in err
    assert cli.main(["config", "locale", "th-TH"]) == cli.OK
    assert "(th-TH, config.toml)" in capsys.readouterr().err


def test_a_new_key_never_goes_between_a_tables_comment_and_its_header(fresh):
    p = fresh / "config" / "config.toml"
    p.write_text('# bobina\n\n# the shop printer\n[printers.x]\npath = "o.bin"\n')
    config.set_value("locale", "pt-BR")
    assert p.read_text() == '# bobina\nlocale = "pt-BR"\n\n# the shop printer\n[printers.x]\npath = "o.bin"\n'
    p.write_text('editor = "nano"\n# about the printer\n\n[printers.x]\npath = "o.bin"\n')
    config.set_value("locale", "fr-CA")
    assert p.read_text().startswith('editor = "nano"\nlocale = "fr-CA"\n# about the printer\n')
    p.write_text('a = [\n  1,\n]\n[printers.x]\npath = "o.bin"\n')  # after a value written over several lines
    config.set_value("locale", "en-US")
    assert config.load()["a"] == [1] and config.load()["locale"] == "en-US"


def test_printer_add_keeps_a_locale_saved_while_it_waited(fresh):
    import threading

    from bobina import fileio

    done = []
    with fileio.locked(config.path()):  # another bobina holds config.toml …
        t = threading.Thread(target=lambda: done.append(cli.main(["printer", "add", "t", "--path", "o.bin"])))
        t.start()
        t.join(0.3)
        assert t.is_alive()  # … printer add waits for it
        (fresh / "config" / "config.toml").write_text('locale = "fr-CA"\n')  # what the other one saved
    t.join(10)
    cfg = config.load()
    assert done == [cli.OK] and cfg["locale"] == "fr-CA" and "t" in cfg["printers"]


def test_save_and_update_take_the_lock(fresh, monkeypatch):
    from bobina import fileio

    held = []
    real = fileio.locked
    monkeypatch.setattr(fileio, "locked", lambda p, **k: held.append(p) or real(p, **k))
    config.save({"editor": "nano"})
    config.update(lambda cfg: cfg.__setitem__("locale", "pt-BR"))
    assert held == [config.path(), config.path()] and config.load() == {"editor": "nano", "locale": "pt-BR"}


def test_an_unknown_document_locale_is_said_with_the_closest_tag(capsys):
    res = build("---\nlocale: pt-BT\n---\n{{ today | date('short') }}\n", locale="pt-BR")
    (n,) = [n for n in res.nudges if n.code == "M205"]
    assert n.message == "locale: 'pt-BT' is not a locale bobina knows: printed in pt-BR, this machine's"
    assert n.suggestion.startswith("did you mean locale: pt-BR?") and n.severity == "warning"
    res = build("---\nlang: portugues\n---\nx\n")
    assert [n.suggestion for n in res.nudges if n.code == "M205"][0].startswith("did you mean lang: pt?")
    assert not [n for n in build("---\nlocale: pt-BR\n---\nx\n").nudges if n.code == "M205"]


def test_first_time_writes_said_json_only_for_a_new_key(monkeypatch):
    from bobina import fileio

    assert locales.first_time("M204") is True
    monkeypatch.setattr(fileio, "locked_update", lambda *a, **k: pytest.fail("written again"))
    assert locales.first_time("M204") is False


def test_the_time_zone_stops_at_tz_and_is_read_once(monkeypatch):
    import os

    calls = []
    monkeypatch.setattr(os.path, "realpath", lambda p: calls.append(p) or p)
    locales._zone.cache_clear()
    monkeypatch.setenv("TZ", "America/Recife")
    assert locales.system_zone() == "America/Recife" and calls == []  # TZ is enough: /etc/localtime not read
    monkeypatch.setenv("TZ", "not/a/zone")
    locales.system_zone()
    locales.system_zone()
    assert len(calls) == 1  # read once for that TZ value


def test_config_locale_shows_what_a_print_would_do(fresh, capsys, monkeypatch):
    monkeypatch.setenv("TZ", "Etc/UTC")
    monkeypatch.setenv("LANG", "es_MX.UTF-8")
    found = locales.Machine().peek()
    assert (found.value, found.source) == ("es-MX", "environment")
    assert cli.main(["config", "locale", "--json"]) == cli.OK
    doc = json.loads(capsys.readouterr().out)
    assert (doc["value"], doc["source"]) == ("es-MX", "environment")
    assert not (fresh / "config" / "config.toml").exists()  # peek writes nothing


def test_each_rebuild_reads_the_locale_again(capsys):
    from bobina.cli import args as A
    from bobina.cli import common

    args = A.parse_args(A.make_parser(), ["check", "x"])
    doc = "{{ today | date('long') }}\n"
    first = common.build(args, doc, ".")
    assert "November 5, 2026" in _text(first.first)
    config.set_value("locale", "pt-BR")  # changed while bobina edit waits in the editor
    assert "5 de novembro de 2026" in _text(common.build(args, doc, ".").first)
