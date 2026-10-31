"""Decisions reach CI Health: a quarantine decision puts a test on the list (and taking it out keeps a flaky one off),
mutes and acknowledgements cover jobs as well as tests (no alert, no new issue), and the page says who decided what."""
from stackvitals.ci.automation import apply_decisions, new_flakes, quarantine_list, sync_issues


def result():
    return {"tests": [{"id": "t::flaky", "state": "flaky", "flake_events": 3, "runs": 20},
                      {"id": "t::ok", "state": "ok"}, {"id": "t::calm", "state": "flaky", "flake_events": 2, "runs": 9}],
            "jobs": [{"workflow": ".github/workflows/ci.yml", "job": "lint", "state": "flaky", "flake_events": 2, "runs": 9}]}


STATE = {"test:t::ok": {"verb": "quarantine", "kind": "test", "id": "t::ok", "until": "2026-11-20", "by": "alice", "reason": "upstream"},
         "test:t::flaky": {"verb": "unquarantine", "kind": "test", "id": "t::flaky", "until": None, "by": "bob", "reason": "must block"},
         "test:t::calm": {"verb": "acknowledge", "kind": "test", "id": "t::calm", "until": None, "by": "carol", "reason": ""},
         "job:ci.yml / lint": {"verb": "mute", "kind": "job", "id": "ci.yml / lint", "until": "2026-11-01", "by": "alice", "reason": "linter bump"}}


def test_quarantine_decisions_join_the_list_and_unquarantine_keeps_a_flaky_test_off():
    r = result()
    apply_decisions(r, STATE)
    # t::calm flaked twice: too few to quarantine on its own (3+ since Phase 14), and acknowledging it adds nothing.
    assert quarantine_list(r, None, STATE) == ["t::ok"]


def test_muted_and_acknowledged_items_raise_no_alert_and_get_no_new_issue():
    r = result()
    apply_decisions(r, STATE)
    assert r["jobs"][0]["muted_until"] == "2026-11-01" and r["tests"][2]["muted_until"] == "9999-12-31"
    assert new_flakes({"tests": [], "jobs": []}, r) == ["test t::flaky"]

    class Api:
        repo = "o/r"
        sent = []

        def _get(self, path, params=None):
            return []

        def send(self, method, path, body=None):
            self.sent.append(body["title"])
            return {}
    api = Api()
    sync_issues(api, r)
    assert api.sent == ["Flaky test: t::flaky"]


def test_the_page_says_who_decided_what():
    from stackvitals.ci.report import _why, decided_text
    r = result()
    apply_decisions(r, STATE)
    assert "acknowledged by carol" in _why(r["tests"][2]) and "9999" not in _why(r["tests"][2])
    assert decided_text(r["jobs"][0]) == "muted by alice until 2026-11-01: linter bump"
