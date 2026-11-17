"""Token budget per page: an agent pays for every page it reads, and docs grow. A page over its budget fails here
(and in CI): split it or cut it, do not just raise the number. Tokens are estimated as characters / 4."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUDGET = {  # tokens; set on 08/11 about 25% above the size then
    "llms.txt": 1000,
    "AGENTS.md": 800,
    "skills/bobina/SKILL.md": 1200,
    "README.md": 3000,
    "docs/CLI.md": 9000,
    "docs/agents.md": 1500,  # set on 11/11, when the MCP section moved here from CLI.md
    "docs/chat.md": 1800,  # set on 11/11, with bobina chat (its terminal screen and paper styles)
    "docs/FORMAT.md": 8500,
    "docs/guides/batch-printing.md": 3500,
    "docs/guides/templates.md": 2500,
    "docs/guides/icons.md": 3800,  # set on 13/11, with icons (generated: one row per icon, not in llms-full.txt)
    "docs/guides/tables.md": 1450,  # set on 15/11, with table styles and fonts (not in llms-full.txt; FORMAT links it)
    "docs/guides/receipts.md": 585,  # set on 16/11, whole receipt recipes split from tables.md (not in llms-full.txt)
    "docs/guides/table-cells.md": 1200,  # set on 16/11, cells, rows and span= split from tables.md (not in llms-full)
    "docs/guides/layout.md": 1150,  # set on 16/11, with boxes (::: {.box}); not in llms-full.txt (FORMAT links it)
    "docs/guides/layout-columns.md": 1250,  # set on 17/11, with columns (:::: {.columns}); not in llms-full.txt
    "docs/guides/layout-columns-turned.md": 690,  # set on 17/11, turned columns split from layout-columns.md (not in llms-full)
    "docs/guides/receipts-supermarket.md": 385,  # set on 17/11, split from receipts.md (not in llms-full.txt)
    "docs/guides/counters.md": 260,  # set on 17/11, when a number is taken: split from FORMAT §7.3 (not in llms-full)
    "docs/pay.md": 3000,
    "docs/contact.md": 3000,
    "docs/SECURITY.md": 2000,
    "docs/INSTALL.md": 1100,  # set on 10/11, as above
    "docs/printers/mtp-ii-58.md": 3000,
    "docs/problems/README.md": 2500,  # the index: since 17/11 the categories, each code's meaning on their pages
    # one page per category of problem codes (generated; set on 17/11 about 25% above the size then)
    "docs/problems/drawing.md": 110,
    "docs/problems/fonts.md": 355,
    "docs/problems/codes.md": 390,
    "docs/problems/layout.md": 395,  # raised on 17/11 for L112 and L113 (turned columns): ~20% headroom
    "docs/problems/images.md": 335,
    "docs/problems/errors.md": 700,
    "docs/problems/printer-and-paper.md": 465,
    "docs/problems/markup-and-data.md": 965,
    "llms-full.txt": 25000,
}


def tokens(text: str) -> int:
    return len(text) // 4


@pytest.mark.parametrize("page", sorted(BUDGET))
def test_page_within_its_token_budget(page):
    n = tokens((ROOT / page).read_text(encoding="utf-8"))
    assert n <= BUDGET[page], f"{page}: ~{n} tokens, budget {BUDGET[page]}"


def test_each_problem_page_is_short():
    pages = [p for p in (ROOT / "docs" / "problems").glob("*.md") if p.stem[1:].isdigit()]  # a code's page
    assert pages and max(tokens(p.read_text(encoding="utf-8")) for p in pages) <= 300


def test_the_first_500_tokens_of_the_readme_tell_an_agent_what_it_needs():
    head = (ROOT / "README.md").read_text(encoding="utf-8")[: 500 * 4]
    for must in ("bobina print", "--yes", "E107", "llms.txt"):
        assert must in head, must
