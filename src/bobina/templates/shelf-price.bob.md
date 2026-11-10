---
# Gallery: grocery. A shelf price: product, the price as big as it fits, the price per kg or unit, the EAN-13.
fields:
  product: { required: true, example: "Arroz tipo 1" }
  price: { required: true, example: "24.90" }
  unit: { default: "un", example: "5 kg", help: "what the price is for: un, 5 kg, 1 L…" }
  per: { example: "R$ 4,98/kg", help: "price per kg/L, as text" }
  ean: { example: "7891234567895", help: "13 digits (EAN-13)" }
  currency: { default: "BRL" }
---
## {{ product }} {.center}

{{ price | currency(currency) }} {.center size=huge}

{{ unit }}{% if per %} · {{ per }}{% endif %} {.center}
{% if ean %}

```barcode {type=ean13}
{{ ean }}
```
{% endif %}
