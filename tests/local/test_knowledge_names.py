import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_flow_m2 import NOW, history  # noqa: E402

from stackvitals.flow.build import build  # noqa: E402
from stackvitals.flow.report import _knowledge_lines  # noqa: E402


def test_a_public_repo_names_areas_not_people():
    data = {"open": [], "closed": history()}
    named = build(data, {"default_branch": "main"}, NOW, names=True)
    hidden = build(data, {"default_branch": "main"}, NOW, names=False)
    assert any(a.get("owner") == "dana" for a in named["knowledge"]["areas"])
    assert all(a.get("owner") is None for a in hidden["knowledge"]["areas"])
    text = " ".join(_knowledge_lines(hidden))
    assert "dana" not in text and "src/db" in text
