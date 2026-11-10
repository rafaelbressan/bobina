---
# A label for a pantry jar. Each {{ name }} below is filled from one row of the data file.
fields:
  product: { required: true, example: "Brown rice" }
  packed:  { help: "date the jar was filled (YYYY-MM-DD)" }
  best_before: { help: "YYYY-MM-DD; leave empty if it does not expire" }
  shelf:   { example: "A" }
---
# {{ product }} {.center}

--- {.dashed}

Packed **{{ packed }}** {.center}
{% if best_before %}

Best before **{{ best_before }}** {.center}
{% endif %}

Shelf {{ shelf }} {.center}
