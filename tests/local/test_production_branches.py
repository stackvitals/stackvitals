"""Production branches (Middleware's prod_branches): deploys from release/* and PRs merged into them count; and a PR
merged into develop counts once a deployment's commits hold its merge commit, with no setting at all."""
from stackvitals.core import delivery
from stackvitals.core.config import parse


def pr(n, base, mc, mg):
    return {"n": n, "base": base, "mc": mc, "mg": mg, "cr": mg, "au": "ana", "at": "User", "ev": []}


def test_prs_on_a_production_branch_or_shipped_by_a_deployment_count():
    flow = {"closed": [pr(1, "main", "m1", "2026-10-01T00:00:00Z"), pr(2, "release/2.0", "r2", "2026-10-02T00:00:00Z"),
                       pr(3, "develop", "d3", "2026-10-03T00:00:00Z"), pr(4, "develop", "d4", "2026-10-03T00:00:00Z")]}
    repo = {"default_branch": "main",
            "deployments": [{"env": "production", "sha": "m0", "at": "2026-09-30T00:00:00Z", "done": "2026-09-30T00:00:00Z", "state": "SUCCESS"},
                            {"env": "production", "sha": "m5", "at": "2026-10-05T00:00:00Z", "done": "2026-10-05T00:00:00Z", "state": "SUCCESS"}],
            "ranges": {"m0..m5": {"shas": ["m5", "d3", "m1"], "complete": True}}}
    plain = delivery.shipped(flow, repo, {}, parse("")[0])[2]
    assert sorted(r[0]["n"] for r in plain) == [1, 3]
    cfg = parse('[delivery]\nproduction_branches = ["release/*"]\n')[0]
    assert sorted(r[0]["n"] for r in delivery.shipped(flow, repo, {}, cfg)[2]) == [1, 2, 3]


def test_a_deploy_run_on_a_production_branch_ships():
    run = {"id": 1, "att": 1, "wfn": "Deploy", "path": ".github/workflows/deploy.yml", "ev": "push", "br": "production", "c": "success"}
    assert delivery._ships(run, r"(?i)deploy", "main") is None
    assert delivery._ships(run, r"(?i)deploy", "main", False, ["production"]) == "deploy"
