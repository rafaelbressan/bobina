"""bobina chat and bobina ai with fake AIs: no network, no real AI program (subprocess and HTTP are mocked), a file
printer and config/state in a temporary folder. Paper is measured with the estimator check and print use."""

import io
import json
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
        if isinstance(a, BaseException):
            raise a
        return ai.Reply(a, self.model)


@pytest.fixture
def printer(tmp_path):
    out = tmp_path / "out.bin"
    assert main(["printer", "add", "test", "--path", str(out), "--default"]) == 0
    return out


class LinesUI:
    """A test double of the chat screen: lines on stdin and stdout (each line read is echoed after "you> ")."""

    def welcome(self, lines):
        print("\n".join(lines) + "\n", flush=True)

    def read(self, session):
        line = sys.stdin.readline()
        if not line:
            return None
        print("you> " + line.rstrip("\n"), flush=True)
        return line.rstrip("\n")

    def answer(self, who, text):
        print(f"{who}:\n{chat.BOLD.sub(lambda m: m.group(1), text)}\n", flush=True)

    def note(self, text):
        print(f"  {text}", flush=True)

    dim = note

    def wait(self, label, fn):
        return fn()

    def choose_ai(self, ready):
        return ready[0]


def fake_ai(monkeypatch, fake):
    monkeypatch.setattr(ai, "backend", lambda name, model=None: fake)
    monkeypatch.setattr(ai, "detect", lambda: [ai.Found("claude", "Claude Code", True, "/bin/claude")])


def run_chat(monkeypatch, capsys, fake, lines, *argv):
    """The chat screen, driven by lines (the session is the same; PlainUI stands for the terminal screen)."""
    from bobina.cli import chat as cli_chat

    capsys.readouterr()
    fake_ai(monkeypatch, fake)
    monkeypatch.setattr(cli_chat, "terminal", lambda: True)
    monkeypatch.setattr(cli_chat, "_ui", lambda args, cfg: LinesUI())
    monkeypatch.setattr(sys, "stdin", io.StringIO("".join(line + "\n" for line in lines)))
    code = main(["chat", *argv])
    return code, capsys.readouterr()


def ask_once(monkeypatch, capsys, fake, *argv, stdin=""):
    """One question, no screen: bobina chat "QUESTION" (stdin is not a terminal here: a pipe)."""
    import os

    capsys.readouterr()
    fake_ai(monkeypatch, fake)
    r, w = os.pipe()
    os.write(w, stdin.encode())
    os.close(w)
    monkeypatch.setattr(sys, "stdin", open(r, encoding="utf-8"))  # noqa: SIM115 - closed with the test
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
    conv.remember("first?", conv.ask("first?"))
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
    assert "printer test" in o and "layout: one strip" in o and "/tickets" in o and "each answer prints right away" in o
    assert o.count("printed on test") == 2 and "fed to the tear bar" in o
    assert "Fake · fake-1:\nThe sky is blue because" in o  # bold shown without the stars
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
    assert "manual mode" in o and "p prints it" in o and "already printed (~" in o and "/again prints" in o
    assert o.count("printed on test") == 2 and "one ticket per answer from now on" in o


def test_an_unreachable_printer_keeps_the_chat_going(monkeypatch, capsys, tmp_path):
    config.set_value("default_printer", "gone")
    config.update(lambda c: c.setdefault("printers", {}).update(gone={"transport": "command", "command": "false"}))
    fake = Fake(["One.", "Two."])
    code, out = run_chat(monkeypatch, capsys, fake, ["a?", "b?"])
    assert code == 0 and out.out.count("not printed:") == 2 and "p tries this answer again" in out.out
    assert "Two." in out.out


def test_an_ai_error_is_said_and_the_chat_goes_on(monkeypatch, capsys, printer):
    fake = Fake([ai.AIError("Claude Code failed: not logged in", "run claude once and log in"), "Fine."])
    code, out = run_chat(monkeypatch, capsys, fake, ["a?", "b?"])
    assert "no answer: Claude Code failed: not logged in" in out.out and "run claude once" in out.out
    assert "Fine." in out.out and out.out.count("printed on") == 1


def test_dry_run_prints_nothing_and_counts_the_paper(monkeypatch, capsys, printer):
    code, out = run_chat(monkeypatch, capsys, Fake(["One."]), ["a?"], "--dry-run")
    assert "nothing prints (--dry-run)" in out.out and "not printed (--dry-run) · " in out.out
    assert not printer.exists() or printer.read_bytes() == b""


def test_the_first_chat_chooses_and_saves_the_ai(monkeypatch, capsys, printer):
    code, out = run_chat(monkeypatch, capsys, Fake(["One."]), ["a?"])
    assert "using Claude Code, the first AI found" in out.err
    assert config.load()["ai"] == "claude"


def test_no_ai_found_says_what_to_install(monkeypatch, capsys):
    monkeypatch.setattr(ai, "detect", lambda: [ai.Found(n, n, False, needs=ai.INSTALL[n]) for n in ai.ORDER])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert main(["chat", "hello?"]) == 1
    e = capsys.readouterr().err
    assert "E601" in e and "no AI found" in e and "ollama pull" in e and "ANTHROPIC_API_KEY" in e


def test_limit_option(monkeypatch, capsys, printer):
    fake = Fake([LONG, LONG])
    code, out = run_chat(monkeypatch, capsys, fake, ["a?"], "--limit", "4cm")
    assert "at most 4 cm of paper" in out.out and "on paper it ends with …" in out.out
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
    monkeypatch.setattr(ai, "program", lambda n: "/usr/bin/codex" if n == "codex" else None)
    monkeypatch.setattr(ai, "ollama_models", lambda timeout=0.5: ["qwen2.5"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    found = ai.detect()
    assert [f.name for f in found] == list(ai.ORDER)
    by = {f.name: f for f in found}
    assert by["codex"].available and not by["claude"].available and by["ollama"].ready
    assert by["anthropic"].ready and not by["openai"].available and "OPENAI_API_KEY" in by["openai"].needs


# ------------------------------------------------------------------------------------------- the backends, mocked


def fake_exec(monkeypatch, answer):
    """Mocks the AI programs: answer(cmd, stdin, cwd) -> (exit code, stdout, stderr); records each call."""
    seen = []
    monkeypatch.setattr(ai, "program", lambda name: f"/opt/bin/{name}")

    def run(cmd, input_text, cwd):
        seen.append({"cmd": cmd, "stdin": input_text, "cwd": cwd})
        return answer(cmd, input_text, cwd)

    monkeypatch.setattr(ai, "_exec", run)
    return seen


def test_claude_code_runs_alone_and_its_model_is_read(monkeypatch):
    """No tools, no settings, hooks, plugins, CLAUDE.md or MCP servers of the user, no session saved."""
    out = {"type": "result", "is_error": False, "result": "Blue.",
           "modelUsage": {"claude-haiku-4-5": {"outputTokens": 3}, "claude-opus-5-5": {"outputTokens": 40}}}  # fmt: skip
    seen = fake_exec(monkeypatch, lambda *a: (0, json.dumps(out), ""))
    r = ai.backend("claude").ask("SYSTEM", [{"role": "user", "content": "why?"}])
    assert r.text == "Blue." and r.model == "claude-opus-5-5"
    cmd = seen[0]["cmd"]
    assert cmd[0] == "/opt/bin/claude" and cmd[1] == "-p" and cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--setting-sources") + 1] == "" and "--safe-mode" in cmd and "--strict-mcp-config" in cmd
    assert "--no-session-persistence" in cmd and "--disable-slash-commands" in cmd and "--system-prompt" in cmd
    assert "why?" in seen[0]["stdin"] and seen[0]["cwd"]
    assert ai.header("Claude", r.model) == "Claude · Opus 5.5"


def test_claude_code_errors_say_its_reason(monkeypatch):
    """A failed turn exits 1 with the JSON result: its reason is shown (not the JSON), and a login hint."""
    out = {"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in · Please run /login",
           "terminal_reason": "api_error", "usage": {"input_tokens": 0}}  # fmt: skip
    fake_exec(monkeypatch, lambda *a: (1, json.dumps(out), ""))
    with pytest.raises(ai.AIError) as e:
        ai.backend("claude").ask("S", [{"role": "user", "content": "x"}])
    assert str(e.value) == "Claude Code failed: Not logged in · Please run /login" and "log in" in e.value.hint
    fake_exec(monkeypatch, lambda *a: (1, "", "Error: something broke\n"))
    with pytest.raises(ai.AIError) as e:
        ai.backend("claude").ask("S", [{"role": "user", "content": "x"}])
    assert str(e.value) == "Claude Code failed: Error: something broke" and not e.value.hint


def test_codex_and_gemini_get_the_transcript_on_stdin_and_no_tools(monkeypatch):
    def answer(cmd, stdin, cwd):
        if cmd[0].endswith("codex"):
            from pathlib import Path

            Path(cmd[cmd.index("--output-last-message") + 1]).write_text("From codex.")
        return 0, "From gemini.\n", ""

    seen = fake_exec(monkeypatch, answer)
    monkeypatch.setattr(ai, "_codex_model", lambda: "gpt-5")
    msgs = [
        {"role": "user", "content": "a?"},
        {"role": "assistant", "content": "A."},
        {"role": "user", "content": "b?"},
    ]
    r = ai.backend("codex").ask("RULES", msgs)
    cmd = seen[0]["cmd"]
    assert r.text == "From codex." and r.model == "gpt-5" and cmd[0] == "/opt/bin/codex"  # the path found (.cmd)
    assert cmd[-1] == "-" and "RULES" in seen[0]["stdin"] and "Person: a?" in seen[0]["stdin"]
    assert "features.shell_tool=false" in cmd and "tools.web_search=false" in cmd and "--ephemeral" in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only" and "mcp_servers={}" in cmd
    r = ai.backend("gemini", "gemini-2.5-pro").ask("RULES", msgs)
    cmd = seen[1]["cmd"]
    assert r.text == "From gemini." and ai.header("Gemini", r.model) == "Gemini · 2.5 Pro"
    assert "RULES" in seen[1]["stdin"] and all("Person: a?" not in c for c in cmd)  # never one huge argument
    assert cmd[cmd.index("--extensions") + 1] == "none" and "--admin-policy" in cmd


def test_gemini_denies_every_tool():
    assert 'toolName = "*"' in ai.GEMINI_POLICY and 'decision = "deny"' in ai.GEMINI_POLICY


def test_a_missing_program_is_said(monkeypatch):
    monkeypatch.setattr(ai, "program", lambda name: None)
    with pytest.raises(ai.AIError) as e:
        ai.backend("gemini").ask("S", [{"role": "user", "content": "x"}])
    assert "not installed" in str(e.value)


@pytest.mark.parametrize(
    "value,url",
    [
        ("", "http://127.0.0.1:11434"),
        ("0.0.0.0", "http://127.0.0.1:11434"),
        ("0.0.0.0:8080", "http://127.0.0.1:8080"),
        ("10.0.0.5", "http://10.0.0.5:11434"),
        ("my0.0.0.0host:9", "http://my0.0.0.0host:9"),  # 0.0.0.0 only as the whole host
        ("localhost", "http://localhost:11434"),
        ("https://box.example", "https://box.example"),
        ("http://box:1234/", "http://box:1234"),
        ("[::1]:11434", "http://[::1]:11434"),
        ("::", "http://[::1]:11434"),
        ("[::]", "http://[::1]:11434"),
    ],
)
def test_ollama_host(value, url):
    assert ai.ollama_host(value) == url


def test_ollama_skips_embedding_models_and_a_refusal_is_said(monkeypatch):
    import urllib.error

    calls = []

    def fake_http(method, url, body=None, timeout=0):
        calls.append((method, url, body))
        if url.endswith("/api/tags"):
            return {"models": [{"name": "nomic-embed-text:latest"}, {"name": "embeddinggemma"},
                               {"name": "gemma3:1b"}]}  # fmt: skip
        if url.endswith("/api/show"):
            return {"capabilities": ["completion"]}
        raise urllib.error.HTTPError(url, 400, "Bad Request", {}, io.BytesIO(b'{"error":"bad thing"}'))

    monkeypatch.setattr(ai, "_http", fake_http)
    with pytest.raises(ai.AIError) as e:
        ai.backend("ollama").ask("S", [{"role": "user", "content": "hi"}])
    assert calls[-1][2]["model"] == "gemma3:1b"
    assert "bad thing" in str(e.value) and "pulled" not in str(e.value) + e.value.hint


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


def fake_api(monkeypatch, reply):
    sent = []

    def http(method, url, body=None, timeout=0, headers=None):
        sent.append({"url": url, "body": body, "headers": headers or {}})
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(ai, "_http", http)
    return sent


def test_the_claude_api_with_the_standard_library(monkeypatch):
    """No SDK: a plain POST with the current API version, low effort and server-side fallbacks on a refusal."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    out = {"model": "claude-opus-5-5", "stop_reason": "end_turn",
           "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "Blue."}]}  # fmt: skip
    sent = fake_api(monkeypatch, out)
    r = ai.backend("anthropic").ask("S", [{"role": "user", "content": "x"}])
    req = sent[0]
    assert r.text == "Blue." and r.model == "claude-opus-5-5" and req["url"] == "https://api.anthropic.com/v1/messages"
    assert req["headers"]["x-api-key"] == "sk-test" and req["headers"]["anthropic-version"] == "2026-10-21"
    assert req["headers"]["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert req["body"]["fallbacks"] == "default" and req["body"]["output_config"] == {"effort": "low"}
    assert req["body"]["system"] == "S" and "temperature" not in req["body"]
    fake_api(monkeypatch, {"stop_reason": "refusal", "content": []})
    with pytest.raises(ai.AIError, match="declined"):
        ai.backend("anthropic").ask("S", [{"role": "user", "content": "x"}])
    sent = fake_api(monkeypatch, out)
    ai.backend("anthropic", "claude-haiku-4-5").ask("S", [{"role": "user", "content": "x"}])
    assert "fallbacks" not in sent[0]["body"] and "anthropic-beta" not in sent[0]["headers"]  # an older model


def test_an_api_refusal_says_its_reason(monkeypatch):
    import urllib.error

    body = io.BytesIO(b'{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}')
    fake_api(monkeypatch, urllib.error.HTTPError("u", 401, "Unauthorized", {}, body))
    with pytest.raises(ai.AIError) as e:
        ai.backend("anthropic").ask("S", [{"role": "user", "content": "x"}])
    assert "invalid x-api-key" in str(e.value) and "ANTHROPIC_API_KEY" in e.value.hint
    fake_api(monkeypatch, urllib.error.URLError("no route"))
    with pytest.raises(ai.AIError, match="cannot reach the OpenAI API"):
        ai.backend("openai").ask("S", [{"role": "user", "content": "x"}])


def test_the_openai_api_with_the_standard_library(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-o")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1/")
    sent = fake_api(monkeypatch, {"model": "gpt-5", "choices": [{"message": {"content": "Hi."}}]})
    r = ai.backend("openai").ask("SYSTEM", [{"role": "user", "content": "x"}])
    assert r.text == "Hi." and r.model == "gpt-5" and sent[0]["url"] == "http://127.0.0.1:9/v1/chat/completions"
    assert sent[0]["headers"]["Authorization"] == "Bearer sk-o" and sent[0]["body"]["messages"][0]["role"] == "system"


def test_model_labels():
    assert ai.model_label("claude-sonnet-4-5-20250929") == "Sonnet 4.5"
    assert ai.model_label("claude-opus-5") == "Opus 5"
    assert ai.model_label("gpt-5") == "GPT-5"
    assert ai.header("Ollama", None) == "Ollama"


# ------------------------------------------------------------------------------------ review fixes and the UI layer


def test_a_damaged_roll_record_never_stops_the_chat(monkeypatch):
    from bobina import fileio, paper
    from bobina.cli import chat as cli_chat

    pr = {"transport": "command", "command": "true"}
    for record in ({"used_mm": 10}, {"roll_mm": 100, "used_mm": 500}, {"roll_mm": "x"}, None):
        monkeypatch.setattr(paper, "get", lambda name, r=record: r)
        left = cli_chat.paper_left_of("cmd", pr)()
        assert left is None or left == 0.0

    def broken(name):
        raise fileio.StateError("broken")

    monkeypatch.setattr(paper, "get", broken)
    assert cli_chat.paper_left_of("cmd", pr)() is None
    assert cli_chat.paper_left_of("file", {"transport": "file", "path": "x.bin"})() is None


def test_the_saved_ai_keeps_its_model_with_ai(monkeypatch):
    from bobina.cli import chat as cli_chat

    config.set_value("ai", "ollama")
    config.set_value("ai_model", "gemma3:1b")
    args = type("A", (), {"ai": "ollama", "model": None})()
    assert cli_chat._choose(args, None) == ("ollama", "gemma3:1b")
    args.ai = "claude"
    assert cli_chat._choose(args, None) == ("claude", None)  # another AI: its own default model


def test_nudges_and_the_roll_are_checked_before_printing(monkeypatch, capsys, tmp_path):
    from bobina import paper

    out = tmp_path / "cmd.bin"
    printers = {"cmd": {"transport": "command", "command": f"tee -a {out}"}}
    config.update(lambda c: c.setdefault("printers", {}).update(printers))
    config.set_value("default_printer", "cmd")
    paper.new_roll("cmd", 20.0)  # 2 cm left
    fake = Fake(["Go → there, then ← back. " * 3])
    code, o = run_chat(monkeypatch, capsys, fake, ["a?"])
    assert "P102" in o.out and "F301" in o.out  # said, and printed anyway
    assert "printed on cmd" in o.out and out.exists()


def test_printed_questions_have_a_limit_and_are_never_cut(monkeypatch, capsys, printer):
    fake = Fake(["Short."])
    long_q = "why " * 60
    code, o = run_chat(monkeypatch, capsys, fake, [long_q, "/questions off", long_q], "--questions")
    assert "too long to print: 239/" in o.out and "/questions off" in o.out
    assert len(fake.calls) == 1  # the long question went only after /questions off
    assert "only the answers print" in o.out


class Screen:
    """A UI that records what the session shows (the thin layer the terminal screen also implements)."""

    def __init__(self, lines):
        self.lines, self.shown = list(lines), []

    def welcome(self, lines):
        self.shown.append(("welcome", lines))

    def read(self, session):
        self.shown.append(("status", session.status()))
        return self.lines.pop(0) if self.lines else None

    def answer(self, who, text):
        self.shown.append(("answer", who, text))

    def note(self, text):
        self.shown.append(("note", text))

    def dim(self, text):
        self.shown.append(("dim", text))

    def wait(self, label, fn):
        self.shown.append(("wait", label))
        return fn()


def _session(lines, answers, **kw):
    from bobina.cli import chat as cli_chat

    pr = {"transport": "command", "command": "true"}  # a printer whose roll is counted
    config.update(lambda c: c.setdefault("printers", {}).update(test=pr))
    args = type("A", (), {"manual": False, "questions": False, "dry_run": False, "argv": ["chat"], "printer": "test",
                          "strict": False, "quiet": False, **kw})()  # fmt: skip
    conv = chat.Conversation(Fake(answers), ticket(), paper_left=lambda: 2500.0)
    ui = Screen(lines)
    return cli_chat.Session(args, conv, "test", pr, ui, 80), ui


def test_the_session_drives_any_screen():
    s, ui = _session(["hi", "/tickets", "/manual", "again", "p", "/questions on"], ["Hello.", "Again."])
    assert s.run() == 0
    kinds = [x[0] for x in ui.shown]
    assert kinds[0] == "welcome" and "wait" in kinds
    welcome = " ".join(ui.shown[0][1])
    assert "Fake AI" in welcome and "one strip" in welcome and "/tickets" in welcome and "10 cm" in welcome
    status = [x[1] for x in ui.shown if x[0] == "status"]
    assert "Fake · fake-1" in status[1] and "strip" in status[0] and "roll 2.5 m left" in status[0]
    assert "tickets" in status[-1] and "manual" in status[-1] and "questions printed" in status[-1]
    dims = [x[1] for x in ui.shown if x[0] == "dim"]
    assert any(d.startswith("printed on test") for d in dims) and "not printed yet: p prints it" in dims


def test_a_stopped_answer_leaves_no_trace():
    from bobina.cli import chat as cli_chat

    s, ui = _session(["hi"], ["One."])

    def stop(label, fn):
        raise cli_chat.Cancelled

    ui.wait = stop
    s.run()
    assert s.conv.messages == [] and ("note", "stopped: no answer (ask again, or another question)") in ui.shown


def test_the_terminal_screen_helpers():
    pytest.importorskip("prompt_toolkit")
    from prompt_toolkit.document import Document
    from prompt_toolkit.validation import ValidationError

    from bobina.cli import chat_tui

    lines = chat_tui.right_aligned("why is the sky blue and not green, if green is in the middle?", 40)
    assert all(len(x) == 39 for x in lines) and len(lines) >= 2
    got = [c.text for c in chat_tui.Commands().get_completions(Document("/q"), None)]
    assert got == ["/questions on", "/questions off", "/quit"]
    assert not list(chat_tui.Commands().get_completions(Document("hello"), None))
    s, _ = _session([], [], questions=True)
    chat_tui.Limit(s).validate(Document("short"))
    with pytest.raises(ValidationError):
        chat_tui.Limit(s).validate(Document("x" * 81))
    assert chat_tui.rich_text("a **b** c") == [("", "a "), ("bold", "b"), ("", " c")]


# --------------------------------------------------------------------------------------------- styles and icons


def test_icons_are_bundled_as_one_bit_bitmaps():
    from pathlib import Path

    from bobina import icons

    assert {"user-round", "sparkles", "bot"} <= set(icons.names())
    im = icons.load("sparkles", 24)
    assert im.mode == "1" and im.size == (24, 24) and 20 < im.convert("L").histogram()[0] < 400
    with pytest.raises(KeyError):
        icons.load("sparkles", 13)
    assert "ISC" in (Path(icons.__file__).parent / "licenses" / "Lucide-LICENSE.txt").read_text()


def _ink_x(im):
    return [x for y in range(im.height) for x in range(im.width) if im.getpixel((x, y)) == 0]


@pytest.mark.parametrize("style", chat.STYLES)
def test_each_style_keeps_the_person_right_and_the_ai_left(style):
    from bobina.rows import BitmapRow

    t = chat.Ticket(profiles.load("mtp-ii-58"), style=style)
    res = t.ticket("Air scatters blue light the most.", question="why is the sky blue?", who="Claude")
    images = [r.image for r in res.rows if isinstance(r, BitmapRow) and r.kind == "chat"]
    rules = [r for r in res.rows if isinstance(r, BitmapRow) and r.kind == "divider"]
    if style == "plain":
        assert not images
        return
    person, speaker = images[0], images[-1]
    xs = _ink_x(person)  # the bubble (across the paper in bubbles) or the "you" line: ending at the right edge
    full = style in ("bubbles", "labels-bubble")
    assert (min(xs) <= 2 if full else min(xs) > person.width // 6) and max(xs) >= person.width - 8
    xs = _ink_x(speaker)  # the AI: its icon and name on the left
    assert min(xs) <= 2 and max(xs) < speaker.width * 2 // 3
    want = {"labels-ruled": 2, "labels-underlined": 2, "labels-exchange": 1}.get(style, 0)
    assert len(rules) == want, style


def test_the_rules_between_exchanges():
    from bobina.rows import BitmapRow

    t = chat.Ticket(profiles.load("mtp-ii-58"), style="labels-exchange")
    res = t.ticket("Ok.", question="and then?", who="Claude", separator=True)
    rules = [r.image for r in res.rows if isinstance(r, BitmapRow) and r.kind == "divider"]
    assert len(rules) == 2 and rules[0].height > rules[1].height  # a double rule, then a dashed one


def test_bubbles_are_white_on_black():
    from bobina.rows import BitmapRow

    t = chat.Ticket(profiles.load("mtp-ii-58"), style="bubbles")
    res = t.ticket("Ok.", question="hello there", who="Claude")
    bubble = next(r for r in res.rows if isinstance(r, BitmapRow)).image
    ink = bubble.convert("L").histogram()[0] / (bubble.width * bubble.height)
    assert 0.5 < ink < 0.97  # a black bubble with white letters, not a thin frame
    xs = [x for x in range(bubble.width) if bubble.getpixel((x, bubble.height // 2)) == 1]
    assert min(xs) > bubble.width // 2  # the white letters on the right of the bubble


def test_the_roll_left_or_how_to_set_it():
    s, ui = _session([], [])
    s.conv.paper_left = lambda: None
    assert s.status().endswith("roll ?")
    assert "bobina paper new 30m" in " ".join(s.welcome())
    s.conv.paper_left = lambda: 7400.0
    assert s.status().endswith("roll 7.4 m left") and "roll: 7.4 m left" in s.welcome()
    s.counts = False  # a file printer: no roll
    assert "roll" not in s.status()


# ------------------------------------------------------------------------------- one question, no screen (way 2)


def test_one_question_shows_the_answer_and_prints_only_with_yes(monkeypatch, capsys, printer):
    code, o = ask_once(monkeypatch, capsys, Fake(["The sky is **blue**."]), "why", "blue?")
    assert code == 0 and o.out == "The sky is blue.\n"
    assert "not printed: ~" in o.err and "add --yes to print" in o.err and not printer.exists()
    code, o = ask_once(monkeypatch, capsys, Fake(["Blue."]), "why blue?", "--yes")
    assert code == 0 and o.out == "Blue.\n" and "printed on test: ~" in o.err and printer.read_bytes()
    rows = [json.loads(x) for x in (config.paths.state_dir() / "history.jsonl").read_text().splitlines()]
    assert rows[-1]["outcome"] == "printed"


def test_one_question_from_stdin_and_json(monkeypatch, capsys, printer):
    code, o = ask_once(monkeypatch, capsys, Fake(["Blue."]), "--json", "--yes", stdin="why is the sky blue?\n")
    doc = json.loads(o.out)
    assert code == 0 and doc["question"] == "why is the sky blue?" and doc["answer"] == "Blue."
    assert doc["printed"] is True and doc["printer"] == "test" and doc["paper_mm"] > 10 and doc["ai"] == "fake"
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("schemas", Path(__file__).with_name("test_schemas.py"))
    schemas = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(schemas)
    schemas._check(doc, schemas._schema("chat"))  # the same checker as the other schemas


def test_one_question_contradictions_are_said(monkeypatch, capsys, printer):
    code, o = ask_once(monkeypatch, capsys, Fake(["Blue."]), "q?", "--dry-run", "--yes", "--manual")
    assert code == 0 and "--dry-run wins over --yes" in o.err and "--manual does nothing with one question" in o.err
    assert "not printed (--dry-run): ~" in o.err and not printer.exists()
    code, o = ask_once(monkeypatch, capsys, Fake(["Blue."]), "q?", stdin="other question\n")
    assert "the text on stdin was not read" in o.err


def test_one_question_failures_and_their_exit_codes(monkeypatch, capsys):
    code, o = ask_once(monkeypatch, capsys, Fake(["Blue."]), "q?", "--yes")
    assert code == 4 and o.out == "Blue.\n" and "E401" in o.err  # no printer: the answer shown, nothing printed
    config.update(lambda c: c.setdefault("printers", {}).update(gone={"transport": "command", "command": "false"}))
    code, o = ask_once(monkeypatch, capsys, Fake(["Blue."]), "q?", "--yes", "--printer", "gone")
    assert code == 4 and "E402" in o.err and "Blue." in o.out
    code, o = ask_once(monkeypatch, capsys, Fake([ai.AIError("Claude Code failed: Not logged in", "log in")]), "q?")
    assert code == 4 and "E602" in o.err and "Not logged in" in o.err and o.out == ""
    code, o = ask_once(monkeypatch, capsys, Fake(["x"]), "")
    assert code == 1 and "an empty question" in o.err
    code, o = ask_once(monkeypatch, capsys, Fake(["x"]), "q?", "--printer", "nope", "--yes")
    assert code == 4 and "unknown printer 'nope'" in o.err


def test_one_printed_question_over_its_limit_is_refused(monkeypatch, capsys, printer):
    fake = Fake(["Blue."])
    code, o = ask_once(monkeypatch, capsys, fake, "why " * 40, "--questions", "--yes")
    assert code == 1 and "too long to print: 159/" in o.err and not fake.calls  # never sent, never cut
    code, o = ask_once(monkeypatch, capsys, fake, "why " * 40, "--questions")  # nothing prints: no limit
    assert code == 0 and fake.calls


def test_ctrl_c_while_one_question_waits(monkeypatch, capsys):
    stopped = []
    monkeypatch.setattr(ai, "cancel", lambda: stopped.append(True))
    code, o = ask_once(monkeypatch, capsys, Fake([KeyboardInterrupt()]), "q?")
    assert code == 130 and stopped


def test_the_screen_needs_a_terminal(monkeypatch, capsys):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    fake_ai(monkeypatch, Fake([]))
    monkeypatch.setattr(sys, "stdin", Tty(""))
    monkeypatch.setenv("BOBINA_NONINTERACTIVE", "1")
    assert main(["chat"]) == 7
    e = capsys.readouterr().err
    assert "E107" in e and 'bobina chat "QUESTION"' in e


def test_json_in_the_screen_is_a_note(monkeypatch, capsys, printer):
    code, o = run_chat(monkeypatch, capsys, Fake([]), [], "--json")
    assert code == 0 and "--json does nothing in the chat screen" in o.err


# ---------------------------------------------------------------------------------------------- --limit, values


@pytest.mark.parametrize(
    "value,mm",
    [("10cm", 100), ("100mm", 100), ("0.1m", 100), ("10in", 254), ('4"', 101.6), ("10 inches", 254), ("1ft", 304.8),
     ("2 1/2in", 63.5), ("1,5cm", 15)],
)  # fmt: skip
def test_limit_units(value, mm):
    from bobina.cli import chat as cli_chat

    args = type("A", (), {"limit": value})()
    assert cli_chat._limit(args, {}, None) == pytest.approx(mm)


@pytest.mark.parametrize(
    "value,said",
    [("0", "more than 0"), ("0cm", "more than 0"), ("-5cm", "more than 0"), ("1km", "use 15m"),
     ("1cm", "at least 1.5cm"), ("ten cm", "use 15m")],
)  # fmt: skip
def test_limit_mistakes_are_refused_clearly(value, said):
    from bobina.cli import chat as cli_chat
    from bobina.cli.common import Fail

    args = type("A", (), {"limit": value})()
    with pytest.raises(Fail) as e:
        cli_chat._limit(args, {}, None)
    assert said in str(e.value) and e.value.problem == "E304"


def test_a_huge_limit_is_capped_and_the_roll_is_said(capsys):
    from bobina.cli import chat as cli_chat

    assert cli_chat._limit(type("A", (), {"limit": "10m"})(), {}, None) == 1000
    assert "capped at 1m" in capsys.readouterr().err
    assert cli_chat._limit(type("A", (), {"limit": "50cm"})(), {}, 300.0) == 500
    assert "the roll has ~30 cm left" in capsys.readouterr().err


def test_a_bare_number_is_centimetres_with_a_note(monkeypatch, capsys, printer):
    code, o = ask_once(monkeypatch, capsys, Fake(["x"]), "q?", "--limit", "10")
    assert code == 0 and "--limit 10: read as 10cm; give a unit to be sure" in o.err
    from bobina.cli import chat as cli_chat

    assert cli_chat._limit(type("A", (), {"limit": None})(), {"chat_limit": 6}, None) == 60  # a TOML number
    assert "chat_limit = 6 in config.toml: read as 6cm" in capsys.readouterr().err


def test_limit_from_the_command_line(monkeypatch, capsys, printer):
    code, o = ask_once(monkeypatch, capsys, Fake(["x"]), "q?", "--limit=-5cm")
    assert code == 1 and "more than 0" in o.err


@pytest.mark.parametrize(
    "argv,want",
    [(["--layout", "ticket"], None), (["--layout", "continuous"], None), (["--style", "c1"], None),
     (["--style", "bubble"], None), (["--layout", "tickts"], "did you mean tickets?"),
     (["--style", "lables"], "did you mean labels?"), (["--layout", "xyz"], "strip, tickets"),
     (["--style", "zzz"], "labels-underline, labels-dashes, labels-dots")],
)  # fmt: skip
def test_layout_and_style_values(monkeypatch, capsys, argv, want):
    if want is None:
        code, o = ask_once(monkeypatch, capsys, Fake(["x"]), "q?", *argv)
        assert code == 0
        return
    with pytest.raises(SystemExit) as e:
        main(["chat", "q?", *argv])
    assert e.value.code == 1 and want in capsys.readouterr().err


def test_a_bad_setting_in_config_lists_the_valid_ones(monkeypatch, capsys):
    config.set_value("chat_layout", "roll")
    code, o = ask_once(monkeypatch, capsys, Fake(["x"]), "q?")
    assert code == 1 and "chat_layout = 'roll' in config.toml: use strip, tickets" in o.err


def test_config_defaults_apply_and_options_win(monkeypatch, capsys, printer):
    config.set_value("chat_questions", True)
    config.set_value("chat_style", "labels-ruled")
    code, o = ask_once(monkeypatch, capsys, Fake(["Blue."]), "my question?", "--yes")
    assert code == 0 and b"my question?" in printer.read_bytes()  # chat_questions = true


# ---------------------------------------------------------------------------------------------- p, /again, /say


def test_print_again_and_say(monkeypatch, capsys, printer):
    fake = Fake(["One.", "Two."])
    code, o = run_chat(monkeypatch, capsys, fake, ["a?", "p", "/again", "/say p"])
    out = o.out
    assert "already printed (~" in out and "/again prints another copy" in out
    assert out.count("printed on test") == 3  # the answer, the copy, and the answer to "p"
    assert [m["content"] for m in fake.calls[1][1]][-1] == "p"


def test_p_retries_a_failed_print(monkeypatch, capsys, tmp_path):
    out = tmp_path / "later.bin"
    config.update(lambda c: c.setdefault("printers", {}).update(flaky={"transport": "command", "command": "false"}))
    config.set_value("default_printer", "flaky")

    def fix_it(line_after):
        config.update(lambda c: c["printers"].update(flaky={"transport": "command", "command": f"tee -a {out}"}))

    from bobina.cli import chat as cli_chat

    real = cli_chat.Session.command

    def command(self, line):
        if line == "p":
            fix_it(line)
        return real(self, line)

    monkeypatch.setattr(cli_chat.Session, "command", command)
    code, o = run_chat(monkeypatch, capsys, Fake(["One."]), ["a?", "p"])
    assert "not printed:" in o.out and "p tries this answer again" in o.out and "printed on flaky" in o.out
    assert out.read_bytes()


# ------------------------------------------------------------------------------------------------- review fixes


def test_the_api_version_is_the_documented_one():
    """The claude-api skill (curl/examples.md, "Basic Message Request") documents the raw HTTP header as
    -H "anthropic-version: 2026-10-21" for POST /v1/messages; this is that value, written out here on purpose."""
    assert ai.ANTHROPIC_VERSION == "2026-10-21"


def test_one_question_reports_problems_as_print(monkeypatch, capsys, printer):
    arrows = "Go → there, ← back."  # F301: printed as an image (a note)
    long_word = "Antidisestablishmentarianism" * 2  # L101: a word longer than the line (a warning)
    code, o = ask_once(monkeypatch, capsys, Fake([long_word]), "q?", "--yes", "--strict")
    assert code == 3 and "nothing printed (--strict)" in o.err and not printer.exists()
    code, o = ask_once(monkeypatch, capsys, Fake([arrows]), "q?", "--yes", "--problems", "jsonl")
    lines = [json.loads(x) for x in o.err.splitlines() if x.startswith("{")]
    assert code == 0 and lines and lines[0]["code"] == "F301" and lines[0]["outcome"] == "printing anyway (--yes)"
    code, o = ask_once(monkeypatch, capsys, Fake([arrows]), "q?", "--yes", "-q")
    assert code == 0 and o.err == "" and o.out.startswith("Go")


def test_the_chat_screen_reports_problems_with_the_shared_renderer(monkeypatch, capsys, printer):
    code, o = run_chat(monkeypatch, capsys, Fake(["Go → there."]), ["a?"])
    assert "1 note — printing anyway" in o.out and "· note    [F301]" in o.out
    code, o = run_chat(monkeypatch, capsys, Fake(["Antidisestablishmentarianism" * 2]), ["a?"], "--strict")
    assert "not printed (--strict)" in o.out and o.out.count("printed on test") == 0


def test_a_pipe_that_never_brings_a_question(monkeypatch, capsys):
    import os

    from bobina.cli import chat as cli_chat

    fake_ai(monkeypatch, Fake([]))
    monkeypatch.setattr(cli_chat, "STDIN_WAIT_S", 0.1)
    r, w = os.pipe()  # the writer stays open: nothing comes, nothing ends
    monkeypatch.setattr(sys, "stdin", open(r, encoding="utf-8"))  # noqa: SIM115
    try:
        assert main(["chat"]) == 7
    finally:
        os.close(w)
    assert "E107" in capsys.readouterr().err


def test_stdin_is_looked_at_without_reading_it(monkeypatch, capsys):
    import os

    from bobina.cli import chat as cli_chat

    r, w = os.pipe()
    os.write(w, b"other question")
    monkeypatch.setattr(sys, "stdin", open(r, encoding="utf-8"))  # noqa: SIM115
    assert cli_chat._stdin_waiting()
    assert sys.stdin.read(5) == "other"  # nothing was taken from it
    os.close(w)


def test_one_question_says_strip_means_nothing(monkeypatch, capsys):
    code, o = ask_once(monkeypatch, capsys, Fake(["x"]), "q?", "--layout", "strip")
    assert code == 0 and "a single answer is always one ticket" in o.err


def test_say_alone_says_what_it_is(monkeypatch, capsys, printer):
    fake = Fake([])
    code, o = run_chat(monkeypatch, capsys, fake, ["/say", "/say   "])
    assert o.out.count("/say TEXT sends TEXT to the AI as it is") == 2 and not fake.calls


# ---------------------------------------------------------------------------------- the D set and the name


def test_the_name_replaces_you_on_paper(monkeypatch, capsys, printer):
    code, o = ask_once(monkeypatch, capsys, Fake(["Blue."]), "q?", "--questions", "--yes", "--name", "Ana")
    assert code == 0
    config.set_value("chat_name", "Ana Maria")
    from bobina.cli import chat as cli_chat

    args = type("A", (), {"name": None})()
    assert cli_chat._name(args, config.load()) == "Ana Maria"
    assert cli_chat._name(type("A", (), {"name": "  "})(), {}) == "you"
    assert cli_chat._name(type("A", (), {"name": "x" * 30})(), {}) == "x" * 20
    assert "is long for one line" in capsys.readouterr().err


def _ink_box(im):
    from PIL import ImageOps

    return ImageOps.invert(im.convert("L")).getbbox()


@pytest.mark.parametrize("style", ["labels-underline", "labels-dashes", "labels-hook"])
def test_short_marks_stay_by_their_speaker(style):
    """Never a rule across the paper: the mark under a name is about as wide as the icon and the name."""
    from bobina.rows import BitmapRow

    t = chat.Ticket(profiles.load("mtp-ii-58"), style=style, name="Ana")
    res = t.ticket("Ok.", question="hi?", who="Claude")
    person, ai_line = [r.image for r in res.rows if isinstance(r, BitmapRow) and r.kind == "chat"]
    w = person.width
    x0, _, x1, _ = _ink_box(person.crop((0, 26, w, person.height)))  # below the icon and the name
    assert x1 >= w - 2 and x1 - x0 < w // 2  # on the right, short
    x0, _, x1, _ = _ink_box(ai_line.crop((0, 26, w, ai_line.height)))
    assert x0 <= 1 and x1 - x0 < w // 2  # on the left, short


@pytest.mark.parametrize("style", ["labels-dots", "labels-hook"])
def test_between_exchanges_a_small_mark_in_the_middle(style):
    from bobina.rows import BitmapRow

    t = chat.Ticket(profiles.load("mtp-ii-58"), style=style)
    res = t.ticket("Ok.", question="and then?", who="Claude", separator=True)
    mark = next(r.image for r in res.rows if isinstance(r, BitmapRow) and r.kind == "divider")
    x0, _, x1, _ = _ink_box(mark)
    assert x0 > mark.width // 4 and x1 < mark.width * 3 // 4  # centred, short


def test_the_outlined_bubble_has_the_name_above_it():
    from bobina.rows import BitmapRow

    t = chat.Ticket(profiles.load("mtp-ii-58"), style="labels-outline", name="Ana")
    res = t.ticket("Ok.", question="hello there", who="Claude")
    name_line, bubble, _ai = [r.image for r in res.rows if isinstance(r, BitmapRow) and r.kind == "chat"]
    ink = bubble.convert("L").histogram()[0] / (bubble.width * bubble.height)
    assert ink < 0.25  # a thin frame, white inside
    x0, _, x1, _ = _ink_box(bubble)
    assert x1 >= bubble.width - 2 and x0 > bubble.width // 3  # fitted to the text, on the right
