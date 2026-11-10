---
# A shelf tag: price from prices.xlsx (a), category and id from catalog.json (b). See docs/guides/batch-printing.md, step 5.
---
# {{ name }} {.center}

{{ price }} ({{ size }}) {.center}

{{ a.category }}{% if b.category %} / {{ b.category }}{% endif %} {.center}

{% if id %}id {{ id }} {.center}{% endif %}
