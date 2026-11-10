---
fields:
  title: { help: "optional heading" }
  text: { required: true, example: "Call the plumber after 2 pm.", help: "the note (Markdown allowed)" }
  date: { default: "{{ now | datetime('short') }}" }
---
{% if title %}
## {{ title }}

{% endif %}
{{ text | markdown }}

{{ date }} {.right}
