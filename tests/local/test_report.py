from datetime import datetime, timezone

import pytest

from mergescout.github.graphql import GraphQLError
from mergescout.measure.__main__ import run_api_cost
from mergescout.measure.jsonl import append_jsonl, read_jsonl
from mergescout.measure.report import render_markdown, summarize

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


def rec(repo, full, incr, issues, bucket="50-199", capped=False):
    def part(cost):
        return {"pages": 1, "cost": cost, "items": 10, "capped": capped}
    return {"repo": repo, "bucket": bucket, "status": "ok",
            "full": part(full), "incremental": part(incr), "issues": part(issues)}


def test_summarize_means_and_tiers():
    results = [rec("a/b", 2, 1, 1), rec("c/d", 4, 1, 3, capped=True), {"repo": "x/y", "status": "not_found"}]
    s = summarize(results, daily_points=120_000, tier_sizes=(10_000,))
    assert (s["repos_measured"], s["not_found"], s["capped"]) == (2, 1, 1)
    assert (s["mean_full"], s["mean_incremental"], s["mean_issues"]) == (3.0, 1.0, 2.0)
    tier = s["tiers"][0]
    assert tier["tier"] == 10_000
    assert tier["first_fill_days"] == pytest.approx(10_000 * 5 / 120_000)
    assert tier["refresh_cycle_days"] == pytest.approx(10_000 * 3 / 120_000)
    assert "| 10000 |" in render_markdown(s)


def test_jsonl_round_trip(tmp_path):
    path = tmp_path / "r.jsonl"
    append_jsonl(path, {"a": 1})
    append_jsonl(path, {"a": 2})
    assert read_jsonl(path) == [{"a": 1}, {"a": 2}]
    assert read_jsonl(tmp_path / "missing.jsonl") == []


def test_run_api_cost_skips_done_and_does_not_record_failures(tmp_path, fake_gql):
    results = tmp_path / "api_cost.jsonl"
    append_jsonl(results, rec("done/repo", 1, 1, 1))

    def responder(query, variables):
        if variables["owner"] == "broken":
            raise GraphQLError("boom")
        conn = "issues" if "issues(" in query else "pullRequests"
        return {"repository": {conn: {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}}}, 1

    sample = [{"repo": "done/repo", "bucket": "50-199"}, {"repo": "broken/repo", "bucket": "50-199"},
              {"repo": "new/repo", "bucket": "10k+"}]
    measured = run_api_cost(fake_gql(responder), sample, results, NOW)
    rows = read_jsonl(results)
    assert measured == 1
    assert [r["repo"] for r in rows] == ["done/repo", "new/repo"]
    assert rows[1]["bucket"] == "10k+"
