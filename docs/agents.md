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
  7 confirmation, 8 security, 9 a payment code left out (`Q111`), 10 a newer release (`bobina update --check`). [CLI.md](CLI.md#exit-codes) has the table.
- Servers, bots and cron: `BOBINA_NONINTERACTIVE=1`, one process per job
  ([CLI.md](CLI.md#long-jobs-and-limits)).

## Files for agents

- [llms.txt](../llms.txt): the index, with the facts an agent needs first; [llms-full.txt](../llms-full.txt): the
  docs in one file.
- [skills/bobina/SKILL.md](../skills/bobina/SKILL.md): a ready skill (when to print, what never to do).

## The MCP server (`bobina mcp`)

`bobina mcp` gives agents bobina as tools (check, preview, print with `confirm: true` after the user agreed,
paper): setup and the tool list in [mcp.md](mcp.md).
