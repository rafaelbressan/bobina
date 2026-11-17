# Receipts: whole recipes

Copy one, change the items, run `bobina check FILE` (it says the width each column got), then print. Every table
feature used here is explained in the [tables guide](tables.md) and in `bobina help table`. Whole files with their
images: [examples/tables](../../examples/tables/) (a table bill, a bar check, a supermarket receipt). A
supermarket receipt, seven columns on 58 mm: [receipts-supermarket.md](receipts-supermarket.md).

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

## An NFC-e footer

The QR code on the left, three lines beside it, in the middle of its height ([columns](layout-columns.md)):

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
