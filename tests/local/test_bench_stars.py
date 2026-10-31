import gzip
import json
from datetime import datetime, timedelta, timezone

import httpx

from mergescout.bench.ci import TokenPool, fetch_all
from mergescout.bench.stars import aggregate_stars, read_stars, star_stats

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
WEEK = 7 * 86400


def weeks(totals, running=5):
    # Newest first, like the API: the running week, then complete weeks back in time.
    start = int((NOW - timedelta(days=3)).timestamp())
    rows = [{"week": start, "total": running, "days": []}]
    rows += [{"week": start - (i + 1) * WEEK, "total": t, "days": []} for i, t in enumerate(totals)]
    return rows


def test_growth_counts_the_last_12_complete_weeks_against_the_stars_before_them():
    s = star_stats(weeks([10] * 12 + [99]), stars=1125, now=NOW)
    # 120 gained in 12 complete weeks; the running week's 5 are left out; 1,000 stars before them.
    assert s == {"gained_12w": 120, "growth_12w": 0.12}


def test_a_repo_younger_than_12_weeks_has_no_growth_figure():
    assert star_stats(weeks([3] * 8), stars=40, now=NOW) is None


def pool_for(answers):
    def handler(request):
        repo = request.url.path.split("/repos/")[1].split("/stargazers")[0]
        status, body = answers.get(repo, (200, weeks([10] * 12)))
        return httpx.Response(status, json=body, headers={"x-ratelimit-remaining": "4000"})
    return TokenPool(["tok-a"], client=httpx.Client(transport=httpx.MockTransport(handler)), reserve=100)


def test_star_samples_skip_missing_repos_and_keep_the_rest():
    repos = [{"name": "o/a", "language": "Go", "stars": 1125}, {"name": "o/gone", "language": "Go", "stars": 500}]
    got = fetch_all(pool_for({"o/gone": (404, {"message": "Not Found"})}), repos, NOW, read=read_stars)
    assert [r["repo"] for r in got["records"]] == ["o/a"] and got["records"][0]["gained_12w"] == 120 and got["complete"]


def test_star_benchmarks_group_by_language_and_size(monkeypatch):
    import mergescout.bench.stars as st
    monkeypatch.setattr(st, "MIN_GROUP", 3)
    recs = [{"repo": f"o/r{i}", "language": "Go", "stars": 2000, "gained_12w": 10 * (i + 1), "growth_12w": 0.01 * (i + 1),
             "day": "2026-10-16"} for i in range(3)]
    g = aggregate_stars(recs, NOW)["groups"]["Go|1k-10k"]
    assert g["repos"] == 3 and g["gained_12w"]["p50"] == 20 and g["growth_12w"]["p50"] == 0.02


def test_star_samples_are_stored_and_published_beside_the_ci_ones(tmp_path):
    from mergescout.bench.__main__ import publish
    from test_bench import FakeReleases
    rel = FakeReleases()
    recs = [{"repo": "o/a", "language": "Go", "stars": 2000, "gained_12w": 10, "growth_12w": 0.005, "day": "2026-10-16"}]
    publish(tmp_path, rel, recs, NOW, log=lambda m: None, kind="stars", build=aggregate_stars)
    stored = gzip.decompress(rel.files[("bench-2026-W42", "stars-2026-10-16.ndjson.gz")]).decode()
    assert json.loads(stored)["repo"] == "o/a" and ("bench-latest", "stars-benchmarks.json") in rel.files
    assert ("bench-latest", "ci-benchmarks.json") not in rel.files
