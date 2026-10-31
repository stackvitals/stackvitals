"""A PR whose CI passed only because quarantined tests were let through says so, naming them."""
from stackvitals.ci.feedback import MARKER, quarantine_note, quarantined_failures


def report(run, att, failed):
    return {"t": "tests", "run": run, "att": att, "art": run * 10 + att, "name": "junit", "total": 5, "skipped": 0,
            "flaky": [], "slow": [], "failed": [[t, "k", "boom"] for t in failed]}


def test_quarantined_failures_on_the_final_attempts_of_green_runs_are_named():
    data = {"runs": [{"id": 1, "att": 1}, {"id": 1, "att": 2}, {"id": 2, "att": 1}],
            "tests": [report(1, 1, ["a", "b"]), report(1, 2, ["a"]), report(2, 1, ["c"])]}
    assert quarantined_failures(data, [1, 2], {"a", "c"}) == ["a", "c"]
    assert quarantined_failures(data, [1], set()) == []
    assert quarantined_failures(data, [1], None) == []


def test_the_note_names_the_tests_and_never_pings_anyone():
    text = quarantine_note(["tests/x.py::t1", "@admins `x`"], "o/r")
    assert text.startswith(MARKER) and "passed only because" in text and "tests/x.py::t1" in text
    assert "@admins" not in text


def test_the_let_through_note_says_how_long_each_test_has_been_quarantined_and_who_owns_it():
    from datetime import datetime, timezone
    result = {"tests": [{"id": "t::old", "state": "flaky", "since": "2026-09-01T00:00:00Z", "owners": ["@qa"]},
                        {"id": "t::new", "state": "flaky", "since": "2026-10-20T00:00:00Z", "owners": []}]}
    text = quarantine_note(["t::old", "t::new"], "o/r", result, datetime(2026, 10, 22, tzinfo=timezone.utc))
    assert "flaky since 2026-09-01, 51 days" in text and "@\u200bqa" in text and "@qa" not in text
    assert "over 30 days" in text and "/stackvitals unquarantine test:" in text
    assert "flaky since 2026-10-20, 2 days" in text
