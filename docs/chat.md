# Chat with an AI on paper (`bobina chat`, `bobina ai`)

`bobina chat` is a conversation in the terminal: you type, an AI answers, and each answer also prints on the
roll. Everything shows in the terminal too.

```bash
bobina chat                      # the first time, it asks which AI (and saves the choice)
bobina chat --questions          # print your messages too, on the right; the answers stay on the left
bobina chat --layout tickets     # one ticket per answer, to tear off
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
| `ollama` | a local model through Ollama on localhost (`OLLAMA_HOST`) | `ollama pull llama3.2` |
| `anthropic` | the Claude API (default model `claude-opus-5-5`) | `ANTHROPIC_API_KEY` and `pip install 'bobina[ai]'` |
| `openai` | the OpenAI API (default model `gpt-5`) | `OPENAI_API_KEY` and `pip install 'bobina[ai]'` |

AI programs run in an empty folder, without tools: they only answer. No AI on the machine: the chat stops with
`E601` and lists what to install or set.

## Short answers are a guardrail

Every turn, the AI is told the paper width and characters per line (from the printer profile), the limit per
answer in characters, the paper this conversation has used and the roll left (when `bobina paper` knows it); and
to write short plain sentences, with no Markdown but **bold**.

- The limit is about 10 cm of paper per answer: `--limit 6cm`, or `chat_limit = "6cm"` in config.toml.
- A longer answer: the AI is asked once to rewrite it shorter. Still too long: it prints cut at the limit with
  "…", the terminal says so and shows all of it. Paper never asks to "continue".
- At each metre of paper in one conversation, a note in the terminal (never on paper).

An answer is printed as plain text: never as a `.bob.md` document (no templates, raw bytes, images or files).

## Layouts

- `strip` (default): one strip for the whole conversation. The AI and model (`Claude · Opus 5.5`) and the date
  on top once, a dashed line between answers, no paper fed between them; the end of the chat (or `/tickets`)
  feeds the strip to the tear bar.
- `tickets`: each answer is its own ticket, with the AI, the model and the time on top, fed to the tear bar
  (with the tear mark when `marks` is on) to tear off.

`--layout`, `chat_layout` in config.toml, or `/strip` and `/tickets` inside the chat. Paper counts include the
header, the dashed lines and the feeds, measured as `bobina check` measures a document; printed answers go to
`bobina history`.

## Inside the chat

| Type | Does |
|---|---|
| `p` | print the last answer (manual mode, or again after the printer failed) |
| `/manual`, `/auto` | print only on `p`, or every answer right away (the default) |
| `/strip`, `/tickets` | switch the layout |
| `/help`, `/quit` | the commands; end (also Ctrl-D) |

The printer off or out of reach: the chat goes on in the terminal, says the answer was not printed, and `p`
tries again.
