---
# Gallery: clothing. A hang tag: brand, piece, size in big letters, colour, price and the SKU as a barcode.
fields:
  brand: { required: true, example: "Atelier Sol" }
  piece: { required: true, example: "Camisa de linho" }
  garment_size: { required: true, example: "M" }
  color: { example: "Branca" }
  price: { required: true, example: "149.90", help: "a number: printed as money in the locale's currency" }
  currency: { default: "BRL" }
  sku: { example: "CAM-LIN-M-BR", help: "Code 128 content (letters and digits)" }
labels:
  en: { size: SIZE, color: Colour }
  pt: { size: TAMANHO, color: Cor }
---
# {{ brand }} {.center}

{{ piece }} {.center}

--- {.dashed}

{{ label.size }} {.center size=small}

{{ garment_size }} {.center size=huge}
{% if color %}

{{ label.color }}: {{ color }} {.center}
{% endif %}

## {{ price | currency(currency) }} {.center}
{% if sku %}

```barcode {type=code128}
{{ sku }}
```
{% endif %}
