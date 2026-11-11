"""The AIs bobina chat talks to, and how they are found on this machine.

Order of preference (decided 11/11): AI programs already logged in (Claude Code, Codex, Gemini CLI: called
non-interactively with their own login, no keys), then a local model (Ollama on localhost), then an API key in the
environment (ANTHROPIC_API_KEY, OPENAI_API_KEY; their SDKs are the extra bobina[ai], never a hard dependency).
The choice lives in config.toml: ai = "NAME", ai_model = "MODEL" ("" or absent: the AI's own default)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ORDER = ("claude", "codex", "gemini", "ollama", "anthropic", "openai")
TIMEOUT_S = 300  # a CLI that starts, thinks and answers; a short chat answer takes seconds
EXTRA = "pip install 'bobina[ai]' (or: uv tool install 'bobina[ai]')"


class AIError(Exception):
    """The AI did not answer: what happened, and what to do (hint)."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


@dataclass
class Reply:
    text: str
    model: str | None = None  # the model that answered, as the AI names it (claude-opus-5-5, llama3.2:3b)


@dataclass
class Found:
    """One AI and whether this machine has it."""

    name: str
    label: str
    available: bool
    detail: str = ""  # how it is reached (the program's path, the host, the variable)
    needs: str = ""  # what to install or set (when not available or not ready)
    ready: bool = True  # available and usable now (an API key without its SDK is available, not ready)
    models: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.ready = self.ready and self.available

    def as_dict(self) -> dict:
        return {"name": self.name, "label": self.label, "available": self.available, "ready": self.ready,
                "detail": self.detail, "needs": self.needs, "models": self.models}  # fmt: skip


# ---------------------------------------------------------------------------------------------------------- names


def model_label(model: str | None) -> str:
    """claude-opus-5-5 -> Opus 5.5, claude-sonnet-4-5-20250929 -> Sonnet 4.5, gpt-5 -> GPT-5,
    gemini-2.5-pro -> 2.5 Pro; anything else as it is."""
    if not model:
        return ""
    m = re.fullmatch(r"(?:anthropic\.)?claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?(?:\[.*\])?", model)
    if m:
        return f"{m.group(1).title()} {m.group(2)}" + (f".{m.group(3)}" if m.group(3) else "")
    if model in ("opus", "sonnet", "haiku", "fable"):
        return model.title()
    m = re.fullmatch(r"gemini-(.+)", model)
    if m:
        return " ".join(w if re.match(r"\d", w) else w.title() for w in m.group(1).split("-"))
    if model.lower().startswith("gpt"):
        return "GPT" + model[3:]
    return model


def header(vendor: str, model: str | None) -> str:
    """The first line of the printed ticket: "Claude · Opus 5.5" (the AI alone when the model is unknown)."""
    label = model_label(model)
    return f"{vendor} · {label}" if label else vendor


# -------------------------------------------------------------------------------------------------------- prompts


def transcript(system: str | None, messages: list[dict]) -> str:
    """One prompt for a program that takes a single text: the instructions, the conversation so far, the question."""
    lines = []
    if system:
        lines += ["<instructions>", system, "</instructions>", ""]
    if len(messages) > 1:
        lines.append("The conversation so far:")
        for m in messages[:-1]:
            who = "Person" if m["role"] == "user" else "You"
            lines.append(f"{who}: {m['content']}")
        lines.append("")
    lines.append("Answer this message from the person (only the answer, nothing before or after it):")
    lines.append(messages[-1]["content"])
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------------- backends


class Backend:
    name = ""
    label = ""  # what it is: "Claude Code"
    vendor = ""  # the first word of the ticket header: "Claude"

    def __init__(self, model: str | None = None):
        self.model = model or None

    def ask(self, system: str, messages: list[dict]) -> Reply:
        raise NotImplementedError


_PROCS: set = set()  # AI programs running now: cancel() stops them (Esc or Ctrl-C in the chat)


def cancel() -> None:
    """Stops the AI programs this process started and that are still answering."""
    for p in list(_PROCS):
        try:
            p.kill()
        except OSError:
            pass


def _exec(cmd: list[str], input_text: str, cwd: str) -> tuple[int, str, str]:
    """Runs a program with input on stdin; (exit code, stdout, stderr). Killed by cancel() or after TIMEOUT_S."""
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                         text=True, encoding="utf-8", errors="replace")  # fmt: skip
    _PROCS.add(p)
    try:
        out, errs = p.communicate(input_text, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        raise
    finally:
        _PROCS.discard(p)
    return p.returncode, out or "", errs or ""


def program(name: str) -> str | None:
    """The path of an AI program; on Windows the .cmd shim npm installs (subprocess does not try PATHEXT)."""
    return shutil.which(name)


def _run(cmd: list[str], *, input_text: str, what: str, cwd: str) -> tuple[int, str, str]:
    """Runs an AI program in an empty folder (no project files or instructions of the current folder reach it)."""
    path = program(cmd[0])
    if not path:
        raise AIError(f"{what} is not installed here ({cmd[0]} not found)", "bobina ai list shows what is")
    try:
        return _exec([path, *cmd[1:]], input_text, cwd)
    except FileNotFoundError:
        raise AIError(f"{what} is not installed here ({cmd[0]} not found)", "bobina ai list shows what is") from None
    except subprocess.TimeoutExpired:
        raise AIError(f"{what} did not answer in {TIMEOUT_S} s", "ask again, or a shorter question") from None
    except OSError as e:
        raise AIError(f"cannot run {cmd[0]}: {e.strerror or e}") from None


LOGIN = re.compile(r"log ?in|/login|auth|credential|api key|unauthori", re.I)


def _failed(what: str, code: int, why: str, login_hint: str) -> AIError:
    lines = [x for x in why.strip().splitlines() if x.strip()]
    why = lines[-1][:300] if lines else f"exit {code}"
    return AIError(f"{what} failed: {why}", login_hint if LOGIN.search(why) else "")


# Claude Code with nothing of the user's setup: no settings, hooks, plugins, CLAUDE.md, MCP servers, slash commands
# or tools, and no session saved. A chat turn only answers; it changes nothing.
CLAUDE_FLAGS = ["-p", "--output-format", "json", "--tools", "", "--safe-mode", "--setting-sources", "",
                "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"]  # fmt: skip


class ClaudeCode(Backend):
    name, label, vendor = "claude", "Claude Code", "Claude"
    login = "run claude once in a terminal and log in (/login)"

    def ask(self, system: str, messages: list[dict]) -> Reply:
        cmd = ["claude", *CLAUDE_FLAGS, "--system-prompt", system] + (["--model", self.model] if self.model else [])
        with tempfile.TemporaryDirectory(prefix="bobina-chat-") as cwd:
            code, out, errs = _run(cmd, input_text=transcript(None, messages), what="Claude Code", cwd=cwd)
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):  # not the JSON result: its words, or the error it wrote
            if code:
                raise _failed("Claude Code", code, errs or out, self.login)
            return Reply(out.strip(), self.model)
        if code or data.get("is_error"):  # the reason is in the result, also when it exits with an error
            why = str(data.get("result") or "").strip() or (errs.strip().splitlines() or [""])[-1]
            why = why or str(data.get("terminal_reason") or data.get("subtype") or f"exit {code}")
            raise AIError(f"Claude Code failed: {why[:300]}", self.login if LOGIN.search(why) else "")
        usage = data.get("modelUsage") or {}
        model = max(usage, key=lambda k: (usage[k] or {}).get("outputTokens", 0)) if usage else self.model
        return Reply(str(data.get("result") or ""), model)


def _codex_model() -> str | None:
    try:
        import tomllib

        cfg = tomllib.loads((Path.home() / ".codex" / "config.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cfg.get("model") if isinstance(cfg.get("model"), str) else None


# Codex with no tool that reaches the machine: no shell, no image viewer, no web search, no sub-agents, no MCP
# servers, a read-only sandbox, nothing saved (keys from its config reference).
CODEX_FLAGS = ["exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never",
               "-c", "features.shell_tool=false", "-c", "features.unified_exec=false",
               "-c", "features.view_image=false", "-c", "tools.web_search=false", "-c", "features.multi_agent=false",
               "-c", "mcp_servers={}"]  # fmt: skip


class Codex(Backend):
    name, label, vendor = "codex", "Codex CLI", "Codex"

    def ask(self, system: str, messages: list[dict]) -> Reply:
        with tempfile.TemporaryDirectory(prefix="bobina-chat-") as cwd:
            last = Path(cwd) / ".answer.txt"
            cmd = ["codex", *CODEX_FLAGS, "--output-last-message", str(last)]
            cmd += (["--model", self.model] if self.model else []) + ["-"]  # -: the whole prompt from stdin
            code, out, errs = _run(cmd, input_text=transcript(system, messages), what="Codex", cwd=cwd)
            if code:
                raise _failed("Codex", code, errs or out, "run: codex login")
            text = last.read_text(encoding="utf-8").strip() if last.exists() else out.strip()
        return Reply(text, self.model or _codex_model())


# Gemini CLI with every tool denied (built-in and MCP: a deny-all policy given with --admin-policy, so the model
# does not even see them) and no extensions.
GEMINI_POLICY = '[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 999\n'


class Gemini(Backend):
    name, label, vendor = "gemini", "Gemini CLI", "Gemini"

    def ask(self, system: str, messages: list[dict]) -> Reply:
        with tempfile.TemporaryDirectory(prefix="bobina-chat-") as cwd:
            policy = Path(cwd) / ".no-tools.toml"
            policy.write_text(GEMINI_POLICY, encoding="utf-8")
            cmd = ["gemini", "--admin-policy", str(policy), "--extensions", "none", "--approval-mode", "default"]
            cmd += (["--model", self.model] if self.model else []) + ["--prompt", "Answer the last message above."]
            code, out, errs = _run(cmd, input_text=transcript(system, messages), what="Gemini CLI", cwd=cwd)
        if code:
            raise _failed("Gemini CLI", code, errs or out, "run gemini once in a terminal and log in")
        return Reply(out.strip(), self.model)


def _http(method: str, url: str, body: dict | None = None, timeout: float = TIMEOUT_S) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - a local Ollama, http by design
        return json.loads(resp.read().decode("utf-8"))


OLLAMA_PORT = 11434


def ollama_host(value: str | None = None) -> str:
    """OLLAMA_HOST as a URL: a scheme and the port 11434 added when missing; 0.0.0.0 (or ::), where a server
    listens on every address, is reached on loopback. 'localhost', '[::1]:11434', 'https://box' all work."""
    raw = (os.environ.get("OLLAMA_HOST", "") if value is None else value).strip() or "127.0.0.1"
    scheme, sep, rest = raw.partition("://")
    if not sep:
        scheme, rest = "http", raw
    hostport, _, path = rest.partition("/")
    if hostport.startswith("["):  # [IPv6]:port
        host, _, port = hostport[1:].partition("]")
        port = port.lstrip(":")
    elif hostport.count(":") > 1:  # a bare IPv6 address
        host, port = hostport, ""
    else:
        host, _, port = hostport.partition(":")
    host = {"0.0.0.0": "127.0.0.1", "::": "::1", "": "127.0.0.1"}.get(host, host)
    if not port:
        port = str(OLLAMA_PORT) if scheme == "http" else ""
    shown = f"[{host}]" if ":" in host else host
    return f"{scheme}://{shown}" + (f":{port}" if port else "") + (f"/{path.rstrip('/')}" if path.strip("/") else "")


EMBEDDING = re.compile(r"embed|bge-|e5-|minilm|nomic-embed|mxbai|snowflake-arctic-embed|granite-embedding", re.I)


def ollama_models(timeout: float = 0.5) -> list[str] | None:
    """The chat models of a local Ollama (embedding-only models left out), or None when none answers."""
    try:
        tags = _http("GET", ollama_host() + "/api/tags", timeout=timeout)
    except (OSError, ValueError, urllib.error.URLError):
        return None
    names = [str(m.get("name")) for m in tags.get("models") or [] if m.get("name")]
    return [n for n in names if not EMBEDDING.search(n)]


def _can_chat(model: str) -> bool:
    """/api/show capabilities ("completion" for a model that writes text); True when Ollama does not say."""
    try:
        caps = _http("POST", ollama_host() + "/api/show", {"model": model}, timeout=5).get("capabilities")
    except (OSError, ValueError, urllib.error.URLError):
        return True
    return not isinstance(caps, list) or "completion" in caps


class Ollama(Backend):
    name, label, vendor = "ollama", "Ollama (local)", "Ollama"

    def ask(self, system: str, messages: list[dict]) -> Reply:
        model = self.model
        if not model:
            models = ollama_models()
            if models is None:
                raise AIError(f"Ollama is not answering at {ollama_host()}", "start it: ollama serve")
            model = next((m for m in models if _can_chat(m)), None)
            if not model:
                raise AIError("Ollama has no chat model yet", "ollama pull llama3.2, then ask again")
            self.model = model
        body = {"model": model, "stream": False, "messages": [{"role": "system", "content": system}, *messages]}
        try:
            out = _http("POST", ollama_host() + "/api/chat", body)
        except urllib.error.HTTPError as e:
            said = ""
            try:
                said = json.loads(e.read().decode("utf-8", "replace")).get("error", "")
            except (OSError, ValueError, AttributeError):
                pass
            hint = f"ollama pull {model}" if e.code == 404 else "bobina ai use ollama --model NAME (ollama list)"
            raise AIError(f"Ollama refused {model}: {said or f'{e.code} {e.reason}'}", hint) from None
        except (OSError, ValueError, urllib.error.URLError) as e:
            raise AIError(f"Ollama is not answering at {ollama_host()}: {e}", "start it: ollama serve") from None
        return Reply(str((out.get("message") or {}).get("content") or ""), out.get("model") or model)


ANTHROPIC_DEFAULT = "claude-opus-5-5"
# models that take output_config.effort and server-side fallbacks on a refusal (others: a plain request)
ANTHROPIC_CURRENT = {"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class AnthropicAPI(Backend):
    name, label, vendor = "anthropic", "Claude API (ANTHROPIC_API_KEY)", "Claude"

    def ask(self, system: str, messages: list[dict]) -> Reply:
        try:
            import anthropic
        except ImportError:
            raise AIError("the Anthropic SDK is not installed", EXTRA) from None
        model = self.model or ANTHROPIC_DEFAULT
        client = anthropic.Anthropic()
        kw: dict = {"model": model, "max_tokens": 16000, "system": system, "messages": messages}
        try:
            if model in ANTHROPIC_CURRENT:  # a chat answer: low effort; a refusal falls back on the server
                r = client.beta.messages.create(
                    **kw,
                    output_config={"effort": "low"},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            else:
                r = client.messages.create(**kw)
        except anthropic.AuthenticationError:
            raise AIError("the Anthropic API refused ANTHROPIC_API_KEY", "check the key, or unset it") from None
        except anthropic.NotFoundError:
            raise AIError(f"the Anthropic API does not know the model {model}", "bobina ai use anthropic --model "
                          + ANTHROPIC_DEFAULT) from None  # fmt: skip
        except anthropic.RateLimitError:
            raise AIError("the Anthropic API is rate limiting this key", "wait a little and ask again") from None
        except anthropic.APIStatusError as e:
            raise AIError(f"the Anthropic API failed ({e.status_code}): {e.message}") from None
        except anthropic.APIConnectionError:
            raise AIError("cannot reach the Anthropic API", "check the network") from None
        if r.stop_reason == "refusal":
            raise AIError("Claude declined to answer that", "ask it another way")
        text = "".join(b.text for b in r.content if b.type == "text")
        return Reply(text, getattr(r, "model", None) or model)


OPENAI_DEFAULT = "gpt-5"


class OpenAIAPI(Backend):
    name, label, vendor = "openai", "OpenAI API (OPENAI_API_KEY)", "OpenAI"

    def ask(self, system: str, messages: list[dict]) -> Reply:
        try:
            import openai
        except ImportError:
            raise AIError("the OpenAI SDK is not installed", EXTRA) from None
        model = self.model or OPENAI_DEFAULT
        try:
            r = openai.OpenAI().chat.completions.create(
                model=model, messages=[{"role": "system", "content": system}, *messages]
            )
        except openai.AuthenticationError:
            raise AIError("the OpenAI API refused OPENAI_API_KEY", "check the key, or unset it") from None
        except openai.APIStatusError as e:
            raise AIError(f"the OpenAI API failed ({e.status_code}): {e.message}") from None
        except openai.APIConnectionError:
            raise AIError("cannot reach the OpenAI API", "check the network") from None
        return Reply(r.choices[0].message.content or "", getattr(r, "model", None) or model)


BACKENDS: dict[str, type[Backend]] = {
    b.name: b for b in (ClaudeCode, Codex, Gemini, Ollama, AnthropicAPI, OpenAIAPI)
}  # fmt: skip


def backend(name: str, model: str | None = None) -> Backend:
    return BACKENDS[name](model)


# ------------------------------------------------------------------------------------------------------ detection

INSTALL = {
    "claude": "install Claude Code (https://claude.com/claude-code), then run claude once to log in",
    "codex": "npm install -g @openai/codex, then codex login",
    "gemini": "npm install -g @google/gemini-cli, then run gemini once to log in",
    "ollama": "install Ollama (https://ollama.com), then ollama pull llama3.2",
    "anthropic": "export ANTHROPIC_API_KEY=… and " + EXTRA,
    "openai": "export OPENAI_API_KEY=… and " + EXTRA,
}


def _sdk(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None


def detect() -> list[Found]:
    """Every AI bobina knows, in the order of preference, with what this machine has of each."""
    out = []
    for name, cls in (("claude", ClaudeCode), ("codex", Codex), ("gemini", Gemini)):
        path = program(name)
        out.append(Found(name, cls.label, bool(path), f"{path} (its own login)" if path else "", INSTALL[name]))
    models = ollama_models()
    detail = f"{ollama_host()}: " + (", ".join(models[:4]) or "no model pulled yet") if models is not None else ""
    out.append(Found("ollama", Ollama.label, models is not None, detail,
                     INSTALL["ollama"] if not models else "", ready=bool(models), models=models or []))  # fmt: skip
    for name, var, module in (("anthropic", "ANTHROPIC_API_KEY", "anthropic"), ("openai", "OPENAI_API_KEY", "openai")):
        has_key, has_sdk = bool(os.environ.get(var, "").strip()), _sdk(module)
        needs = INSTALL[name] if not has_key else ("" if has_sdk else EXTRA)
        out.append(Found(name, BACKENDS[name].label, has_key, f"{var} is set" if has_key else "", needs,
                         ready=has_key and has_sdk))  # fmt: skip
    return out


def none_found_hint() -> str:
    return "any one of these works:\n" + "\n".join(f"  {n:9s} {INSTALL[n]}" for n in ORDER)
