"""All four DORA metrics per team, from the deployments that shipped each team's pull requests (DevLake's DORA by team)."""
from datetime import datetime, timezone

from stackvitals.core import delivery

START, END = datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 29, tzinfo=timezone.utc)


def row(n, author, dep_id, day):
    p = {"n": n, "au": author}
    ph = {"devlake_cycle_min": 60.0 * n, "cycle_to_merge": 1.0, "pickup": 0.5, "review": 0.5}
    dep = {"id": dep_id, "finished": f"2026-10-{day:02d}T12:00:00Z", "sha": dep_id} if dep_id else None
    return (p, ph, dep)


def test_each_team_gets_dora_from_the_deployments_that_shipped_its_prs():
    rows = [row(1, "ana", "d1", 5), row(2, "ana", "d2", 12), row(3, "bo", "d2", 12), row(4, "bo", None, 0)]
    incidents = [{"deployment": "d1", "created": "2026-10-06T00:00:00Z", "resolved": "2026-10-06T02:00:00Z",
                  "hours_to_restore": 2.0}]
    ident = {"teams": {"web": ["ana"], "api": ["bo"]}}
    got = delivery.by_team(rows, ident, rows, incidents, START, END)
    assert got["web"]["dora"]["deployments"] == 2 and got["api"]["dora"]["deployments"] == 1
    assert got["web"]["dora"]["change_failure_rate"] == 0.5 and got["api"]["dora"]["change_failure_rate"] is None  # N/A without incidents, as DevLake
    assert got["web"]["n"] == 2 and "dora" not in delivery.by_team(rows, ident)["web"]
