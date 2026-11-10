---
# Gallery: food. A food label: product, made today, use-by date computed from the days it keeps, storage, who made it.
fields:
  product: { required: true, example: "Molho de tomate" }
  days: { default: "3", help: "days it keeps: the use-by date is today + days" }
  storage: { example: "Refrigerado 0–4 °C" }
  by: { example: "Ana", help: "who prepared it" }
  batch: { example: "L0811" }
labels:
  en: { made: Made, until: USE BY, storage: Storage, by: By, batch: Batch }
  pt: { made: Feito em, until: VALIDADE, storage: Conservação, by: Por, batch: Lote }
---
# {{ product }} {.invert .center}

{{ label.made }}: {{ now | date("short") }} {.center}

## {{ label.until }} {{ now | add(days=days) | date("short") }} {.center}
{% if storage %}

{{ label.storage }}: {{ storage }} {.center}
{% endif %}
{% if by or batch %}

{% if by %}{{ label.by }}: {{ by }}{% endif %}{% if by and batch %} · {% endif %}{% if batch %}{{ label.batch }}: {{ batch }}{% endif %} {.center size=small}
{% endif %}
