"""The deployment sampler: two REST requests per repo (deployments, releases), production deployments first, else stable
releases; deployment days per week and month over 90 days with DevLake's lower median and 2023 tiers; groups of 20+ repos
with ranges, the share of repos each source covers, and the requests counted."""
from datetime import datetime, timedelta, timezone

import httpx

from mergescout.bench.ci import TokenPool
from mergescout.bench.deploys import aggregate_deploys, repo_deploys

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def iso(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pool_for(answers):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        body = answers.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, json=body, headers={"x-ratelimit-remaining": "4000", "x-ratelimit-reset": "0"})
    return TokenPool(["t"], client=httpx.Client(transport=httpx.MockTransport(handler))), calls


def test_production_deployments_count_first_then_stable_releases():
    deployments = [{"environment": "Production – web", "created_at": iso(d)} for d in range(0, 90, 2)]  # every other day
    deployments += [{"environment": "Preview", "created_at": iso(1)}]
    pool, calls = pool_for({"/repos/o/app/deployments": deployments, "/repos/o/app/releases": []})
    rec = repo_deploys(pool, {"name": "o/app", "language": "TypeScript", "stars": 900}, NOW)
    assert rec["source"] == "deployments api" and rec["deploy_days"] == 45 and rec["requests"] == 2
    assert rec["days_per_week"] == 3 and rec["tier"] == "high"
    releases = [{"tag_name": f"v1.{k}.0", "published_at": iso(k * 14), "prerelease": False, "draft": False} for k in range(6)]
    releases += [{"tag_name": "v2.0.0-rc.1", "published_at": iso(3), "prerelease": False, "draft": False}]
    pool, _ = pool_for({"/repos/o/lib/deployments": [], "/repos/o/lib/releases": releases})
    lib = repo_deploys(pool, {"name": "o/lib", "language": "Python", "stars": 5000}, NOW)
    assert lib["source"] == "releases" and lib["deploy_days"] == 6 and lib["days_per_week"] == 0
    assert lib["tier"] == "medium"  # 2 release days a month at the median
    pool, _ = pool_for({"/repos/o/none/deployments": [], "/repos/o/none/releases": []})
    assert repo_deploys(pool, {"name": "o/none", "language": "Go", "stars": 200}, NOW)["source"] is None


def test_groups_report_source_shares_and_frequency_with_ranges():
    recs = [{"repo": f"o/r{k}", "language": "Python", "stars": 500, "source": "releases" if k % 2 else "deployments api",
             "deploy_days": k, "days_per_week": k % 6, "days_per_month": k % 20, "tier": "high" if k % 6 else "medium",
             "requests": 2} for k in range(1, 41)]
    recs += [{"repo": f"o/n{k}", "language": "Python", "stars": 500, "source": None, "deploy_days": 0, "days_per_week": 0,
              "days_per_month": 0, "tier": None, "requests": 2} for k in range(10)]
    out = aggregate_deploys(recs, NOW)
    g = out["groups"]["Python|100-1k"]
    assert g["repos"] == 50 and g["sources"] == {"deployments api": 0.4, "releases": 0.4, "none": 0.2}
    assert g["days_per_week"]["repos"] == 40 and "p50_low" in g["days_per_week"]
    assert out["requests"] == 100 and out["population"] and out["gaps"]
