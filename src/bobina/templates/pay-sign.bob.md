---
# A counter sign: "Pay with …", a big payment code, the receiver, and the amount or "any amount".
fields:
  scheme: { required: true, example: "pix", help: "pix, upi, epc, promptpay, paynow… (bobina help pay)" }
  to: { required: true, example: "you@example.com", help: "who receives: Pix key, UPI ID, IBAN, phone…" }
  name: { required: true, example: "Café Sol" }
  amount: { default: "", help: "leave it empty and the payer types the amount" }
  city: { default: "", help: "Pix only: the city (default BRASIL)" }
labels:
  en: { pay: "Pay with", any: "any amount" }
  pt: { pay: "Pague com", any: "valor livre" }
---
## {{ label.pay }} {{ scheme | payname }} {.center}

```pay {scheme="{{ scheme }}" to="{{ to }}" name="{{ name }}" amount="{{ amount }}" city="{{ city }}" size=full caption=none}
```

**{{ name }}** {.center}

{% if amount %}{{ amount | paymoney(scheme) }}{% else %}{{ label.any }}{% endif %} {.center}
