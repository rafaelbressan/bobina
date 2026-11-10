---
fields:
  title: { required: true, example: "FRAGILE" }
  lines: { help: "list of lines under the title" }
  barcode: { help: "Code 128 content" }
  qr: { help: "QR code content" }
---
# {{ title }} {.invert .center}
{% for l in lines or [] %}

{{ l }} {.center}
{% endfor %}
{% if barcode %}

```barcode {type=code128}
{{ barcode }}
```
{% endif %}
{% if qr %}

```qr
{{ qr }}
```
{% endif %}
