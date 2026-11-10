"""bobina history: every print job recorded (privately) and shown like git log."""

import json

from bobina import cli, history


def jobs():
    return history.load()


def test_outcomes_are_recorded_with_details(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.bob.md").write_text("A {{ seq.t }}\n")
    (tmp_path / "f.bob.md").write_text("F\n\n![](missing.png)\n")
    assert cli.main(["print", "a.bob.md", "--then", "a.bob.md", "--compact-all", "-o", "x.bin"]) == cli.OK
    assert cli.main(["print", "a.bob.md", "--then", "nope.bob.md", "-o", "y.bin"]) == cli.USAGE
    assert cli.main(["print", "f.bob.md", "--strict", "-o", "z.bin"]) == cli.STRICT
    assert cli.main(["print", "a.bob.md", "--dry-run"]) == cli.OK
    saved, failed, strict, dry = jobs()
    assert saved["outcome"] == "saved" and saved["labels"] == 2 and saved["cuts"] == 1 and saved["saved_to"] == "x.bin"
    assert [p["file"] for p in saved["parts"]] == ["a", "a"] and saved["schema"] == "bobina.history/1"
    assert failed["outcome"] == "failed" and failed["problems"][0]["code"] == "E201"
    assert strict["outcome"] == "nothing printed (--strict)" and strict["problems"][0]["code"] == "I101"
    assert dry["outcome"] == "dry run"
    capsys.readouterr()
    assert cli.main(["history"]) == cli.OK
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 4 and lines[0].startswith(dry["id"])  # newest first
    assert cli.main(["history", "show", "last"]) == cli.OK
    assert "dry run" in capsys.readouterr().out
    assert cli.main(["history", "stats", "--json"]) == cli.OK
    st = json.loads(capsys.readouterr().out)
    assert st["jobs"] == 4 and dict(st["top_problems"]) == {"E201": 1, "I101": 1}
    assert cli.main(["history", "--outcome", "failed", "--json"]) == cli.OK
    assert [r["id"] for r in json.loads(capsys.readouterr().out)] == [failed["id"]]


def test_private_values_are_not_kept(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "p.bob.md").write_text("{{ chave }}\n")
    cli.main(["print", "p.bob.md", "--set", "chave=11999990000", "--set-all=lote=SEGREDO", "-o", "x.bin"])
    cli.main(["print", "meu telefone 11999990000", "--dry-run"])
    raw = history.path().read_text()
    assert "11999990000" not in raw and "SEGREDO" not in raw
    first, second = jobs()
    assert first["argv"][first["argv"].index("--set") + 1] == "chave=***" and "text" in second["argv"]


def test_history_can_be_turned_off_and_is_bounded(tmp_path, monkeypatch):
    from bobina import config

    monkeypatch.chdir(tmp_path)
    cfg = config.load()
    cfg["history_max"] = 3
    config.save(cfg)
    for _ in range(15):  # trimmed back to 3 when more than 10 over (no rewrite on every print)
        cli.main(["print", "x", "--dry-run"])
    assert 3 <= len(jobs()) <= 13
    cfg["history"] = False
    config.save(cfg)
    before = len(jobs())
    cli.main(["print", "x", "--dry-run"])
    assert len(jobs()) == before


def test_clear_needs_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.common, "open_tty", lambda: None)
    cli.main(["print", "x", "--dry-run"])
    assert cli.main(["history", "clear"]) == cli.USAGE and jobs()
    assert cli.main(["history", "clear", "--yes"]) == cli.OK and not jobs()


def test_a_broken_history_never_breaks_a_print(tmp_path, monkeypatch, capsys):
    from bobina import config

    monkeypatch.chdir(tmp_path)
    history.path().parent.mkdir(parents=True, exist_ok=True)
    history.path().write_bytes(b'{"id": "x", "time": "2026"}\n\xff\xfe not json\n')
    cfg = config.load()
    cfg["history_max"] = "lots"
    config.save(cfg)
    assert cli.main(["print", "x", "-o", "a.bin"]) == cli.OK
    assert (tmp_path / "a.bin").exists()
    assert cli.main(["history"]) == cli.OK  # damaged lines are skipped, not a crash
    monkeypatch.setattr(history, "path", lambda: tmp_path)  # a directory: appending fails
    assert cli.main(["print", "y", "-o", "b.bin"]) == cli.OK
    assert "not recorded in the history" in capsys.readouterr().err


def test_redaction_by_position_not_by_shape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.bob.md").write_text("A\n")
    argv = history.redact(
        ["print", "11999990000", "--then", "PIX:chave-aleatoria-7f3a", "--then", "a.bob.md", "--set", "k=v1",
         "--set-all=lote=SEGREDO", "--where", "nome=Fulano", "--data", "d.csv", "-o", "x.bin"]
    )  # fmt: skip
    joined = " ".join(argv)
    for secret in ("11999990000", "chave-aleatoria-7f3a", "v1", "SEGREDO", "Fulano"):
        assert secret not in joined
    assert "a.bob.md" in argv and "d.csv" in argv and "x.bin" in argv and "nome=***" in argv


def test_problem_messages_are_stored_with_data_masked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "q.bob.md").write_text("```barcode {type=ean13}\n{{ codigo }}\n```\n")
    cli.main(["print", "q.bob.md", "--set", "codigo=SEGREDO123", "-o", "x.bin"])
    raw = history.path().read_text()
    assert "SEGREDO123" not in raw
    p = jobs()[-1]["problems"][0]
    assert p["code"].startswith("Q") and "***" in p["message"]


def test_mask():
    assert history.mask("key 11 99999-0000 and fulano at x", {"fulano"}) == "key *** and *** at x"


def test_filters_are_validated(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cli.main(["print", "x", "--dry-run"])
    capsys.readouterr()
    assert cli.main(["history", "--outcome", "dry-run"]) == cli.OK and "dry run" in capsys.readouterr().out
    assert cli.main(["history", "--outcome", "printd"]) == cli.USAGE
    assert cli.main(["history", "--since", "yesterday"]) == cli.OK
    assert cli.main(["history", "--since", "ontem demais"]) == cli.USAGE
    capsys.readouterr()
    assert cli.main(["history", "--outcome", "failed"]) == cli.OK
    assert "no job matches (the history has 1)" in capsys.readouterr().out
