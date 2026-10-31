"""Pre-launch audit: the threat model names the triage endpoint exception and the shared github.io origin."""
from pathlib import Path

DOC = (Path(__file__).parents[2] / "docs" / "threat-model.md").read_text(encoding="utf-8")


def test_the_threat_model_names_the_triage_url_exception():
    assert "The one exception is the triage key" in DOC and "`[ci.triage] url`" in DOC and "write access can change" in DOC


def test_the_threat_model_notes_the_shared_github_io_origin():
    assert "`<owner>.github.io`" in DOC and "same tab can read the tab's token" in DOC


def test_privacy_names_the_public_benchmark_home():
    from stackvitals.core import dataflow
    assert "from stackvitals/stackvitals's releases" in dataflow.markdown()
