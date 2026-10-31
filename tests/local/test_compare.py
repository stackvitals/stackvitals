"""The compare pages, the README's table and llms.txt come from one list (core/compare.py) and stay in step; every claim
about another tool names a source, and every number of ours links the card it comes from."""
from pathlib import Path

from stackvitals.core import compare, llmsdoc

ROOT = Path(__file__).resolve().parents[2]
# Rebuild after editing compare.py:
#   python -c "from pathlib import Path; from stackvitals.core import compare; [Path(p).write_text(t, encoding='utf-8', newline='\n') for p, t in compare.pages().items()]"


def test_the_compare_pages_are_current():
    for path, text in compare.pages().items():
        assert (ROOT / path).read_text(encoding="utf-8") == text, f"{path} is out of date with core/compare.py"
    written = {p.relative_to(ROOT).as_posix() for p in (ROOT / compare.PAGES).glob("*.md")}
    assert written == set(compare.pages()), "a compare page was added or left behind by hand"


def test_every_tool_names_sources_and_every_number_links_its_evidence():
    for a in compare.ALTERNATIVES:
        assert a["sources"] and all(url.startswith(("https://", "http://web.archive.org/")) for _, url in a["sources"]), a["slug"]
        assert a["better"] and a["ours"] and a["not_measured"], a["slug"]
        for _, src in a["measured"]:
            assert (ROOT / compare.PAGES / src).resolve().exists(), src
    for _, page in compare.FACTS:
        assert (ROOT / "docs" / page.split("#")[0]).exists(), page


def test_the_readme_and_llms_txt_carry_the_same_list():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert compare.readme_table() in readme, "the README's compare table is out of date with core/compare.py"
    llms = llmsdoc.markdown(ROOT)
    assert "## Compared with" in llms and all(line in llms for line in compare.llms_facts())
    for a in compare.ALTERNATIVES:
        assert f"docs/compare/{a['slug']}.md" in llms
