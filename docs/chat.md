# Chat with an AI on paper (`bobina chat`, `bobina ai`)

`bobina chat` is a conversation in the terminal: you type, an AI answers, and each answer also prints on the
roll. Everything shows in the terminal too.

```bash
bobina chat                      # the first time, it asks which AI (and saves the choice)
bobina chat --questions          # print your messages too, on the right; the answers stay on the left
bobina chat --layout tickets     # one ticket per answer, to tear off
bobina chat --style bubbles      # how the two speakers look on paper
bobina chat --manual             # print only when you type p
bobina chat --dry-run            # nothing prints; the paper each answer would take is shown
```

## Which AI (`bobina ai`)

`bobina ai list` shows what this machine already has, best first, and `bobina ai use NAME [--model MODEL]`
saves the choice in config.toml (`ai`, `ai_model`); `bobina chat --ai NAME --model MODEL` overrides it for one
chat. `bobina ai list --json` has every AI, found or not, and what each one needs.

| NAME | What | Needs |
|---|---|---|
| `claude` | Claude Code, called with its own login | the `claude` program, logged in once |
| `codex` | Codex CLI, with its own login | `codex login` |
| `gemini` | Gemini CLI, with its own login | `gemini`, logged in once |
| `ollama` | a local chat model through Ollama (`OLLAMA_HOST`; embedding models are skipped) | `ollama pull llama3.2` |
| `anthropic` | the Claude API (default model `claude-opus-5-5`) | `ANTHROPIC_API_KEY` and `pip install 'bobina[ai]'` |
| `openai` | the OpenAI API (default model `gpt-5`) | `OPENAI_API_KEY` and `pip install 'bobina[ai]'` |

AI programs only answer: they run in an empty folder, with the conversation on stdin and nothing that reaches the
machine. Claude Code runs without tools and without your settings, hooks, plugins, CLAUDE.md or MCP servers,
saving no session; Codex without its shell, image, web search and agent tools or MCP servers, in a read-only
sandbox, saving nothing; Gemini CLI with every tool denied by a policy and no extensions. No AI on the machine:
the chat stops with `E601` and lists what to install or set.

## Short answers are a guardrail

Every turn, the AI is told the paper width and characters per line (from the printer profile), the limit per
answer in characters, the paper this conversation has used and the roll left (when `bobina paper` knows it); and
to write short plain sentences, with no Markdown but **bold**.

- The limit is about 10 cm of paper per answer: `--limit 6cm`, or `chat_limit = "6cm"` in config.toml.
- A longer answer: the AI is asked once to rewrite it shorter. Still too long: it prints cut at the limit with
  "…", the terminal says so and shows all of it. Paper never asks to "continue".
- With `--questions`, your message prints too and has a limit of about 3 printed lines (`chat_question_limit`):
  a longer one is not sent, and the terminal says why; it is never cut.
- At each metre of paper in one conversation, a note in the terminal (never on paper). Problems of the ticket
  (a letter the printer lacks, the roll running out) are said before it prints, as `bobina print` says them.

An answer is printed as plain text: never as a `.bob.md` document (no templates, raw bytes, images or files).

## On paper: layouts and styles

- `--layout strip` (default): one strip for the whole conversation. The AI and model (`Claude · Opus 5.5`) and
  the date on top once, no paper fed between answers; the end of the chat (or `/tickets`) feeds the strip to the
  tear bar.
- `--layout tickets`: each answer is its own ticket, with the AI, the model and the time on top, fed to the tear
  bar (with the tear mark when `marks` is on) to tear off.
- `--style plain` (default): your message right-aligned, the answer left-aligned, a dashed line between answers.
  `bubbles`: your message white on black in a bubble on the right, by a person icon; the answer under a ✦ and
  the AI's name. `boxes`: your message in a framed box, the answer under a robot icon. `labels`: "you" and a
  person icon over your message, ✦ and the AI's name over the answer. The icons are Lucide (ISC license).

`--layout` and `--style`, or `chat_layout` and `chat_style` in config.toml; `/strip` and `/tickets` in the chat.
Paper counts include the header, the icons, the dashed lines and the feeds, measured as `bobina check` measures a
document; printed answers go to `bobina history`.

## In the terminal

On a terminal, with `pip install 'bobina[ai]'`, the chat opens with a welcome block, keeps the terminal's
scrollback, and keeps a framed input box under the last message with a status line under it (the AI, the
printer, the layout, auto or manual, the paper of this chat and the roll left). Your messages show on the right,
the AI's under ✦ and its name, and what each answer took on paper in a dim line. Without a terminal (a pipe, an
agent) or without prompt_toolkit, the chat reads and writes plain lines. `NO_COLOR` turns the colours off.

| Type | Does |
|---|---|
| `p` | print the last answer (manual mode, or again after the printer failed) |
| `/manual`, `/auto` | print only on `p`, or every answer right away (the default) |
| `/strip`, `/tickets` | switch the layout |
| `/questions on`, `/questions off` | print your messages too, or not |
| `/help`, `/quit` | the commands (Tab completes them); end (also Ctrl-D) |
| Esc or Ctrl-C | stop the answer being written; the chat goes on |

The printer off or out of reach: the chat goes on in the terminal, says the answer was not printed, and `p`
tries again.
