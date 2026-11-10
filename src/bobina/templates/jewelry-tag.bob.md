---
# Gallery: jewellery. A small tag: piece, code, metal, weight, price; short lines, it is cut to a narrow strip.
fields:
  piece: { required: true, example: "Anel solitário" }
  code: { required: true, example: "AN-0231" }
  metal: { example: "Ouro 18k" }
  weight: { example: "2,4 g" }
  price: { example: "1890.00" }
  currency: { default: "BRL" }
---
**{{ piece }}** {.center}

{{ code }}{% if metal %} · {{ metal }}{% endif %}{% if weight %} · {{ weight }}{% endif %} {.center size=small}
{% if price %}

**{{ price | currency(currency) }}** {.center}
{% endif %}
