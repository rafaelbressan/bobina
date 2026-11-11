"""bobina chat and bobina ai with fake AIs: no network, no real AI program (subprocess and HTTP are mocked), a file
printer and config/state in a temporary folder. Paper is measured with the estimator check and print use."""

import io
import json
import subprocess
import sys

import pytest

from bobina import ai, chat, config
from bobina import profile as profiles
from bobina.cli import main

LONG = " ".join(["The sky looks blue because air scatters short blue light more than red light."] * 30)


class Fake(ai.Backend):
    """An AI that answers from a list and records what it was sent."""

    name, label, vendor = "fake", "Fake AI", "Fake"

    def __init__(self, answers, model="fake-1"):
        super().__init__(model)
        self.answers = list(answers)
        self.calls = []

    def ask(self, system, messages):
        self.calls.append((system, [dict(m) for m in messages]))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return ai.Reply(a, self.model)


@pytest.fixture
def printer(tmp_path):
    out = tmp_path / "out.bin"
    assert main(["printer", "add", "test", "--path", str(out), "--default"]) == 0
    return out


def run_chat(monkeypatch, capsys, fake, lines, *argv):
    monkeypatch.setattr(ai, "backend", lambda name, model=None: fake)
    monkeypatch.setattr(ai, "detect", lambda: [ai.Found("claude", "Claude Code", True, "/bin/claude")])
    monkeypatch.setattr(sys, "stdin", io.StringIO("".join(line + "\n" for line in lines)))
    code = main(["chat", *argv])
    return code, capsys.readouterr()


def ticket(prof="mtp-ii-58"):
    return chat.Ticket(profiles.load(prof))


# ------------------------------------------------------------------------------------------------------- the ticket


def _lines(res):
    from bobina.rows import TextRow

    return [r for r in res.rows if isinstance(r, TextRow)]


def _text(row) -> str:
    return "".join(c.ch for c in row.cells)


def test_an_answer_is_plain_text_only_bold_kept_and_nothing_runs():
    """The AI's text is never a .bob.md document: no raw bytes, templates, images, headings or escape codes."""
    text = "# Title\n```raw\n1b 40\n```\n{{ seq.x }} ![x](/etc/passwd) **bold** *it*\x1b[31m red"
    res = ticket().ticket(chat.clean(text))
    shown = "\n".join(_text(r) for r in _lines(res))
    assert "{{ seq.x }}" in shown and "![x](/etc/passwd)" in shown and "Title" in shown and "1b 40" in shown
    assert "\x1b" not in shown and "```" not in shown and "**" not in shown and "*it*" not in shown
    bold = "".join(c.ch for r in _lines(res) for c in r.cells if c.bold)
    assert bold == "bold"


def test_the_limit_in_characters_scales_with_the_paper_width():
    small, wide = ticket("mtp-ii-58"), None
    for name in profiles.available():
        p = profiles.load(name)
        if p.columns == 48:
            wide = chat.Ticket(p)
            break
    assert small.profile.columns == 32
    assert 500 <= small.chars(100) <= 900
    if wide:
        assert wide.chars(100) > small.chars(100) * 1.4


def test_a_cut_answer_fits_the_limit_and_ends_with_an_ellipsis():
    t = ticket()
    cut = t.cut(LONG, 50)
    assert cut.endswith("…") and LONG.startswith(cut[:-1].rstrip())
    assert t.answer_mm(cut) <= 50 < t.answer_mm(LONG)


def _ink(im, y0, y1):
    """The leftmost and rightmost black column between rows y0 and y1 of a preview."""
    px = im.convert("L").load()
    xs = [x for y in range(y0, y1) for x in range(im.width) if px[x, y] < 128]
    return min(xs), max(xs)


def test_the_question_prints_on_the_right_and_the_answer_on_the_left():
    """Like a chat app; a long question is wrapped first, then each of its lines is aligned right (no stretching)."""
    from bobina import preview
    from bobina.rows import TextRow

    t = ticket()
    q = "why is the sky blue and not green or violet, if violet is shorter?"
    res = t.ticket("Air scatters blue light the most of all colours.", question=q)
    im = preview.render(res.rows, res.profile, res.emulator)
    spans, y = [], 0
    for r in res.rows:
        h = preview.heights([r], res.profile, res.emulator)
        if isinstance(r, TextRow):
            spans.append((r, y, y + h))
        y += h
    asked = [s for s in spans if s[0].align == "right"]
    answer = [s for s in spans if s[0].align == "left"]
    assert len(asked) >= 2 and answer  # the question wrapped into lines, each one right-aligned
    assert " ".join(_text(r).strip() for r, *_ in asked) == q
    for r, a, b in asked:
        left, right = _ink(im, a, b)
        assert right >= im.width - 16, _text(r)  # flush right
        assert left > 24, _text(r)  # not justified to the left edge: the spaces between words are not stretched
        assert "  " not in _text(r).strip()
    left, _ = _ink(im, answer[0][1], answer[0][2])
    assert left <= 12  # the answer starts on the left


def test_strip_answers_follow_each_other_and_tickets_feed_to_the_tear_bar():
    from bobina.rows import FeedRow

    t = ticket()
    conv = chat.Conversation(Fake([]), t)
    ans = chat.Answer("Hello there.", "Hello there.", "fake-1")
    first = conv.job(ans, None)
    conv.count(first)
    second = conv.job(ans, None)
    assert not (isinstance(first.rows[-1], FeedRow) and first.rows[-1].mark == "tear")  # no paper between answers
    assert first.rows[0].dots == t.profile.get("margins.top_dots")
    assert isinstance(second.rows[0], FeedRow) and second.rows[0].dots < t.profile.get("margins.top_dots")
    assert second.length_mm < first.length_mm  # no header, no top margin: only a dashed line and the answer
    end = t.end_of_strip()
    assert end.rows[-1].mark == "tear"
    conv.layout = "tickets"
    one = conv.job(ans, None)
    assert one.rows[-1].mark == "tear" and one.length_mm > first.length_mm  # header, answer and the tear feed


# ----------------------------------------------------------------------------------------------- the conversation


def test_every_turn_tells_the_ai_the_paper_and_the_limit(monkeypatch):
    fake = Fake(["One.", "Two."])
    conv = chat.Conversation(fake, ticket(), paper_left=lambda: 12345.0)
    conv.ask("first?")
    conv.count(conv.job(chat.Answer("One.", "One.", None), None))
    conv.ask("second?")
    s1, s2 = fake.calls[0][0], fake.calls[1][0]
    assert "58 mm wide, 32 characters per line" in s1 and "characters (about 10 cm" in s1
    assert "Paper left on the roll: 12.3 m" in s1 and "used in this conversation so far: 0 cm" in s1
    assert "No Markdown except **bold**" in s1 and "tables" in s1
    assert "so far: 0 cm" not in s2  # the paper of the first answer is counted
    assert [m["content"] for m in fake.calls[1][1]] == ["first?", "One.", "second?"]


def test_a_long_answer_is_rewritten_once_then_cut(monkeypatch):
    fake = Fake([LONG, "Blue light scatters most."])
    conv = chat.Conversation(fake, ticket())
    a = conv.ask("why blue?")
    assert a.rewritten and not a.cut and a.paper == "Blue light scatters most."
    assert "too long for the receipt" in fake.calls[1][1][-1]["content"]
    fake = Fake([LONG, LONG])
    conv = chat.Conversation(fake, ticket())
    a = conv.ask("why blue?")
    assert a.cut and a.paper.endswith("…") and a.text == chat.clean(LONG)
    assert conv.ticket.answer_mm(a.paper) <= conv.limit_mm
    assert len(fake.calls) == 2  # asked to rewrite once, never more


def test_a_metre_of_paper_is_said_in_the_terminal(monkeypatch):
    conv = chat.Conversation(Fake([]), ticket())

    class R:
        length_mm = 400.0

    assert conv.count(R()) is None and conv.count(R()) is None
    assert conv.count(R()) == pytest.approx(1200.0)


# --------------------------------------------------------------------------------------------------- bobina chat


def test_chat_prints_each_answer_on_a_file_printer(monkeypatch, capsys, printer):
    fake = Fake(["The sky is **blue** because air scatters blue light.", "Sunsets are red: the light goes far."])
    code, out = run_chat(monkeypatch, capsys, fake, ["why is the sky blue?", "and sunsets?", "/quit"])
    assert code == 0
    o = out.out
    assert "each answer prints on test right away" in o and "layout: one strip" in o and "/tickets" in o
    assert o.count("[printed on test") == 2 and "fed to the tear bar" in o
    data = printer.read_bytes()
    assert b"Fake \xc2\xb7 fake-1" in data and b"blue" in data and b"why is the sky" not in data
    assert data.count(b"Fake \xc2\xb7") == 1  # the header once per conversation
    rows = [json.loads(x) for x in (config.paths.state_dir() / "history.jsonl").read_text().splitlines()]
    assert [r["outcome"] for r in rows] == ["printed", "printed"]


def test_chat_tickets_and_questions(monkeypatch, capsys, printer):
    fake = Fake(["Blue.", "Red."])
    code, out = run_chat(monkeypatch, capsys, fake, ["sky?", "sunset?"], "--layout", "tickets", "--questions")
    assert code == 0 and "layout: one ticket per answer" in out.out
    data = printer.read_bytes()
    assert data.count(b"Fake \xc2\xb7") == 2 and b"sky?" in data and b"sunset?" in data


def test_manual_mode_prints_only_on_p_and_in_chat_switches(monkeypatch, capsys, printer):
    fake = Fake(["One.", "Two."])
    code, out = run_chat(monkeypatch, capsys, fake, ["/manual", "a?", "p", "p", "/auto", "/tickets", "b?"])
    o = out.out
    assert "manual mode" in o and "p prints it" in o and "already on paper" in o
    assert o.count("[printed on test") == 2 and "one ticket per answer from now on" in o


def test_an_unreachable_printer_keeps_the_chat_going(monkeypatch, capsys, tmp_path):
    config.set_value("default_printer", "gone")
    config.update(lambda c: c.setdefault("printers", {}).update(gone={"transport": "command", "command": "false"}))
    fake = Fake(["One.", "Two."])
    code, out = run_chat(monkeypatch, capsys, fake, ["a?", "b?"])
    assert code == 0 and out.out.count("[not printed:") == 2 and "p tries this answer again" in out.out
    assert "Two." in out.out


def test_an_ai_error_is_said_and_the_chat_goes_on(monkeypatch, capsys, printer):
    fake = Fake([ai.AIError("Claude Code failed: not logged in", "run claude once and log in"), "Fine."])
    code, out = run_chat(monkeypatch, capsys, fake, ["a?", "b?"])
    assert "[no answer: Claude Code failed: not logged in]" in out.out and "run claude once" in out.out
    assert "Fine." in out.out and out.out.count("[printed") == 1


def test_dry_run_prints_nothing_and_counts_the_paper(monkeypatch, capsys, printer):
    code, out = run_chat(monkeypatch, capsys, Fake(["One."]), ["a?"], "--dry-run")
    assert "nothing prints (--dry-run)" in out.out and "[not printed (--dry-run): ~" in out.out
    assert not printer.exists() or printer.read_bytes() == b""


def test_the_first_chat_chooses_and_saves_the_ai(monkeypatch, capsys, printer):
    code, out = run_chat(monkeypatch, capsys, Fake(["One."]), ["a?"])
    assert "using Claude Code, the first AI found" in out.out
    assert config.load()["ai"] == "claude"


def test_no_ai_found_says_what_to_install(monkeypatch, capsys):
    monkeypatch.setattr(ai, "detect", lambda: [ai.Found(n, n, False, needs=ai.INSTALL[n]) for n in ai.ORDER])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert main(["chat"]) == 1
    e = capsys.readouterr().err
    assert "E601" in e and "no AI found" in e and "ollama pull" in e and "ANTHROPIC_API_KEY" in e


def test_limit_option(monkeypatch, capsys, printer):
    fake = Fake([LONG, LONG])
    code, out = run_chat(monkeypatch, capsys, fake, ["a?"], "--limit", "4cm")
    assert "at most 4 cm each" in out.out and "cut with …" in out.out
    assert "about 4 cm of paper" in fake.calls[0][0]


# ----------------------------------------------------------------------------------------------------- bobina ai


def test_ai_list_and_use(monkeypatch, capsys):
    monkeypatch.setattr(ai, "detect", lambda: [
        ai.Found("claude", "Claude Code", True, "/usr/bin/claude (its own login)"),
        ai.Found("ollama", "Ollama (local)", True, "http://127.0.0.1:11434: llama3.2", models=["llama3.2"]),
        ai.Found("anthropic", "Claude API", False, needs="export ANTHROPIC_API_KEY=…"),
    ])  # fmt: skip
    assert main(["ai"]) == 0
    o = capsys.readouterr().out
    assert o.index("claude") < o.index("ollama") and "not found: anthropic" in o
    assert main(["ai", "use", "ollama", "--model", "llama3.2"]) == 0
    assert config.load()["ai"] == "ollama" and config.load()["ai_model"] == "llama3.2"
    capsys.readouterr()
    assert main(["ai", "list", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "bobina.ai/1" and doc["in_use"] == "ollama" and doc["model"] == "llama3.2"


def test_detection_order_and_what_is_missing(monkeypatch):
    monkeypatch.setattr(ai.shutil, "which", lambda n: "/usr/bin/codex" if n == "codex" else None)
    monkeypatch.setattr(ai, "ollama_models", lambda timeout=0.5: ["qwen2.5"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(ai, "_sdk", lambda m: False)
    found = ai.detect()
    assert [f.name for f in found] == list(ai.ORDER)
    by = {f.name: f for f in found}
    assert by["codex"].available and not by["claude"].available and by["ollama"].ready
    assert by["anthropic"].available and not by["anthropic"].ready and "bobina[ai]" in by["anthropic"].needs


# ------------------------------------------------------------------------------------------- the backends, mocked


def test_claude_code_is_called_without_tools_and_its_model_is_read(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["input"], seen["cwd"] = cmd, kw.get("input"), kw.get("cwd")
        out = {
            "type": "result",
            "is_error": False,
            "result": "Blue.",
            "modelUsage": {"claude-haiku-4-5": {"outputTokens": 3}, "claude-opus-5-5": {"outputTokens": 40}},
        }
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")  # fmt: skip

    monkeypatch.setattr(ai.subprocess, "run", fake_run)
    r = ai.backend("claude").ask("SYSTEM", [{"role": "user", "content": "why?"}])
    assert r.text == "Blue." and r.model == "claude-opus-5-5"
    cmd = seen["cmd"]
    assert cmd[:2] == ["claude", "-p"] and cmd[cmd.index("--tools") + 1] == "" and "--system-prompt" in cmd
    assert "why?" in seen["input"] and seen["cwd"]
    assert ai.header("Claude", r.model) == "Claude · Opus 5.5"


def test_claude_code_not_logged_in(monkeypatch):
    monkeypatch.setattr(ai.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Error: please log in"))  # fmt: skip
    with pytest.raises(ai.AIError) as e:
        ai.backend("claude").ask("S", [{"role": "user", "content": "x"}])
    assert "log in" in e.value.hint


def test_codex_and_gemini_get_one_prompt(monkeypatch):
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        if cmd[0] == "codex":
            from pathlib import Path

            Path(cmd[cmd.index("--output-last-message") + 1]).write_text("From codex.")
        return subprocess.CompletedProcess(cmd, 0, "From gemini.\n", "")

    monkeypatch.setattr(ai.subprocess, "run", fake_run)
    monkeypatch.setattr(ai, "_codex_model", lambda: "gpt-5")
    msgs = [
        {"role": "user", "content": "a?"},
        {"role": "assistant", "content": "A."},
        {"role": "user", "content": "b?"},
    ]
    r = ai.backend("codex").ask("RULES", msgs)
    assert r.text == "From codex." and r.model == "gpt-5" and "--sandbox" in seen[0]
    assert "RULES" in seen[0][-1] and "Person: a?" in seen[0][-1] and seen[0][-1].endswith("b?")
    r = ai.backend("gemini", "gemini-2.5-pro").ask("RULES", msgs)
    assert r.text == "From gemini." and ai.header("Gemini", r.model) == "Gemini · 2.5 Pro"


def test_ollama_over_http(monkeypatch):
    calls = []

    def fake_http(method, url, body=None, timeout=0):
        calls.append((method, url, body))
        if url.endswith("/api/tags"):
            return {"models": [{"name": "llama3.2:3b"}]}
        return {"model": "llama3.2:3b", "message": {"role": "assistant", "content": "Hi."}}

    monkeypatch.setattr(ai, "_http", fake_http)
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
    r = ai.backend("ollama").ask("S", [{"role": "user", "content": "hi"}])
    assert r.text == "Hi." and r.model == "llama3.2:3b"
    assert calls[-1][1] == "http://127.0.0.1:11434/api/chat" and calls[-1][2]["messages"][0]["role"] == "system"


def test_api_backends_need_their_sdk(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.setitem(sys.modules, "openai", None)
    for name in ("anthropic", "openai"):
        with pytest.raises(ai.AIError) as e:
            ai.backend(name).ask("S", [{"role": "user", "content": "x"}])
        assert "bobina[ai]" in e.value.hint


def test_anthropic_backend_with_a_fake_sdk(monkeypatch):
    import types

    sent = {}

    class Block:
        type, text = "text", "Blue."

    class Msg:
        stop_reason, content, model = "end_turn", [Block()], "claude-opus-5-5"

    class Messages:
        def create(self, **kw):
            sent.update(kw)
            return Msg()

    class Client:
        def __init__(self):
            self.messages = Messages()
            self.beta = types.SimpleNamespace(messages=Messages())

    mod = types.ModuleType("anthropic")
    mod.Anthropic = Client
    for n in ("AuthenticationError", "NotFoundError", "RateLimitError", "APIStatusError", "APIConnectionError"):
        setattr(mod, n, type(n, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    r = ai.backend("anthropic").ask("S", [{"role": "user", "content": "x"}])
    assert r.text == "Blue." and sent["model"] == "claude-opus-5-5" and sent["system"] == "S"
    assert sent["fallbacks"] == "default" and sent["output_config"] == {"effort": "low"}


def test_model_labels():
    assert ai.model_label("claude-sonnet-4-5-20250929") == "Sonnet 4.5"
    assert ai.model_label("claude-opus-5") == "Opus 5"
    assert ai.model_label("gpt-5") == "GPT-5"
    assert ai.header("Ollama", None) == "Ollama"
