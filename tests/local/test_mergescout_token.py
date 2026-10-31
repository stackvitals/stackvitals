"""MergeScout finds a token the same way as the rest of the suite (real data, 2026-10-21: with only GH_TOKEN set it fell
back to a six-day-old snapshot, and 3 of its top 4 issues were already closed)."""
from mergescout.tool.store import data_token


def test_gh_token_and_the_suites_own_token_are_used(monkeypatch):
    for name in ("MERGESCOUT_TOKEN", "STACKVITALS_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert data_token() is None
    monkeypatch.setenv("GH_TOKEN", "gh")
    assert data_token() == "gh"
    monkeypatch.setenv("STACKVITALS_TOKEN", "sv")
    assert data_token() == "sv"
    monkeypatch.setenv("MERGESCOUT_TOKEN", "ms")
    assert data_token() == "ms"
