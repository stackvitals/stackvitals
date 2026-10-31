"""Rows for DORA over any date range (Middleware lets a team pick dates; the app computes from these)."""
from datetime import datetime, timezone

from stackvitals.core import delivery

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def test_rows_carry_failures_recovery_and_lead_times():
    deps = [{"id": "d1", "finished": "2026-10-01T00:00:00Z"}, {"id": "d2", "finished": "2026-10-10T00:00:00Z"},
            {"id": "old", "finished": "2025-01-01T00:00:00Z"}]
    deployed = [{"deployment": "d1", "cycle_min": 90}, {"deployment": "d2", "cycle_min": 30}, {"deployment": "old", "cycle_min": 5}]
    incidents = [{"deployment": "d2", "hours_to_restore": 3.0}, {"deployment": "d2", "hours_to_restore": 1.5}]
    got = delivery.dora_rows(deps, deployed, incidents, NOW)
    assert got["deployments"] == [["2026-10-01T00:00:00Z", False, None], ["2026-10-10T00:00:00Z", True, 1.5]]
    assert got["prs"] == [["2026-10-01T00:00:00Z", 1.5], ["2026-10-10T00:00:00Z", 0.5]]
