"""The contact block: every network's link (what the printed QR holds, byte for byte), the forms people type for it
(a phone, @name, the app's link), the errors (Q112, the code left out), the untested note (P303), the caption, the
cards (vCard, MeCard: data never becomes another field) and the generated docs page."""

import json
from pathlib import Path

import pytest

from bobina import cli, contact
from bobina.engine import build
from bobina.rows import QRRow

ROOT = Path(__file__).resolve().parents[1]


def qr(doc: str, **kw) -> list[str]:
    res = build(doc, **kw)
    return [r.data for r in res.rows if isinstance(r, QRRow)]


def codes(res) -> list[str]:
    return [n.code for n in res.nudges]


def text(res) -> str:
    from bobina.rows import TextRow

    return "\n".join("".join(c.ch for c in r.cells) for r in res.rows if isinstance(r, TextRow))


LINKS = [  # (network, body, attributes, the link in the QR)
    ("whatsapp", "+55 11 90000-0000", "", "https://wa.me/5511900000000"),
    ("whatsapp", "0055 (11) 90000.0000", "", "https://wa.me/5511900000000"),
    ("whatsapp", "+55 11 90000-0000", '{text="Olá, quero um pote"}',
     "https://wa.me/5511900000000?text=Ol%C3%A1%2C%20quero%20um%20pote"),
    ("whatsapp", "https://wa.me/5511900000000", "", "https://wa.me/5511900000000"),
    ("whatsapp", "https://chat.whatsapp.com/AbCdEfGhIjK123", "", "https://chat.whatsapp.com/AbCdEfGhIjK123"),
    ("whatsapp", "whatsapp.com/channel/0029VaAbCdEf", "", "https://whatsapp.com/channel/0029VaAbCdEf"),
    ("whatsapp", "https://wa.me/c/5511900000000", "", "https://wa.me/c/5511900000000"),
    ("telegram", "@ana_souza", "", "https://t.me/ana_souza"),
    ("telegram", "https://t.me/ana_souza", "", "https://t.me/ana_souza"),
    ("telegram", "t.me/joinchat/AbCdEfGhIjKlMn", "", "https://t.me/+AbCdEfGhIjKlMn"),
    ("telegram", "+AbCdEfGhIjKlMn", "", "https://t.me/+AbCdEfGhIjKlMn"),
    ("telegram", "+55 11 90000-0000", "", "https://t.me/+5511900000000"),
    ("signal", "+55 11 90000-0000", "", "https://signal.me/#p/+5511900000000"),
    ("signal", "https://signal.me/#eu/AbCd-Ef_123", "", "https://signal.me/#eu/AbCd-Ef_123"),
    ("wechat", "https://u.wechat.com/kAbCdEfGhIj", "", "https://u.wechat.com/kAbCdEfGhIj"),
    ("line", "@linedevelopers", "", "https://line.me/R/ti/p/%40linedevelopers"),
    ("line", "https://line.me/ti/p/AbCdEf", "", "https://line.me/ti/p/AbCdEf"),
    ("viber", "+55 11 90000-0000", "", "viber://chat?number=%2B5511900000000"),
    ("kakao", "_xcLqmC", "", "https://pf.kakao.com/_xcLqmC"),
    ("kakao", "https://open.kakao.com/o/sAbCdEf", "", "https://open.kakao.com/o/sAbCdEf"),
    ("kakaotalk", "pf.kakao.com/_xcLqmC/chat", "", "https://pf.kakao.com/_xcLqmC/chat"),
    ("kik", "ana.souza", "", "https://kik.me/ana.souza"),
    ("messenger", "ana.souza", "", "https://m.me/ana.souza"),
    ("discord", "discord.gg/abcd1234", "", "https://discord.gg/abcd1234"),
    ("discord", "https://discord.com/invite/abcd1234", "", "https://discord.gg/abcd1234"),
    ("phone", "+55 11 90000-0000", "", "tel:+5511900000000"),
    ("sms", "+55 11 90000-0000", '{text="Pedido 42"}', "sms:+5511900000000?body=Pedido%2042"),
    ("email", "ana@example.com", '{subject="Orçamento"}', "mailto:ana@example.com?subject=Or%C3%A7amento"),
    ("instagram", "@ana.souza", "", "https://www.instagram.com/ana.souza/"),
    ("instagram", "https://www.instagram.com/ana.souza/", "", "https://www.instagram.com/ana.souza/"),
    ("facebook", "ana.souza", "", "https://www.facebook.com/ana.souza"),
    ("fb", "https://m.facebook.com/ana.souza", "", "https://www.facebook.com/ana.souza"),
    ("threads", "@ana.souza", "", "https://www.threads.com/@ana.souza"),
    ("threads", "https://www.threads.net/@ana.souza", "", "https://www.threads.com/@ana.souza"),
    ("tiktok", "@ana.souza", "", "https://www.tiktok.com/@ana.souza"),
    ("x", "@ana_souza", "", "https://x.com/ana_souza"),
    ("twitter", "https://twitter.com/ana_souza", "", "https://x.com/ana_souza"),
    ("youtube", "@anasouza", "", "https://www.youtube.com/@anasouza"),
    ("youtube", "UCabcdefghijklmnopqrstuv", "", "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv"),
    ("linkedin", "in/ana-souza", "", "https://www.linkedin.com/in/ana-souza/"),
    ("linkedin", "ana-souza", "", "https://www.linkedin.com/in/ana-souza/"),
    ("linkedin", "company/padaria-sol", "", "https://www.linkedin.com/company/padaria-sol/"),
    ("vk", "ana_souza", "", "https://vk.com/ana_souza"),
    ("snapchat", "ana.souza", "", "https://www.snapchat.com/add/ana.souza"),
    ("snapchat", "https://www.snapchat.com/add/ana.souza", "", "https://www.snapchat.com/add/ana.souza"),
    ("pinterest", "anasouza", "", "https://www.pinterest.com/anasouza/"),
    ("reddit", "u/ana_souza", "", "https://www.reddit.com/user/ana_souza/"),
    ("reddit", "r/bread", "", "https://www.reddit.com/r/bread/"),
    ("twitch", "anasouza", "", "https://www.twitch.tv/anasouza"),
    ("spotify", "https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF?si=abc", "",
     "https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF"),
    ("spotify", "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M", "", "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"),
    ("baidu", "https://tieba.baidu.com/f?kw=bread", "", "https://tieba.baidu.com/f?kw=bread"),
]  # fmt: skip


@pytest.mark.parametrize("network, body, attrs, link", LINKS, ids=[f"{n}-{i}" for i, (n, *_) in enumerate(LINKS)])
def test_the_qr_holds_the_network_link(network, body, attrs, link):
    assert qr(f"```contact {network} {attrs}\n{body}\n```\n") == [link]


def test_every_network_has_a_case_and_its_example_works():
    covered = {contact.find(n).name for n, *_ in LINKS} | {"vcard", "mecard"}
    assert covered == set(contact.NETWORKS)
    for n in contact.NETWORKS.values():  # the example of the help and the docs builds a code
        res = build(n.block + "\n")
        assert [r for r in res.rows if isinstance(r, QRRow)], n.name
        assert "Q112" not in codes(res), n.name


BAD = [  # (network, body, what the message or hint says)
    ("whatsapp", "11 90000-0000", "has no country code"),
    ("whatsapp", "+55 11", "is not a phone number"),
    ("whatsapp", "https://example.com/5511900000000", "is not a WhatsApp link"),
    ("telegram", "@ab", "is not a Telegram user name"),
    ("signal", "ana.01", "Signal links a user name only through its own link"),
    ("wechat", "ana_souza", "WeChat draws its contact QR itself"),
    ("line", "ana_souza", "LINE adds a personal ID only through its own link"),
    ("instagram", "ana souza", "is not an Instagram user name"),
    ("instagram", "https://evil.example/ana", "is not a instagram link"),
    ("x", "@this_name_is_far_too_long", "is not an X user name"),
    ("baidu", "ana", "Baidu has no public profile address"),
    ("spotify", "https://open.spotify.com/blah/1", "is not a Spotify link"),
    ("vcard", "phone: +55 11 90000-0000", "needs a name: line"),
    ("whatsapp", "", "needs a value in the block body"),
    ("nope", "x", "unknown network 'nope'"),
    ("instgram", "@ana", "did you mean instagram?"),
]


@pytest.mark.parametrize("network, body, says", BAD)
def test_a_wrong_value_gives_q112_with_what_to_write_and_leaves_the_code_out(network, body, says):
    res = build(f"```contact {network}\n{body}\n```\n\nThe rest prints\n")
    q = [n for n in res.nudges if n.code == "Q112"]
    assert q and says in (q[0].message + " " + (q[0].suggestion or ""))
    assert not [r for r in res.rows if isinstance(r, QRRow)]
    assert "The rest prints" in text(res)


def test_a_block_without_a_network_says_how_to_write_one():
    res = build("```contact\n+55 11 90000-0000\n```\n")
    assert any(n.code == "Q112" and "```contact whatsapp" in n.message for n in res.nudges)


def test_q112_exits_9_and_allow_makes_it_0(tmp_path):
    doc = tmp_path / "card.bob.md"
    doc.write_text("```contact whatsapp\n11 90000-0000\n```\n\nAna\n")
    out = tmp_path / "o.bin"
    assert cli.main(["print", str(doc), "-o", str(out), "--yes"]) == cli.LEFT_OUT
    assert cli.main(["print", str(doc), "-o", str(out), "--yes", "--force", "--allow", "Q112"]) == cli.OK


def test_caption_auto_none_and_custom():
    res = build("```contact whatsapp\n+55 11 90000-0000\n```\n")
    assert "WhatsApp +55 11 90000-0000" in text(res)
    assert "Instagram @ana.souza" in text(build("```contact instagram\nana.souza\n```\n"))
    assert "WhatsApp" not in text(build("```contact whatsapp {caption=none}\n+55 11 90000-0000\n```\n"))
    assert "Fale comigo" in text(build('```contact whatsapp {caption="Fale comigo"}\n+55 11 90000-0000\n```\n'))
    assert "Ana Souza" in text(build("```contact vcard\nname: Ana Souza\n```\n"))


def test_every_network_is_untested_and_says_so_with_what_reads_it():
    res = build("```contact snapchat\nana.souza\n```\n")
    p = [n for n in res.nudges if n.code == "P303"]
    assert p and "Snapchat app" in p[0].message and "Snapcode" in p[0].message and contact.MARK in p[0].message
    card = [n for n in build("```contact vcard\nname: Ana\n```\n").nudges if n.code == "P303"]
    assert card and "a phone camera" in card[0].message


def test_an_unknown_attribute_names_the_ones_the_network_takes():
    res = build('```contact instagram {text="hi"}\nana\n```\n')
    m = [n for n in res.nudges if n.code == "M101"]
    assert m and "does not use 'text='" in m[0].message and "caption" in m[0].suggestion
    assert qr("```contact instagram {size=half module=6}\nana\n```\n") == ["https://www.instagram.com/ana/"]


def test_only_the_first_line_is_a_value():
    res = build("```contact instagram\nana\nbeto\n```\n")
    assert [r.data for r in res.rows if isinstance(r, QRRow)] == ["https://www.instagram.com/ana/"]
    assert any(n.code == "M101" and "only the first line" in n.message for n in res.nudges)


# ---------------------------------------------------------------- cards


def test_vcard_has_the_fields_phones_read():
    [card] = qr("```contact vcard\nname: Ana Souza\nphone: +55 11 90000-0000\nphone: +55 11 3456-7890\n"
                "email: ana@example.com\norg: Padaria Sol\ntitle: Gerente\nurl: https://example.com\n"
                "address: Rua A, 10, São Paulo\nnote: Encomendas até 18h\n```\n")  # fmt: skip
    assert card == "\r\n".join([
        "BEGIN:VCARD", "VERSION:3.0", "N:Souza;Ana;;;", "FN:Ana Souza", "ORG:Padaria Sol", "TITLE:Gerente",
        "TEL;TYPE=CELL:+55 11 90000-0000", "TEL;TYPE=CELL:+55 11 3456-7890", "EMAIL:ana@example.com",
        "URL:https://example.com", "ADR:;;Rua A\\, 10\\, São Paulo;;;;", "NOTE:Encomendas até 18h", "END:VCARD",
    ])  # fmt: skip


def test_mecard():
    [card] = qr("```contact mecard\nname: Ana Souza\nphone: +55 11 90000-0000\nemail: ana@example.com\n```\n")
    assert card == "MECARD:N:Souza,Ana;TEL:+55 11 90000-0000;EMAIL:ana@example.com;;"


def test_data_never_becomes_another_card_field():
    doc = "```contact vcard\nname: {{ name }}\nnote: {{ note }}\n```\n"
    [card] = qr(doc, fields={"name": "Ana;Souza", "note": "x\nTEL:+1 555 0100"})
    assert "TEL:" not in card.replace("NOTE:x\\nTEL", "")  # the new line in the value is escaped, not a field
    assert "FN:Ana\\;Souza" in card
    [me] = qr("```contact mecard\nname: {{ name }}\n```\n", fields={"name": "Ana;TEL:1"})
    assert me == "MECARD:N:Ana\\;TEL\\:1;;"


def test_a_card_line_bobina_does_not_know_is_said():
    res = build("```contact vcard\nname: Ana\nbirthday: 1990-01-01\n```\n")
    assert any(n.code == "M101" and "is not a card line" in n.message for n in res.nudges)


def test_values_from_data_fill_the_block():
    assert qr("```contact whatsapp\n{{ phone }}\n```\n", fields={"phone": "+55 11 90000-0000"}) == [
        "https://wa.me/5511900000000"
    ]
    assert qr("```contact {{ net }}\n@ana\n```\n", fields={"net": "instagram"}) == ["https://www.instagram.com/ana/"]


# ---------------------------------------------------------------- help and docs


def test_help_contact_lists_networks_and_one_network(capsys):
    assert cli.main(["help", "contact"]) == cli.OK
    out = capsys.readouterr().out
    assert "whatsapp" in out and "vcard" in out and "P303" in out
    assert cli.main(["help", "contact", "twitter"]) == cli.OK  # an alias names the network
    assert "contact x" in capsys.readouterr().out
    assert cli.main(["help", "contact", "whatsap"]) == cli.USAGE
    assert "did you mean whatsapp" in capsys.readouterr().err
    assert cli.main(["help", "contact", "signal", "--json"]) == cli.OK
    j = json.loads(capsys.readouterr().out)
    assert j["kind"] == "contact-network" and j["network"] == "signal" and not j["tested_in_app"]


def test_the_docs_page_is_generated_from_the_registry():
    page = (ROOT / "docs" / "contact.md").read_text(encoding="utf-8")
    assert page == contact.docs_page(), "run: python tools/gen_contact_docs.py"


def test_every_network_says_where_its_link_format_is_documented():
    for n in contact.NETWORKS.values():
        assert n.source, n.name


def test_tested_md_lists_the_contact_networks():
    tested = (ROOT / "docs" / "TESTED.md").read_text(encoding="utf-8")
    assert "## Contact codes" in tested and "P303" in tested


# ---------------------------------------------------------------- review fixes


@pytest.mark.parametrize("network, body, link", [
    ("messenger", "https://m.me/ana.souza", "https://m.me/ana.souza"),
    ("facebook", "https://www.facebook.com/profile.php?id=1000123", "https://www.facebook.com/profile.php?id=1000123"),
    ("whatsapp", "https://wa.me/+5511900000000", "https://wa.me/5511900000000"),
    ("whatsapp", "https://wa.me/5511900000000?text=oi", "https://wa.me/5511900000000?text=oi"),
    ("youtube", "https://www.youtube.com/@anasouza", "https://www.youtube.com/@anasouza"),
])  # fmt: skip
def test_links_the_apps_share_are_kept(network, body, link):
    assert qr(f"```contact {network}\n{body}\n```\n") == [link]


@pytest.mark.parametrize("network, body, says", [
    ("signal", "11 90000-0000", "has no country code"),
    ("youtube", "https://youtube.com/watch?v=abc", "is not a YouTube channel link"),
    ("facebook", "https://www.facebook.com/profile.php", "has no profile id"),
])  # fmt: skip
def test_more_values_that_make_no_link(network, body, says):
    q = [n for n in build(f"```contact {network}\n{body}\n```\n").nudges if n.code == "Q112"]
    assert q and says in q[0].message


@pytest.mark.parametrize("info", ["contact whatsapp business", "contact @ana.souza", "contact whats app {size=half}"])
def test_a_contact_line_bobina_cannot_split_is_q112_never_text(info):
    res = build(f"```{info}\n+55 11 90000-0000\n```\n")
    assert "Q112" in codes(res) and "M102" not in codes(res)
    assert "90000" not in text(res)  # the value is not printed as plain text


def test_text_on_a_group_link_is_said():
    res = build('```contact whatsapp {text="Olá"}\nhttps://chat.whatsapp.com/AbC123\n```\n')
    assert any(n.code == "M101" and "text= works on a phone chat only" in n.message for n in res.nudges)
