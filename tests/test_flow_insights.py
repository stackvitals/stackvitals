"""Insights as a whole: findings ranked by the hours at stake that never name a person, alerts sent once per change of
state with the replay a new threshold gets, and the instant-alerts Worker's own tests (signatures, payloads)."""
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stackvitals.core import alerts, findings

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def test_findings_rank_by_hours_split_stale_review_requests_and_name_nobody():
    red = {"prs": 40, "red_prs": 6, "red_hours_total": 50.0, "rerun_hours_total": 30.0, "measures": {},
           "rerun_jobs": [{"workflow": "CI", "job": "tests", "hours": 21.5, "prs": 4, "runs": [[101, 1]]}],
           "rerun_tests": [], "top": [{"pr": 7, "hours": 20.0}]}
    delivery = {"window_days": 90, "incidents": [], "stuck": {"hanging_review": [
        {"pr": 1, "since": "2026-10-15T12:00:00Z", "hours": 120.0},
        {"pr": 2, "since": "2025-01-01T00:00:00Z", "hours": 15000.0}]}}
    flow = {"load": [{"reviewer": "bob", "open_requests": 9}],
            "groups": {"insider": {"pickup": {"median_s": 7200, "n": 30}}, "outsider": {"pickup": {"median_s": 108000, "n": 12}}}}
    out = findings.build("o/r", red, delivery, flow, [], NOW)
    kinds = [f["kind"] for f in out]
    # A request older than the 90-day window counts 90 days, not the 625 it has been waiting.
    assert kinds[0] == "stale_review" and out[0]["hours"] == 90 * 24
    assert {"review_wait", "red_ci", "fix_job", "outsider_wait"} <= set(kinds)
    assert all(f["evidence"] and f["n"] for f in out)
    assert "bob" not in " ".join(f["title"] + f["action"] for f in out)


def test_alerts_fire_once_per_change_and_a_new_threshold_gets_its_replay():
    limits = {"pickup_p75_hours": 10}
    state, sent = {}, []
    for value in (5.0, 8.5, 9.0, 12.0, 12.5, None, 12.0, 4.0):
        state, events = alerts.evaluate({"pickup_p75_hours": (value, 30 if value is not None else 0)}, limits, state)
        sent += [e["level"] for e in events]
    # A day without enough data changes nothing: the miss is not sent twice.
    assert sent == ["heads_up", "miss", "recovered"]
    history = {"pickup_p75_hours": [(f"d{k}", v, 30) for k, v in enumerate([2, 11, 3, 12, 12, 9, 5])]}
    assert alerts.replay(history, limits) == {"pickup_p75_hours": 4}


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is needed for the Worker's tests")
def test_the_instant_alerts_worker_passes_its_own_tests():
    worker = Path(__file__).resolve().parents[1] / "worker"
    done = subprocess.run(["node", "--test", "test/index.test.mjs"], cwd=worker, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
