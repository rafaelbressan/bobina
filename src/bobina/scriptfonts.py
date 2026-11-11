"""Fonts for scripts the bundled fonts cannot draw (Thai, Devanagari, Chinese, …): Noto, downloaded once.

The first time a line needs a script that no bundled font has, bobina downloads the matching Noto font, says so
before it starts (which font, its license, its size, where from) and keeps it in the data folder
(~/.local/share/bobina/fonts/<pack>/, with the license next to it); from then on it is used offline.

- Every file is pinned: an https URL at a fixed commit of an official Noto source (notofonts on GitHub, the
  Google Fonts repository for the license texts), its exact size and sha256. Nothing else is ever fetched; a
  file that does not match is thrown away. Redirects are not followed.
- No network, or downloads turned off (`font_downloads = false` in config.toml, or BOBINA_FONT_DOWNLOADS=0):
  the line still prints, with boxes for those letters and a warning (F305) saying how to get the font later
  (`bobina fonts get thai`).
- One weight (Regular; bold is drawn by the usual one-dot double strike). Chinese, Japanese and Korean use the
  per-language subsets of Noto Sans CJK (4.5 to 8.3 MB): the notice says the size.

`support()` answers "can bobina draw this script (or language) now, or after a download?" for other modules.
"""

from __future__ import annotations

import hashlib
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import paths

NOTO = "4cf78353cd1668040ba8efa13029cd910fcdf9e2"  # notofonts/notofonts.github.io, 2026-11-09
CJK = "f8d157532fbfaeda587e826d4cd5b21a49186f7c"  # notofonts/noto-cjk, 2024-09-19 (Sans 2.004)
GF = "5bb28733cec313b63fbd415b574b5ae35c8aa8b8"  # google/fonts, 2026-11-08 (license texts)
RAW = "https://raw.githubusercontent.com/"
HOSTS = ("raw.githubusercontent.com",)
MAX_BYTES = 12_000_000  # the largest pinned file is 8.3 MB (Noto Sans SC)
TIMEOUT_S = 20  # per network operation
DEADLINE_S = 180  # the whole file: 8 MB at 50 KB/s (an MCP call is stopped after 5 minutes)
LICENSE = "SIL Open Font License 1.1"


@dataclass(frozen=True)
class Pack:
    id: str  # what `bobina fonts get` takes: thai, devanagari, chinese
    family: str
    scripts: tuple[str, ...]  # ISO 15924 codes it draws (Unicode script property)
    url: str
    size: int
    sha256: str
    license_url: str
    license_size: int
    license_sha256: str

    @property
    def file(self) -> str:
        return self.url.rsplit("/", 1)[1]

    @property
    def license_file(self) -> str:
        return self.license_url.rsplit("/", 1)[1]


def _noto(id_, family, scripts, size, sha, lic_size, lic_sha, folder="") -> Pack:
    name = family.replace(" ", "")
    return Pack(
        id_,
        family,
        scripts,
        f"{RAW}notofonts/notofonts.github.io/{NOTO}/fonts/{name}/hinted/ttf/{name}-Regular.ttf",
        size,
        sha,
        f"{RAW}google/fonts/{GF}/ofl/{folder or name.lower()}/OFL.txt",
        lic_size,
        lic_sha,
    )


CJK_LICENSE = (4301, "6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2")  # noto-cjk Sans/LICENSE


def _cjk(id_, family, scripts, region, size, sha) -> Pack:
    name = family.replace(" ", "")
    lic = f"{RAW}notofonts/noto-cjk/{CJK}/Sans/LICENSE"
    return Pack(
        id_, family, scripts, f"{RAW}notofonts/noto-cjk/{CJK}/Sans/SubsetOTF/{region}/{name}-Regular.otf", size, sha,
        lic, CJK_LICENSE[0], CJK_LICENSE[1],
    )  # fmt: skip


# Sizes and sha256 come from tools/pin_script_fonts.py (it downloads every pinned file and checks it).
# fmt: off
PACKS: dict[str, Pack] = {p.id: p for p in (
    # id, family, scripts, font size, font sha256, license size, license sha256
    _noto("thai", "Noto Sans Thai", ("Thai",),
          37780, "61cf814eec46b294d6ea4401ac295d0cecd5207bd2331dcc5a15e7301d30ee44",
          4380, "2e98fd23a52d253db8612cd5942c8f2ff4111b21d2367050fdca91d8ccc374a0"),
    _noto("lao", "Noto Sans Lao", ("Laoo",),
          35884, "0a86e5e1ccfe34ca78c43fac6829dc751b42bcc469272a9a55325aae587bfbe7",
          4379, "a42993999944845fb5af693ea678a372a053db1f0981d55e911dcfa9d330f279"),
    _noto("khmer", "Noto Sans Khmer", ("Khmr",),
          114576, "e66675f2082788f0511a714bef5a1748928294b38c8e286a96ea73a864b5e605",
          4381, "be0407f060aea48787ff9e75d8d3aedef70aef113b3ce9aca26fdaacd10b1870"),
    _noto("myanmar", "Noto Sans Myanmar", ("Mymr",),
          195088, "fafce4db400bc0b214907ccdbfb0ad2f18a57bfefd08c8a571830b84088cf2fc",
          4383, "246a75859267af7da466823969d2e2b407ed8455ee5f74f4c8d63d8783be9b57"),
    _noto("devanagari", "Noto Sans Devanagari", ("Deva",),
          243520, "4e3c66638958c3e2ab5d37f47a8deb89fffeb7be9985c665a519bbc7ba762313",
          4386, "a216f6f8d85c7228093e0ee5e258d9d377e6671f68acb4db1930b29583d0f331"),
    _noto("bengali", "Noto Sans Bengali", ("Beng",),
          143072, "b55c62ee531e3214da6c0701daecea89a52ba42db7d8206b92e6b51f397a3193",
          4383, "754f0e221aa7d5a915489f3bf1f20fe53ddc35ab2834a4d91656d78f9622de70"),
    _noto("gurmukhi", "Noto Sans Gurmukhi", ("Guru",),
          55172, "658d0207da305a1411c539a8b0bbeda64d4146e54fb4827facddb890b6b90d74",
          4384, "3f7451b7e2c8381be0c5712f7b0dd5c2d75fe787ae16a99f18b7fa45627a0fde"),
    _noto("gujarati", "Noto Sans Gujarati", ("Gujr",),
          200704, "9b5a7aaeeb649a2e75a49d8b006a1f87db1b61c0df3b001609f4e0725d88dbf6",
          4384, "c0b88977aa18b5e4fd05d646d560da89fde61b6581fa4507cb00dd90bd1bf7d4"),
    _noto("oriya", "Noto Sans Oriya", ("Orya",),
          131216, "a16645d056017927406546aa78e4ce15e782fd8783467267b75450453d007415",
          4381, "c90ff15ade263a49148e35af34e9c177c6d56881e81260b29f10123e9e227eca"),
    _noto("tamil", "Noto Sans Tamil", ("Taml",),
          73992, "3c0a186feb3c63c7f6d63e1511dcdc144e745ae09b98e217c83f3e317974f6f9",
          4381, "f8ff8ce7d0a81bf8d5e121c635ef027250c531f2fd37d5988b8dd6e45f19d7f1"),
    _noto("telugu", "Noto Sans Telugu", ("Telu",),
          235176, "b274780b69d1d23fe84b55e809a152cb2ac5306d33864b1f87622f6971871aae",
          4382, "481c72a8f1b4f645a7e6b10326be41b2da2c15cb470ff48a07fab773eed00102"),
    _noto("kannada", "Noto Sans Kannada", ("Knda",),
          182416, "9ad74dc64838c6855b96f671fc08e425a58921b9d0c71712ea79c328a27e6e38",
          4383, "9d49a4e56df9b36403b139f48bf07fd87cc5e716cb3203c54b04b674adb16238"),
    _noto("malayalam", "Noto Sans Malayalam", ("Mlym",),
          112936, "c08de7fa8d032a5d6a4d120fb82c78cec60b362a4e73fa26360d89759ff2a7f9",
          4385, "1df18163a0bf60f02131401ba1609df90051f40c4047684dda1c8a2e9586f7f2"),
    _noto("sinhala", "Noto Sans Sinhala", ("Sinh",),
          154912, "9e32612d47004552f3125e78648a9e2e7899a216ccd3cefbb93a9b5f4c809feb",
          4383, "2d6f7c43bce61f4b1919379f901bc613484f5285f520b6d29bb7c1f31b17e841"),
    _noto("tibetan", "Noto Serif Tibetan", ("Tibt",),
          609688, "ee97bf3dc56e813651db734c9f35f8f1d41e7e31acf5f7d893e64ad22b292446",
          4383, "0077789fc3cb20f358278ba4c6437eb14ade97d4d3e3281eaa42853efcd9dc8b"),
    _noto("ethiopic", "Noto Sans Ethiopic", ("Ethi",),
          376804, "f6f7fc379db9438959a2b0527e7a2cf36ea9c84626d56ec444fff37fc24c3c10",
          4384, "72606b23f312cb25973958f2892d4d2c2012deabadbf0f763232624a9649fc69"),
    _noto("thaana", "Noto Sans Thaana", ("Thaa",),
          27308, "7543935bdcef770c9d3dd54222651b29040e5ec82f3bc58542392b2c7a9cbd3c",
          4382, "5de6fbfe9ca25509fd60e47be3fab3cc236abe20bc1b123a5c2bd12f067fd13c"),
    _noto("arabic", "Noto Sans Arabic", ("Arab",),
          234892, "bdff3e5659d67e67def05b33f749683b9376ae819d65d3dd62ac4640b3aaef48",
          4382, "07fc70bfeb985cc1a87a8587d0a0c80bab11c86c9dc3fd95b6f0cb332f983e96"),
    _noto("hebrew", "Noto Sans Hebrew", ("Hebr",),
          26860, "cdefaf8efd47045f6820928eba84db5bed7557539328952b5f828315485e02ee",
          4382, "9b9fe028b5ba74d231659a1bbaf0ed09b11e759d1ca6a070999e16d151616b47"),
    _noto("armenian", "Noto Sans Armenian", ("Armn",),
          30752, "720df88c332417a235b4d6209d14ec2e2bf4bfe2a954b7453d869ea593bfce1e",
          4384, "0468358b316f69f405b55cadf8a8314e16e3610b8feaad96772bd5d968112d02"),
    _noto("georgian", "Noto Sans Georgian", ("Geor",),
          52888, "d3e33254b09e7bb2c5cf0f17e554b80462056c5a107097f258d495168c3a9346",
          4384, "8c02263c5d73d40544f9ed91e30c4e947407057a3cc430d7b786189aeceff6df"),
    _cjk("chinese", "Noto Sans SC", ("Hani",), "SC",
         8331336, "faa6c9df652116dde789d351359f3d7e5d2285a2b2a1f04a2d7244df706d5ea9"),
    _cjk("chinese-traditional", "Noto Sans TC", ("Hani", "Bopo"), "TC",
         5683368, "5bab0cb3c1cf89dde07c4a95a4054b195afbcfe784d69d75c340780712237537"),
    _cjk("japanese", "Noto Sans JP", ("Hani", "Hira", "Kana"), "JP",
         4533028, "dff723ba59d57d136764a04b9b2d03205544f7cd785a711442d6d2d085ac5073"),
    _cjk("korean", "Noto Sans KR", ("Hang", "Hani"), "KR",
         4644748, "69975a0ac8472717870aefeab0a4d52739308d90856b9955313b2ad5e0148d68"),
)}
# fmt: on

# Han is shared by four languages: the kana or hangul around it, else a subset already downloaded, else Chinese.
HAN_ORDER = ("chinese", "chinese-traditional", "japanese", "korean")
LANGUAGE_SCRIPTS = {"Jpan": ("Hani", "Hira", "Kana"), "Kore": ("Hang", "Hani"), "Hans": ("Hani",), "Hant": ("Hani",)}


class FontDownloadError(Exception):
    pass


# -- scripts -----------------------------------------------------------------------------------------------


def script_of(ch: str) -> str:
    from fontTools import unicodedata

    return unicodedata.script(ch)


def script_name(code: str) -> str:
    from fontTools import unicodedata

    return unicodedata.script_name(code, default=code)


NEUTRAL = {"Zyyy", "Zinh", "Zzzz"}  # common (digits, punctuation), inherited (combining marks), unknown


def split_runs(text: str) -> list[tuple[str, str]]:
    """Text -> [(script, part)] in order. Digits, punctuation and combining marks stay with the run they are in
    (a leading one joins the first run); text with no script at all is one run of 'Zyyy'."""
    runs: list[list] = []
    for ch in text:
        s = script_of(ch)
        if s in NEUTRAL or (runs and runs[-1][0] == s):
            if runs:
                runs[-1][1] += ch
            else:
                runs.append(["Zyyy", ch])
        elif runs and runs[-1][0] == "Zyyy":  # neutral start: it belongs to the first real script
            runs[-1] = [s, runs[-1][1] + ch]
        else:
            runs.append([s, ch])
    return [(s, t) for s, t in runs]


RTL = {"Arab", "Hebr", "Syrc", "Thaa", "Nkoo", "Adlm", "Rohg", "Mand", "Samr"}
# Scripts that cannot be drawn one character per cell: letters join, reorder or stack (shaping), or run right to
# left. A line with one of them that the printer cannot print is drawn whole, never cell by cell.
SIMPLE = {"Latn", "Grek", "Cyrl", "Armn", "Geor", "Ethi", "Hani", "Hira", "Kana", "Hang", "Bopo"} | NEUTRAL


def needs_shaping(ch: str) -> bool:
    return script_of(ch) not in SIMPLE


def shaped(text: str) -> bool:
    """Any letter that joins, stacks or runs right to left: such text is never drawn letter by letter."""
    return any(s not in SIMPLE for s in scripts_in(text))


# -- packs ------------------------------------------------------------------------------------------------


def fonts_dir() -> Path:
    return paths.data_dir() / "fonts"


def pack_dir(pack: Pack) -> Path:
    return fonts_dir() / pack.id


@lru_cache(maxsize=64)
def _verified(path: str, size: int, mtime_ns: int, sha: str) -> bool:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest() == sha


def installed(pack: Pack) -> Path | None:
    """The font file when it is here and intact (size and sha256 as pinned; checked once per process)."""
    p = pack_dir(pack) / pack.file
    try:
        st = p.stat()
    except OSError:
        return None
    if st.st_size != pack.size:
        return None
    try:
        return p if _verified(str(p), st.st_size, st.st_mtime_ns, pack.sha256) else None
    except OSError:
        return None


@lru_cache(maxsize=256)
def scripts_in(text: str) -> frozenset[str]:
    """The scripts of a text (once per text: a block asks for every word it splits)."""
    return frozenset(script_of(c) for c in set(text))


def packs_for(script: str, context: str = "", lang: str = "") -> list[Pack]:
    """Packs that draw `script`, best first. For Han: the document's language (lang: ja, ko, zh_TW), else the kana
    or hangul in `context`, else a subset already downloaded, else HAN_ORDER (Simplified Chinese first)."""
    if script != "Hani":
        return [p for p in PACKS.values() if script in p.scripts]
    ids = list(HAN_ORDER)
    lang = lang.replace("-", "_").lower()
    scripts = scripts_in(context)
    first = None
    if lang.startswith("ja") or scripts & {"Hira", "Kana"}:
        first = "japanese"
    elif lang.startswith("ko") or "Hang" in scripts:
        first = "korean"
    elif lang.startswith("zh"):
        trad = any(x in lang for x in ("hant", "_tw", "_hk", "_mo"))
        first = "chinese-traditional" if trad else "chinese"
    if first:
        ids.remove(first)
        ids.insert(0, first)
    else:
        ids.sort(key=lambda i: installed(PACKS[i]) is None)  # stable: keeps HAN_ORDER among equals
    return [PACKS[i] for i in ids]


def downloads_off() -> str:
    """Why automatic downloads are off ('' when on): BOBINA_FONT_DOWNLOADS=0, or `font_downloads = false` in
    config.toml. `bobina fonts get` downloads either way (the user asked for it)."""
    env = os.environ.get("BOBINA_FONT_DOWNLOADS", "").strip().lower()
    if env:
        return "automatic font downloads are off (BOBINA_FONT_DOWNLOADS)" if env in OFF else ""
    from . import config

    try:
        v = config.load().get("font_downloads", True)
    except Exception:  # noqa: BLE001 - a damaged config is reported by the commands that need it
        return ""
    return "automatic font downloads are off (font_downloads in config.toml)" if str(v).lower() in OFF else ""


OFF = ("0", "false", "no", "off")


def downloads_on() -> bool:
    return not downloads_off()


def human_size(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB" if n >= 1_000_000 else f"{max(1, round(n / 1000))} KB"


def source(pack: Pack) -> str:
    """Where it comes from, short: github.com/notofonts/noto-cjk."""
    return "github.com/" + "/".join(pack.url[len(RAW) :].split("/")[:2])


def notice(pack: Pack) -> str:
    return (
        f"downloading {pack.family} ({human_size(pack.size)}, {LICENSE}) from {source(pack)}, once: kept in "
        f"{pack_dir(pack)} and used offline from now on"
    )


NOTICE = None  # set by the command line: called with notice() before a download starts (a terminal line)


def fetch(url: str, size: int) -> bytes:
    """GET a pinned https URL: no redirects, no more than `size` bytes, TIMEOUT_S per read, DEADLINE_S in all.
    Tests replace this function: nothing in the test suite reaches the network."""
    if not url.startswith("https://") or url.split("/")[2] not in HOSTS:
        raise FontDownloadError(f"refused: {url} is not a pinned https source")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    start = time.monotonic()
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "bobina"}), timeout=TIMEOUT_S) as r:
            if r.status != 200:
                raise FontDownloadError(f"{url.split('/')[2]} answered {r.status}")
            chunks, got = [], 0
            while chunk := r.read(1 << 16):
                got += len(chunk)
                if got > size:
                    raise FontDownloadError("the file is larger than pinned")
                if time.monotonic() - start > DEADLINE_S:
                    raise FontDownloadError(f"the download did not finish in {DEADLINE_S // 60} minutes")
                chunks.append(chunk)
            return b"".join(chunks)
    except urllib.error.HTTPError as e:
        raise FontDownloadError(f"{url.split('/')[2]} answered {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", None) or e
        raise FontDownloadError(f"no network ({reason})") from None


def _checked(data: bytes, size: int, sha: str, what: str) -> bytes:
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
        raise FontDownloadError(f"{what} does not match its pinned checksum: not used")
    return data


def download(pack: Pack) -> Path:
    """Downloads the pack (license first, then the font), checks both, writes them atomically."""
    from . import fileio

    if (p := installed(pack)) is not None:
        return p
    if pack.size > MAX_BYTES or pack.license_size > MAX_BYTES:
        raise FontDownloadError(f"{pack.family} is larger than {human_size(MAX_BYTES)}")
    if NOTICE is not None:
        NOTICE(notice(pack))
    lic = _checked(fetch(pack.license_url, pack.license_size), pack.license_size, pack.license_sha256, "the license")
    font = _checked(fetch(pack.url, pack.size), pack.size, pack.sha256, pack.family)
    d = pack_dir(pack)
    try:
        fileio.atomic_write(d / pack.license_file, lic, mode=0o644)
        fileio.atomic_write(d / pack.file, font, mode=0o644)  # last: the font is there only with its license
    except OSError as e:
        raise FontDownloadError(f"cannot write {d}: {e.strerror or e}") from None
    return d / pack.file


# -- for other modules ------------------------------------------------------------------------------------


def scripts_of(tag: str) -> tuple[str, ...]:
    """ISO 15924 codes for a script code (Thai), a script name (Devanagari), a language or locale (th, ja_JP,
    zh_Hant). Empty when unknown."""
    from fontTools import unicodedata

    t = tag.strip().replace("-", "_")
    if len(t) == 4 and t.isalpha():
        code = t.title()
        return LANGUAGE_SCRIPTS.get(code, (code,))
    code = unicodedata.script_code(t.replace("_", " "), default=None) if len(t) > 4 else None
    if code:
        return (code,)
    t = language_names().get(t.replace("_", " ").lower(), t)  # hindi -> hi, cantonese -> zh_Hant
    from babel.core import get_global

    likely = get_global("likely_subtags")
    parts = t.split("_")
    full = likely.get(t) or likely.get(parts[0]) or ""
    script = next((x for x in parts[1:] if len(x) == 4), None) or next(
        (x for x in full.split("_")[1:] if len(x) == 4), None
    )
    return LANGUAGE_SCRIPTS.get(script, (script,)) if script else ()


# Names people use that CLDR does not list as such. Cantonese is written in Traditional characters (Hong Kong).
LANGUAGE_ALIASES = {"mandarin": "zh", "cantonese": "zh_Hant", "chinese traditional": "zh_Hant", "farsi": "fa"}


@lru_cache(maxsize=1)
def language_names() -> dict[str, str]:
    """English language names (CLDR), lower case -> code: hindi -> hi, japanese -> ja, tamil -> ta."""
    from babel import Locale

    names = {name.lower(): code for code, name in Locale("en").languages.items()}
    return {**names, **LANGUAGE_ALIASES}


def language_tag(tag: str) -> str:
    """A language name or tag as a tag: Cantonese -> zh_Hant, Hindi -> hi, ja-JP -> ja_JP (for the Han choice)."""
    t = tag.strip().replace("-", "_")
    return language_names().get(t.replace("_", " ").lower(), t)


def _bundled_draws(script: str) -> bool:
    from . import rasterfont

    sample = SAMPLES.get(script)
    return bool(sample) and all(ord(c) in rasterfont.cmap(rasterfont.resolve("DejaVu Sans").path) for c in sample)


# one or two common letters per script: enough to know whether the bundled fallback draws it
SAMPLES = {
    "Latn": "aç", "Grek": "αω", "Cyrl": "жя", "Armn": "աֆ", "Geor": "აჰ", "Hebr": "אש", "Arab": "بم",
    "Thai": "กส", "Deva": "कन", "Beng": "কন", "Guru": "ਕਨ", "Gujr": "કન", "Orya": "କନ", "Taml": "கந",
    "Telu": "కన", "Knda": "ಕನ", "Mlym": "കന", "Sinh": "කන", "Laoo": "ກສ", "Khmr": "កន", "Mymr": "ကန",
    "Ethi": "ሀለ", "Thaa": "ހށ", "Tibt": "ཀན", "Hani": "中文", "Hira": "あい", "Kana": "アイ", "Hang": "한글",
    "Bopo": "ㄅㄆ",
}  # fmt: skip


def support(tag: str) -> str:
    """Can bobina draw this script or language? 'ready' (a bundled font, or a font already downloaded), 'download'
    (a pinned Noto font exists: downloaded on first use, or now with `bobina fonts get`; see downloads_on() for
    whether that happens by itself) or 'none' (unknown, or no font bobina knows). For locale code: support("th"),
    support("ja_JP"), support("Deva")."""
    scripts = scripts_of(tag)
    if not scripts:
        return "none"
    worst = "ready"
    for s in scripts:
        if _bundled_draws(s):
            continue
        packs = packs_for(s, "".join(SAMPLES.get(x, "") for x in scripts), language_tag(tag))
        if not packs:
            return "none"
        if installed(packs[0]) is None:
            worst = "download"
    return worst


def packs_needed(text: str, lang: str = "") -> list[Pack]:
    """The packs a text needs: its letters that no bundled font draws, by script (`bobina fonts get DOCUMENT`)."""
    from . import rasterfont

    bundled = rasterfont.cmap(rasterfont.resolve("DejaVu Sans").path)
    near = "".join(SAMPLES.get(s, "") for s in scripts_in(text))  # kana or hangul in the text: Japanese, Korean
    needed = {script_of(ch) for ch in set(text) if not ch.isspace() and ord(ch) not in bundled}
    out: list[Pack] = []
    for script in sorted(needed):
        packs = packs_for(script, near, lang)
        if packs and packs[0] not in out:
            out.append(packs[0])
    return out


def resolve_names(names: list[str]) -> tuple[list[Pack], list[str]]:
    """`bobina fonts get` arguments -> packs: a pack id (thai, chinese), 'all', a script or a language."""
    found: list[Pack] = []
    unknown: list[str] = []
    for n in names:
        key = n.strip().lower()
        if key == "all":
            found += PACKS.values()
            continue
        if key in PACKS:
            found.append(PACKS[key])
            continue
        scripts = scripts_of(n)
        near, lang = "".join(SAMPLES.get(x, "") for x in scripts), language_tag(n)
        packs = [packs_for(s, near, lang) for s in scripts if not _bundled_draws(s)]
        if scripts and all(packs) and packs:
            found += [p[0] for p in packs]
        elif scripts and not packs and all(_bundled_draws(s) for s in scripts):
            continue  # nothing to download: the bundled fonts draw it
        else:
            unknown.append(n)
    return list(dict.fromkeys(found)), unknown


# -- per document -----------------------------------------------------------------------------------------

_FAILED: dict[str, tuple[str, float]] = {}  # pack id -> (why, when): a batch of 1000 labels tries once
FAILED_TTL_S = 120  # then again: a long-running process (bobina mcp) notices the network coming back


def _failed(pack_id: str) -> str | None:
    hit = _FAILED.get(pack_id)
    if hit and time.monotonic() - hit[1] < FAILED_TTL_S:
        return hit[0]
    _FAILED.pop(pack_id, None)
    return None


class Resolver:
    """Which downloaded font draws a run, for one document: downloads once (F304, after the notice) or says why
    not (F305); both once per pack and document. hints[script]: what to say about a letter still missing."""

    def __init__(self, nudges, lang: str = ""):
        self.n = nudges
        self.lang = lang  # the document's locale/lang: which Chinese, Japanese or Korean font draws Han
        self.hints: dict[str, str] = {}
        self._told: set[str] = set()
        self._off: str | None = None  # downloads_off(), read once per document

    def off(self) -> str:
        if self._off is None:
            self._off = downloads_off()
        return self._off

    def path(self, script: str, text: str, line: int | None, context: str = "") -> str | None:
        packs = packs_for(script, context, self.lang)
        if not packs:
            return None
        letters = "".join(c for c in text if script_of(c) == script)
        here = [(p, f) for p in packs if (f := installed(p)) is not None]
        for _p, f in here:  # a subset already here that has every letter (Han in the Japanese subset, say)
            if covers(str(f), letters):
                return str(f)
        pack = packs[0]
        if here and here[0][0] == pack:  # the best font is here and lacks a letter: the others are drawn
            self.hints[script] = f"{pack.family} has no such letter: replace it, or pick a font that has it"
            return str(here[0][1])
        why = _failed(pack.id) or self.off() or None
        if why is None:
            try:
                f = download(pack)
            except FontDownloadError as e:
                why = str(e)
                _FAILED[pack.id] = (why, time.monotonic())
            else:
                if pack.id not in self._told:
                    self._told.add(pack.id)
                    self.n.add(
                        "F304",
                        f"{pack.family} downloaded for {script_name(script)} text ({human_size(pack.size)}, {LICENSE},"
                        f" from {source(pack)}): kept in {pack_dir(pack)}, used offline from now on",
                        line,
                        "to never download fonts: font_downloads = false in config.toml",
                    )
                return str(f)
        if here:  # another subset is here (Japanese for a Chinese letter): it draws what it has
            self.hints[script] = f"{pack.family} may have it, not downloaded ({why}): bobina fonts get {pack.id}"
            return str(here[0][1])
        if pack.id not in self._told:
            self._told.add(pack.id)
            self.n.add(
                "F305",
                f"{script_name(script)} text needs {pack.family} ({human_size(pack.size)}), not downloaded: {why};"
                " those letters print as boxes",
                line,
                f"bobina fonts get {pack.id} (once, with the network); then it works offline",
            )
        return None


def covers(path: str, text: str) -> bool:
    """The font has every letter of `text` (spaces aside; a font whose table cannot be read counts as complete)."""
    from . import rasterfont

    cm = rasterfont.cmap(path)
    return not cm or all(ord(c) in cm for c in text if not c.isspace())


def direction(text: str) -> str:
    """'R' when the first letter with a direction is right-to-left (Arabic, Hebrew), 'L' for other letters, ''
    for none (digits, spaces, punctuation: they take the direction around them)."""
    for ch in text:
        s = script_of(ch)
        if s in NEUTRAL:
            continue
        return "R" if s in RTL else "L"
    return ""


def base_rtl(text: str) -> bool:
    """A paragraph is right-to-left when its first letter with a direction is (Unicode bidi, rule P2)."""
    return direction(text) == "R"
