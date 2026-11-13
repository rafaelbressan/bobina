"""Regenerates docs/contact.md (every contact network, what its block takes, its link format and where that format
is documented) from the registry in src/bobina/contact.py, the same text as `bobina help contact NETWORK`. Run after
changing a network: python tools/gen_contact_docs.py (tests/test_contact.py fails until the page matches). Never
edit docs/contact.md by hand."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bobina.contact import docs_page  # noqa: E402

PAGE = ROOT / "docs" / "contact.md"


def main() -> None:
    PAGE.write_text(docs_page(), encoding="utf-8")
    print(f"wrote {PAGE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
