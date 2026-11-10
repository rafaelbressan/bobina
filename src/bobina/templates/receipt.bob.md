---
fields:
  shop: { required: true, example: "Padaria do Zé" }
  items: { required: true, type: table, columns: [item, qty, price], help: "list of [item, quantity, unit price]" }
  currency: { default: "BRL", help: "ISO 4217 code" }
  date: { default: "{{ now | datetime('short') }}" }
  pay_to: { was: [pix], help: "who receives: a Pix key, UPI ID, IBAN, phone…; adds a payment QR code for the total" }
  pay_scheme: { default: "pix", help: "pix, upi, epc, promptpay, paynow… (bobina help pay)" }
  pay_name: { was: [pix_name], help: "receiver name in the code (default: shop)" }
  pay_city: { was: [pix_city], default: "", help: "Pix only: the city (default BRASIL)" }
  footer: { help: "last line (default: thank you)" }
labels:
  en: { item: Item, qty: Qty, price: Price, total: TOTAL, thanks: "Thank you!" }
  pt: { item: Item, qty: Qtd, price: Valor, total: TOTAL, thanks: "Obrigado!" }
---
# {{ shop }} {.center}

{{ date }} {.center}

--- {.dashed}

{% set ns = namespace(total=0) %}
| {{ label.item }} | {{ label.qty }} | {{ label.price }} |
|---|--:|--:|
{% for it in items or [] %}
{% set ns.total = ns.total + (it[1] | float) * (it[2] | float) %}
| {{ it[0] }} | {{ it[1] }} | {{ ((it[1] | float) * (it[2] | float)) | currency(currency) }} |
{% endfor %}

## {{ label.total }} {{ ns.total | currency(currency) }} {.right}
{% if pay_to %}

```pay {scheme="{{ pay_scheme }}" to="{{ pay_to }}" amount="{{ '%.2f' | format(ns.total) }}" name="{{ pay_name or shop }}"{% if pay_scheme == "pix" %} city="{{ pay_city }}"{% endif %}}
```
{% endif %}

{{ footer or label.thanks }} {.center}
