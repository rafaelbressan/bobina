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
