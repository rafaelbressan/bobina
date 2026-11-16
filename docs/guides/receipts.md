# Receipts: whole recipes

Copy one, change the items, run `bobina check FILE` (it says the width each column got), then print. Every table
feature used here is explained in the [tables guide](tables.md).

## Totals

A table whose title cells are empty prints no title and no rule: label on the left, value on the right. A
`prefix=` in the empty title cell of a column puts the currency before each value, and the row still counts as
empty.

```markdown
| | {prefix="R$ "} |
|---|--:|
| SUBTOTAL | 157,50 |
| SERVICE 10% | 15,75 |
| **TOTAL** | **173,25** |
```

## A bar bill

The printer font, three columns, the receipt style; the totals under it.

```markdown
## Café Example {.center}

| Qty | Item | Price |
|--:|---|--:|
| 2 | Espresso | 18,00 |
| 1 | Bagel | 39,00 |
| 1 | Lemon pie | 28,00 |
{style=receipt}

| | {prefix="R$ "} |
|---|--:|
| SUBTOTAL | 85,00 |
| SERVICE 10% | 8,50 |
| **TOTAL** | **93,50** |
```

## A supermarket receipt

Seven columns on 58 mm: a smaller font, the narrow columns given a width, the description taking the rest.

```markdown
## MERCADO EXEMPLO {.center}

| IT {width=3ch} | CÓD {width=7ch} | DESCRIÇÃO | QTD {width=5ch} | UN {width=2ch} | UNIT {width=5ch} | TOTAL {width=6ch} |
|---|---|---|--:|---|--:|--:|
| 001 | 2000000010014 | ARROZ BRANCO TIPO 1 5KG | 1 | un | 24,90 | 24,90 |
| 003 | 2000000010038 | BANANA PRATA | 1.635 | kg | 9,99 | 16,33 |
{style=receipt font=Terminus size=16px}

| | {prefix="R$ "} |
|---|--:|
| SUBTOTAL | 41,23 |
| **VALOR TOTAL** | **41,23** |
{font=Terminus size=16px}
```

`bobina check` says `column widths in Terminus 16px columns: IT 3 · CÓD 7 · DESCRIÇÃO 14 · QTD 5 · UN 2 · UNIT 5 ·
TOTAL 6 (+6 gaps = 48 of 48)`. Each 13-digit code prints on two lines, of 7 and 6 digits, without a warning: you
gave its column 7. On 80 mm the same table has 72 columns, and DESCRIÇÃO takes the 24 more.
