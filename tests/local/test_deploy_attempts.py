"""Failed and cancelled deploy attempts (Middleware's deployment success rate and duration): from the Deployments API's
states, or from every run of a deploy workflow."""
from datetime import datetime, timezone

from stackvitals.core import delivery
from stackvitals.core.config import parse

START, END = datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 29, tzinfo=timezone.utc)
CFG = parse("")[0]


def test_deployments_api_states_give_the_success_rate_and_time():
    repo = {"deployments": [
        {"env": "production", "at": "2026-10-02T10:00:00Z", "done": "2026-10-02T10:12:00Z", "state": "SUCCESS"},
        {"env": "production", "at": "2026-10-03T10:00:00Z", "done": None, "state": "FAILURE"},
        {"env": "Preview", "at": "2026-10-03T11:00:00Z", "state": "FAILURE"},
        {"env": "production", "at": "2026-10-04T10:00:00Z", "done": "2026-10-04T10:04:00Z", "state": "INACTIVE"}]}
    got = delivery.deploy_attempts(repo, {}, CFG, "deployments api", START, END)
    assert (got["attempts"], got["succeeded"], got["failed"], got["success_rate"], got["median_minutes"]) == (3, 2, 1, 0.6667, 12.0)


def run(i, c, st, up):
    return {"id": i, "att": 1, "wfn": "Deploy", "path": ".github/workflows/deploy.yml", "ev": "push", "br": "main", "c": c,
            "cr": st, "st": st, "up": up}


def test_deploy_workflow_runs_count_failed_and_cancelled_attempts():
    ci = {"runs": [run(1, "success", "2026-10-02T10:00:00Z", "2026-10-02T10:06:00Z"),
                   run(2, "failure", "2026-10-03T10:00:00Z", "2026-10-03T10:02:00Z"),
                   run(3, "cancelled", "2026-10-04T10:00:00Z", "2026-10-04T10:01:00Z")]}
    got = delivery.deploy_attempts({"default_branch": "main"}, ci, CFG, "deploy workflows", START, END)
    assert (got["attempts"], got["failed"], got["cancelled"], got["success_rate"], got["median_minutes"]) == (3, 1, 1, 0.5, 6.0)
    assert delivery.deploy_attempts({}, {}, CFG, "releases", START, END) is None
