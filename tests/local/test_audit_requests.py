"""Pre-launch audit: closing a flaky-test issue as not planned is a decision, so it needs triage access like any other."""
from test_core_requests import GitHub, run


def _closed(login):
    return {"action": "closed", "sender": {"login": login},
            "issue": {"number": 8, "title": "Flaky test: t::a", "state_reason": "not_planned", "labels": [{"name": "flaky-test"}]}}


def test_a_closer_without_triage_access_records_nothing(tmp_path, capsys):
    gh = GitHub()
    out, seen = run(tmp_path, "issues", _closed("mallory"), gh)
    assert "test:t::a" not in seen["state"]
    assert "no decision was recorded" in capsys.readouterr().out
    assert any(p.endswith("/collaborators/mallory/permission") for _m, p, _b in gh.calls)


def test_a_closer_with_triage_access_acknowledges(tmp_path):
    _out, seen = run(tmp_path, "issues", _closed("alice"), GitHub(permission="triage"))
    assert seen["state"]["test:t::a"]["verb"] == "acknowledge"
