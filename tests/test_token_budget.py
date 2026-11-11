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
    "docs/chat.md": 1200,  # set on 11/11, with bobina chat
    "docs/FORMAT.md": 8500,
    "docs/guides/batch-printing.md": 3500,
    "docs/guides/templates.md": 2500,
    "docs/pay.md": 3000,
    "docs/SECURITY.md": 2000,
    "docs/INSTALL.md": 1100,  # set on 10/11, as above
    "docs/printers/mtp-ii-58.md": 3000,
    "docs/problems/README.md": 2500,
    "llms-full.txt": 25000,
}


def tokens(text: str) -> int:
    return len(text) // 4


@pytest.mark.parametrize("page", sorted(BUDGET))
def test_page_within_its_token_budget(page):
    n = tokens((ROOT / page).read_text(encoding="utf-8"))
    assert n <= BUDGET[page], f"{page}: ~{n} tokens, budget {BUDGET[page]}"


def test_each_problem_page_is_short():
    pages = [p for p in (ROOT / "docs" / "problems").glob("*.md") if p.name != "README.md"]
    assert pages and max(tokens(p.read_text(encoding="utf-8")) for p in pages) <= 300


def test_the_first_500_tokens_of_the_readme_tell_an_agent_what_it_needs():
    head = (ROOT / "README.md").read_text(encoding="utf-8")[: 500 * 4]
    for must in ("bobina print", "--yes", "E107", "llms.txt"):
        assert must in head, must
