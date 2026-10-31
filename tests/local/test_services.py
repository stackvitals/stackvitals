"""Services inside a repo: [services.<name>] paths (CODEOWNERS-style) and an optional deploy pattern, so a monorepo gets
review phases and DORA per service; a PR touching two services counts in both, and the repo's own numbers are unchanged."""
from datetime import datetime, timedelta, timezone

from stackvitals.core import delivery
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
TOML = """[services.api]
paths = ["services/api/", "libs/shared/**"]
deploy = "api-prod"
[services.web]
paths = ["apps/web/"]
"""


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def row(n, paths, merged_days_ago, dep=None, cycle_h=10.0):
    p = {"n": n, "paths": paths, "mg": iso(NOW - timedelta(days=merged_days_ago)), "au": "amy"}
    ph = {"cycle_to_merge": cycle_h, "pickup": 1.0, "review": 2.0, "devlake_cycle_min": int(cycle_h * 60)}
    return (p, ph, dep)


def test_settings_name_each_service_paths_and_deploy_pattern():
    cfg, notes = parse(TOML)
    assert notes == []
    assert cfg["services"] == {"api": {"paths": ["services/api/", "libs/shared/**"], "deploy": "api-prod"},
                               "web": {"paths": ["apps/web/"], "deploy": ""}}
    cfg, notes = parse('[services.api]\npaths = "services/api/"\n[services.web]\npaths = ["apps/"]\ndeploy = "("\n')
    assert "api" not in cfg["services"] and cfg["services"]["web"]["deploy"] == ""
    assert len(notes) == 2 and all("services." in n for n in notes)


def test_review_phases_per_service_count_a_shared_pr_in_both():
    cfg = parse(TOML)[0]
    rows = [row(1, ["services/api/main.go"], 3), row(2, ["apps/web/index.ts", "libs/shared/x.ts"], 4),
            row(3, ["docs/readme.md"], 5)]
    got = delivery.by_service(rows, [], [], cfg, NOW - timedelta(days=30), NOW)
    assert got["api"]["prs"] == 2 and got["web"]["prs"] == 1
    # Two pull requests are too few for a P50: it says so instead of guessing.
    assert got["api"]["n"] == 2 and got["api"]["cycle_to_merge"]["enough"] is False
    assert "dora" not in got["web"]  # no deploy pattern: deployments can't be told apart


def test_dora_per_service_uses_only_its_deployments_and_their_incidents():
    cfg = parse(TOML)[0]
    deps = [{"id": "d1", "name": "api-prod", "sha": "a", "finished": iso(NOW - timedelta(days=2))},
            {"id": "d2", "name": "web-prod", "sha": "b", "finished": iso(NOW - timedelta(days=2))},
            {"id": "d3", "name": "api-prod", "sha": "c", "finished": iso(NOW - timedelta(days=9))}]
    rows = [row(1, ["services/api/a.go"], 3, deps[0]), row(2, ["apps/web/a.ts"], 3, deps[1])]
    incidents = [{"deployment": "d1", "created": iso(NOW - timedelta(days=1)), "resolved": iso(NOW - timedelta(hours=20))},
                 {"deployment": "d2", "created": iso(NOW - timedelta(days=1)), "resolved": iso(NOW - timedelta(hours=20))}]
    got = delivery.by_service(rows, deps, incidents, cfg, NOW - timedelta(days=30), NOW)
    dora = got["api"]["dora"]
    assert got["api"]["deployments"] == 2 and dora["change_failure_rate"] == 0.5
    assert dora["lead_time_hours"] is not None
