"""Golden bitmaps: the exact preview of each document in tests/golden must not change by accident.
Regenerate after an intended change with: BOBINA_UPDATE_GOLDEN=1 pytest tests/test_golden.py"""

import os
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from bobina.engine import build

GOLDEN = Path(__file__).parent / "golden"
CONFORMANCE = Path(__file__).parent.parent / "spec" / "conformance"
GALLERY = Path(__file__).parent.parent / "examples" / "templates"  # the images of docs/guides/templates.md
DOCS = sorted(GOLDEN.glob("*.bob.md")) + sorted(CONFORMANCE.glob("*.bob.md")) + sorted(GALLERY.glob("*.bob.md"))


@pytest.mark.parametrize("doc", DOCS, ids=[f"{d.parent.name}/{d.stem}" for d in DOCS])
def test_golden(doc):
    res = build(doc.read_text(), base_dir=str(doc.parent))
    img = res.image.convert("L")
    ref = doc.with_suffix("").with_suffix(".png")
    if os.environ.get("BOBINA_UPDATE_GOLDEN") or not ref.exists():
        img.save(ref)
        pytest.skip(f"golden written: {ref.name}")
    expected = Image.open(ref).convert("L")
    assert img.size == expected.size, f"size {img.size} != {expected.size}"
    diff = ImageChops.difference(img, expected).getbbox()
    assert diff is None, f"bitmap differs in box {diff}"
