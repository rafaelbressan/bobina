"""The pay block: payloads byte for byte against published reference examples (the source is next to each), the
errors (Q111 with an example, nothing printed), the untested note (P302) and the caption."""

import pytest

from bobina import pay
from bobina.engine import build
from bobina.rows import QRRow

# ---------------------------------------------------------------- reference vectors

# dtinth/promptpay-qr, index.test.js (commit a9e4f2d), the reference PromptPay implementation
PROMPTPAY = [
    ("0801234567", None, "00020101021129370016A000000677010111011300668012345675802TH530376463046197"),
    ("080-123-4567", None, "00020101021129370016A000000677010111011300668012345675802TH530376463046197"),
    ("+66-89-123-4567", None, "00020101021129370016A000000677010111011300668912345675802TH5303764630429C1"),
    ("000-000-0000", 4.22, "00020101021229370016A000000677010111011300660000000005802TH530376454044.226304E469"),
    ("1111111111111", None, "00020101021129370016A000000677010111021311111111111115802TH530376463047B5A"),
    ("0123456789012", None, "00020101021129370016A000000677010111021301234567890125802TH530376463040CBD"),
    ("012345678901234", None, "00020101021129390016A00000067701011103150123456789012345802TH530376463049781"),
]


@pytest.mark.parametrize("to, amount, expected", PROMPTPAY)
def test_promptpay_matches_the_reference_implementation(to, amount, expected):
    assert pay.SCHEMES["promptpay"].build({"to": to}, amount) == expected


def test_paynow_matches_a_published_charity_code():
    # daffodilistic/pyPayNowSg tests/test_payload.py: reproduces IMH's published PayNow QR (UEN, editable amount)
    kv = {"to": "200002150HWCF", "name": "NATIONAL HEALTHCARE GRO"}
    expected = (
        "00020101021126400009SG.PAYNOW010120213200002150HWCF030115204000053037025802SG"
        "5923NATIONAL HEALTHCARE GRO6009Singapore6304DF3F"
    )
    assert pay.SCHEMES["paynow"].build(kv, None) == expected


def test_epc_matches_the_example_of_the_epc_guidelines():
    # EPC069-12 v3.0, version 002 example; the document uses character set 2 (ISO 8859-1), bobina always 1 (UTF-8)
    kv = {"to": "FR1420041010050500013M02606", "name": "François D'Alsace S.A.", "note": "Client:Marie Louise La Lune"}
    got = pay.SCHEMES["epc"].build(kv, 12.3)
    expected = "\n".join(
        ["BCD", "002", "2", "SCT", "", "François D'Alsace S.A.", "FR1420041010050500013M02606", "EUR12.3", "", "",
         "Client:Marie Louise La Lune"]
    )  # fmt: skip
    assert got.split("\n")[2] == "1" and got.replace("\n1\n", "\n2\n", 1) == expected


def test_epc_ends_at_the_last_filled_field_and_takes_a_creditor_reference():
    got = pay.SCHEMES["epc"].build({"to": "DE71110220330123456789", "name": "Franz Mustermänn"}, None)
    assert got.endswith("DE71110220330123456789")  # no amount, no reference: nothing after the IBAN
    got = pay.SCHEMES["epc"].build({"to": "DE71110220330123456789", "name": "F", "ref": "RF18539007547034"}, 12.3)
    assert got.split("\n")[-1] == "RF18539007547034"  # the EPC v1 example's structured reference


@pytest.mark.parametrize(
    "kv, amount, expected",
    [  # BIP-0021 examples
        ({"to": "175tWpb8K1S7NmH4Zx6rewF9WQrcZv245W"}, None, "bitcoin:175tWpb8K1S7NmH4Zx6rewF9WQrcZv245W"),
        ({"to": "175tWpb8K1S7NmH4Zx6rewF9WQrcZv245W", "name": "Luke-Jr"}, 20.3,
         "bitcoin:175tWpb8K1S7NmH4Zx6rewF9WQrcZv245W?amount=20.3&label=Luke-Jr"),
        ({"to": "175tWpb8K1S7NmH4Zx6rewF9WQrcZv245W", "name": "Luke-Jr", "note": "Donation for project xyz"}, 50,
         "bitcoin:175tWpb8K1S7NmH4Zx6rewF9WQrcZv245W?amount=50&label=Luke-Jr&message=Donation%20for%20project%20xyz"),
    ],
)  # fmt: skip
def test_bitcoin_matches_bip21(kv, amount, expected):
    assert pay.SCHEMES["bitcoin"].build(kv, amount) == expected


def test_upi_follows_the_linking_spec():
    kv = {"to": "shop@okbank", "name": "Chai Point", "note": "Order 42"}
    got = pay.SCHEMES["upi"].build(kv, 120)
    assert got == "upi://pay?pa=shop@okbank&pn=Chai%20Point&am=120.00&cu=INR&tn=Order%2042"


def test_pix_is_unchanged():
    from bobina import codes

    kv = {"to": "you@example.com", "name": "Shop", "city": "Rio"}
    assert pay.SCHEMES["pix"].build(kv, 10.0) == codes.pix_payload("you@example.com", "Shop", "Rio", "10.00")


@pytest.mark.parametrize(
    "scheme, kv, amount, expected",
    [
        ("paypal", {"to": "paypal.me/yourname", "currency": "usd"}, 25, "https://paypal.me/yourname/25.00USD"),
        ("cashapp", {"to": "yourtag"}, None, "https://cash.app/$yourtag"),
        (
            "venmo",
            {"to": "@yourname", "note": "Coffee"},
            4,
            "https://venmo.com/yourname?txn=pay&amount=4.00&note=Coffee",
        ),
        ("revolut", {"to": "https://revolut.me/yourname"}, None, "https://revolut.me/yourname"),
        ("lightning", {"to": "lnbc1pvjluezpp5"}, None, "lightning:LNBC1PVJLUEZPP5"),
    ],
)
def test_profile_links(scheme, kv, amount, expected):
    assert pay.SCHEMES[scheme].build(kv, amount) == expected


# ---------------------------------------------------------------- through the document


def _codes(res):
    return [n.code for n in res.nudges]


def _text(res):
    return "".join(c.ch for r in res.rows for c in getattr(r, "cells", [])).replace("\xa0", " ")


def test_any_qr_takes_a_caption():
    res = build('```qr {caption="Cardápio"}\nhttps://example.com/menu\n```\n')
    assert "Cardápio" in _text(res) and not [n for n in res.nudges if n.code == "M101"]
    assert "Cardápio" not in _text(build("```qr\nhttps://example.com/menu\n```\n"))  # no caption by default


def test_the_caption_says_the_scheme_and_the_amount():
    res = build('---\nlocale: pt-BR\n---\n```pay {scheme=pix to="you@example.com" amount=10}\n```\n')
    assert "Pix · R$ 10,00" in _text(res) and "P302" not in _codes(res)  # Pix was scanned by banking apps


def test_caption_none_and_custom():
    doc = '```pay {scheme=upi to="shop@okbank" name="N" amount=1 caption=%s}\n```\n'
    none, custom = build(doc % "none"), build(doc % '"Scan to pay"')
    assert [r for r in none.rows if isinstance(r, QRRow)] and "UPI" not in _text(none)
    assert "Scan to pay" in _text(custom)


def test_an_untested_scheme_gets_p302_and_still_prints():
    res = build('```pay {scheme=upi to="shop@okbank" name="Chai" amount=120}\n```\n')
    assert "P302" in _codes(res) and [r for r in res.rows if isinstance(r, QRRow)]


@pytest.mark.parametrize(
    "block, says",
    [
        ('```pay {scheme=upii to="a@b"}\n```', "did you mean scheme=upi"),
        ('```pay {to="a@b"}\n```', "pay needs scheme="),
        ('```pay {scheme=epc to="DE00 3704 0044 0532 0130 00" name="X"}\n```', "check digit"),
        ('```pay {scheme=upi to="shop" name="X"}\n```', "UPI ID"),
        ('```pay {scheme=upi to="shop@okbank"}\n```', "needs name="),
        ('```pay {scheme=pix to="a@b.c" amount=10.0055}\n```', "more than 2 decimals"),
        ('```pay {scheme=pix to="a@b.c" amount=1.890}\n```', "could mean 1890 or 1.89"),
        ('---\nlang: en\n---\n```pay {scheme=pix to="a@b.c" amount="R$ 1.890"}\n```', "could mean 1890 or 1.89"),
        ('```pay {scheme=pix to="a@b.c" amount="dez"}\n```', "is not a number"),
        ('```pay {scheme=epc to="DE71110220330123456789" name="X" ref="RF18539007547034" note="y"}\n```', "not both"),
    ],
)
def test_a_wrong_or_missing_attribute_gives_q111_with_the_fix_and_prints_nothing(block, says):
    res = build(block + "\n")
    q = [n for n in res.nudges if n.code == "Q111"]
    assert q and says in (q[0].message + " " + (q[0].suggestion or ""))
    assert not [r for r in res.rows if isinstance(r, QRRow)]


def test_an_attribute_the_scheme_does_not_use_names_the_ones_it_does():
    res = build('```pay {scheme=promptpay to="0812345678" bic=X}\n```\n')
    m = [n for n in res.nudges if n.code == "M101"]
    assert m and "takes to, name, amount" in m[0].suggestion


def test_other_reprints_the_pasted_payload_with_its_label():
    res = build('```pay {scheme=other label="WeChat Pay"}\nwxp://f2f0abc\n```\n')
    assert "WeChat Pay" in _text(res) and "P302" in _codes(res)
    assert [r for r in res.rows if isinstance(r, QRRow)]


def test_amount_from_data_per_row():
    res = build('```pay {scheme=pix to="a@b.c" amount="{{ total }}"}\n```\n', fields={"total": "12,50"})
    assert "12,50" in _text(res) or "12.50" in _text(res)


def test_every_scheme_is_in_the_docs_and_help():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    fmt = (root / "docs" / "FORMAT.md").read_text(encoding="utf-8")
    tested = (root / "docs" / "TESTED.md").read_text(encoding="utf-8")
    text = pay.help_text()
    for name in pay.SCHEMES:
        assert f"`{name}`" in fmt and f"`{name}`" in tested and name in text, name


# ---------------------------------------------------------------- review of 48cf490


def test_paynow_counts_bytes_not_characters():
    got = pay.SCHEMES["paynow"].build({"to": "201403121W", "name": "Kopi Café"}, None)
    assert "5909Kopi Cafe" in got  # tag 59, 9 bytes: the accent became a plain letter


@pytest.mark.parametrize(
    "scheme, kv",
    [
        ("paynow", {"to": "201403121W", "name": "K", "ref": "ORDER-2026-11-08-000123456"}),  # 26 > 25
        ("promptpay", {"to": "0123456789012345"}),  # 16 digits: not an e-wallet ID (15)
    ],
)
def test_a_value_that_does_not_fit_is_refused_not_cut(scheme, kv):
    with pytest.raises(pay.PayError):
        pay.SCHEMES[scheme].build(kv, None)


def test_amount_zero_is_an_open_amount_as_pix_always_took_it():
    res = build('```pay {scheme=pix to="a@b.c" amount=0}\n```\n')
    assert [r for r in res.rows if isinstance(r, QRRow)] and "Q111" not in _codes(res)


def test_an_amount_the_code_cannot_carry_is_a_note_not_a_warning():
    res = build('```pay {scheme=cashapp to="yourtag" amount=10 name="Shop"}\n```\n')
    warnings = [n.code for n in res.nudges if n.severity == "warning"]
    assert "M156" in _codes(res) and not warnings


def test_a_misspelt_key_is_reported_once_and_other_blocks_still_check_theirs():
    res = build('```pay {scheme=upi to="shop@okbank" name="X" foo=1 #pay1}\n```\n\n```qr {labell=x}\nhi\n```\n')
    m = [n.message for n in res.nudges if n.code == "M101"]
    assert sum("foo" in x for x in m) == 1 and any("labell" in x for x in m) and not any("id" in x for x in m)


def test_the_receipt_takes_any_scheme_without_warnings():
    doc = (
        "---\ntemplate: receipt\nlocale: en\nshop: s\npay_scheme: promptpay\npay_to: '0812345678'\n"
        "items:\n  - [Tea, 1, 40]\n---\n"
    )
    res = build(doc)
    assert not [n for n in res.nudges if n.severity == "warning"] and [r for r in res.rows if isinstance(r, QRRow)]


def test_pix_without_an_amount_is_an_open_code_the_payer_fills():
    res = build('---\nlocale: pt-BR\n---\n```pay {scheme=pix to="you@example.com" name="Café Sol" city="Rio"}\n```\n')
    payload = pay.SCHEMES["pix"].build({"to": "you@example.com", "name": "Café Sol", "city": "Rio"}, None)
    assert "54" not in payload.split("5303986")[1][:2]  # no tag 54 (amount) after the currency
    assert "Pix · Café Sol" in _text(res) and not [n for n in res.nudges if n.severity == "warning"]


# ---------------------------------------------------------------- review of dcf367e


@pytest.mark.parametrize("off", ["none", "no", "false", '""'])
def test_every_off_word_turns_the_caption_off(off):
    res = build(f'```pay {{scheme=pix to="a@b.c" amount=10 caption={off}}}\n```\n')
    assert [r for r in res.rows if isinstance(r, QRRow)] and _text(res).strip() == ""


def test_caption_auto_on_a_plain_qr_prints_nothing_and_a_computed_none_is_kept():
    assert "auto" not in _text(build("```qr {caption=auto}\nhi\n```\n"))
    res = build('```pay {scheme=other name="none"}\nwxp://x\n```\n')
    assert "none" in _text(res)  # the automatic caption is text, never a keyword


def test_caption_is_checked_on_blocks_that_do_not_take_it():
    res = build('```text {caption="Order"}\nABC\n```\n')
    assert any("caption" in n.message for n in res.nudges if n.code == "M101")


def test_the_old_pix_block_warns_once_with_the_way_to_write_it():
    res = build('```pix {key="a@b.c" amount=10}\n```\n')
    warnings = [n.code for n in res.nudges if n.severity == "warning"]
    assert "Q111" in warnings and "M101" not in warnings


def test_old_pix_names_on_pay_say_their_new_names():
    res = build('```pay {scheme=pix key="a@b.c"}\n```\n')
    assert any("write to=" in (n.suggestion or "") for n in res.nudges if n.code == "M101")


def test_the_receipt_says_when_an_old_field_name_is_used():
    doc = "---\ntemplate: receipt\nshop: s\nitems:\n  - [a, 1, 2]\npix: a@b.c\n---\n"
    m = [n for n in build(doc).nudges if n.code == "M101"]
    assert m and "pay_to" in m[0].message


@pytest.mark.parametrize(
    "key, normalized",
    [("529.982.247-25", "52998224725"), ("11.222.333/0001-81", "11222333000181"),  # leak-ok: well-known test CPF/CNPJ and a fake phone
     ("+55 (11) 99999-8888", "+5511999998888"), ("123E4567-E12B-12D1-A456-426655440000",  # leak-ok: well-known test CPF/CNPJ and a fake phone
     "123e4567-e12b-12d1-a456-426655440000"), ("you@example.com", "you@example.com")],
)  # fmt: skip
def test_pix_keys_are_normalized(key, normalized):
    assert pay.pix_key(key) == normalized


@pytest.mark.parametrize("key", ["52998224724", "DE89 3704 0044 0532 0130 00", "11999998888", "k" * 30])
def test_what_is_not_a_pix_key_is_refused(key):
    with pytest.raises(pay.PayError):
        pay.pix_key(key)


# ---------------------------------------------------------------- consulting the fields (help pay SCHEME, docs/pay.md)


def test_the_payment_docs_page_is_current():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("gen", root / "tools" / "gen_pay_docs.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.PAGE.read_text(encoding="utf-8") == pay.docs_page(), "run: python tools/gen_pay_docs.py"


@pytest.mark.parametrize("name", list(pay.SCHEMES))
def test_every_field_of_every_scheme_says_what_it_means(name):
    s = pay.SCHEMES[name]
    assert s.fields and all(f.means for f in s.fields.values())
    assert set(s.required) <= set(s.fields)
    card = pay.help_scheme(name)
    assert all(f"{k}=" in card for k in s.fields) and max(len(line) for line in card.split("\n")[2:]) <= 110


def test_help_pay_scheme_from_the_command_line(capsys):
    import json

    from bobina import cli

    assert cli.main(["help", "pay", "pix"]) == cli.OK
    out = capsys.readouterr().out
    assert "descrição" in out and "73 minus the key" in out  # the card wraps text inside its columns
    assert cli.main(["help", "pay", "pix", "--json"]) == cli.OK
    data = json.loads(capsys.readouterr().out)
    assert data["kind"] == "pay-scheme" and data["fields"]["note"]["official"] == "26.02 descrição"
    assert cli.main(["help", "pay", "pixx"]) == cli.USAGE
    assert "did you mean pix" in capsys.readouterr().err
    assert cli.main(["help", "format", "pix"]) == cli.USAGE


@pytest.mark.parametrize(
    "attrs, says",
    [
        ('to="you@example.com" name="' + "N" * 26 + '"', "name has 26 characters; Pix allows 25"),
        ('to="you@example.com" city="' + "C" * 16 + '"', "city has 16 characters; Pix allows 15"),
        ('to="you@example.com" ref="PED-42"', "letters and digits only"),
        ('to="you@example.com" note="' + "x" * 60 + '"', "allows 58"),  # 73 - 15 characters of key
    ],
)
def test_pix_limits_are_errors_with_the_room_left_never_cuts(attrs, says):
    res = build("```pay {scheme=pix " + attrs + "}\n```\n")
    q = [n for n in res.nudges if n.code == "Q111"]
    assert q and says in q[0].message and "bobina help pay pix" in q[0].suggestion


def test_a_long_pix_note_that_fits_is_kept_whole():
    note = "x" * 58  # the old code cut every description at 40
    payload = pay.SCHEMES["pix"].build({"to": "you@example.com", "note": note}, None)
    assert note in payload


# ---------------------------------------------------------------- review of 176769e


@pytest.mark.parametrize("field", ["name", "city", "note"])
def test_letters_pix_cannot_carry_are_refused_not_dropped(field):
    with pytest.raises(pay.PayError, match="cannot carry"):
        pay.SCHEMES["pix"].build({"to": "you@example.com", field: "山田"}, None)


def test_accents_still_become_plain_letters():
    assert "5908Cafe Sol" in pay.SCHEMES["pix"].build({"to": "you@example.com", "name": "Café Sol"}, None)


def test_ref_stars_is_the_official_no_txid():
    assert pay.SCHEMES["pix"].build({"to": "you@example.com", "ref": "***"}, None).count("0503***") == 1


def test_a_key_that_leaves_no_room_for_a_note_says_so():
    key = "a" * 63 + "@example.com"  # 75 characters
    with pytest.raises(pay.PayError, match="no room for note"):
        pay.SCHEMES["pix"].build({"to": key, "note": "x"}, None)


def test_pix_payload_never_cuts_a_description():
    from bobina import codes

    with pytest.raises(ValueError, match="allows 58"):
        codes.pix_payload("you@example.com", "N", "BRASIL", None, "***", "x" * 70)


def test_the_json_keeps_the_keys_programs_already_read():
    s = pay.schemes_json()[0]
    assert {"to", "required", "attributes", "fields", "example"} <= set(s)


def test_every_example_block_works_as_copied():
    for s in pay.SCHEMES.values():
        res = build(s.block + "\n")
        assert not [n for n in res.nudges if n.severity == "warning"], (s.name, [n.message for n in res.nudges])


def test_the_required_footnote_only_where_something_is_required():
    assert "* required" not in pay.help_scheme("other") and "* required" in pay.help_scheme("pix")


def test_help_topic_in_capitals(capsys):
    from bobina import cli

    assert cli.main(["help", "PAY", "pix"]) == cli.OK


@pytest.mark.parametrize("scheme, kv", [("paynow", {"to": "201403121W", "name": "N" * 26}),
                                        ("epc", {"to": "DE71110220330123456789", "name": "N" * 71})])  # fmt: skip
def test_every_limit_says_how_much_to_cut(scheme, kv):
    with pytest.raises(pay.PayError) as e:
        pay.SCHEMES[scheme].build(kv, None)
    assert e.value.hint == "cut 1"


# ---------------------------------------------------------------- every scheme, not only Pix


def _build(scheme, kv, amount=None):
    return pay.SCHEMES[scheme].build(kv, amount)


@pytest.mark.parametrize(
    "scheme, to, expected",
    [
        ("wise", "https://wise.com/pay/me/yourtag", "https://wise.com/pay/me/yourtag"),
        ("mercadopago", "https://link.mercadopago.com.br/yourshop", "https://link.mercadopago.com.br/yourshop"),
        ("mercadopago", "https://mpago.la/2abc3De", "https://mpago.la/2abc3De"),
        ("picpay", "seunome", "https://picpay.me/seunome"),
        ("picpay", "https://picpay.me/seunome", "https://picpay.me/seunome"),
        ("revolut", "revolut.me/yourname", "https://revolut.me/yourname"),
        ("cashapp", "https://cash.app/$yourtag", "https://cash.app/$yourtag"),
        ("paypal", "https://www.paypal.me/yourname", "https://paypal.me/yourname"),
    ],
)
def test_profile_links_accept_a_name_or_the_full_link(scheme, to, expected):
    assert _build(scheme, {"to": to}) == expected


@pytest.mark.parametrize(
    "scheme, to",
    [
        ("wise", "https://example.com/pay/me/x"),  # another site: never print someone else's link as Wise
        ("wise", "http://wise.com/pay/me/x"),  # not https
        ("mercadopago", "https://mercadopago.example.com/x"),
        ("mercadopago", "link.mercadopago.com.br/yourshop"),  # the link must be whole (https://)
        ("picpay", "seu nome"),  # a space is not a user name
        ("venmo", "you/../admin"),
        ("paypal", "a" * 65),
    ],
)
def test_profile_links_refuse_what_is_not_theirs(scheme, to):
    with pytest.raises(pay.PayError):
        _build(scheme, {"to": to})


def test_paypal_currency_must_be_three_letters():
    with pytest.raises(pay.PayError, match="3-letter"):
        _build("paypal", {"to": "you", "currency": "dollars"}, 10)
    assert _build("paypal", {"to": "you"}, 10) == "https://paypal.me/you/10.00"  # the account's own currency


def test_venmo_without_amount_or_note_is_the_plain_profile():
    assert _build("venmo", {"to": "you"}) == "https://venmo.com/you"


@pytest.mark.parametrize(
    "to, expected",
    [
        ("lnbc2500u1pvjluezpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypq",
         "lightning:LNBC2500U1PVJLUEZPP5QQQSYQCYQ5RQWZQFQQQSYQCYQ5RQWZQFQQQSYQCYQ5RQWZQFQYPQ"),
        ("LNURL1DP68GURN8GHJ7UM9WFMXJCM99E3K7MF0V9CXJ0M385EKVCENXC6R2C35XVUKXEFCV5MKVV34X5EKZD3EV56NYD3HXQURZEPEXEJXXEPNXSCRVWFNV9NXZCN9XQ6XYEFHVGCXXCMYXYMNSERXFQ5FNS",
         "lightning:LNURL1DP68GURN8GHJ7UM9WFMXJCM99E3K7MF0V9CXJ0M385EKVCENXC6R2C35XVUKXEFCV5MKVV34X5EKZD3EV56NYD3HXQURZEPEXEJXXEPNXSCRVWFNV9NXZCN9XQ6XYEFHVGCXXCMYXYMNSERXFQ5FNS"),
        ("you@wallet.example", "lightning:you@wallet.example"),
    ],
)  # fmt: skip
def test_lightning_invoice_lnurl_and_address(to, expected):
    assert _build("lightning", {"to": to}) == expected


@pytest.mark.parametrize("to", ["bitcoin:bc1q…", "lnbc 2500", "not-an-address"])
def test_lightning_refuses_what_a_wallet_cannot_read(to):
    with pytest.raises(pay.PayError):
        _build("lightning", {"to": to})


def test_upi_encodes_spaces_ampersands_and_accents():
    got = _build("upi", {"to": "shop.42@okbank", "name": "Chá & Café", "note": "Order #42 / table 3"}, 99.5)
    assert got == (
        "upi://pay?pa=shop.42@okbank&pn=Ch%C3%A1%20%26%20Caf%C3%A9&am=99.50&cu=INR&tn=Order%20%2342%20%2F%20table%203"
    )  # one & per parameter: an & in a value can never start a new one


def test_upi_without_amount_lets_the_payer_type_it():
    assert "am=" not in _build("upi", {"to": "shop@okbank", "name": "X"}) and "cu=" not in _build(
        "upi", {"to": "shop@okbank", "name": "X"}
    )


def test_epc_with_bic_and_a_bad_bic():
    got = _build("epc", {"to": "DE89 3704 0044 0532 0130 00", "name": "X", "bic": "cobadeffxxx"}, None)
    assert got.split("\n")[4] == "COBADEFFXXX" and got.split("\n")[6] == "DE89370400440532013000"
    with pytest.raises(pay.PayError, match="BIC"):
        _build("epc", {"to": "DE89370400440532013000", "name": "X", "bic": "COBA"}, None)


def test_epc_amount_range_and_a_non_rf_ref_joins_the_text():
    with pytest.raises(pay.PayError, match="out of range"):
        _build("epc", {"to": "DE89370400440532013000", "name": "X"}, 1_000_000_000.0)
    got = _build("epc", {"to": "DE89370400440532013000", "name": "X", "ref": "INV-42", "note": "thanks"}, None)
    assert got.split("\n")[-1] == "INV-42 thanks" and got.split("\n")[9] == ""  # no structured reference


def test_paynow_mobile_proxy_and_a_fixed_amount():
    got = _build("paynow", {"to": "+65 8123 4567", "name": "Kopi Corner", "ref": "A42"}, 4.5)
    assert "0101" + "0" in got  # 26.01 proxy type 0: mobile
    assert "0211+6581234567" in got  # 26.02 the mobile with +65
    assert "03010" in got and "010212" in got and "54044.50" in got  # amount fixed: not editable, dynamic code
    assert got.endswith(pay.codes.crc16(got[:-4]))
    assert "62070103A42" in got  # 62 (7 characters) holding 62.01 bill number A42


def test_paynow_refuses_what_is_neither_a_uen_nor_a_mobile():
    with pytest.raises(pay.PayError):
        _build("paynow", {"to": "+55 11 99999-8888", "name": "X"})  # leak-ok: a fake Brazilian phone


def test_promptpay_amount_and_every_emv_code_carries_a_valid_crc():
    got = _build("promptpay", {"to": "0812345678"}, 120)
    assert "010212" in got and "5406120.00" in got
    for s, kv in [("pix", {"to": "you@example.com"}), ("promptpay", {"to": "0812345678"}),
                  ("paynow", {"to": "201403121W", "name": "K"})]:  # fmt: skip
        code = _build(s, kv)
        assert code[-8:-4] == "6304" and code[-4:] == pay.codes.crc16(code[:-4]), s


def test_bitcoin_refuses_a_wrong_address_and_too_many_decimals():
    with pytest.raises(pay.PayError):
        _build("bitcoin", {"to": "0x52908400098527886E0F7030069857D2E4169EE7"})  # an ethereum address
    res = build('```pay {scheme=bitcoin to="bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq" amount=0.000000001}\n```\n')
    assert any("more than 8 decimals" in n.message for n in res.nudges if n.code == "Q111")


def test_money_is_written_in_the_jobs_one_locale():
    # never as the currency's country does: a caption next to an English date reads R$10.00, a pt-BR one R$ 10,00
    pix = '```pay {scheme=pix to="you@example.com" amount=10}\n```\n'
    assert "Pix · R$10.00" in _text(build(pix))  # the engine alone, without a locale: English
    assert "Pix · R$ 10,00" in _text(build(pix, locale="pt-BR"))  # the machine's
    assert "Pix · R$10.00" in _text(build("---\nlocale: en\n---\n" + pix, locale="pt-BR"))  # the document's wins
    assert "₹120.00" in _text(build('```pay {scheme=upi to="shop@okbank" name="N" amount=120}\n```\n', locale="en-IN"))
    usd = build("{{ 24.9 | currency('USD') }} {{ today | date('short') }}\n", locale="pt-BR")
    assert "US$ 24,90 05/11/2026" in _text(usd)


def test_a_template_price_in_brl_without_a_locale(capsys):
    from bobina.engine import build as b

    assert "R$24.90" in _text(b("{{ 24.9 | currency }}\n"))
    assert "R$ 24,90" in _text(b("---\nlocale: pt-BR\n---\n{{ 24.9 | currency }}\n"))


def test_a_bad_cpf_is_not_only_about_phones():
    with pytest.raises(pay.PayError) as e:
        pay.pix_key("123.456.789-00")  # leak-ok: made-up CPF, its check digits are wrong on purpose
    assert "check the CPF" in e.value.hint


def test_the_legend_of_help_pay_says_the_mark_once():
    assert "⚠ = ⚠" not in pay.help_text()


def test_a_brl_price_is_read_as_brazilians_type_it():
    # a document that says pt-BR means thousands; elsewhere (even with the machine's pt-BR) 1.890 is printed as typed
    assert "R$ 1.890,00" in _text(build('---\nlocale: pt-BR\n---\n{{ "1.890" | currency }}\n'))
    res = build('{{ "1.890" | currency }}\n', locale="pt-BR")
    assert "1.890" in _text(res) and "M202" in _codes(res)
    res = build('{{ "1.890" | currency }}\n')
    assert "1.890" in _text(res) and "M202" in _codes(res)
    assert "R$1,890.00" in _text(build('{{ "1.890,00" | currency }}\n'))  # two separators: one reading
    res = build('{{ "1.890" | paymoney("pix") }}\n', locale="pt-BR")  # a payment never takes it, in any locale
    assert "M202" in _codes(res)
    res = build(
        '```pay {scheme=pix to="you@example.com" amount="1.890,00"}\n```\n'
    )  # a payment takes no bare 1.890 (Q111)
    assert "Pix · R$1,890.00" in _text(res)


def test_only_typed_amounts_with_two_decimals_can_read_two_ways():
    res = build("{{ 1.126 | currency }}\n")  # a computed float is one number
    assert "R$1.13" in _text(res) and "M202" not in _codes(res)
    res = build('{{ "1.500" | paymoney("bitcoin") }}\n')  # 1500 or 1.5 BTC: refused, as the pay block does
    assert "M202" in _codes(res)
    res = build('```pay {scheme=pix to="a@b.c" amount=-1.890}\n```\n')
    assert "negative" in " ".join(n.message for n in res.nudges if n.code == "Q111")


def test_a_payment_hint_does_not_offer_locale():
    res = build('{{ "1.890" | paymoney("pix") }}\n')
    assert [n for n in res.nudges if n.code == "M202" and "locale" not in n.suggestion]


def test_signs_and_odd_currencies():
    res = build('{{ "-1.890" | currency }}\n')
    assert "M202" in _codes(res)  # a signed amount reads two ways too
    for doc in ('{{ "1.500" | currency("BTC") }}\n', '{{ "1.890" | currency("jpy") }}\n'):
        assert "M202" in _codes(build(doc)), doc  # 1500 or 1.5 in any currency: never a guess
    assert "0.00012345 BTC" in _text(build('{{ "0.00012345" | currency("BTC") }}\n'))  # not rounded to 0,00
    assert "¥" in _text(build("{{ 1890 | currency('jpy') }}\n"))  # the code in any case
    for amount in ("-R$ 10,00", "\u221210,00"):
        res = build('```pay {scheme=pix to="a@b.c" amount="' + amount + '"}\n```\n')
        assert "negative" in " ".join(n.message for n in res.nudges if n.code == "Q111"), amount
    res = build('```pay {scheme=pix to="a@b.c" amount="+1.890"}\n```\n')
    assert "could mean" in " ".join(n.message for n in res.nudges if n.code == "Q111")


def test_schemes_scanned_in_their_app_carry_no_p302():
    for scheme, kv in [
        ("picpay", 'to="seunome"'),
        ("paypal", 'to="yourname"'),
        ("bitcoin", 'to="bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"'),
    ]:
        assert "P302" not in _codes(build("```pay {scheme=%s %s}\n```\n" % (scheme, kv))), scheme  # noqa: UP031
    assert "P302" in _codes(build('```pay {scheme=venmo to="yourname"}\n```\n'))  # not tested yet
