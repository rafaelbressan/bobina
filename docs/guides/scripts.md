# Other scripts

Thai, Indic, Khmer, Myanmar, Ethiopic and CJK letters are not in the printer font ([FORMAT §4](../FORMAT.md)).

The first time a document needs one, bobina downloads its Noto font (pinned, 38 KB for Thai, up to 8.3 MB for
CJK), says so first (font, OFL license, size, source; `F304`) and keeps it in `~/.local/share/bobina/fonts/` for
offline use. No network, or `bobina config set font_downloads off`: boxes and `F305` (`bobina fonts get thai`, a
language or a document). Han follows `lang:` (ja, ko, zh-TW), else nearby kana or hangul, else Simplified Chinese.
These lines, and Arabic or Hebrew ones, are drawn whole (joined, stacked, right to left), never letter by letter.
