# Receipts: a supermarket receipt

More whole recipes: [receipts.md](receipts.md); every table feature: [tables.md](tables.md).

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

`bobina check` says `column widths in Terminus 16px columns: IT 3 · CÓD 7 · DESCRIÇÃO 14 · QTD 5 · UN 2 · UNIT 5 ·
TOTAL 6 (+6 gaps = 48 of 48)`. Each 13-digit code prints on two lines, of 7 and 6 digits, without a warning: you
gave its column 7. The discount line starts under DESCRIÇÃO (one empty cell for each column before it) and
takes the rest of the row. On 80 mm the same table has 72 columns, and DESCRIÇÃO takes the 24 more.
