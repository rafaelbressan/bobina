"""The strip rules, stressed with concrete jobs (spreadsheets, counters, several files per part).

Rules: a part is everything between two --then (one or more files + their options). Inside a part its
--compact/--no-compact decides; --compact-all is the default for every part; the specific wins. Between two
parts there is a ✂ cut line only if both are compact, otherwise the feed to the tear bar."""

import openpyxl
import pytest

from bobina.cli import args as cargs
from bobina.cli import common


@pytest.fixture
def kit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in "abcd":
        (tmp_path / f"{name}.bob.md").write_text(name.upper() + "\n")
    (tmp_path / "pote.bob.md").write_text("Pote {{ seq.pote }} {{ item }}\n")
    (tmp_path / "tampa.bob.md").write_text("Tampa {{ seq.pote }} {{ item }}\n")
    (tmp_path / "cozinha.csv").write_text("item,n\narroz,2\nfeijao,1\ncafe,0\n")
    wb = openpyxl.Workbook()
    wb.active.title = "Outra"
    ws = wb.create_sheet("Lav")
    ws.append(["item"])
    ws.append(["sabao"])
    ws.append(["esponja"])
    wb.save(tmp_path / "lavanderia.xlsx")
    return tmp_path


def job(*argv):
    a = cargs.parse_args(cargs.make_parser(), ["print", *argv])
    res, *_ = common.load_job(a)
    from bobina.rows import TextRow

    words = [  # the text of each label, from its print rows
        " ".join("".join(c.ch for c in row.cells).strip() for row in r.rows if isinstance(row, TextRow))
        for r in res.labels
    ]
    joins = res.joins if hasattr(res, "joins") else []
    return words, joins


def test_a_part_with_two_files_shares_its_compact(kit):
    words, joins = job("a.bob.md", "b.bob.md", "--then", "c.bob.md", "d.bob.md", "--compact")
    assert [w.split()[0] for w in words] == ["A", "B", "C", "D"]
    assert joins == ["tear", "tear", "cut"]


def test_only_d_compact_needs_its_own_part(kit):
    _, joins = job("a.bob.md", "b.bob.md", "--then", "c.bob.md", "--then", "d.bob.md", "--compact")
    assert joins == ["tear", "tear", "tear"]  # D's neighbour C is not compact


def test_compact_all_with_one_part_opting_out(kit):
    _, joins = job("a.bob.md", "b.bob.md", "--then", "c.bob.md", "--no-compact", "--then", "d.bob.md", "--compact-all")
    assert joins == ["cut", "tear", "tear"]


def test_redundant_compacts_and_compact_all(kit):
    _, joins = job("A", "--compact", "--then", "B", "--compact", "--compact-all")
    assert joins == ["cut"]


def test_both_flags_in_one_part_is_an_error(kit):
    with pytest.raises(SystemExit):
        job("A", "--compact", "--no-compact")


def test_compact_all_overridden_everywhere_notes_it(kit, capsys):
    _, joins = job("A", "--no-compact", "--then", "B", "--no-compact", "--compact-all")
    assert joins == ["tear"] and "--compact-all has no effect" in capsys.readouterr().err


def test_spreadsheet_parts_and_a_counter_across_them(kit):
    words, joins = job(
        "pote.bob.md", "--data", "cozinha.csv", "--compact",
        "--then", "pote.bob.md", "--data", "lavanderia.xlsx", "--sheet", "Lav",
    )  # fmt: skip
    assert words == ["Pote 1 arroz", "Pote 2 feijao", "Pote 3 cafe", "Pote 4 sabao", "Pote 5 esponja"]
    assert joins == ["cut", "cut", "tear", "tear"]


def test_copies_keep_their_number_and_filters_stay_in_their_part(kit):
    words, joins = job(
        "pote.bob.md", "--data", "cozinha.csv", "--copies-from", "n",
        "--then", "pote.bob.md", "--data", "lavanderia.xlsx", "--sheet", "Lav", "--where", "item=sabao",
        "--then", "fim", "--no-compact", "--compact-all",
    )  # fmt: skip
    assert words == ["Pote 1 arroz", "Pote 1 arroz", "Pote 2 feijao", "Pote 3 sabao", "fim"]  # cafe: 0 copies
    assert joins == ["cut", "cut", "cut", "tear"]


def test_two_files_with_one_data_set(kit):
    words, joins = job("pote.bob.md", "tampa.bob.md", "--data", "cozinha.csv", "--where", "n!=0", "--compact")
    assert words == ["Pote 1 arroz", "Pote 2 feijao", "Tampa 3 arroz", "Tampa 4 feijao"]
    assert joins == ["cut", "cut", "cut"]


def test_unquoted_words_are_refused_with_the_quoted_form(kit):
    a = cargs.parse_args(cargs.make_parser(), ["print", "oi", "mundo"])
    with pytest.raises(common.Fail, match='bobina print "oi mundo"'):
        common.load_job(a)


# --- which options belong to a part and which to the whole job (docs/CLI.md "One strip") -------------------


def nudges(*argv):
    a = cargs.parse_args(cargs.make_parser(), ["print", *argv])
    res, *_ = common.load_job(a)
    return [(n.code, n.source) for n in res.visible_nudges()], res


def test_part_options_stay_in_their_part(kit):
    (kit / "oi.bob.md").write_text("Oi {{ nome }}\n")
    (kit / "foto.bob.md").write_text("Foto\n\n![](falta.png)\n")
    found, _ = nudges("oi.bob.md", "--set", "nome=Ana", "--then", "oi.bob.md")
    assert found == [("M130", "part 2 (oi.bob.md)")]  # --set did not leak into part 2
    found, _ = nudges("foto.bob.md", "--then", "foto.bob.md", "--allow", "I101")
    assert found == [("I101", "part 1 (foto.bob.md)")]  # --allow silenced only its own part
    words, joins = job(
        "a.bob.md", "--then", "b.bob.md", "--repeat", "2", "--then", "c.bob.md", "--copies", "2", "--compact"
    )
    assert [w for w in words] == ["A", "B", "B", "C", "C"] and joins == ["tear", "tear", "tear", "cut"]


def test_job_flags_work_from_any_part(kit):
    a = cargs.parse_args(
        cargs.make_parser(), ["print", "a.bob.md", "--then", "b.bob.md", "--dry-run", "--strict", "-q"]
    )
    common.load_job(a)
    assert a.dry_run and a.strict and a.quiet


@pytest.mark.parametrize(
    "argv, message",
    [
        (["a.bob.md", "--printer", "office", "--then", "b.bob.md", "--printer", "kitchen"],
         "--printer applies to the whole job"),
        (["a.bob.md", "-o", "x.bin", "--then", "b.bob.md", "-o", "y.bin"], "-o applies to the whole job"),
        (["a.bob.md", "--then", "b.bob.md", "--profile", "nope"], "unknown profile 'nope'"),
        (["-", "--then", "-"], "only one part can read stdin"),
    ],
)  # fmt: skip
def test_job_option_conflicts_are_errors(kit, argv, message):
    a = cargs.parse_args(cargs.make_parser(), ["print", *argv])
    with pytest.raises(common.Fail, match=message):
        common.load_job(a)


def test_reprint_flags_do_not_mix_with_documents(kit):
    from bobina import cli

    assert cli.main(["print", "--last", "--then", "a.bob.md"]) == cli.USAGE
    assert cli.main(["print", "--again", "a.bob.md"]) == cli.USAGE


def test_usage_errors_exit_with_the_usage_code(kit):
    from bobina import cli

    for argv in (["print", "a.bob.md", "--compact", "--no-compact"], ["print", "a.bob.md", "--then"]):
        with pytest.raises(SystemExit) as e:
            cli.main(argv)
        assert e.value.code == cli.USAGE


def test_every_part_is_checked_and_all_problems_are_reported_together(kit, capsys):
    from bobina import cli

    (kit / "foto.bob.md").write_text("Foto\n\n![](falta.png)\n")
    (kit / "mau.bob.md").write_text("{% include 'x' %}\n")
    code = cli.main(
        ["print", "a.bob.md", "--then", "nope.bob.md", "--then", "foto.bob.md",
         "--then", "pote.bob.md", "--data", "cozinha.csv", "--where", "cor=azul", "--then", "mau.bob.md",
         "-o", str(kit / "o.bin")]
    )  # fmt: skip
    e = capsys.readouterr().err
    assert code == cli.SECURITY  # the most serious problem decides the exit code
    assert not (kit / "o.bin").exists()  # nothing is produced when any part fails
    assert e.splitlines()[0] == "3 errors, 1 warning — nothing printed"
    for expected in ("part 2 (nope.bob.md): file not found", "part 4 (pote.bob.md): --where: no column 'cor'",
                     "[M310] part 5 (mau.bob.md)", "[I101] part 3 (foto.bob.md), line 3"):  # fmt: skip
        assert expected in e


def test_set_all_and_allow_all_reach_every_part_and_the_part_wins(kit):
    (kit / "lote.bob.md").write_text("{{ item }} lote {{ lote }}\n")
    (kit / "foto.bob.md").write_text("Foto\n\n![](falta.png)\n")
    words, _ = job(
        "lote.bob.md", "--set", "item=arroz",
        "--then", "lote.bob.md", "--set", "item=sal", "--set", "lote=B7",
        "--set-all", "lote=2026-11",
    )  # fmt: skip
    assert words == ["arroz lote 2026-11", "sal lote B7"]
    found, _ = nudges("foto.bob.md", "--then", "foto.bob.md", "--allow-all", "I101")
    assert found == []


def test_preview_formats(kit, capsys):
    from bobina import cli

    for ext in ("png", "jpg", "pdf", "webp"):
        assert cli.main(["preview", "a.bob.md", "-o", str(kit / f"p.{ext}")]) == cli.OK
    assert cli.main(["preview", "a.bob.md", "-o", str(kit / "p.svg")]) == cli.USAGE
    assert "cannot save a preview as '.svg'" in capsys.readouterr().err


def test_then_equals_and_no_abbreviations(kit):
    from bobina import cli

    words, _ = job("a.bob.md", "--then=b.bob.md")
    assert [w for w in words] == ["A", "B"]
    for argv in (["print", "a.bob.md", "--the", "b.bob.md"], ["print", "a.bob.md", "--dat", "x.csv"],
                 ["print", "a.bob.md", "--set-a=k=v"]):  # fmt: skip
        with pytest.raises(SystemExit) as e:
            cli.main(argv)
        assert e.value.code == cli.USAGE


def test_a_later_part_brings_its_own_counter_settings(kit):
    (kit / "cnt.bob.md").write_text("---\ncounters:\n  jar: {start: 100, format: 'J-{:03}'}\n---\n{{ seq.jar }}\n")
    words, _ = job("a.bob.md", "--then", "cnt.bob.md", "--repeat", "2")
    assert words == ["A", "J-100", "J-101"]
    (kit / "cnt2.bob.md").write_text("---\ncounters:\n  jar: {start: 5}\n---\n{{ seq.jar }}\n")
    a = cargs.parse_args(cargs.make_parser(), ["print", "cnt.bob.md", "--then", "cnt2.bob.md"])
    with pytest.raises(common.Fail) as e:
        common.load_job(a)
    assert "declared differently" in str(e.value) and e.value.problems()[0].source == "part 2 (cnt2.bob.md)"
