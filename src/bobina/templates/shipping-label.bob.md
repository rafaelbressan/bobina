---
# Gallery: logistics. A shipping label: recipient and address, sender, order number and the tracking code.
fields:
  to: { required: true, example: "Maria Silva" }
  address: { required: true, example: "Rua das Flores, 123 - ap 4", help: "street, number, complement" }
  city: { required: true, example: "Rio de Janeiro - RJ" }
  zip: { required: true, example: "20000-000" }
  from: { example: "Loja Exemplo · Rua A, 1 · São Paulo - SP" }
  order: { example: "#1042" }
  tracking: { example: "BR123456789BR", help: "Code 128 content" }
labels:
  en: { to: TO, from: From, order: Order }
  pt: { to: DESTINATÁRIO, from: Remetente, order: Pedido }
---
{{ label.to }} {.invert}

## {{ to }}

{{ address }}

{{ city }}

**{{ zip }}** {size=large}
{% if from %}

--- {.dashed}

{{ label.from }}: {{ from }} {size=small}
{% endif %}
{% if order %}

{{ label.order }} {{ order }}
{% endif %}
{% if tracking %}

```barcode {type=code128}
{{ tracking }}
```
{% endif %}
