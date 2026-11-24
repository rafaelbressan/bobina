"""Features bobina implements but nobody has seen on paper yet: they follow the ESC/POS specification and are tested
on the bytes, not on a printer. A job that uses one gets note P301; `bobina profile show` lists the ones a profile
turns on; docs/TESTED.md and the docs sections carry the same mark. When a feature is confirmed on paper, set
tested_on_paper (with the evidence) and the notes go away."""

from __future__ import annotations

MARK = "⚠ not tested on paper"

FEATURES = {
    "codepage": {
        "title": "native text through code pages (ESC t)",
        "where": 'profiles with encoding = "codepage" (most imported profiles)',
        "tested_on_paper": False,
        "evidence": "",
    },
    "cutter": {
        "title": "automatic cutter (GS V) where a label ends (not between --compact labels: glued on purpose)",
        "where": 'profiles with cutter = "full" or "partial"',
        "tested_on_paper": False,
        "evidence": "",
    },
    "native-barcode-imported": {
        "title": "native barcodes (GS k) on an imported profile",
        "where": "imported profiles whose printer has barcode commands (barcode.native not empty)",
        "tested_on_paper": False,
        "evidence": "",
    },
    "box": {
        "title": "boxes (::: {.box}): a frame around blocks, its title and grey, printed as one image",
        "where": "documents with ::: {.box} (docs/guides/layout.md)",
        "tested_on_paper": True,
        "evidence": "MTP-II, 18/11: a border title box (MESA, # 12) and a dashed band box with .shade (PAGO, Total R$ "
        "93,50) printed as the preview: frame whole, title cut into the border, band black, grey even; on the grey "
        "the thin top bar of a T fades (text on .shade: prefer bold)",
    },
    "inverted-box": {
        "title": "inverted boxes (::: {.box .invert}): one black band, what it holds printed white",
        "where": "documents with ::: {.box .invert} (docs/guides/layout.md)",
        "tested_on_paper": True,
        "evidence": "MTP-II, 24/11 (printed 22/11): a band-title box holding an inverted logo, bold lines, a 2x span "
        "and plain text, and a box with a QR in its white tile beside two lines, printed as the preview (the QR "
        "scanned): the black even, the tile white; plain small white text prints thin (bold holds up better)",
    },
    "columns": {
        "title": "columns side by side (:::: {.columns}), each row of them printed as one image",
        "where": "documents with :::: {.columns} (docs/guides/layout-columns.md)",
        "tested_on_paper": True,
        "evidence": "MTP-II, 18/11: an NFC-e footer (a QR at 40%, two lines at 60%, valign=middle) and two auto text "
        "columns (the right one .right) printed as the preview, the text at the QR's middle; the QR scanned",
    },
    "turned-columns": {
        "title": "turned columns (:::: {.columns orientation=vertical}): a label along the roll, read sideways",
        "where": "documents with :::: {.columns orientation=vertical} (docs/guides/layout-columns-turned.md)",
        "tested_on_paper": True,
        "evidence": "MTP-II, 18/11: a 100 mm shelf label (name, 500 g and an EAN-13 at module 4 with 10-module margins "
        "at 60%, R$ 18,90 size=3x at 40%, valign=middle) printed as the preview and the phone scanned its EAN-13; it "
        "reads right with the paper's right edge up. The first strip that day: a 72 mm label's EAN-13 at module 2 did "
        "not scan, and a box drawn at 75% blurred letters (both changed)",
    },
    "charts": {
        "title": "charts drawn from a table (chart=line, bar, area, sparkline)",
        "where": "tables with chart= (docs/guides/charts.md)",
        "tested_on_paper": True,
        "evidence": "MTP-II, 24/11 (printed 22/11): a line chart with .grid and dates, a two-series bar chart with its "
        "legend, an area chart with a title and negative values, and a sparkline in a column, printed as the "
        "preview: 2-dot lines clean, the dotted grey of meta and area even, turned Y labels legible",
    },
    "zebra": {
        "title": "the light grey dots behind table text (style=zebra, .shade on a cell or row)",
        "where": "tables with style=zebra or .shade (the pattern: SHADE_DOT and SHADE_STEP in imaging.py)",
        "tested_on_paper": True,
        "evidence": "MTP-II, 16/11: four patterns printed (2-dot squares every 3, 4, 6; 3-dot every 6); 2 every 4 "
        "reads as an even grey with clean text, 3-dot squares read as accents; grid strokes of 2 and 3 dots: 2 kept "
        "the text black, 3 faded the text in its rows",
    },
}


def untested() -> dict:
    return {k: v for k, v in FEATURES.items() if not v["tested_on_paper"]}


def of_profile(prof) -> list[str]:
    """The untested features this profile turns on (whether or not a given job uses them)."""
    out = []
    if prof.get("encoding") == "codepage":
        out.append("codepage")
    if prof.get("cutter", "none") in ("full", "partial"):
        out.append("cutter")
    if prof.get("measured", True) is False and prof.get("barcode.native"):
        out.append("native-barcode-imported")
    return [f for f in out if f in untested()]
