"""Contact QR codes: the ```contact block. The network after `contact`, the value in the body:

    ```contact whatsapp
    +55 11 90000-0000
    ```

The value is what people type for that network (a phone with its country code, a user name, @handle) or the link
the app shares (a group invite, a channel); bobina builds the network's public link and a caption under the code.
`vcard` and `mecard` take `key: value` lines (name, phone, email, org, title, url, address, note). A network nobody
has scanned with its real app gives the note P303 (`tested=` marks the ones that were). A value bobina cannot turn
into a link raises ContactError: the layout reports Q112 with an example, and the code is left out (the rest prints).

The link formats and where each one is documented are in NETWORKS (`source=`). Codes that only the app itself can
draw (Snapcode, Spotify Code, WeChat's and KakaoTalk's own QR, Kik Code) are never imitated: bobina prints a plain QR
of the network's public link, which any phone camera opens, and says so (`proprietary=`). No brand logos."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

MARK = "⚠ not tested in the app"
QR_ATTRS = {"width", "module", "ecc", "align", "render", "caption", "id"}


class ContactError(ValueError):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True)
class Network:
    name: str
    title: str  # caption and help ("WhatsApp")
    group: str  # messenger | social | card
    build: Callable[[str, dict], tuple]  # (value, attributes) -> (payload, caption detail[, [(warning, hint)]])
    example: str  # a working block body
    takes: str  # what the body takes, for help and the errors
    attrs: dict[str, str] | None = None  # extra attributes and what they do (text=, subject=)
    source: str = ""  # where the link format is documented
    proprietary: str = ""  # the app's own code that bobina never imitates
    tested: str = ""  # evidence of a scan by the real app; empty: P303
    aliases: tuple[str, ...] = ()
    app: str = ""  # what reads it, for P303 ("a phone camera"); default: "the TITLE app"

    @property
    def block(self) -> str:
        """A working block, ready to copy."""
        return "\n".join([f"```contact {self.name}", self.example, "```"])


# ---------------------------------------------------------------- values


def phone(value: str, network: str) -> tuple[str, str]:
    """A phone in international form -> ("+5511900000000", "+55 11 90000-0000" as typed). Without the country code
    the link would open someone else's chat: it is refused with how to write it, never guessed."""
    shown = " ".join(value.split())
    d = re.sub(r"[\s().\-/]", "", value)
    if d.startswith("00"):
        d = "+" + d[2:]
    if not d.startswith("+"):
        raise ContactError(
            f"{network}: '{shown}' has no country code",
            "write it with + and the country code: +55 11 90000-0000 (Brazil), +1 415 555 0100 (US)",
        )
    if not re.fullmatch(r"\+[1-9]\d{6,14}", d):
        raise ContactError(f"{network}: '{shown}' is not a phone number", "+, the country code and the number: "
                           "+55 11 90000-0000 (up to 15 digits)")  # fmt: skip
    return d, shown


LINK = re.compile(r"^(?:https?://)?([^/?#\s]+)(/[^\s]*)?$", re.I)


def _host_path(value: str) -> tuple[str, str] | None:
    """('wa.me', '/5511…') for a link (with or without https://), None for a plain value."""
    if "/" not in value and not value.lower().startswith(("http:", "https:")):
        return None
    m = LINK.match(value.strip())
    if not m or "." not in m.group(1):
        return None
    host = m.group(1).lower().removeprefix("www.")
    if host.startswith("m.") and "." in host[2:]:  # m.facebook.com, never m.me
        host = host[2:]
    return host, m.group(2) or ""


def handle(value: str, network: str, rule: str, what: str, hosts: tuple[str, ...] = (), prefix: str = "") -> str:
    """A user name from `@name`, `name` or the profile link (any of `hosts`, path `prefix` + name)."""
    v = value.strip()
    hp = _host_path(v)
    if hp:
        host, path = hp
        if host not in hosts:
            raise ContactError(f"{network}: '{v}' is not a {network} link", f"write {what}, or paste the link from "
                               f"the app ({', '.join(hosts) or 'none'})")  # fmt: skip
        v = path.strip("/")
        if prefix and v.lower().startswith(prefix.lower()):
            v = v[len(prefix) :]
        v = v.split("/")[0].split("?")[0]
    v = v.lstrip("@")
    if not re.fullmatch(rule, v):
        raise ContactError(f"{network}: '{value.strip()}' is not {what}", f"{what}: {RULES.get(rule, rule)}")
    return v


def pasted(value: str, network: str, hosts: tuple[str, ...], what: str, path: str = r"/\S+") -> str:
    """A link copied from the app: https, one of `hosts`, a path. Kept as it is (https:// added when missing)."""
    v = value.strip()
    hp = _host_path(v)
    if not hp or hp[0] not in hosts or not re.fullmatch(path, hp[1]):
        raise ContactError(f"{network}: '{v}' is not {what}", f"paste {what} ({', '.join(hosts)})")
    return v if v.lower().startswith("https://") else "https://" + re.sub(r"^http://", "", v, flags=re.I)


INSTAGRAM_USER = r"[A-Za-z0-9._]{1,30}"
RULES = {
    INSTAGRAM_USER: "letters, digits, . and _ (up to 30)",
    r"[A-Za-z][A-Za-z0-9_]{3,31}": "a letter, then letters, digits and _ (5 to 32 in all)",
    r"[A-Za-z0-9_.]{2,32}": "letters, digits, _ and . (up to 32)",
    r"[A-Za-z][A-Za-z0-9._-]{2,14}": "a letter, then letters, digits, . _ - (3 to 15 in all)",
    r"[A-Za-z0-9._]{2,20}": "letters, digits, . and _ (2 to 20)",
    r"[A-Za-z0-9.]{5,50}": "letters, digits and . (5 to 50)",
    r"[A-Za-z0-9._-]{3,30}": "letters, digits, . _ - (3 to 30)",
    r"[A-Za-z0-9._]{2,24}": "letters, digits, . and _ (2 to 24)",
    r"[A-Za-z0-9_]{1,15}": "letters, digits and _ (up to 15)",
    r"[A-Za-z0-9_-]{3,100}": "letters, digits, _ and - (as in the profile link)",
    r"[a-z0-9._-]{1,20}": "lower-case letters, digits, . _ - (up to 20)",
    r"[A-Za-z0-9-]{2,32}": "letters, digits and - (the invite code)",
    r"[A-Za-z0-9_]{3,30}": "letters, digits and _ (3 to 30)",
    r"[A-Za-z0-9_-]{3,21}": "letters, digits, _ and - (3 to 21)",
    r"[A-Za-z0-9_]{4,25}": "letters, digits and _ (4 to 25)",
}


def _q(text: str) -> str:
    return quote(text, safe="")


# ---------------------------------------------------------------- messengers


def _whatsapp(v, kv):
    from urllib.parse import parse_qs

    hp = _host_path(v)
    text = str(kv.get("text") or "")
    no_text = [("whatsapp: text= works on a phone chat only (left out)", "a group, channel or catalog link opens "
                "as it is")] if text else []  # fmt: skip
    if hp and hp[0] == "chat.whatsapp.com":
        link = pasted(v, "whatsapp", ("chat.whatsapp.com",), "a group invite link", r"/[A-Za-z0-9]+/?")
        return link, "group", no_text
    if hp and hp[0] == "whatsapp.com" and hp[1].startswith("/channel/"):
        return (
            pasted(v, "whatsapp", ("whatsapp.com",), "a channel link", r"/channel/[A-Za-z0-9]+/?"),
            "channel",
            no_text,
        )
    if hp and hp[0] == "wa.me" and hp[1].startswith("/c/"):
        return pasted(v, "whatsapp", ("wa.me",), "a catalog link", r"/c/\d{7,15}/?"), "catalog", no_text
    if hp and hp[0] == "wa.me":
        path, _, query = hp[1].partition("?")
        v = "+" + path.strip("/").lstrip("+")
        text = text or (parse_qs(query).get("text") or [""])[0]  # the message of a pasted link stays
    elif hp:
        raise ContactError(f"whatsapp: '{v}' is not a WhatsApp link", "a phone (+55 11 90000-0000), or a wa.me, "
                           "chat.whatsapp.com or whatsapp.com/channel link")  # fmt: skip
    digits, shown = phone(v, "whatsapp")
    return f"https://wa.me/{digits[1:]}" + (f"?text={_q(text)}" if text else ""), shown


def _telegram(v, kv):
    hp = _host_path(v)
    if hp:
        if hp[0] not in ("t.me", "telegram.me"):
            raise ContactError(f"telegram: '{v}' is not a t.me link", "a user name (@ana_souza), +invite or t.me/…")
        path = hp[1].strip("/")
        if path.lower().startswith("joinchat/"):
            path = "+" + path[9:]
        v = path
    if v.startswith("+") and re.fullmatch(r"\+[\d\s().-]+", v):  # t.me/+5511…: the phone link
        digits, shown = phone(v, "telegram")
        return f"https://t.me/{digits}", shown
    if v.startswith("+"):
        code = v[1:]
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,64}", code):
            raise ContactError(f"telegram: '{v}' is not an invite link", "paste the link from the group's settings")
        return f"https://t.me/+{code}", "invite"
    u = handle(v, "telegram", r"[A-Za-z][A-Za-z0-9_]{3,31}", "a Telegram user name or channel")
    return f"https://t.me/{u}", f"@{u}"


def _signal(v, kv):
    hp = _host_path(v)
    if hp:
        if hp[0] != "signal.me":
            raise ContactError(f"signal: '{v}' is not a signal.me link", "a phone (+55 11 90000-0000) or the "
                               "signal.me link from Settings › Profile › Username › QR code or link")  # fmt: skip
        if re.fullmatch(r"/#eu/[A-Za-z0-9_-]+", hp[1]):
            return "https://signal.me" + hp[1], "user name"
        m = re.fullmatch(r"/#p/(\+\d+)", hp[1])
        if not m:
            raise ContactError(f"signal: '{v}' is not a signal.me link", "the link from the app, signal.me/#eu/…")
        v = m.group(1)
    if not v.lstrip().startswith(("+", "00")) and not re.search(r"\d{6}", re.sub(r"[\s().\-/]", "", v)):
        raise ContactError(f"signal: '{v}' is a user name", "Signal links a user name only through its own link: "
                           "Settings › Profile › Username › QR code or link, then paste it here")  # fmt: skip
    digits, shown = phone(v, "signal")
    return f"https://signal.me/#p/{digits}", shown


def _wechat(v, kv):
    hp = _host_path(v)
    if not hp:
        raise ContactError(f"wechat: '{v}' is a WeChat ID", "WeChat draws its contact QR itself: scan yours (Me › "
                           "My QR Code) with any QR reader and paste the link it holds (u.wechat.com/…)")  # fmt: skip
    return pasted(v, "wechat", ("u.wechat.com", "weixin.qq.com"), "the link of a WeChat QR code"), ""


def _kakao(v, kv):
    if re.fullmatch(r"_[A-Za-z0-9]{4,20}", v.strip()):  # a channel ID: pf.kakao.com/_ABCDE
        return f"https://pf.kakao.com/{v.strip()}", "channel"
    hp = _host_path(v)
    if hp and hp[0] == "open.kakao.com":
        return pasted(v, "kakao", ("open.kakao.com",), "an open chat link", r"/o/[A-Za-z0-9]+/?"), "open chat"
    if hp and hp[0] == "pf.kakao.com":
        return pasted(v, "kakao", ("pf.kakao.com",), "a channel link", r"/_[A-Za-z0-9]+(/chat)?/?"), "channel"
    raise ContactError(f"kakao: '{v}' is not a KakaoTalk link", "a channel ID (_ABCDE), or an open chat link "
                       "(open.kakao.com/o/…) or channel link (pf.kakao.com/_…) from the app")  # fmt: skip


def _line(v, kv):
    hp = _host_path(v)
    if hp:
        return pasted(v, "line", ("line.me",), "a LINE add-friend link", r"/(R/)?ti/p/\S+"), ""
    u = v.strip()
    if not u.startswith("@"):
        hint = "LINE adds a personal ID only through its own link: Home › Add friends › QR code › share, then paste it"
        raise ContactError(f"line: '{u}' is a personal LINE ID", hint + "; an official account: @id")
    u = handle(u, "line", r"[a-z0-9._-]{1,20}", "a LINE official account ID (@id)")
    return f"https://line.me/R/ti/p/%40{u}", f"@{u}"


def _viber(v, kv):
    hp = _host_path(v)
    if hp:
        return pasted(v, "viber", ("invite.viber.com", "vb.me"), "a Viber invite link"), ""
    digits, shown = phone(v, "viber")
    return f"viber://chat?number=%2B{digits[1:]}", shown


def _discord(v, kv):
    hp = _host_path(v)
    if hp and hp[0] not in ("discord.gg", "discord.com"):
        raise ContactError(f"discord: '{v}' is not a Discord invite", "the invite code, or discord.gg/CODE")
    code = handle(v, "discord", r"[A-Za-z0-9-]{2,32}", "a Discord invite code", ("discord.gg", "discord.com"),
                  "invite/")  # fmt: skip
    return f"https://discord.gg/{code}", "invite"


def _phone_link(scheme: str, network: str, extra: str = ""):
    def build(v, kv):
        digits, shown = phone(v, network)
        text = str(kv.get("text") or "") if extra else ""
        return f"{scheme}:{digits}" + (f"?{extra}={_q(text)}" if text else ""), shown

    return build


EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email(v, kv):
    a = v.strip().removeprefix("mailto:")
    if not EMAIL.match(a):
        raise ContactError(f"email: '{a}' is not an e-mail address", "name@example.com")
    subject = str(kv.get("subject") or "")
    return f"mailto:{a}" + (f"?subject={_q(subject)}" if subject else ""), a


# ---------------------------------------------------------------- social profiles


def _profile(host: str, network: str, rule: str, what: str, path: str = "{u}", at: bool = False,
             hosts: tuple[str, ...] = (), prefix: str = ""):  # fmt: skip
    """A profile link https://host/<path with the user name>; the value is the name, @name or the profile link."""

    def build(v, kv):
        u = handle(v, network, rule, what, hosts or (host.removeprefix("www."),), prefix)
        return f"https://{host}/" + path.format(u=u), ("@" if at else "") + u

    return build


def _facebook(v, kv):
    hp = _host_path(v)
    if hp and hp[0] in ("facebook.com", "fb.com"):
        m = re.fullmatch(r"/profile\.php\?(?:.*&)?id=(\d{5,20})(&.*)?", hp[1])
        if m:  # a profile without a user name
            return f"https://www.facebook.com/profile.php?id={m.group(1)}", ""
        if hp[1].lower().startswith("/profile.php"):
            raise ContactError(f"facebook: '{v}' has no profile id", "copy the profile link again from the app")
    u = handle(v, "facebook", r"[A-Za-z0-9.]{5,50}", "a Facebook user or page name", ("facebook.com", "fb.com"))
    return f"https://www.facebook.com/{u}", u


def _youtube(v, kv):
    hp = _host_path(v)
    if hp:
        link = pasted(v, "youtube", ("youtube.com",), "a YouTube channel link (youtube.com/@name)",
                      r"/(@[A-Za-z0-9._-]+|channel/UC[A-Za-z0-9_-]{22}|c/[^/?\s]+|user/[^/?\s]+)/?")  # fmt: skip
        return link, ""
    s = v.strip()
    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", s):
        return f"https://www.youtube.com/channel/{s}", "channel"
    u = handle(s, "youtube", r"[A-Za-z0-9._-]{3,30}", "a YouTube handle (@name)")
    return f"https://www.youtube.com/@{u}", f"@{u}"


def _linkedin(v, kv):
    hp = _host_path(v)
    if hp:
        return pasted(v, "linkedin", ("linkedin.com",), "a LinkedIn profile or page link",
                      r"/(in|company|school)/[^\s/]+/?"), ""  # fmt: skip
    s = v.strip().strip("/")
    kind, _, name = s.rpartition("/")
    kind = kind or "in"
    if kind not in ("in", "company", "school"):
        raise ContactError(f"linkedin: '{s}' is not a LinkedIn profile", "in/name (a person) or company/name")
    name = handle(name, "linkedin", r"[A-Za-z0-9_-]{3,100}", "a LinkedIn profile name")
    return f"https://www.linkedin.com/{kind}/{name}/", name


def _reddit(v, kv):
    s = v.strip()
    hp = _host_path(s)
    if hp:
        if hp[0] != "reddit.com":
            raise ContactError(f"reddit: '{s}' is not a reddit link", "u/name or r/community")
        s = hp[1].strip("/")
    kind, _, name = s.rpartition("/")
    kind = {"u": "user", "user": "user", "r": "r", "": "user"}.get(kind.lower())
    if kind is None:
        raise ContactError(f"reddit: '{v.strip()}' is not a reddit user or community", "u/name or r/community")
    name = handle(name, "reddit", r"[A-Za-z0-9_-]{3,21}", "a reddit name")
    return f"https://www.reddit.com/{kind}/{name}/", ("u/" if kind == "user" else "r/") + name


SPOTIFY_KINDS = ("artist", "user", "playlist", "album", "track", "show", "episode")


def _spotify(v, kv):
    s = v.strip()
    m = re.fullmatch(r"spotify:(\w+):([A-Za-z0-9]+)", s)
    if m and m.group(1) in SPOTIFY_KINDS:
        return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}", m.group(1)
    hp = _host_path(s)
    if hp and hp[0] == "open.spotify.com":
        m = re.fullmatch(r"/(?:intl-[a-z-]+/)?(\w+)/([A-Za-z0-9._-]+)/?(\?.*)?", hp[1])
        if m and m.group(1) in SPOTIFY_KINDS:
            return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}", m.group(1)
    raise ContactError(f"spotify: '{s}' is not a Spotify link", "Share › Copy link in the app "
                       "(open.spotify.com/artist/…), or spotify:artist:ID")  # fmt: skip


def _baidu(v, kv):
    hp = _host_path(v)
    if not hp or not (hp[0] == "baidu.com" or hp[0].endswith(".baidu.com")):
        raise ContactError(f"baidu: '{v}' is not a Baidu link", "Baidu has no public profile address to build: "
                           "copy the share link of your page in the Baidu app and paste it")  # fmt: skip
    return pasted(v, "baidu", (hp[0],), "a Baidu link"), ""


# ---------------------------------------------------------------- cards

CARD_KEYS = {
    "name": "the person's name (required): Ana Souza",
    "phone": "a phone, best with the country code (repeat the line for more)",
    "email": "an e-mail address (repeat for more)",
    "org": "company or organization",
    "title": "job title",
    "url": "a web address",
    "address": "a postal address, in one line",
    "note": "any other text",
}
MECARD_KEYS = ("name", "phone", "email", "url", "address", "note")


def card_fields(body: str, network: str) -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    """`key: value` lines -> ({key: [values]}, [(warning, hint)]). Unknown keys and lines without `:` are said,
    never guessed."""
    out: dict[str, list[str]] = {}
    warn = []
    for line in body.splitlines():
        if not line.strip():
            continue
        k, sep, val = line.partition(":")
        k = k.strip().lower()
        if not sep or k not in CARD_KEYS:
            warn.append((f"{network}: '{line.strip()[:40]}' is not a card line (left out)",
                         f"write key: value with {', '.join(CARD_KEYS)}"))  # fmt: skip
            continue
        if val.strip():
            out.setdefault(k, []).append(" ".join(val.split()))
    if not out.get("name"):
        raise ContactError(f"{network} needs a name: line", "name: Ana Souza")
    return out, warn


def _vtext(s: str) -> str:
    """RFC 2426 §4: a text value with \\ , ; and new lines escaped (data never becomes another field)."""
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def vcard(fields: dict[str, list[str]]) -> str:
    name = fields["name"][0]
    first, _, last = name.rpartition(" ")
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"N:{_vtext(last)};{_vtext(first)};;;", f"FN:{_vtext(name)}"]
    for key, field in (("org", "ORG"), ("title", "TITLE")):
        lines += [f"{field}:{_vtext(v)}" for v in fields.get(key, [])[:1]]
    lines += [f"TEL;TYPE=CELL:{_vtext(v)}" for v in fields.get("phone", [])]
    lines += [f"EMAIL:{_vtext(v)}" for v in fields.get("email", [])]
    lines += [f"URL:{_vtext(v)}" for v in fields.get("url", [])]
    lines += [f"ADR:;;{_vtext(v)};;;;" for v in fields.get("address", [])[:1]]
    lines += [f"NOTE:{_vtext(v)}" for v in fields.get("note", [])[:1]]
    return "\r\n".join([*lines, "END:VCARD"])


def _mtext(s: str) -> str:
    """MECARD: \\ ; , and : escaped with a backslash."""
    return re.sub(r"([\\;,:])", r"\\\1", s)


def mecard(fields: dict[str, list[str]]) -> str:
    name = fields["name"][0]
    first, _, last = name.rpartition(" ")
    parts = [f"N:{_mtext(last)},{_mtext(first)}" if first else f"N:{_mtext(name)}"]
    for key, field in (("phone", "TEL"), ("email", "EMAIL"), ("url", "URL"), ("address", "ADR"), ("note", "NOTE")):
        parts += [f"{field}:{_mtext(v)}" for v in fields.get(key, [])]
    return "MECARD:" + ";".join(parts) + ";;"


def _card(kind: str):
    def build(body, kv):
        fields, warnings = card_fields(body, kind)
        return (vcard(fields) if kind == "vcard" else mecard(fields)), fields["name"][0], warnings

    return build


# ---------------------------------------------------------------- the registry

N = Network
NO_CODE = "{app} draws its own code ({code}); bobina prints a plain QR of the public link instead"
U = INSTAGRAM_USER

NETWORKS: dict[str, Network] = {
    n.name: n
    for n in (
        N("whatsapp", "WhatsApp", "messenger", _whatsapp, "+55 11 90000-0000",
          "a phone with the country code, or a chat.whatsapp.com group, whatsapp.com/channel or wa.me/c catalog link",
          {"text": "a message the chat opens with (the person can still edit it)"},
          "WhatsApp Help Center, 'How to use click to chat' (wa.me/NUMBER, ?text=); Meta developers, catalog links "
          "(wa.me/c/NUMBER)"),
        N("telegram", "Telegram", "messenger", _telegram, "@ana_souza",
          "a user name or channel (@name), a +invite or t.me link, or a phone (+55 …)", None,
          "core.telegram.org/api/links (t.me/USERNAME, t.me/+INVITE, t.me/+PHONE)"),
        N("signal", "Signal", "messenger", _signal, "+55 11 90000-0000",
          "a phone with the country code, or the signal.me link of a user name", None,
          "Signal-Desktop ts/util/signalRoutes.ts (signal.me/#p/PHONE, signal.me/#eu/USERNAME)"),
        N("wechat", "WeChat", "messenger", _wechat, "https://u.wechat.com/kAbCdEfGhIjKlMnOpQrStUv",
          "the link inside your WeChat QR code (Me › My QR Code, read with any QR reader)", None,
          "WeChat has no public link format for an ID: the link of the app's own QR is reprinted",
          proprietary=NO_CODE.format(app="WeChat", code="the contact QR in the app")),
        N("line", "LINE", "messenger", _line, "@linedevelopers",
          "an official account (@id), or the line.me add-friend link a personal profile shares", None,
          "LINE Developers, 'Gain friends of your LINE Official Account' (line.me/R/ti/p/%40ID)"),
        N("viber", "Viber", "messenger", _viber, "+55 11 90000-0000",
          "a phone with the country code, or an invite.viber.com link", None,
          "developers.viber.com/docs/tools/deep-links (viber://chat?number=)"),
        N("kakao", "KakaoTalk", "messenger", _kakao, "_xcLqmC",
          "a channel ID (_ABCDE), or an open.kakao.com/o open chat or pf.kakao.com channel link", None,
          "developers.kakao.com, Kakao Talk Channel (pf.kakao.com/_ID, /chat)",
          proprietary=NO_CODE.format(app="KakaoTalk", code="its QR code in the app"), aliases=("kakaotalk",)),
        N("kik", "Kik", "messenger", _profile("kik.me", "kik", r"[A-Za-z0-9._]{2,20}", "a Kik user name"),
          "ana.souza", "a Kik user name", None, "Kik's profile links (kik.me/USERNAME)",
          proprietary=NO_CODE.format(app="Kik", code="the Kik Code")),
        N("messenger", "Messenger", "messenger",
          _profile("m.me", "messenger", r"[A-Za-z0-9.]{5,50}", "a Facebook user or page name"), "ana.souza",
          "a Facebook user or page name", None, "Meta, Messenger links (m.me/NAME)"),
        N("discord", "Discord", "messenger", _discord, "discord.gg/abcd1234", "an invite code or discord.gg link",
          None, "Discord Support, invites (discord.gg/CODE)"),
        N("phone", "Phone", "messenger", _phone_link("tel", "phone"), "+55 11 90000-0000",
          "a phone with the country code: the code dials it", None, "RFC 3966 (tel:)", aliases=("tel",),
          app="a phone camera"),
        N("sms", "SMS", "messenger", _phone_link("sms", "sms", "body"), "+55 11 90000-0000",
          "a phone with the country code: the code opens a text message to it",
          {"text": "the message the text opens with"}, "RFC 5724 (sms:NUMBER?body=)", app="a phone camera"),
        N("email", "E-mail", "messenger", _email, "ana@example.com", "an e-mail address",
          {"subject": "the subject the e-mail opens with"}, "RFC 6068 (mailto:)", aliases=("mail", "e-mail"),
          app="a phone camera"),
        N("instagram", "Instagram", "social", _profile("www.instagram.com", "instagram", U, "an Instagram user name",
          "{u}/", at=True, hosts=("instagram.com",)), "@ana.souza", "an Instagram user name or profile link", None,
          "the profile address the app shares (instagram.com/USERNAME)"),
        N("facebook", "Facebook", "social", _facebook, "ana.souza",
          "a Facebook user or page name, or the profile link", None, "facebook.com/USERNAME", aliases=("fb",)),
        N("threads", "Threads", "social", _profile("www.threads.com", "threads", U, "a Threads user name", "@{u}",
          at=True, hosts=("threads.com", "threads.net"), prefix="@"), "@ana.souza", "a Threads user name", None,
          "threads.com/@USERNAME (threads.net moved to threads.com in April 2025)"),
        N("tiktok", "TikTok", "social", _profile("www.tiktok.com", "tiktok", r"[A-Za-z0-9._]{2,24}",
          "a TikTok user name", "@{u}", at=True, hosts=("tiktok.com",), prefix="@"), "@ana.souza",
          "a TikTok user name", None, "tiktok.com/@USERNAME"),
        N("x", "X", "social", _profile("x.com", "x", r"[A-Za-z0-9_]{1,15}", "an X user name", at=True,
          hosts=("x.com", "twitter.com")), "@ana_souza", "an X (Twitter) user name", None, "x.com/USERNAME",
          aliases=("twitter",)),
        N("youtube", "YouTube", "social", _youtube, "@anasouza", "a handle (@name), a channel ID (UC…) or a link",
          None, "YouTube Help, 'Understand your channel URLs' (youtube.com/@HANDLE, /channel/ID)"),
        N("linkedin", "LinkedIn", "social", _linkedin, "in/ana-souza",
          "in/name (a person), company/name or school/name, or the profile link", None,
          "the public profile address (linkedin.com/in/NAME, /company/NAME)"),
        N("vk", "VK", "social", _profile("vk.com", "vk", r"[A-Za-z0-9_.]{2,32}", "a VK short name",
          hosts=("vk.com", "vk.ru", "vk.me")), "ana_souza", "a VK user or community short name", None,
          "VK for developers (vk.com/SHORTNAME; vk.me/SHORTNAME opens the chat)"),
        N("snapchat", "Snapchat", "social", _profile("www.snapchat.com", "snapchat", r"[A-Za-z][A-Za-z0-9._-]{2,14}",
          "a Snapchat user name", "add/{u}", hosts=("snapchat.com",), prefix="add/"), "ana.souza",
          "a Snapchat user name", None, "Snapchat profile URLs (snapchat.com/add/USERNAME)",
          proprietary=NO_CODE.format(app="Snapchat", code="the Snapcode")),
        N("pinterest", "Pinterest", "social", _profile("www.pinterest.com", "pinterest", r"[A-Za-z0-9_]{3,30}",
          "a Pinterest user name", "{u}/", hosts=("pinterest.com",)), "anasouza", "a Pinterest user name", None,
          "pinterest.com/USERNAME"),
        N("reddit", "Reddit", "social", _reddit, "u/ana_souza", "u/name (a user) or r/community", None,
          "reddit.com/user/NAME, reddit.com/r/COMMUNITY"),
        N("twitch", "Twitch", "social", _profile("www.twitch.tv", "twitch", r"[A-Za-z0-9_]{4,25}",
          "a Twitch user name", hosts=("twitch.tv",)), "anasouza", "a Twitch user name", None, "twitch.tv/USERNAME"),
        N("spotify", "Spotify", "social", _spotify, "https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF",
          "the link from Share › Copy link (an artist, profile, playlist, album, track or podcast)", None,
          "open.spotify.com/TYPE/ID (the spotify:TYPE:ID URI too)",
          proprietary=NO_CODE.format(app="Spotify", code="the Spotify Code")),
        N("baidu", "Baidu", "social", _baidu, "https://tieba.baidu.com/f?kw=bread",
          "the share link of your page in the Baidu app (any baidu.com address)", None,
          "Baidu publishes no profile address format: the app's share link is reprinted"),
        N("vcard", "vCard", "card", _card("vcard"), "name: Ana Souza\nphone: +55 11 90000-0000\nemail: ana@example.com",
          "key: value lines: " + ", ".join(CARD_KEYS), None, "RFC 2426 (vCard 3.0, the version phone cameras read)",
          aliases=("card", "contact"), app="a phone camera and its contacts app"),
        N("mecard", "MeCard", "card", _card("mecard"), "name: Ana Souza\nphone: +55 11 90000-0000",
          "key: value lines: " + ", ".join(MECARD_KEYS), None, "NTT DOCOMO MeCard (MECARD:N:…;TEL:…;;)",
          app="a phone camera and its contacts app"),
    )
}  # fmt: skip
ALIASES = {a: n.name for n in NETWORKS.values() for a in n.aliases}


def find(name: str) -> Network | None:
    name = name.strip().lower()
    return NETWORKS.get(ALIASES.get(name, name))


def closest(name: str) -> str:
    import difflib

    m = difflib.get_close_matches(name.lower(), [*NETWORKS, *ALIASES], n=1, cutoff=0.6)
    return ALIASES.get(m[0], m[0]) if m else ""


def caption(n: Network, detail: str) -> str:
    """The line under the code: "WhatsApp +55 11 90000-0000", "Instagram @ana.souza", "vCard" → the name."""
    if n.group == "card":
        return detail
    return " ".join(x for x in (n.title, detail) if x)


def network_json(n: Network) -> dict:
    return {
        "network": n.name,
        "title": n.title,
        "group": n.group,
        "example": n.block,
        "takes": n.takes,
        "attributes": dict(n.attrs or {}),
        "aliases": list(n.aliases),
        "source": n.source,
        "proprietary": n.proprietary,
        "tested_in_app": bool(n.tested),
        "evidence": n.tested,
    }


def networks_json() -> list[dict]:
    return [network_json(n) for n in NETWORKS.values()]


GROUPS = {"messenger": "Messengers and calls", "social": "Social networks", "card": "Contact cards (name, phone…)"}


def help_network(name: str) -> str:
    n = NETWORKS[name]
    status = f"✓ tested in the app: {n.tested}" if n.tested else MARK
    out = [f"{n.title} — contact {n.name}" + (f" (also: {', '.join(n.aliases)})" if n.aliases else ""),
           f"  {status}", ""]  # fmt: skip
    out += [f"  {line}" for line in n.block.split("\n")] + ["", f"  the body: {n.takes}"]
    for k, v in (n.attrs or {}).items():
        out.append(f"  {k}=  {v}")
    if n.proprietary:
        out.append(f"  {n.proprietary}.")
    out += [f"  link format: {n.source}", "  caption=auto|none|text and the QR's width= module= ecc= work on every "
            "network. A value bobina cannot turn into a link: Q112, the code is left out."]  # fmt: skip
    return "\n".join(out)


def help_text(name: str | None = None) -> str:
    if name:
        return help_network(name)
    out = ["```contact — contact and profile QR codes: the network after contact, the value in the body",
           "(docs/contact.md)", "", "  ```contact whatsapp", "  +55 11 90000-0000", "  ```", "",
           "  caption=auto (\"WhatsApp +55 11 90000-0000\"), none or your text",
           "  width= module= ecc= as on a QR"]  # fmt: skip
    for g, title in GROUPS.items():
        out += ["", title.upper()]
        for n in NETWORKS.values():
            if n.group == g:
                out.append(f"  {n.name:<10} {n.takes[:58]}{'…' if len(n.takes) > 58 else ''}")
    out += ["", "⚠ = every network is not tested in the app yet (note P303): the link follows the network's",
            "published format, but nobody has scanned a print with the real app.",
            "One network: bobina help contact NETWORK."]  # fmt: skip
    return "\n".join(out)


def docs_page() -> str:
    """docs/contact.md, generated (tools/gen_contact_docs.py): every network, from the same registry as the help."""
    out = ["# Contact codes: every network", "",
           "<!-- generated by tools/gen_contact_docs.py from src/bobina/contact.py: do not edit by hand -->", "",
           "One block, ```` ```contact NETWORK ````, with the value in the body: a phone with its country code, a user",
           "name or the link the app shares. bobina builds the network's public link, prints it as a QR code and",
           "writes a caption under it. The same text is in `bobina help contact NETWORK` (`--json` for programs).",
           "The block itself: [FORMAT.md §6.8](FORMAT.md).", "",
           "Codes that only the app can draw (Snapcode, Spotify Code, the WeChat and KakaoTalk QR codes, Kik Code)",
           "are never imitated: bobina prints a plain QR code of the public link, which any phone camera opens.",
           "No brand logos.", "",
           "| Attribute | Means |", "|---|---|",
           "| `caption=` | `auto` (default: \"WhatsApp +55 11 90000-0000\"), `none`, or your own text |",
           "| `width=` `module=` `ecc=` `.left` `.right` | as on a ```` ```qr ```` block |"]  # fmt: skip
    for g, title in GROUPS.items():
        out += ["", f"## {title}"]
        for n in NETWORKS.values():
            if n.group != g:
                continue
            status = f"✅ tested in the app: {n.tested}" if n.tested else MARK
            out += ["", f"### `{n.name}` — {n.title}" + (f" (also `{'`, `'.join(n.aliases)}`)" if n.aliases else ""),
                    "", status, "", "````markdown", n.block, "````", "", f"The body: {n.takes}."]  # fmt: skip
            out += [f"`{k}=`: {v}." for k, v in (n.attrs or {}).items()]
            if n.proprietary:
                out.append(f"{n.proprietary}.")
            out += ["", f"Link format: {n.source}."]
    return "\n".join(out) + "\n"
