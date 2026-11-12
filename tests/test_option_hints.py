"""What people actually type for an option: typos, synonyms, Portuguese, the option of another
command, flags that do not apply. The hint must name the intended option (or the command that has it)."""

import re

import pytest

from bobina.cli import args as A

A.make_parser()

CASES = [  # (command, typed, expected option or "belongs:CMD" or "printing")
    ("print", "--copies-form", "--copies-from"),
    ("print", "--copiesfrom", "--copies-from"),
    ("print", "--copy", "--copies"),
    ("print", "--copias", "--copies"),
    ("print", "--dryrun", "--dry-run"),
    ("print", "--dry_run", "--dry-run"),
    ("print", "--DRY-RUN", "--dry-run"),
    ("print", "-dry-run", "--dry-run"),
    ("print", "--simulate", "--dry-run"),
    ("print", "--teste", "--dry-run"),
    ("print", "--out", "--output"),
    ("print", "--salvar", "--output"),
    ("print", "--csv", "--data"),
    ("print", "--planilha", "--data"),
    ("print", "--dados", "--data"),
    ("print", "--filtro", "--where"),
    ("print", "--filter", "--where"),
    ("print", "--linhas", "--rows"),
    ("print", "--compactall", "--compact-all"),
    ("print", "--compact_all", "--compact-all"),
    ("print", "--no-compac", "--no-compact"),
    ("print", "--nocompact", "--no-compact"),
    ("print", "--setall", "--set-all"),
    ("print", "--allowall", "--allow-all"),
    ("print", "--allow-network", "--allow-net"),
    ("print", "--allownet", "--allow-net"),
    ("print", "--untrusted", "--sandbox"),
    ("check", "--sandbx", "--sandbox"),
    ("print", "--impressora", "--printer"),
    ("print", "--lastt", "--last"),
    ("print", "--agian", "--again"),
    ("print", "--key", "--on"),
    ("print", "--chave", "--on"),
    ("print", "--pages", "belongs:preview"),
    ("print", "--realistic", "belongs:preview"),
    ("print", "--perfil", "--profile"),
    ("print", "--sheets", "--sheet"),
    ("print", "--aba", "--sheet"),
    ("print", "--rpeat", "--repeat"),
    ("print", "--repetir", "--repeat"),
    ("print", "--quite", "--quiet"),
    ("print", "--strcit", "--strict"),
    ("print", "--forca", "--force"),
    ("print", "--pergunta", "--ask"),
    ("print", "--perguntar", "--ask"),
    ("preview", "--page", "--page"),
    ("preview", "--pgaes", "--pages"),
    ("preview", "--realista", "--realistic"),
    ("check", "--output", "belongs:print"),
    ("init", "--impressora", "--printer"),
    ("init", "--cmd", "--command"),
    ("init", "--sim", "--yes"),
    ("history", "--count", "--limit"),
    ("history", "--tail", "--limit"),
    ("history", "--desde", "--since"),
    ("history", "--outcom", "--outcome"),
    ("history", "--longo", "--long"),
    ("calibrate", "--out", "--output"),
    ("config", "--josn", "--json"),
    ("config", "--data", "belongs:print"),
    ("calibrate", "--dryrun", "--dry-run"),
    ("edit", "--templte", "--template"),
    ("edit", "--yse", "--yes"),
    ("fonts", "--nota", "--note"),
    ("help", "--quite", "--quiet"),
    ("library", "--overwrite", "--force"),
    ("library", "--notes", "--note"),
    ("mcp", "--impressora", "--printer"),
    ("mcp", "--allow-net", "belongs:print"),  # a tool argument (allow_net), not an option of the server
    ("mode", "--confirm", "--yes"),
    ("paper", "--diametro", "--diameter"),
    ("paper", "--thicknes", "--thickness"),
    ("paper", "--largura", "--width"),
    ("printer", "--chanel", "--channel"),
    ("printer", "--cmd", "--command"),
    ("printer", "--padrao", "--default"),
    ("profile", "--data", "belongs:print"),
    ("send", "--simulate", "--dry-run"),
    ("seq", "--jsno", "--json"),
    ("status", "--lista", "--list"),
    ("template", "--output", "belongs:print"),
    ("view", "--pages", "belongs:preview"),
    ("view", "--compat", "--compact"),
    ("print", "--model", "--profile"),  # the printer model; in chat and ai --model is the AI's
    ("preview", "--model", "--profile"),
    ("chat", "--perguntas", "--questions"),
    ("chat", "--ia", "--ai"),
    ("chat", "--tickets", "--layout"),
    ("chat", "--modle", "--model"),
    ("chat", "--limt", "--limit"),
    ("chat", "--estilo", "--style"),
    ("chat", "--tema", "--theme"),
    ("chat", "--colors", "--theme"),
    ("chat", "--nome", "--name"),
    ("chat", "--username", "--name"),
    ("ai", "--modelo-ia", "--model"),
    ("ai", "--llm-model", "--model"),
]


def _expected(hint, want):
    if want.startswith("belongs:"):
        return f"bobina {want.split(':')[1]}" in hint
    m = re.search(r"did you mean (.*?)\?", hint)
    return bool(m) and want in re.findall(r"--[\w-]+", m.group(1))


@pytest.mark.parametrize("cmd,typed,want", CASES)
def test_hint(cmd, typed, want):
    if want == "--page" and typed == "--page":
        pytest.skip("--page is a real preview option")
    hint = A.option_hint(typed, cmd)
    assert _expected(hint, want), f"{cmd} {typed}: {hint!r}"


def test_end_to_end_the_subcommand_usage_and_hint(capsys):
    from bobina.cli import main

    with pytest.raises(SystemExit) as code:
        main(["print", "x.bob.md", "--copies-form", "2"])
    assert code.value.code == 1
    e = capsys.readouterr().err
    assert "usage: bobina print" in e and "did you mean --copies-from?" in e
    with pytest.raises(SystemExit):
        main(["--printer", "t", "preview", "x.bob.md", "--pgaes"])
    e = capsys.readouterr().err
    assert "usage: bobina preview" in e and "did you mean --pages?" in e


def test_printing_options_on_a_command_that_never_prints_are_a_note_not_an_error(tmp_path, capsys):
    """Nudges, not blocks: old scripts with -n/-y still run; a note says the option does nothing."""
    from bobina.cli import main

    doc = tmp_path / "a.bob.md"
    doc.write_text("oi\n")
    assert main(["check", str(doc), "--yes"]) == 0
    assert "--yes does nothing in bobina check" in capsys.readouterr().err
    assert main(["-n", "preview", str(doc), "-o", str(tmp_path / "p.png")]) == 0
    assert "--dry-run does nothing in bobina preview" in capsys.readouterr().err
    assert "--yes" not in A.COMMANDS["preview"].format_help()  # not offered in the help


def test_random_typos_of_every_option_are_recognised():
    """Every long option of every command, with each neighbour swap, each dropped letter, _ for -, upper case and
    one dash: the intended option is named (alone, or among the two or three equally close ones)."""
    misses = []
    for cmd, p in A.COMMANDS.items():
        opts = A._options(p)
        for o in opts:
            w = o[2:]
            typos = {"--" + w[:i] + w[i + 1] + w[i] + w[i + 2 :] for i in range(len(w) - 1)}
            typos |= {"--" + w[:i] + w[i + 1 :] for i in range(len(w))}
            typos |= {"--" + w.replace("-", "_"), "--" + w.upper(), "-" + w}
            for t in typos - set(opts):
                if len(t) <= 3:
                    continue
                m = re.search(r"did you mean (.*?)\?", A.option_hint(t, cmd))
                if not m or o not in re.findall(r"--[\w-]+", m.group(1)):
                    misses.append((cmd, o, t))
    assert not misses, misses[:10]


def test_every_option_was_reviewed_for_synonyms():
    """The process for a new option: list its synonyms in ALSO_KNOWN, or put it in NO_SYNONYMS."""
    opts = {o for p in A.COMMANDS.values() for o in A._options(p)}
    missing = sorted(opts - set(A.ALSO_KNOWN) - A.NO_SYNONYMS)
    assert not missing, f"new options {missing}: add them to ALSO_KNOWN (synonyms) or NO_SYNONYMS in cli/args.py"
    stale = sorted((set(A.ALSO_KNOWN) | A.NO_SYNONYMS) - opts)
    assert not stale, f"options that no longer exist: {stale}: remove them from cli/args.py"


REAL_SYNONYMS = {"--model": {"chat", "ai"}}


def test_synonyms_do_not_collide():
    seen = {}
    for opt, words in A.ALSO_KNOWN.items():
        for w in words:
            assert w not in seen, f"{w} is a synonym of both {seen[w]} and {opt}"
            seen[w] = opt
            # a synonym is never a real option, except these, reviewed: --model is the AI's model in chat and ai, and
            # what people type for --profile everywhere else (a real option never reaches the hint)
            real = {c for c, p in A.COMMANDS.items() if w in A._options(p)}
            assert real <= REAL_SYNONYMS.get(w, set()), f"{w} is a real option of {sorted(real)}"


def test_every_command_has_hint_cases_and_a_kind():
    """The process for a new command: a kind in COMMAND_KIND and at least one realistic case in CASES."""
    with_cases = {c for c, *_ in CASES}
    missing = sorted(set(A.COMMANDS) - with_cases)
    assert not missing, f"new commands {missing}: add realistic mistyped options to CASES in this file"
    assert set(A.COMMANDS) == set(A.COMMAND_KIND)


def test_every_synonym_is_suggested():
    for opt, words in A.ALSO_KNOWN.items():
        for cmd, p in A.COMMANDS.items():
            if opt in A._options(p):
                for w in words:
                    assert opt in A.option_hint(w, cmd), (cmd, w)
                break


def test_a_new_command_without_a_kind_cannot_be_added():
    import argparse

    sub = argparse.ArgumentParser().add_subparsers()
    with pytest.raises(RuntimeError, match="add it to COMMAND_KIND"):
        A._cmd(sub, "novo", "x", "x", [], lambda a: 0)
