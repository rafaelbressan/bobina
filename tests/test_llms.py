"""Docs for agents: llms.txt points at files that exist, llms-full.txt is current, and every command, subcommand and
option the agent docs show is a real one, on the command it is shown with (a renamed option must not leave agents
with a wrong recipe)."""

import re
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT_DOCS = ["llms.txt", "skills/bobina/SKILL.md", "AGENTS.md", "README.md"]


def _gen():
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen", ROOT / "tools" / "gen_llms_full.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    return gen


def _local(link: str) -> bool:
    return not re.match(r"[a-z]+:|#|/", link)


def test_every_local_link_in_llms_txt_exists():
    links = [x.split("#")[0] for x in re.findall(r"\]\(([^)]+)\)", (ROOT / "llms.txt").read_text()) if _local(x)]
    assert links and not [x for x in links if not (ROOT / x).exists()]


def test_llms_full_is_current_and_its_links_resolve_from_the_root():
    gen = _gen()
    current = (ROOT / "llms-full.txt").read_text(encoding="utf-8")
    assert current == gen.render(), "run: python tools/gen_llms_full.py"
    prose = re.sub(r"^```.*?^```", "", current, flags=re.S | re.M)  # fenced blocks: whole lines only
    prose = re.sub(r"`[^`\n]*`", "", prose)  # inline code: examples of syntax are not links
    targets = {m.split("#")[0] for m in re.findall(r"\]\(([^)\s]+)\)", prose) if _local(m)}
    assert not [t for t in targets if t and not (ROOT / t).exists()]


def _parser():
    from bobina.cli import args as A

    A.make_parser()
    return A


def _commands_in(text: str):
    """Each `bobina …` code span: (command, the rest as tokens)."""
    for span in re.findall(r"`(bobina [^`]+)`", text):
        try:
            words = shlex.split(span.replace("\\n", " "))
        except ValueError:
            words = span.split()
        if len(words) > 1:
            yield words[1], words[2:]


@pytest.mark.parametrize("doc", AGENT_DOCS)
def test_every_command_and_option_shown_exists_on_that_command(doc):
    A = _parser()
    text = (ROOT / doc).read_text(encoding="utf-8")
    everywhere = {o for p in A.COMMANDS.values() for o in A._options(p)}
    wrong = []
    for cmd, rest in _commands_in(text):
        if cmd == "help":
            continue
        if cmd not in A.COMMANDS:
            wrong.append(f"bobina {cmd}")
            continue
        p = A.COMMANDS[cmd]
        opts = set(A._options(p)) | {s for a in p._actions for s in a.option_strings}
        choices = [a.choices for a in p._actions if a.choices and not a.option_strings]
        if choices and rest and re.fullmatch(r"[a-z]+", rest[0]) and rest[0] not in choices[0]:
            wrong.append(f"bobina {cmd} {rest[0]}")
        wrong += [f"bobina {cmd} … {w}" for w in rest if w.startswith("-") and w.split("=")[0] not in opts]
    loose = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", text)) - everywhere - {"--version", "--help"}
    assert not wrong and not loose, (wrong, sorted(loose))
