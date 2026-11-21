"""The terminal view shows what the paper shows: a line of text in a smaller font whole (the frame widens, as for a
table), a dotted rule as dots."""

from bobina import view
from bobina.engine import build

RECEIPT = (
    "SUPERMERCADO EXEMPLO SA F46 - LOJA 46 - Rio de Janeiro {font=Terminus size=16px}\n\n"
    "linha nativa curta\n\n--- {.dotted}\n\nfim\n"
)
SMALL_TABLE = "| Item | Valor |\n|---|---:|\n| ARROZ TIPO 1 PACOTE 5KG MARCA EXEMPLO DA CASA | 25,90 |\n"
QR_AND_TEXT = (
    ":::: {.columns valign=middle}\n::: {.column width=40%}\n```qr\nhttps://exemplo.com/consulta/276712\n```\n:::\n"
    "::: {.column width=60%}\nConsulte pela chave de acesso em www.fazenda.rj.gov.br/nfce/consulta "
    "{font=Terminus size=12px}\n:::\n::::\n"
)


def shown(doc: str) -> list[str]:
    res = build(doc, profile_name="mtp-ii-58")
    frame = view.width(res.rows, res.profile)
    lines = view.lines(res.rows, res.profile, frame=frame)
    assert all(len(ln) == frame for ln in lines)
    return lines


def test_a_line_in_a_smaller_font_shows_whole_as_on_paper():
    lines = shown(RECEIPT)
    assert lines[1].rstrip() == "SUPERMERCADO EXEMPLO SA F46 - LOJA 46 - Rio de"  # Terminus 16px: 48 letters a line
    assert lines[2].rstrip() == "Janeiro" and len(lines[1]) > 32  # the frame widens to it
    assert any(ln.rstrip() == "linha nativa curta" for ln in lines)


def test_a_line_in_a_smaller_font_shows_whole_in_a_frame_a_table_already_widened():
    lines = shown(SMALL_TABLE + "{font=Terminus size=12px}\n\n" + RECEIPT)
    assert len(lines[0]) > 48 and any("LOJA 46 - Rio de" in ln for ln in lines)


def test_text_in_a_smaller_font_beside_a_qr_code_shows_whole():
    lines = shown(QR_AND_TEXT)
    text = [ln for ln in lines if "Consulte" in ln or "fazenda" in ln]
    assert [ln[13:].rstrip() for ln in text] == [
        "Consulte pela chave de acesso em",
        "www.fazenda.rj.gov.br/nfce/consulta",
    ]
    assert all(any(0x2800 < ord(ch) <= 0x28FF for ch in ln[:13]) for ln in text)  # the QR beside them, in braille


def test_a_centred_line_in_a_smaller_font_is_centred_on_its_own_width():
    lines = shown("SUPERMERCADO EXEMPLO SA F46 - LOJA 46 - Rio de Janeiro {font=Terminus size=16px .center}\n")
    first, second = lines[1], lines[2]
    assert first.rstrip() == "SUPERMERCADO EXEMPLO SA F46 - LOJA 46 - Rio de"
    assert second.index("Janeiro") == (46 - 7) // 2


def test_a_dotted_rule_shows_as_sparse_dots():
    lines = shown("a\n\n--- {.dotted}\n\nb\n\n--- {.dashed}\n\nc\n")
    dotted = lines[lines.index("a".ljust(32)) + 1]
    dashed = lines[lines.index("b".ljust(32)) + 1]
    assert dotted.strip() and set(dotted) == {"⠂", " "} and dotted.count("⠂") == 16
    assert dashed.count("⠂") == 32  # a dashed rule stays as it was: denser than a dotted one


def test_the_dotted_rule_between_table_rows_shows():
    lines = shown("| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n{style=lines}\n")
    between = lines[[k for k, ln in enumerate(lines) if ln.startswith("1")][0] + 1]
    assert between.strip() and all(0x2800 <= ord(ch) <= 0x28FF or ch == " " for ch in between)
