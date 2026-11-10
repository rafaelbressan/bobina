"""--ask: missing fields asked on the terminal; answers are literal data like --set."""

from bobina import cli
from bobina.cli import common


class FakeTTY:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.shown = []

    def write(self, s):
        self.shown.append(s)

    def flush(self):
        pass

    def readline(self):
        return (self.answers.pop(0) + "\n") if self.answers else ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def run_ask(monkeypatch, tmp_path, doc, *answers, extra=()):
    tty = FakeTTY(*answers)
    monkeypatch.setattr(common, "open_tty", lambda: tty)
    (tmp_path / "d.bob.md").write_text(doc, encoding="utf-8")
    out = tmp_path / "o.bin"
    code = cli.main(["print", str(tmp_path / "d.bob.md"), "--ask", "-o", str(out), *extra])
    return code, (out.read_bytes() if out.exists() else b""), "".join(tty.shown)


def test_template_fields_are_asked_in_order_with_table_rows(monkeypatch, tmp_path):
    code, data, shown = run_ask(
        monkeypatch,
        tmp_path,
        "---\ntemplate: receipt\n---\n",
        "Padaria do Zé",
        "pão; 2; 1.50",
        "café; 1; 4",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    )
    assert code == cli.OK
    assert "Padaria do Z" in data.decode("utf-8", "replace") and b"7" in data
    assert shown.index("shop") < shown.index("items") < shown.index("currency")
    assert "one row per line: item; qty; price" in shown and "[BRL]" in shown and "[automatic]" in shown


def test_plain_document_asks_its_variables_only(monkeypatch, tmp_path):
    code, data, shown = run_ask(monkeypatch, tmp_path, "Oi {{ nome }}, hoje é {{ today }}\n", "Rafa")
    assert code == cli.OK and b"Oi Rafa" in data
    assert "nome" in shown and "today" not in shown.replace("hoje", "")


def test_answers_are_literal(monkeypatch, tmp_path):
    code, data, _ = run_ask(monkeypatch, tmp_path, "{{ title }}\n", "# PROMO **x** {{ 7*7 }}")
    assert code == cli.OK
    assert b"# PROMO **x** {{ 7*7 }}" in data and b"49" not in data


def test_set_and_front_matter_values_are_not_asked(monkeypatch, tmp_path):
    doc = "---\nfrom: Ana\ntemplate: card\n---\n"
    code, _, shown = run_ask(monkeypatch, tmp_path, doc, "Feliz", "texto", extra=("--set", "title=Oi"))
    assert code == cli.OK
    assert "message" in shown and "title" not in shown and "from" not in shown


def test_required_field_left_empty_still_prints_with_nudge(monkeypatch, tmp_path, capsys):
    code, _, shown = run_ask(monkeypatch, tmp_path, "---\ntemplate: card\n---\n", "", "", "msg", "")
    assert code == cli.OK and "required: type a value" in shown
    assert "M131" in capsys.readouterr().err


def test_ask_without_terminal_is_a_usage_error(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "open_tty", lambda: None)
    (tmp_path / "d.bob.md").write_text("{{ x }}\n")
    assert cli.main(["print", str(tmp_path / "d.bob.md"), "--ask", "-o", str(tmp_path / "o")]) == cli.USAGE
