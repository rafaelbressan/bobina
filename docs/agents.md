# bobina for agents

bobina is made to be run by programs and AI agents as well as by people: every print shows a confirmation screen,
every problem has a code, and every command that returns data has `--json`.

## The four rules

1. **No terminal, add `--yes`.** `bobina print FILE --yes`. Without it nobody can answer the confirmation screen
   and the print stops with `E107` (exit 7). `print -n` shows the screen and prints nothing.
2. **Look before paper.** `bobina check FILE` (paper length and problems), `bobina view FILE` (the preview in the
   terminal), `bobina preview FILE -o out.png` (the exact image). Print only what the user asked for.
3. **Read the codes.** Warnings never block: each one has a code, a suggestion and the evidence. `bobina help CODE`
   says what to do; [problems/README.md](problems/README.md) lists every code.
4. **Try without hardware.** `bobina printer add test --path out.bin` is a file printer: each job's bytes are
   appended to `out.bin`.

## Machine output

- `bobina check FILE --json` (and `print`, `preview`) gives `{"stats", "problems"}`; `--problems json|jsonl`
  writes problems to stderr. Schemas: [schemas/README.md](schemas/README.md).
- `bobina help --json` describes every command, option, topic and problem code.
- Exit codes: 0 ok, 1 usage, 2 document, 3 strict, 4 unreachable, 5 printer not ready, 6 language,
  7 confirmation, 8 security, 9 a payment code left out (`Q111`). [CLI.md](CLI.md#exit-codes) has the table.
- Servers, bots and cron: `BOBINA_NONINTERACTIVE=1`, one process per job
  ([CLI.md](CLI.md#long-jobs-and-limits)).

## Files for agents

- [llms.txt](../llms.txt): the index, with the facts an agent needs first; [llms-full.txt](../llms-full.txt): the
  docs in one file.
- [skills/bobina/SKILL.md](../skills/bobina/SKILL.md): a ready skill (when to print, what never to do).

## The MCP server (`bobina mcp`)

`bobina mcp` is a Model Context Protocol server on stdin/stdout for agents (Claude Code, Claude Desktop, Cursor).
It needs an extra: `uv tool install 'bobina[mcp]'`.

```bash
claude mcp add bobina -- bobina mcp                  # Claude Code
claude mcp add bobina -- bobina mcp --printer test   # defaults of check, preview, print (and status, paper)
```

`--printer`, `--profile`, `--allow` and `--strict` given to `bobina mcp` are the defaults of the document tools;
`--printer` is also the default of `status` and `paper`.

Claude Desktop, Cursor: `{"mcpServers": {"bobina": {"command": "bobina", "args": ["mcp"]}}}` in their MCP config.

| Tool | Runs |
|---|---|
| `check` | `check --json`: stats and problems, nothing printed |
| `preview` | `preview --json`, every file listed and attached as images up to 10 (temporary files unless `output`) |
| `print` | `print --dry-run --json`; with `confirm: true` (after the user agreed), `print --yes --json` |
| `template_list`, `template_show` | `template list --json`; `template show NAME --json` and the document to fill |
| `help` | `help TOPIC [NAME] --json`: a topic, a problem code (`Q111`), a pay scheme (`pay pix`) |
| `status`, `paper` | `status --json`, `paper --json` |
| `paper_new` | `paper new LENGTH --json`: a roll the user loaded, with the length they gave (`30m`; a unit is required) |

The document is `text` (given on stdin) or `path` (absolute, or `@NAME`); the other arguments are the options of
the command: `set`, `data`, `profile`, `printer` (check and preview take it too: look with the printer print
uses), `allow`, `allow_net`, `strict`, `copies`. Each result starts with the command line it ran and its exit
code, then the CLI's JSON (docs/schemas) and stderr, where problems are written as `--problems json`. It is an
error unless the exit is 0 or 9. Each call is one bobina process with `BOBINA_NONINTERACTIVE=1`, no stdin and a
session of its own: the safety is the CLI's (sandboxed templates, network images only with `allow_net`, the
limits in [CLI.md](CLI.md#long-jobs-and-limits)). A call that does not finish in 300 s (a print too) or that the
client cancels is stopped with everything it started (Ctrl-C, then a kill); its result has no exit code and, for a
print, says that part of the job may already be on paper: check the paper and `bobina history` before printing
again.
