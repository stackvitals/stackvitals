"""The weekly bug backlog (DevLake's weekly bug retro), from GitHub bug labels alone or with a tracker's bugs."""
from datetime import datetime, timezone

from stackvitals.core import bugs

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)  # a Thursday


def test_weeks_count_opened_closed_and_still_open_bugs_from_labels_and_trackers():
    issues = [{"n": 1, "cr": "2026-10-27T09:00:00Z", "cl": None, "lb": ["type: bug"]},
              {"n": 2, "cr": "2026-10-20T09:00:00Z", "cl": "2026-10-28T09:00:00Z", "lb": ["kind/bug"]},
              {"n": 3, "cr": "2026-10-21T09:00:00Z", "cl": None, "lb": ["enhancement"]}]
    tracked = [{"src": "jira", "key": "WEB-9", "type": "BUG", "created": "2026-09-01T00:00:00Z", "cat": "TODO", "url": "u"},
               {"src": "jira", "key": "WEB-8", "type": "BUG", "created": "2026-10-01T00:00:00Z", "cat": "DONE", "canceled": True}]
    got = bugs.backlog(issues, tracked, NOW, weeks=2)
    assert got["weeks"] == [{"week": "2026-10-19", "opened": 1, "closed": 0, "open": 2},
                            {"week": "2026-10-26", "opened": 1, "closed": 1, "open": 2}]
    assert got["open"] == 2 and got["oldest"][0] == {"src": "jira", "id": "WEB-9", "days": 58, "url": "u"}
    assert got["sources"] == ["github", "jira"]


def test_no_bugs_means_no_section():
    assert bugs.backlog([{"n": 1, "cr": "2026-10-27T09:00:00Z", "lb": ["docs"]}], [], NOW) is None
