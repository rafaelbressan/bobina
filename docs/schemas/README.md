# JSON schemas

| Schema | Output |
|---|---|
| [problem.schema.json](problem.schema.json) (`bobina.problem/1`) | each problem: `check --json` → `problems[]`, `--problems json|jsonl` |
| [check.schema.json](check.schema.json) | `bobina check FILE --json` |
| [history.schema.json](history.schema.json) (`bobina.history/1`) | one line of `history.jsonl`, `bobina history --json` |
| [print.schema.json](print.schema.json) (`bobina.print/1`) | `bobina print … --json`: outcome, exit, printer, saved_to, stats, problems |
| [preview.schema.json](preview.schema.json) (`bobina.preview/1`) | `bobina preview … --json`: exit, files, stats, problems |
| [config.schema.json](config.schema.json) (`bobina.config/1`) | `bobina config locale [TAG] --json`: value, source, prints_as, example |
| [init.schema.json](init.schema.json) (`bobina.init/1`) | `bobina init --json`: printer, found, profile, locale, roll, test_strip, problems, next |
| [chat.schema.json](chat.schema.json) (`bobina.chat/1`) | `bobina chat "QUESTION" --json`: answer, AI and model, paper, printed or not, problems |

`bobina help --json` (`bobina.help/1`) describes the commands, their options, the topics and every problem code
with what to do. tests/test_schemas.py checks real outputs against these files.
