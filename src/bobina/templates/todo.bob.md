---
fields:
  title: { help: "heading (default: To do)" }
  items: { required: true, help: "list of tasks; prefix with 'x ' for done" }
  date: { default: "{{ now | date('full') }}" }
labels:
  en: { title: "To do" }
  pt: { title: "Tarefas" }
---
# {{ title or label.title }}

{{ date }}

{% for it in items or [] %}
{% if it is string and it.startswith("x ") %}
- [x] {{ it[2:] }}
{% else %}
- [ ] {{ it }}
{% endif %}
{% endfor %}
