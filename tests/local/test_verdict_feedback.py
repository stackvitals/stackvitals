from datetime import date, datetime, timezone

from stackvitals.core.decisions import Decision, Store, parse_command, verdict_accuracy
from stackvitals.core.requests import seen_state

TODAY = date(2026, 10, 22)
NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)


def test_people_can_confirm_or_dispute_a_verdict_from_a_comment():
    out = parse_command("/stackvitals dispute test:t::a because the change broke it", TODAY)
    assert out == [Decision("dispute", "test", "t::a", None, "the change broke it")]
    assert parse_command('/stackvitals confirm job:"ci.yml / e2e"', TODAY)[0].verb == "confirm"


def test_feedback_is_logged_but_never_changes_what_is_in_force(tmp_path):
    store = Store(tmp_path)
    store.record([Decision("quarantine", "test", "t::a", "2026-11-20", "flaky")], by="ann", source="comment", now=NOW)
    store.record([Decision("dispute", "test", "t::a", None, "broke")], by="bob", source="comment", now=NOW,
                 seen={("test", "t::a"): {"state": "flaky", "flake_events": 4}})
    assert store.state(TODAY)["test:t::a"]["verb"] == "quarantine"
    rows = store.feedback()
    assert [(r["verb"], r["seen"]["state"]) for r in rows] == [("dispute", "flaky")]


def test_verdict_accuracy_counts_confirms_against_disputes_per_verdict():
    rows = ([{"verb": "confirm", "kind": "test", "id": f"t{i}", "seen": {"state": "flaky"}} for i in range(3)]
            + [{"verb": "dispute", "kind": "test", "id": "t9", "seen": {"state": "flaky"}},
               {"verb": "dispute", "kind": "job", "id": "j", "seen": {"state": "ok"}},
               {"verb": "confirm", "kind": "job", "id": "k", "seen": None}])
    out = verdict_accuracy(rows)
    assert out["flaky"]["confirmed"] == 3 and out["flaky"]["disputed"] == 1 and out["flaky"]["share"] == 0.75
    assert out["flaky"]["low"] < 0.75 < out["flaky"]["high"]
    assert out["ok"]["share"] == 0.0 and out["unknown"]["confirmed"] == 1


def test_the_verdict_people_saw_is_read_from_the_published_findings():
    result = {"tests": [{"id": "t::a", "state": "flaky", "flake_events": 4}, {"id": "t::b", "state": "flaky", "flake_events": 2}],
              "jobs": [{"workflow": ".github/workflows/ci.yml", "job": "e2e", "state": "broken", "flake_events": 0}]}
    assert seen_state(result, "test", "t::a") == {"state": "flaky", "flake_events": 4, "verdict": "known flaky"}
    assert seen_state(result, "test", "t::b")["verdict"] == "flaked before"
    assert seen_state(result, "job", "ci.yml / e2e")["verdict"] == "already failing"
    # The pull request comment names a job by the workflow's display name.
    assert seen_state(result, "job", "CI / e2e")["state"] == "broken"
    assert seen_state(result, "test", "missing") is None and seen_state(None, "test", "t::a") is None


def test_accuracy_is_counted_per_verdict_shown_not_per_state():
    rows = [{"verb": "dispute", "kind": "test", "id": "t::b", "by": "x", "seen": {"state": "flaky", "verdict": "flaked before"}}]
    assert "flaked before" in verdict_accuracy(rows) and "flaky" not in verdict_accuracy(rows)


def test_a_bare_dispute_on_a_pull_request_says_which_items_it_needs():
    import pytest
    from stackvitals.core.decisions import CommandError
    with pytest.raises(CommandError, match="test:"):
        parse_command("/stackvitals dispute because wrong", TODAY, default=("pr", "12"))


def test_the_answer_on_github_says_what_was_recorded():
    from stackvitals.core.requests import _decided
    text = _decided([Decision("dispute", "test", "t::a", None, "broke"), Decision("confirm", "job", "ci.yml / e2e", None, "")])
    assert "verdict was wrong" in text and "verdict was right" in text and "undo" not in text
