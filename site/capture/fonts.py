#!/usr/bin/env python3
"""Copy the fonts bobina bundles (src/bobina/fonts) to the site as WOFF2, with their licenses.

WOFF2 is only a compressed container: the font data is not changed, subset or renamed (the OFL FAQ allows WOFF
copies under the original name on these terms). Needs fontTools with brotli:

    site/.capture-venv/bin/python -m pip install --index-url https://pypi.org/simple fonttools brotli
    site/.capture-venv/bin/python site/capture/fonts.py
"""

import shutil
from pathlib import Path

from fontTools.ttLib import woff2

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "bobina" / "fonts"
OUT = ROOT / "site" / "public" / "fonts"
FONTS = {  # source file → (web file, license)
    "AtkinsonHyperlegible-Regular.ttf": ("atkinson-hyperlegible-regular.woff2", "AtkinsonHyperlegible-OFL.txt"),
    "AtkinsonHyperlegible-Bold.ttf": ("atkinson-hyperlegible-bold.woff2", "AtkinsonHyperlegible-OFL.txt"),
    "spleen-12x24.otf": ("spleen-12x24.woff2", "Spleen-BSD-2.txt"),
    "TerminusTTF-4.49.3.ttf": ("terminus.woff2", "Terminus-OFL.txt"),
    "TerminusTTF-Bold-4.49.3.ttf": ("terminus-bold.woff2", "Terminus-OFL.txt"),
}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for src, (dest, lic) in FONTS.items():
        woff2.compress(str(SRC / src), str(OUT / dest))
        shutil.copy(SRC / "licenses" / lic, OUT / lic)
        print(f"{dest}: {(OUT / dest).stat().st_size // 1024} KB")
