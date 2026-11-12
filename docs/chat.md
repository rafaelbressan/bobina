# Chat with an AI on paper (`bobina chat`, `bobina ai`)

Two ways:

- **`bobina chat`** on a terminal opens the chat and keeps it open until you leave (`/quit` or Ctrl-D). Each answer
  shows and prints right away; entering the chat is the consent (`/manual`: print only on `/print`).
- **`bobina chat "QUESTION"`** (or the question on stdin) asks once, writes the answer to stdout and exits, like
  `claude -p`. It prints only with `--yes`, as `bobina print` does; without it, it says `not printed: ~4 cm; add
  --yes to print`. `--json` writes the answer, the AI and model, the paper and whether it printed
  ([schema](schemas/chat.schema.json)).

```bash
bobina chat                                   # the first time, it asks which AI (and saves the choice)
bobina chat --questions --layout tickets      # your messages print too; one ticket per answer
bobina chat "why is the sky blue?" --yes      # one answer, printed
echo "a haiku about paper" | bobina chat --json --dry-run
```

| Option | What | config.toml |
|---|---|---|
| `--ai NAME`, `--model MODEL` | the AI and its model for this run | `ai`, `ai_model` |
| `--printer NAME` | where answers print (shown in the welcome block and the status line) | `default_printer` |
| `--layout strip\|tickets` | one strip (default), or one ticket per answer fed to the tear bar | `chat_layout` |
| `--style STYLE` | how the two speakers look on paper (below); default `labels-underline` | `chat_style` |
| `--name NAME` | your name over your messages, on paper and on screen (default "you") | `chat_name` |
| `--questions` | print your messages too, on the right (about 3 lines at most; never cut: a longer one is not sent) | `chat_questions` |
| `--limit LENGTH` | paper per answer: `10cm` (default), `100mm`, `4in` (a bare number is cm); 1.5 cm to 1 m | `chat_limit` |
| `--manual` | the chat: print only on `/print` (`p`) | |
| `--dry-run` | never print; show the paper each answer would take | |
| `--yes` | one question: print the answer | |

Options apply to that run only. Values have synonyms and typo hints (`--layout ticket`, `--style c1`).

## Which AI (`bobina ai`)

`bobina ai list` shows what this machine already has, best first; `bobina ai use NAME [--model MODEL]` saves the
choice; `bobina ai list --json` has every AI, found or not, and what each one needs.

| NAME | What | Needs |
|---|---|---|
| `claude` | Claude Code, called with its own login | the `claude` program, logged in once |
| `codex` | Codex CLI, with its own login | `codex login` |
| `gemini` | Gemini CLI, with its own login | `gemini`, logged in once |
| `ollama` | a local chat model through Ollama (`OLLAMA_HOST`; embedding models are skipped) | `ollama pull llama3.2` |
| `anthropic` | the Claude API (default model `claude-opus-5-5`) | `ANTHROPIC_API_KEY` |
| `openai` | the OpenAI API (default model `gpt-5`) | `OPENAI_API_KEY` |

AI programs only answer: they run in an empty folder, with the conversation on stdin and nothing that reaches the
machine. Claude Code runs without tools and without your settings, hooks, plugins, CLAUDE.md or MCP servers,
saving no session; Codex without its shell, image, web search and agent tools or MCP servers, in a read-only
sandbox; Gemini CLI with every tool denied by a policy and no extensions. The APIs are called over HTTPS with no
SDK: every AI works with a plain install. No AI: `E601` lists what to install or set; no answer: `E602`.

## Short answers are a guardrail

Every turn, the AI is told the paper width and characters per line (from the printer profile), the limit per
answer in characters, the paper this conversation has used and the roll left (when `bobina paper` knows it); and
to write short plain sentences, with no Markdown but **bold**. A longer answer is rewritten once; still too long,
it prints cut at the limit with "…" (the terminal shows all of it). Paper never asks to "continue". At each metre
of paper in one conversation, a note in the terminal. Problems of the ticket (a letter the printer lacks, the roll
running out) are said before it prints, as `bobina print` says them. An answer is printed as plain text: never as
a `.bob.md` document (no templates, raw bytes, images or files).

## On paper: layouts and styles

- `strip`: the AI and model (`Claude · Opus 5.5`) and the date on top once, the answers one after the other, no
  paper fed between them; the end of the chat (or `/tickets`) feeds the strip to the tear bar.
- `tickets`: each answer is its own ticket, with the AI, the model and the time on top, fed to the tear bar (with
  the tear mark when `marks` is on) to tear off. One question is always one ticket.

Styles keep the conversation reading as one: marks are short and sit by their speaker (right for you, left
for the AI), never across the paper. The `labels` family puts your name and a person icon over your message and ✦
and the AI's name over the answer; then: `labels-underline` (the default: a short solid mark under each name),
`labels-dashes` (a short dashed one), `labels-dots` (no marks; a small "· · ·" in the middle between exchanges),
`labels-outline` (your message in a framed bubble under your name), `labels-filled` (a black bubble, the AI's name
with a short dotted mark), `labels-hook` (a short mark with a hook under each name, "— ✦ —" between exchanges).
Earlier looks stay available: `labels`, `labels-ruled`, `labels-underlined`, `labels-exchange`, `labels-bubble`,
`bubbles`, `boxes`, `plain`. Icons: Lucide (ISC license).

## The chat screen

It opens with a welcome block, keeps the terminal's scrollback, and keeps a framed input box under the last message
with a status line: the AI, the printer, the layout, auto or manual, the paper of this chat and the roll (`roll
7.4 m left`, or `roll ?` until `bobina paper new 30m` says its length). Your messages show on the right, the AI's
under ✦ and its name, what each answer took on paper in a dim line. `NO_COLOR` turns colours off. The screen needs
a terminal: without one (or with `BOBINA_NONINTERACTIVE`), ask one question instead (`E107` says so).

| Type | Does |
|---|---|
| `/print` (`p`) | print the last answer if it is not on paper yet (manual mode, or after the printer failed) |
| `/again` | print another copy of the last answer |
| `/manual`, `/auto` | print only on `/print`, or every answer right away (the default) |
| `/strip`, `/tickets`, `/questions on\|off` | switch the layout; print your messages too, or not |
| `/say TEXT` | send TEXT as it is: the single letter p, or a line that starts with / |
| `/help`, `/quit` | the commands (Tab completes them); end (also Ctrl-D) |
| Esc or Ctrl-C | stop the answer being written; the chat goes on |

The printer off or out of reach: the chat goes on, says the answer was not printed, and `p` tries again.
