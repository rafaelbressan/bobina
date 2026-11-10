---
# Gallery: retail. A sale price: the band, the old price struck through, the new price big, until when.
fields:
  product: { required: true, example: "Café 500 g" }
  old: { required: true, example: "21.90" }
  new: { required: true, example: "16.90" }
  until: { example: "15/11", help: "last day of the offer, as text" }
  currency: { default: "BRL" }
labels:
  en: { sale: SALE, until: until }
  pt: { sale: OFERTA, until: até }
---
# {{ label.sale }} {.invert .center}

## {{ product }} {.center}

~~{{ old | currency(currency) }}~~ {.center}

{{ new | currency(currency) }} {.center size=huge}
{% if until %}

{{ label.until }} {{ until }} {.center}
{% endif %}
