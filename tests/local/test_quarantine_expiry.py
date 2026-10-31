"""Quarantine with an end (Datadog's quarantine policies): a flaky test quarantined on its own longer than max_days
fails builds again and is listed as overdue; ones a person quarantined stay."""
from datetime import datetime, timezone

from stackvitals.ci.automation import expired, quarantine_list
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def test_old_flaky_tests_leave_quarantine_after_max_days():
    result = {"tests": [{"id": "old", "state": "flaky", "flake_events": 9, "since": "2026-08-01T00:00:00Z"},
                        {"id": "new", "state": "flaky", "flake_events": 9, "since": "2026-10-20T00:00:00Z"}]}
    cfg = parse("[ci.quarantine]\nmax_days = 30\nalways = [\"old\"]\n")[0]
    assert expired(result, cfg, NOW) == ["old"]
    # "always" is a person's choice: it keeps the test in.
    assert quarantine_list(result, cfg, {}, NOW) == ["new", "old"]
    assert quarantine_list(result, parse("[ci.quarantine]\nmax_days = 30\n")[0], {}, NOW) == ["new"]
    assert quarantine_list(result, parse("")[0], {}, NOW) == ["new", "old"]


def test_a_bad_max_days_is_refused():
    cfg, notes = parse("[ci.quarantine]\nmax_days = -3\n")
    assert cfg["ci"]["quarantine"]["max_days"] == 0 and notes
