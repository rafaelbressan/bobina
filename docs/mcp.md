# The MCP server (`bobina mcp`)

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
| `paper_new` | `paper new --json`: a roll the user loaded, with the length (`30m`, `50ft`) or diameter (`40mm`) and width they gave; a package code (`57x30`) is refused: ask the user |

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
