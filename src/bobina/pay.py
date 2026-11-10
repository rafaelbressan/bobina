"""Payment QR codes: the ```pay block. One block for every scheme, with the same attribute names:

    to=      who receives (Pix key, UPI ID, IBAN, PromptPay phone, PayNow UEN/phone, address, user name, link)
    name=    receiver name           amount=  amount in the scheme's currency
    ref=     your reference / order  note=    text for the payer

plus a few scheme extras (city=, bic=, currency=, label=). Pix is one scheme like the others. A scheme that nobody
has scanned with its real app gives note P302 (TESTED marks the ones that were). Errors raise PayError: the layout
turns them into Q111 with the scheme's example, and nothing is printed."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

from . import codes

OLD_NAMES = {"key": "to", "txid": "ref", "description": "note"}  # the removed pix block's names, for the hint
QR_ATTRS = {"size", "module", "ecc", "align", "render", "caption", "scheme", "id"}
MARK = "⚠ not tested in a payment app"


class PayError(ValueError):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True)
class Field:
    """What a common field means in one scheme: for `bobina help pay SCHEME`, docs/pay.md and the errors."""

    means: str
    official: str = ""  # the field's name in the scheme's specification
    limit: str = ""


CAPTION_ONLY = Field("shown in the caption only; not part of the code")


@dataclass(frozen=True)
class Scheme:
    name: str
    title: str  # caption and help ("UPI", "SEPA")
    group: str  # standard | link | other
    build: Callable[[dict, float | None], str]
    example: str  # attributes of a working block
    fields: dict[str, Field]  # every attribute the scheme takes, in help order
    required: tuple[str, ...] = ("to",)
    currency: str | None = None  # ISO 4217 for the caption; None: the amount is a plain number
    decimals: int = 2
    tested: str = ""  # evidence of a scan by the real app; empty: P302
    app: str = ""  # what scans it, for P302 ("a SEPA banking app"); default: "the TITLE app"
    notes: tuple[str, ...] = ()  # what else to know (an amount the code cannot carry…)
    body: str = ""  # what goes in the block body (scheme=other: the pasted payload)

    @property
    def attrs(self) -> tuple[str, ...]:
        return tuple(self.fields)

    @property
    def to(self) -> str:
        return self.fields["to"].means if "to" in self.fields else ""

    @property
    def block(self) -> str:
        """A working block, ready to copy."""
        return "\n".join([f"```pay {{scheme={self.name} {self.example}}}", *([self.body] if self.body else []), "```"])


def _need(kv: dict, key: str, what: str) -> str:
    v = str(kv.get(key) or "").strip()
    if not v:
        raise PayError(f"needs {key}=: {what}")
    return v


def _money(a: float | None, decimals: int = 2) -> str:
    return "" if a is None else f"{a:.{decimals}f}"


# ---------------------------------------------------------------- open standards


def _cpf_cnpj_ok(d: str) -> bool:
    """CPF (11 digits) or CNPJ (14) check digits, mod 11."""
    if len(set(d)) == 1:
        return False
    weights = ([list(range(10, 1, -1)), list(range(11, 1, -1))] if len(d) == 11 else
               [[5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]])  # fmt: skip
    n = len(d) - 2
    for i, w in enumerate(weights):
        r = sum(int(x) * y for x, y in zip(d[: n + i], w, strict=True)) % 11
        if int(d[n + i]) != (0 if r < 2 else 11 - r):
            return False
    return True


UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def pix_key(key: str) -> str:
    """One of the five Pix key types, normalized as the BR Code wants it: CPF or CNPJ digits, +55 phone, e-mail,
    random key (EVP). Anything else is refused: a Pix code with a key that does not exist pays nobody."""
    k = key.strip()
    if UUID.match(k.lower()):
        return k.lower()
    if EMAIL.match(k):
        return k
    d = re.sub(r"[\s().\-/]", "", k)
    if re.fullmatch(r"\+55\d{10,11}", d):
        return d
    if re.fullmatch(r"\d{11}|\d{14}", d):
        if not _cpf_cnpj_ok(d):
            what = "CPF" if len(d) == 11 else "CNPJ"
            raise PayError(
                f"Pix key {k}: the {what} check digits do not match",
                f"check the {what} digit by digit; if it is a phone, write +55 in front",
            )
        return d
    raise PayError(f"'{k}' is not a Pix key", "a CPF, CNPJ, e-mail, phone with +55 or random key (EVP)")


def _fits(what: str, value: str, limit: int, scheme: str) -> str:
    if limit <= 0 and value:
        raise PayError(f"{scheme} leaves no room for {what}", f"leave {what}= out, or use a shorter key")
    if len(value) > limit:
        raise PayError(f"{what} has {len(value)} characters; {scheme} allows {limit}", f"cut {len(value) - limit}")
    return value


def _latin(what: str, value: str, scheme: str) -> str:
    """Accents dropped (é → e), as EMV codes need; any other non-ASCII character is refused, never dropped."""
    import unicodedata

    base = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    bad = sorted({c for c in base if not c.isascii()})
    if bad:
        raise PayError(f"{what} has characters {scheme} cannot carry: {' '.join(bad)}", "write it in Latin letters")
    return base


def _pix(kv, a):
    key = pix_key(_need(kv, "to", "a Pix key (CPF/CNPJ, e-mail, phone +55…, or random key)"))
    name = _fits("name", _latin("name", str(kv.get("name") or ""), "Pix"), 25, "Pix")
    city = _fits("city", _latin("city", str(kv.get("city") or ""), "Pix"), 15, "Pix")
    ref = str(kv.get("ref") or "").strip()
    ref = "" if ref == "***" else ref  # *** is the BR Code's "no txid", the default
    if ref and not (ref.isascii() and ref.isalnum()):
        raise PayError(f"ref '{ref}' must be letters and digits only (the Pix txid)", "for example PEDIDO42")
    _fits("ref", ref, 25, "Pix")
    note = _latin("note", str(kv.get("note") or ""), "Pix")
    _fits("note", note, 73 - len(key), f"Pix with this key ({len(key)} characters)")
    return codes.pix_payload(key, name or "N", city or "BRASIL", _money(a) or None, ref or "***", note)


UPI_ID = re.compile(r"^[A-Za-z0-9.\-_]{2,256}@[A-Za-z][A-Za-z0-9]{1,64}$")


def _upi(kv, a):
    pa = _need(kv, "to", "a UPI ID like shop@okbank")
    if not UPI_ID.match(pa):
        raise PayError(f"'{pa}' is not a UPI ID", "a UPI ID looks like name@bank (shop@okbank)")
    q = [("pa", pa), ("pn", _need(kv, "name", "the receiver's name (UPI asks for it)"))]
    if a is not None:
        q += [("am", _money(a)), ("cu", "INR")]
    q += [("tr", kv.get("ref") or ""), ("tn", kv.get("note") or "")]
    return "upi://pay?" + "&".join(f"{k}={quote(str(v), safe='@.-_')}" for k, v in q if v)


def _mod97(s: str) -> bool:  # IBAN and ISO 11649 (RF) check digits: the first 4 characters moved to the end
    return int("".join(str(int(c, 36)) for c in s[4:] + s[:4])) % 97 == 1


def iban_ok(iban: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban)) and _mod97(iban)


def _rf_ok(ref: str) -> bool:  # creditor reference: RF + 2 check digits + up to 21 characters
    return bool(re.fullmatch(r"RF\d{2}[A-Z0-9]{1,21}", ref)) and _mod97(ref)


def _epc(kv, a):
    name = _need(kv, "name", "the receiver's name, as the bank knows it")
    iban = _need(kv, "to", "an IBAN (DE89 3704 0044 0532 0130 00)").replace(" ", "").upper()
    if not iban_ok(iban):
        raise PayError(f"IBAN {iban} has a wrong check digit or format", "copy the IBAN from the bank statement")
    bic = str(kv.get("bic") or "").replace(" ", "").upper()
    if bic and not re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?", bic):
        raise PayError(f"BIC {bic} must have 8 or 11 letters and digits")
    _fits("name", name, 70, "EPC")
    if a is not None and not 0.01 <= a <= 999_999_999.99:
        raise PayError(f"amount {a} out of range", "between 0.01 and 999999999.99 euros")
    ref, note = str(kv.get("ref") or "").strip(), str(kv.get("note") or "").strip()
    structured = ref.replace(" ", "").upper() if ref.upper().startswith("RF") else ""
    if structured and not _rf_ok(structured):
        raise PayError(f"creditor reference {ref} has a wrong check digit", "an RF reference from the invoice")
    if structured and note:
        raise PayError("EPC takes a creditor reference (ref=RF…) or a text (note=), not both")
    text = note if structured else " ".join(x for x in (ref, note) if x)
    _fits("ref and note", text, 140, "EPC")
    amount = f"EUR{a:.2f}".rstrip("0").rstrip(".") if a is not None else ""
    lines = ["BCD", "002", "1", "SCT", bic, name, iban, amount, "", structured, text]
    while not lines[-1]:  # EPC069-12: no separator after the last populated element
        lines.pop()
    payload = "\n".join(lines)
    if len(payload.encode()) > 331:
        raise PayError("the code has more than 331 bytes", "shorten the name or the text")
    return payload


def _emv(fields: list[tuple[str, str]]) -> str:
    p = "".join(codes._tlv(t, v) for t, v in fields) + "6304"
    return p + codes.crc16(p)


def _promptpay(kv, a):
    digits = re.sub(r"\D", "", _need(kv, "to", "a phone (081 234 5678), a 13-digit tax ID or a 15-digit e-wallet ID"))
    if len(digits) == 15:
        kind, target = "03", digits
    elif len(digits) == 13:
        kind, target = "02", digits
    elif 9 <= len(digits) <= 11:
        kind, target = "01", ("0000000000000" + re.sub(r"^0", "66", digits))[-13:]
    else:
        raise PayError(f"'{kv['to']}' is not a PromptPay phone, tax ID or e-wallet ID", "a phone like 081 234 5678")
    fields = [("00", "01"), ("01", "12" if a is not None else "11")]
    fields += [("29", codes._tlv("00", "A000000677010111") + codes._tlv(kind, target)), ("58", "TH"), ("53", "764")]
    if a is not None:
        fields.append(("54", _money(a)))
    return _emv(fields)


def _paynow(kv, a):
    to = _need(kv, "to", "a UEN (201403121W) or a Singapore mobile (+65 8123 4567)")
    name = _need(kv, "name", "the receiver's name as registered for PayNow")
    digits = re.sub(r"[\s-]", "", to)
    if re.fullmatch(r"(\+?65)?[89]\d{7}", digits):
        kind, proxy = "0", "+65" + digits[-8:]  # mobile
    elif re.fullmatch(r"[0-9A-Za-z]{8,13}", digits):
        kind, proxy = "2", digits.upper()  # UEN
    else:
        raise PayError(f"'{to}' is not a PayNow UEN or Singapore mobile", "a UEN like 201403121W or +65 8123 4567")
    name = _fits("name", _latin("name", name, "PayNow"), 25, "PayNow")  # EMV lengths count bytes
    merchant = codes._tlv("00", "SG.PAYNOW") + codes._tlv("01", kind) + codes._tlv("02", proxy)
    merchant += codes._tlv("03", "0" if a is not None else "1")  # amount editable only when none is given
    fields = [("00", "01"), ("01", "12" if a is not None else "11"), ("26", merchant), ("52", "0000"), ("53", "702")]
    if a is not None:
        fields.append(("54", _money(a)))
    fields += [("58", "SG"), ("59", name), ("60", "Singapore")]
    ref = _fits("ref", _latin("ref", str(kv.get("ref") or ""), "PayNow"), 25, "PayNow")
    if ref:
        fields.append(("62", codes._tlv("01", ref)))
    return _emv(fields)


BTC_ADDRESS = re.compile(r"^((bc1|tb1)[02-9ac-hj-np-z]{11,71}|[13mn2][1-9A-HJ-NP-Za-km-z]{25,34})$")


def _bitcoin(kv, a):
    addr = _need(kv, "to", "a bitcoin address (bc1… or 1…/3…)")
    if not BTC_ADDRESS.match(addr):
        raise PayError(f"'{addr}' is not a bitcoin address", "bc1q…, 1… or 3…")
    q = []
    if a is not None:
        q.append(("amount", f"{a:.8f}".rstrip("0").rstrip(".")))
    q += [("label", kv.get("name") or ""), ("message", kv.get("note") or "")]
    tail = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in q if v)
    return f"bitcoin:{addr}" + (f"?{tail}" if tail else "")


def _lightning(kv, a):
    to = _need(kv, "to", "a BOLT11 invoice (lnbc…), an LNURL or a lightning address (you@wallet.example)")
    if re.fullmatch(r"(?i)ln(bc|tb|bcrt)[0-9a-z]+|lnurl[0-9a-z]+", to):
        return "lightning:" + to.upper()  # upper case: the QR alphanumeric mode, a smaller code
    if re.fullmatch(r"[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]{2,}", to, re.I):
        return "lightning:" + to
    raise PayError(f"'{to}' is not a lightning invoice, LNURL or address")


# ---------------------------------------------------------------- profile links

USER = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _user(kv, what, strip=()):
    u = _need(kv, "to", what)
    for s in strip:
        u = re.sub(rf"^(https?://)?(www\.)?{re.escape(s)}/?", "", u, flags=re.I)
    u = u.strip("/")
    if not USER.match(u.lstrip("$@")):
        raise PayError(f"'{u}' is not a user name", what)
    return u


def _paypal(kv, a):
    u = _user(kv, "your PayPal.me name", ("paypal.me",))
    cur = str(kv.get("currency") or "").upper()
    if cur and not re.fullmatch(r"[A-Z]{3}", cur):
        raise PayError(f"currency '{cur}' must be a 3-letter code (USD, EUR, BRL)")
    return f"https://paypal.me/{u}" + (f"/{_money(a)}{cur}" if a is not None else "")


def _cashapp(kv, a):
    return "https://cash.app/$" + _user(kv, "your $cashtag", ("cash.app",)).lstrip("$")


def _venmo(kv, a):
    u = _user(kv, "your Venmo user name", ("venmo.com/u", "venmo.com")).lstrip("@")
    q = [("txn", "pay")] if a is not None or kv.get("note") else []
    if a is not None:
        q.append(("amount", _money(a)))
    if kv.get("note"):
        q.append(("note", kv["note"]))
    tail = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in q)
    return f"https://venmo.com/{u}" + (f"?{tail}" if tail else "")


def _simple(host: str):
    def build(kv, a):
        return f"https://{host}/" + _user(kv, f"your {host} user name", (host,))

    return build


def _app_link(app: str, hosts: str, example: str):
    pattern = re.compile(rf"^https://({hosts})/\S+$", re.I)

    def build(kv, a):
        link = _need(kv, "to", f"the payment link from the {app} app ({example})")
        if not pattern.match(link):
            raise PayError(f"'{link}' is not a {app} link", f"copy the link from the app: {example}")
        return link

    return build


def _other(kv, a):
    return _need(kv, "payload", "the text read from the app's own QR code, in the block body")


# ---------------------------------------------------------------- the registry

APP_TESTED = "scanned with the app on the MTP-II, 09/11/2026: it opened the pay or profile screen"
PIX_TESTED = "scanned by Brazilian banking apps on the MTP-II, 05/11/2026 (CPF, e-mail and phone keys)"

F = Field
NAME_CAPTION = {"name": CAPTION_ONLY}
NO_AMOUNT = ("amount: this scheme cannot carry one; the payer types it (amount= gives note M156)",)
USER_RULE = "letters, digits, . _ - (up to 64)"

SCHEMES: dict[str, Scheme] = {
    s.name: s
    for s in (
        Scheme("pix", "Pix", "standard", _pix, 'to="you@example.com" name="Shop" city="Rio" amount=10.00', {
            "to": F("Pix key: CPF or CNPJ, e-mail, phone with +55, or random key (EVP)", "26.01 chave",
                    "77; CPF/CNPJ check digits verified; punctuation removed"),
            "name": F("receiver name the bank app shows", "59 Merchant Name", "25; accents dropped"),
            "city": F("receiver city", "60 Merchant City", "15; accents dropped; default BRASIL"),
            "amount": F("in R$; empty or 0: the payer types it", "54 Transaction Amount", "up to 9 999 999.99"),
            "ref": F("transaction id (txid), for your reconciliation", "62.05 txid", "25 letters and digits"),
            "note": F("description the payer sees", "26.02 descrição", "73 minus the key length"),
        }, currency="BRL", tested=PIX_TESTED),
        Scheme("upi", "UPI", "standard", _upi, 'to="shop@okbank" name="Chai Point" amount=120', {
            "to": F("receiver's UPI ID (VPA)", "pa", "name@bank"),
            "name": F("receiver name (UPI asks for it)", "pn", ""),
            "amount": F("in ₹; empty: the payer types it", "am (with cu=INR)", "2 decimals"),
            "ref": F("transaction reference", "tr", ""),
            "note": F("text the payer sees", "tn", ""),
        }, required=("to", "name"), currency="INR"),
        Scheme("epc", "SEPA", "standard", _epc,
               'to="DE89 3704 0044 0532 0130 00" name="Café Sol" amount=12.50 note="Invoice 42"', {
            "to": F("receiver's IBAN (spaces allowed)", "line 7, IBAN", "check digits verified"),
            "name": F("receiver name, as the bank knows it", "line 6, beneficiary", "70"),
            "amount": F("in €; empty: the payer types it", "line 8, amount", "0.01 to 999 999 999.99"),
            "ref": F("an RF creditor reference goes structured; any other text joins note", "line 10, remittance "
                     "(structured)", "RF + 2 check digits + 21 (verified)"),
            "note": F("remittance text", "line 11, remittance (unstructured)", "140, with ref; not with an RF ref"),
            "bic": F("receiver's bank code; optional inside the EEA", "line 5, BIC", "8 or 11"),
        }, required=("to", "name"), currency="EUR", app="a SEPA banking app"),
        Scheme("promptpay", "PromptPay", "standard", _promptpay, 'to="081 234 5678" amount=120', {
            "to": F("phone (10 digits), national or tax ID (13) or e-wallet ID (15)", "29.01 / 29.02 / 29.03",
                    "the number of digits picks the kind"),
            **NAME_CAPTION,
            "amount": F("in ฿; empty: the payer types it", "54 Transaction Amount", "2 decimals"),
        }, currency="THB"),
        Scheme("paynow", "PayNow", "standard", _paynow, 'to="201403121W" name="Kopi Corner" amount=4.50 ref="A42"', {
            "to": F("UEN, or Singapore mobile (+65 8… or 9…)", "26.02 proxy (26.01 type)", "UEN 8 to 13"),
            "name": F("receiver name as registered for PayNow", "59 Merchant Name", "25; accents dropped"),
            "amount": F("in S$; empty: the payer types it (26.03 editable)", "54 Transaction Amount", "2 decimals"),
            "ref": F("bill or order number", "62.01 bill number", "25; accents dropped"),
        }, required=("to", "name"), currency="SGD"),
        Scheme("bitcoin", "Bitcoin", "standard", _bitcoin,
               'to="bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq" amount=0.001', {
            "to": F("bitcoin address", "address", "bc1…, 1… or 3…"),
            "name": F("label the wallet shows", "label", ""),
            "amount": F("in BTC", "amount", "8 decimals"),
            "note": F("message the wallet shows", "message", ""),
        }, currency="BTC", decimals=8, app="a bitcoin wallet",
           tested="scanned with a bitcoin wallet on the MTP-II, 09/11/2026: address and amount read"),
        Scheme("lightning", "Lightning", "standard", _lightning, 'to="you@wallet.example"', {
            "to": F("BOLT11 invoice (lnbc…), LNURL or lightning address", "lightning:", ""), **NAME_CAPTION,
        }, app="a lightning wallet", notes=("amount: an invoice carries its own; an address lets the payer type it",)),
        Scheme("paypal", "PayPal", "link", _paypal, 'to="yourname" amount=10 currency=USD', {
            "to": F("your PayPal.me name (or the paypal.me link)", "paypal.me/NAME", USER_RULE), **NAME_CAPTION,
            "amount": F("empty: the payer types it", "paypal.me/NAME/AMOUNT", "2 decimals"),
            "currency": F("3-letter code; default your account's", "suffix of the amount (10USD)", "3 letters"),
        }, tested=APP_TESTED),
        Scheme("cashapp", "Cash App", "link", _cashapp, 'to="$yourtag"', {
            "to": F("your $cashtag", "cash.app/$cashtag", USER_RULE), **NAME_CAPTION}, notes=NO_AMOUNT),
        Scheme("venmo", "Venmo", "link", _venmo, 'to="yourname" amount=10 note="Coffee"', {
            "to": F("your Venmo user name (@ allowed)", "venmo.com/NAME", USER_RULE), **NAME_CAPTION,
            "amount": F("empty: the payer types it", "amount= (with txn=pay)", "2 decimals"),
            "note": F("what the payment is for", "note=", ""),
        }, currency="USD"),
        Scheme("revolut", "Revolut", "link", _simple("revolut.me"), 'to="yourname"', {
            "to": F("your Revolut.me name", "revolut.me/NAME", USER_RULE), **NAME_CAPTION}, notes=NO_AMOUNT,
               tested=APP_TESTED),
        Scheme("wise", "Wise", "link", _app_link("Wise", r"(www\.)?wise\.com", "https://wise.com/pay/…"),
               'to="https://wise.com/pay/me/yourtag"', {
            "to": F("the payment link from the Wise app", "https://wise.com/pay/…", ""), **NAME_CAPTION},
               notes=NO_AMOUNT, tested=APP_TESTED),
        Scheme("picpay", "PicPay", "link", _simple("picpay.me"), 'to="seunome"', {
            "to": F("your PicPay user name", "picpay.me/NAME", USER_RULE), **NAME_CAPTION}, notes=NO_AMOUNT,
               tested=APP_TESTED),
        Scheme("mercadopago", "Mercado Pago", "link",
               _app_link("Mercado Pago", r"link\.mercadopago\.com(\.[a-z]{2})?|mpago\.(la|li)",
                         "https://link.mercadopago.com.br/yourshop"),
               'to="https://link.mercadopago.com.br/yourshop"', {
            "to": F("your link from the Mercado Pago app (\"Seu link\", or an mpago.la link per sale)",
                    "link.mercadopago… / mpago.la", ""), **NAME_CAPTION},
               notes=("amount: \"Seu link\" lets the payer type it; a per-sale mpago.la link carries its own",),
               tested=APP_TESTED),
        Scheme("other", "", "other", _other, 'label="WeChat Pay"', {
            "label": F("the app's name, for the caption", "", ""), **NAME_CAPTION,
            "amount": F("shown in the caption only; the pasted payload decides", "", ""),
        }, required=(), notes=("the block body is the text read from the app's own QR code, reprinted as it is",),
           body="wxp://f2f0…"),
    )
}  # fmt: skip


def closest(name: str) -> str:
    import difflib

    m = difflib.get_close_matches(name.lower(), list(SCHEMES), n=1, cutoff=0.6)
    return m[0] if m else ""


def currency(s: Scheme | None, kv: dict) -> str | None:
    """The currency of an amount: the scheme's, else currency= (PayPal, Wise…), else none."""
    return (s.currency if s else None) or str(kv.get("currency") or "").upper() or None


def money(s: Scheme | None, amount: float, kv: dict, loc, explicit: bool = True) -> str:
    """An amount in the scheme's currency: R$ 10,00 · ₹120.00 · 0.001 BTC. In the document's locale when it declares
    one (explicit), else as the currency's country writes it (templating.CURRENCY_HOME)."""
    from babel import numbers as bnumbers

    from .templating import money_locale

    cur = currency(s, kv)
    if cur == "BTC":
        return f"{amount:.8f}".rstrip("0").rstrip(".") + " BTC"
    if cur:
        return bnumbers.format_currency(amount, cur, locale=money_locale(cur, loc, explicit))
    return bnumbers.format_decimal(amount, format="#,##0.00", locale=loc)


def caption(s: Scheme, amount: float | None, kv: dict, loc, explicit: bool = True) -> str:
    """The line under the code: the scheme and the amount ("Pix · R$ 10,00"), else the receiver's name."""
    title = s.title or str(kv.get("label") or "").strip()
    what = money(s, amount, kv, loc, explicit) if amount is not None else str(kv.get("name") or "").strip()
    return " · ".join(x for x in (title, what) if x)


COMMON_FIELDS = {
    "to": "who receives: a Pix key, UPI ID, IBAN, phone, user name or link, depending on the scheme",
    "name": "the receiver's name (some schemes require it; elsewhere it is only the caption)",
    "amount": "the amount in the scheme's currency, 24.90 or 24,90; empty: the payer types it",
    "ref": "your reference or order number",
    "note": "text the payer sees",
    "caption": 'auto (default: "Pix · R$ 10,00"), none, or your own text, a line under the code',
}
GROUPS = {"standard": "Open standards (bobina builds the code)", "link": "Profile links (any phone camera opens them)",
          "other": "Closed apps (paste the payload from the app's own QR)"}  # fmt: skip


def scheme_json(s: Scheme) -> dict:
    return {
        "scheme": s.name,
        "title": s.title,
        "group": s.group,
        "example": s.block,
        "to": s.to,
        "required": list(s.required),
        "attributes": list(s.attrs),
        "fields": {
            k: {"means": f.means, "official": f.official, "limit": f.limit, "required": k in s.required}
            for k, f in s.fields.items()
        },  # fmt: skip
        "notes": list(s.notes),
        "currency": s.currency,
        "tested_in_app": bool(s.tested),
        "evidence": s.tested,
    }


def schemes_json() -> list[dict]:
    return [scheme_json(s) for s in SCHEMES.values()]


def _table(rows: list[tuple[str, ...]], widths: tuple[int, ...]) -> list[str]:
    """Columns that wrap their text inside the column, for an 80-column terminal."""
    import textwrap

    out = []
    for row in rows:
        cells = [textwrap.wrap(c, w) or [""] for c, w in zip(row, widths, strict=True)]
        for i in range(max(len(c) for c in cells)):
            out.append(
                "  "
                + "  ".join((c[i] if i < len(c) else "").ljust(w) for c, w in zip(cells, widths, strict=True)).rstrip()
            )
    return out


def help_scheme(name: str) -> str:
    s = SCHEMES[name]
    status = f"✓ tested in the app: {s.tested}" if s.tested else MARK
    out = [f"{s.title or 'Closed apps'} — pay scheme={s.name}", f"  {status}", ""]
    out += [f"  {line}" for line in s.block.split("\n")] + [""]
    rows = [("FIELD", f"IN {(s.title or 'THIS SCHEME').upper()}", "OFFICIAL NAME", "LIMIT")]
    rows += [(f"{k}=" + (" *" if k in s.required else ""), f.means, f.official, f.limit) for k, f in s.fields.items()]
    out += _table(rows, (9, 29, 15, 19))
    out += ["", ("  * required. " if s.required else "  ") + "caption=auto|none|text and the QR's size= module= ecc= "
            "work on every scheme."]  # fmt: skip
    out += [f"  {n}" for n in s.notes]
    out += ["  Over a limit or a wrong value: Q111 says what to change, and nothing is printed (never cut)."]
    return "\n".join(out)


def help_text(name: str | None = None) -> str:
    if name:
        return help_scheme(name)
    out = ["```pay — payment QR codes: one block, the same fields for every scheme (docs/pay.md)", "",
           '  ```pay {scheme=upi to="shop@okbank" name="Chai Point" amount=120 note="Order 42"}', "  ```", "",
           "COMMON FIELDS (what each one means in a scheme: bobina help pay SCHEME)"]  # fmt: skip
    out += _table([(f"{k}=", v) for k, v in COMMON_FIELDS.items()], (10, 66))
    for g, title in GROUPS.items():
        out += ["", title.upper()]
        rows = [(s.name, s.to or (s.notes[0] if s.notes else s.example), "✓ tested" if s.tested else "⚠")
                for s in SCHEMES.values() if s.group == g]  # fmt: skip
        out += _table(rows, (12, 52, 8))
    out += ["", "⚠ = not tested in a payment app: the code follows the scheme's specification, but nobody",
            "has scanned a print with the real app yet (note P302). Scan one before customers use it."]  # fmt: skip
    return "\n".join(out)


def docs_page() -> str:
    """docs/pay.md, generated (tools/gen_pay_docs.py): every scheme's fields, from the same registry as the help."""
    out = ["# Payment codes: every scheme and its fields", "",
           "<!-- generated by tools/gen_pay_docs.py from src/bobina/pay.py: do not edit by hand -->", "",
           "One block, ```` ```pay {scheme=…} ````, with the same field names for every scheme. This page says what",
           "each field means in each scheme, its name in the scheme's specification and its limit. The same text is",
           "in `bobina help pay SCHEME` (`--json` for programs). The block itself: [FORMAT.md §6.3](FORMAT.md).", "",
           "| Field | Means |", "|---|---|"]  # fmt: skip
    out += [f"| `{k}=` | {v} |" for k, v in COMMON_FIELDS.items()]
    for s in SCHEMES.values():
        status = f"✅ tested in the app: {s.tested}" if s.tested else MARK
        out += ["", f"## `{s.name}` — {s.title or 'closed apps'}", "", status, "",
                "````markdown", s.block, "````", "",
                "| Field | In this scheme | Official name | Limit |", "|---|---|---|---|"]  # fmt: skip
        out += [f"| `{k}=`{' (required)' if k in s.required else ''} | {f.means} | {f.official} | {f.limit} |"
                for k, f in s.fields.items()]  # fmt: skip
        if s.notes:
            out += [""] + [f"- {n}" for n in s.notes]
    return "\n".join(out) + "\n"
