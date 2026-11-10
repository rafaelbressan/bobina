---
fields:
  title: { required: true, example: "Happy birthday!" }
  message: { required: true, example: "All the best for the year ahead.", help: "the text of the card (Markdown allowed)" }
  from: { help: "signature" }
---
--- {.wavy}

# {{ title }} {.center}

--- {.wavy}

{{ message | markdown }}
{% if from %}

— {{ from }} {.right}
{% endif %}

--- {.double}
