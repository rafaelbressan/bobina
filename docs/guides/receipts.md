# Receipts: whole recipes

Copy one, change the items, run `bobina check FILE` (it says the width each column got), then print. Tables:
[tables guide](tables.md), `bobina help table`; whole files: [examples/tables](../../examples/tables/).

## Totals

A table whose title cells are empty prints no title and no rule: label on the left, value on the right. A
`prefix=` in an empty title cell puts the currency before each value of its column.

```markdown
| | {prefix="R$ "} |
|---|--:|
| SUBTOTAL | 157,50 |
| SERVICE 10% | 15,75 |
| **TOTAL** | **173,25** |
```

## A bar bill

The printer font, three columns, the receipt style; the totals under it, the TOTAL row white on black (a `{…}`
after a row's closing pipe styles the row: [table-cells.md](table-cells.md)).

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
| TOTAL | 93,50 | {.invert .bold}
```

## A supermarket receipt

Seven columns on 58 mm: a smaller font, the narrow columns given a width, the description taking the rest.

```markdown
## MERCADO EXEMPLO {.center}

| IT {width=3ch} | CÓD {width=7ch} | DESCRIÇÃO | QTD {width=5ch} | UN {width=2ch} | UNIT {width=5ch} | TOTAL {width=6ch} |
|---|---|---|--:|---|--:|--:|
| 001 | 2000000010014 | ARROZ BRANCO TIPO 1 5KG | 1 | un | 24,90 | 24,90 |
| 003 | 2000000010038 | BANANA PRATA | 1.635 | kg | 9,99 | 16,33 |
| | | Desconto no item 3 - 3,27 {span=all} |
{style=receipt font=Terminus size=16px}

| | {prefix="R$ "} |
|---|--:|
| SUBTOTAL | 41,23 |
| DESCONTOS | -3,27 |
| **VALOR TOTAL** | **37,96** |
{font=Terminus size=16px}
```

`bobina check` says `… DESCRIÇÃO 14 … (+6 gaps = 48 of 48)`. Each 13-digit code prints on two lines without a
warning: you gave its column 7. The discount line starts under DESCRIÇÃO (one empty cell for each column before
it). On 80 mm DESCRIÇÃO takes 24 more.

## An NFC-e footer

The QR code on the left, three lines beside it, in the middle ([columns](layout-columns.md)):

````markdown
:::: {.columns valign=middle}
::: {.column width=40%}
```qr
https://example.com/nfce/276712
```
:::
::: {.column}
CONSUMIDOR NÃO IDENTIFICADO
NFC-e nº 276712 · Série 4
15/11/2026 11:33
:::
::::
````
