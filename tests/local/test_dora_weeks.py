"""All four DORA numbers week by week (Middleware's trends), each week counted as the whole window is."""
from datetime import datetime, timezone

from stackvitals.core import delivery

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)  # Thursday


def test_weeks_run_monday_to_monday_with_each_weeks_deployments_and_incidents():
    deps = [{"id": "d1", "finished": "2026-10-20T10:00:00Z"}, {"id": "d2", "finished": "2026-10-27T10:00:00Z"},
            {"id": "d3", "finished": "2026-10-28T10:00:00Z"}]
    deployed = [{"deployment": "d1", "cycle_min": 120, "pr": 1}, {"deployment": "d2", "cycle_min": 60, "pr": 2}]
    incidents = [{"deployment": "d2", "deployment_finished": "2026-10-27T10:00:00Z", "created": "2026-10-27T11:00:00Z",
                  "resolved": "2026-10-27T13:00:00Z", "hours_to_restore": 3.0}]
    got = delivery.dora_weeks(deps, deployed, incidents, NOW, weeks=2)
    assert [(w["week"], w["deployments"], w["lead_time_hours"]) for w in got] == [("2026-10-19", 1, 2.0), ("2026-10-26", 2, 1.0)]
    assert got[1]["change_failure_rate"] == 0.5
