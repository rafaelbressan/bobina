# Chat with an AI on paper (`bobina chat`, `bobina ai`)

Two ways:

- **`bobina chat`** on a terminal opens the chat until you leave (`/quit` or Ctrl-D). Each answer shows and prints
  right away; entering the chat is the consent (`/manual`: print only on `/print`).
- **`bobina chat "QUESTION"`** (or the question on stdin) asks once, writes the answer and exits, like `claude -p`.
  It prints only with `--yes`, as `bobina print` does; `--json` writes the answer, the AI and model, the paper and
  whether it printed ([schema](schemas/chat.schema.json)).

```bash
bobina chat --questions --layout tickets      # your messages print too; one ticket per answer
bobina chat "why is the sky blue?" --yes      # one answer, printed
echo "a haiku about paper" | bobina chat --json --dry-run
```

| Option | What | config.toml |
|---|---|---|
| `--ai NAME`, `--model MODEL` | the AI and its model for this run | `ai`, `ai_model` |
| `--printer NAME` | where answers print (shown on the screen) | `default_printer` |
| `--layout strip\|tickets` | one strip (default), or one ticket per answer fed to the tear bar | `chat_layout` |
| `--paper-style NAME` | how the answers look on paper (below) | `chat_paper_style` |
| `--screen-colors NAME` | the colours of the chat screen (below) | `chat_screen_colors` |
| `--name NAME` | your name over your messages (default "you") | `chat_name` |
| `--questions` | print your messages too, on the right (about 3 lines; a longer one is not sent) | `chat_questions` |
| `--limit LENGTH` | paper per answer: `10cm` (default), `100mm`, `4in`; 1.5 cm to 1 m | `chat_limit` |
| `--manual` | the chat: print only on `/print` (`p`) | |
| `--dry-run` | never print; show the paper each answer would take | |
| `--yes` | one question: print the answer | |

Options apply to that run only; values have synonyms and typo hints (`--layout ticket`, `--paper-style d4`).
`bobina chat --help` lists every paper style and screen colours with what they look like.

## Which AI (`bobina ai`)

`bobina ai list` shows what this machine has, best first; `bobina ai use NAME [--model MODEL]` saves the choice.

| NAME | What | Needs |
|---|---|---|
| `claude` | Claude Code, with its own login | the `claude` program, logged in once |
| `codex` | Codex CLI, with its own login | `codex login` |
| `gemini` | Gemini CLI, with its own login | `gemini`, logged in once |
| `ollama` | a local chat model through Ollama (`OLLAMA_HOST`) | `ollama pull llama3.2` |
| `anthropic` | the Claude API (default model `claude-opus-5-5`) | `ANTHROPIC_API_KEY` |
| `openai` | the OpenAI API (default model `gpt-5`) | `OPENAI_API_KEY` |

AI programs only answer: an empty folder, the conversation on stdin, no tools, none of your settings, hooks,
plugins, CLAUDE.md or MCP servers. The APIs are called over HTTPS with no SDK. No AI: `E601`; no answer: `E602`.

## Short answers are a guardrail

Every turn, the AI is told the paper width, the limit per answer, the paper used so far and the roll left, and to
write short plain sentences (no Markdown but **bold**). A longer answer is rewritten once; still too long, it
prints cut with "…" (the screen shows all of it). A note at each metre of paper. The ticket's problems are said
before it prints, as `bobina print` says them. An answer prints as plain text, never as a `.bob.md` document.

## On paper

- `strip`: the AI, model and date on top once, the answers one after the other; the end of the chat (or
  `/tickets`) feeds the strip to the tear bar. `tickets`: each answer its own ticket, fed to the tear bar.
- Paper styles put your name and a person icon over your message, ✦ and the AI's name over the answer; marks are
  short and by their speaker, so the conversation reads as one. `labels-underline`: a short line under
  each name (default) · `labels-dashes`: a short dashed line under each name · `labels-dots`: no lines; a small · · · between
  exchanges · `labels-outline`: your message in a framed bubble · `labels-filled`: your message in a black bubble ·
  `labels-hook`: a hooked line under each name, — ✦ — between exchanges. Earlier looks remain (`--help` lists
  them). Icons: Lucide (ISC license).

## The chat screen

A welcome block, then messages above a framed input box and a status line: the AI, the printer, the layout, auto
or manual, the paper of this chat and the roll (`roll 7.4 m left`, or `roll ?` until `bobina paper new 30m`).
Screen colours (`--screen-colors`, default the terminal's background, else dark): `dark`: light text on a dark
terminal · `light`: dark text on a light terminal · `mono`: no colours; bold and dim only · `contrast`: bright,
high-contrast colours. Your own go over them in `[chat.screen_colors]` (`you`, `you-text`, `ai`, `ai-text`, `dim`,
`frame`, `status`, `warning`, `error`; `you = "#ff8700"`). `NO_COLOR` and `--no-color` win. Without a terminal
(or with `BOBINA_NONINTERACTIVE`), ask one question instead (`E107`).

| Type | Does |
|---|---|
| `/print` (`p`), `/again` | print the last answer if it is not on paper yet; another copy |
| `/manual`, `/auto` | print only on `/print`, or every answer right away (the default) |
| `/strip`, `/tickets`, `/questions on\|off` | switch the layout; print your messages too, or not |
| `/paper-style [NAME]` | list the paper styles, what each looks like; the next answers use NAME |
| `/screen-colors [NAME]` | list the screen colours; switch to NAME |
| `/say TEXT` | send TEXT as it is (the letter p, a line that starts with /) |
| `/help`, `/quit` | the commands (Tab completes them); end (also Ctrl-D) |
| Esc or Ctrl-C | stop the answer being written; the chat goes on |

The printer out of reach: the chat goes on, says the answer was not printed, and `p` tries again.
