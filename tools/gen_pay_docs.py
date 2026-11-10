"""Regenerates docs/pay.md (every payment scheme, what each field means in it, its official name and limit) from
the registry in src/bobina/pay.py, the same text as `bobina help pay SCHEME`. Run after changing a scheme:
python tools/gen_pay_docs.py (tests/test_pay.py fails until the page matches). Never edit docs/pay.md by hand."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bobina.pay import docs_page  # noqa: E402

PAGE = ROOT / "docs" / "pay.md"


def main() -> None:
    PAGE.write_text(docs_page(), encoding="utf-8")
    print(f"wrote {PAGE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
