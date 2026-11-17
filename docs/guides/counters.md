# Counters: when a number is taken

A counter (`counters:` in the front matter, `{{ seq.ticket }}` in the body: [FORMAT §7.3](../FORMAT.md#73-counters))
gives each print new numbers. This page says exactly when a number is taken, given back or skipped.

- Previews, `check` and `--dry-run` only show the next values; they take nothing.
- A print **reserves** its values when it is built, so the confirmation screen shows the numbers that will be
  printed and two prints at the same time never get the same number.
- If the job is then not printed (you quit, the printer is unreachable, the build fails), the values go back, unless
  another print took numbers after them: then they stay skipped.
- A number is never printed twice; a cancelled job may leave a gap (one stopped halfway keeps the numbers of the
  labels that printed).
