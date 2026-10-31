"""llms.txt: the docs index an AI agent reads first, made from docs/ and kept current by this test."""
from pathlib import Path

from stackvitals.core import llmsdoc

ROOT = Path(__file__).resolve().parents[2]


def test_llms_txt_is_current_and_lists_every_docs_page():
    text = (ROOT / "llms.txt").read_text(encoding="utf-8")
    # Rebuild with: python -c "from pathlib import Path; from stackvitals.core import llmsdoc;
    #   Path('llms.txt').write_text(llmsdoc.markdown(Path('.')), encoding='utf-8')"
    assert text == llmsdoc.markdown(ROOT), "llms.txt is out of date with docs/; rebuild it (see the comment above)"
    for page in (ROOT / "docs").rglob("*.md"):
        assert f"]({page.relative_to(ROOT).as_posix()})" in text


def test_each_entry_has_a_plain_first_sentence():
    assert llmsdoc._first_sentence("# T\n\nRead [the guide](x.md) with `cmd`. More text.\n") == "Read the guide with cmd."
