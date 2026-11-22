# Charts

A table is always the data; `chart=` in the `{…}` under it decides that it prints as a chart (line, bar, area or
sparkline) instead of the table. A whole document:

```markdown
---
locale: pt-BR
---
| dia | vendas | meta |
|---|---|---|
| Seg | R$ 1.240,50 | R$ 1.200,00 |
| Ter | R$ 980,00 | R$ 1.200,00 |
| Qua | R$ 1.105,25 | R$ 1.200,00 |
{chart=bar height=30mm .grid}
```

Classes (`.grid`, `.center`) and `key=value` attributes all go in the same `{…}` on the line under the table. The
second line (`---`, `--:`, `:-:`) is still needed, as Markdown needs it to see a table, but its alignment does nothing
for a chart: `---` is enough. Alignment counts only for a table that prints (`.with-table`, or `data=` without
`chart=`).

## Data

- First column: the labels (X axis). Each next column: a series of numbers; the title row names them, and a legend
  prints when there are two or more.
- Numbers are read in the document's locale (front matter `locale: pt-BR`: `R$ 1.240,50` is 1240.5); currency signs
  and thousands separators are fine. A cell that is not a number leaves its row out (`C103`); an empty cell is a gap.
- Repeated labels (a row per product of each day) are summed into one point (`C107`); `aggregate=max` or
  `aggregate=mean` combines them otherwise. `last=7`: only the last 7 points.
- `.with-table`: the table prints too, under the chart.

## From a file

`vendas.csv`, next to the document:

```text
data,produto,valor,meta
2026-11-02,pão,320.50,400
2026-11-02,bolo,210.00,400
2026-11-03,pão,410.00,400
```

A table with only its title row and second line, and `data=` under it:

```markdown
| data | valor |
|---|---|
{chart=bar data=vendas.csv width=half .center}
```

- The titles pick the file's columns by name (the first: the labels); a title the file lacks: `C108`, with its
  columns. CSV, TSV, XLSX and JSON, as `--data` reads them (`bobina help data`).
- The path is relative to the document. `data={{ arquivo }}` with `--set arquivo=nov.csv` works when the value
  names a data file in the document's folder (any other path: `M312`).
- The file is data: its cells print as written, never as Markdown, a variable or a command.
- Without `chart=`, `{data=vendas.csv style=receipt}` prints the rows as a table, with every table style.

## Types

| `chart=` | Draws |
|---|---|
| `line` | a 2-dot line through the points |
| `bar` | a bar per label; several series side by side (black, grey, outlined) |
| `area` | a line, the area down to zero (up to zero below it) in the paper's tested grey |
| `sparkline` | a small line, no axes, no labels, one text line tall: beside a number in columns |

When every label is a date (`2026-11-07`, `27/01`, `Jan 27`, `27 jan`), lines and areas space the points by the time
between them; other labels, and bars, are evenly spaced. Dates without a year follow one another: `Dec 20, Jan 5` is
the next January.

## Size and axes

- `width=` as on every object (`full`, `half`, `50%`, `30mm`); `height=30mm` (default: the width × 0.6). `.center`,
  `.right`; inside boxes and columns.
- Labels come first: the printer font's look and size, or `size=16px`, `font=`; the drawing gets what is left.
  Too small for them: fewer, then smaller labels (`C105`), never cut.
- `y-ticks=3` (the default): round values written short (`300K`, `1.2M`, `-1.5`), turned along the axis;
  `y-labels=horizontal` writes them upright. `x-labels=all|ends|4` (default: as many as fit).
- `.grid`: dotted lines at the Y values. `.no-axes`: no axes and no axis labels. `title="Câmara fria"`: a line above.
- `orientation=vertical`: turned along the roll, read sideways; `width=` is across the paper, `length=90mm` along it.

## Beside a number

```markdown
:::: {.columns valign=middle}
::: {width=40%}
**749K**
supply
:::
::: {}
| | |
|---|---|
| | 120000 |
| | 410000 |
| | 749069 |
{chart=sparkline}
:::
::::
```

## What check says

| Code | When |
|---|---|
| `C101` | what was drawn and how the values were read (`bobina check` only) |
| `C102` | more points than the width shows: neighbours averaged (`aggregate=max`: the largest) |
| `C103` | a value is not a number: its row is left out |
| `C104` | dates out of order: drawn as written, evenly spaced |
| `C105` | too small for its labels: fewer or smaller ones |
| `C106` | nothing to draw (no value column): printed as a table |
| `C107` | repeated labels combined |
| `C108`, `C109` | a title the file lacks; a file not found or unreadable |

Charts are **⚠ not tested on paper** yet (`P301`).
