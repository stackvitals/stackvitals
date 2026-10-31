"""AI-era outcomes: AI-assisted and other merged PRs compared month by month on review wait, size, CI failures, reverts
and failed deployments; and DORA's fifth key, the share of deployments that were unplanned fixes."""
from datetime import datetime, timezone

from stackvitals.core.ai_outcomes import assisted_by, outcomes, rework_rate

NOW = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)


def pr(n, merged, ai=(), labels=(), title=None, author="dev"):
    return {"n": n, "mg": merged, "cr": merged, "ai": list(ai), "lb": list(labels), "ti": title or f"Change {n}", "au": author,
            "add": 10 * n, "del": 0}


def phases(pickup, review):
    return {"pickup": pickup, "review": review}


P1 = pr(1, "2026-10-01T10:00:00Z", ai=["claude"], title="Add cache")
P2 = pr(2, "2026-10-02T10:00:00Z")
P3 = pr(3, "2026-09-15T10:00:00Z", labels=["claude-code-assisted"])
REVERT = pr(4, "2026-10-03T10:00:00Z", title='Revert "Add cache"')
D1 = {"id": "d1", "finished": "2026-10-01T12:00:00Z"}
D2 = {"id": "d2", "finished": "2026-10-03T12:00:00Z"}
ROWS = [(P1, phases(2, 4), D1), (P2, phases(6, 1), D1), (P3, phases(1, 1), None), (REVERT, phases(0.5, 0.5), D2)]
CI = {"runs": [{"id": 9, "pr": [1], "c": "failure", "att": 1, "ev": "pull_request", "cr": "2026-09-01T00:00:00Z"},
               {"id": 9, "pr": [1], "c": "success", "att": 2, "ev": "pull_request", "cr": "2026-09-01T00:00:00Z"},
               {"id": 8, "pr": [2], "c": "success", "att": 1, "ev": "pull_request", "cr": "2026-09-01T00:00:00Z"}]}
INCIDENTS = [{"source": "revert", "number": 4, "created": "2026-10-03T10:00:00Z", "deployment": "d1"}]


def test_assistance_is_read_from_trailers_labels_and_agent_authors():
    assert assisted_by(P1) == ["claude"] and assisted_by(P3) == ["claude"] and assisted_by(P2) == []
    assert assisted_by(pr(5, "2026-10-01T00:00:00Z", author="copilot-swe-agent[bot]")) == ["copilot agent"]


def test_assisted_and_other_prs_are_compared_on_what_happened_after():
    out = outcomes(ROWS, CI, INCIDENTS, NOW, min_n=1)
    a, o = out["window"]["assisted"], out["window"]["others"]
    assert a["n"] == 2 and o["n"] == 2
    assert a["ci_failed_share"] == 0.5 and o["ci_failed_share"] == 0.0
    assert a["reverted_share"] == 0.5 and o["reverted_share"] == 0.0
    # Over deployed PRs only: P1 shipped in the deployment the revert fixed (P3 never shipped); P2 too, the revert didn't.
    assert a["failed_deploy_share"] == 1.0 and o["failed_deploy_share"] == 0.5
    months = {m["month"]: m for m in out["monthly"]}
    assert months["2026-10"]["assisted"]["n"] == 1 and months["2026-09"]["assisted"]["n"] == 1


def test_rework_rate_is_the_share_of_deployments_that_shipped_a_fix():
    out = rework_rate([D1, D2], ROWS, INCIDENTS, datetime(2026, 9, 1, tzinfo=timezone.utc), NOW)
    assert out == {"rework_rate": 0.5, "rework_deployments": 1, "deployments_n": 2, "rework_range": [0.0945, 0.9055]}
    assert rework_rate([], [], [], datetime(2026, 9, 1, tzinfo=timezone.utc), NOW)["rework_rate"] is None


def test_agent_baseline_is_the_closest_group_of_similar_repos_from_the_crawl():
    from stackvitals.core.ai_outcomes import baseline
    group = {"repos_with_agent_prs": 40, "agent": {"decided": 900, "merged": 0.62}, "outsider": {"decided": 3000, "merged": 0.55}}
    bench = {"agent_prs": {"Python|all": group, "all|all": {**group, "repos_with_agent_prs": 300}}}
    assert baseline(bench, "Python", 50) == {"group": "Python repos", "repos": 40, "agent_merged": 0.62, "outsider_merged": 0.55}
    assert baseline(bench, "Rust", 50)["repos"] == 300
    # A bad or missing file gives no baseline rather than a broken page.
    assert baseline({"agent_prs": {"all|all": {"agent": {"merged": "x"}}}}, "Go", 1) is None and baseline(None, "Go", 1) is None


def test_the_delivery_page_shows_rework_and_what_happened_after_ai_assisted_prs():
    from stackvitals.core import delivery_report
    from stackvitals.core.config import parse
    from stackvitals.core.delivery import build
    from test_core_delivery_surfaces import sample
    from test_core_delivery import NOW as DNOW
    flow, repo = sample()
    flow["closed"][0]["lb"] = ["claude-code-assisted"]
    out = build(flow, repo, {"runs": [], "jobs": []}, [], DNOW, 90, parse("")[0])
    out["ai"]["baseline"] = {"group": "Python repos", "repos": 40, "agent_merged": 0.62, "outsider_merged": 0.55}
    page = delivery_report.render_html(out, "o/r")
    assert "Deployment rework rate" in page and "After merge" in page and "Python repos" in page and "62%" in page
    md = delivery_report.render_markdown(out, "o/r")
    assert "rework rate" in md


def test_coding_agents_prs_are_their_own_kind_while_cycle_time_stays_about_people():
    from stackvitals.core.config import parse
    from stackvitals.core.delivery import build
    from test_core_delivery import NOW as DNOW, pr, review
    people = [pr(10 + k, cr=100 + k, mg=50 + k, fa=60 + k, ev=[review(70 + k)]) for k in range(3)]
    agent = pr(9, cr=90, mg=40, fa=45, ev=[review(44)], au="Copilot", kind="Bot")
    out = build({"closed": people + [agent], "open": []}, {"default_branch": "main"}, {"runs": [], "jobs": []}, [], DNOW, 90,
                parse("")[0])
    assert out["prs"] == 3
    w = out["ai"]["outcomes"]["window"]
    # Phase 13: agents' PRs are no longer pooled with people's AI-marked PRs.
    assert w["agent"]["n"] == 1 and w["assisted"]["n"] == 0 and w["others"]["n"] == 3
    assert out["ai"]["outcomes"]["tools"] == {"copilot agent": 1}


def test_the_digest_says_what_happened_after_ai_assisted_prs_and_the_rework_rate():
    # Phase 13: only like-with-like comparisons reach the digest, each with its verdict.
    from stackvitals.core.digest import compose
    est = lambda gap, low, high, verdict, det=0.09: {"gap": gap, "low": low, "high": high, "verdict": verdict,  # noqa: E731
                                                     "detectable": det, "matched": 40, "of": 50, "matched_share": 0.8}
    delivery = {"phases": {}, "deploy_source": "releases", "window_days": 90,
                "dora": {"deployments": 10, "rework_rate": 0.2, "rework_deployments": 2, "deployments_n": 10},
                "ai": {"outcomes": {"coverage": {"people_prs": 100, "marked": 30, "marked_share": 0.3, "authors": 12,
                                                 "authors_marking": 5},
                                    "matched": {"assisted": {"reverted": est(0.08, 0.02, 0.14, "higher"),
                                                             "ci_failed": est(0.01, -0.05, 0.07, "no measurable difference")},
                                                "agent": {"merged_by_others": est(-0.2, -0.3, -0.1, "lower")}}}}}
    text, _ = compose("o/r", NOW, {"delivery": delivery}, None, [], None)
    assert "rework 20%" in text
    assert ("**AI-assisted work:** 30% of people's merged PRs carry an AI marker (5 of 12 authors). Against the same authors' "
            "other PRs: reverted more often (+8 points, likely +2 to +14); CI failures: no measurable difference (it could "
            "detect 9 points or more)." in text)
    assert ("Coding agents' PRs: merged by someone else less often (-20 points, likely -30 to -10) than people's PRs of the "
            "same month and size." in text)
    # Nothing comparable: no line.
    delivery["ai"]["outcomes"]["matched"] = {"assisted": {"reverted": {"verdict": "too few", "gap": None}}, "agent": {}}
    assert "AI-assisted work" not in compose("o/r", NOW, {"delivery": delivery}, None, [], None)[0]


def test_merge_rate_counts_closed_unmerged_prs_and_a_rerun_that_passed_is_a_flake():
    closed = {**pr(6, None, ai=["claude"]), "st": "CLOSED", "cl": "2026-10-05T10:00:00Z"}
    out = outcomes(ROWS, CI, INCIDENTS, NOW, decided=[r[0] for r in ROWS] + [closed], min_n=1)
    a, o = out["window"]["assisted"], out["window"]["others"]
    assert a["merge_rate"] == round(2 / 3, 4) and o["merge_rate"] == 1.0
    # PR 1's run failed, then passed on a re-run of the same commit.
    assert a["flaky_share"] == 0.5 and o["flaky_share"] == 0.0


def test_fork_runs_are_matched_by_head_branch_and_prs_older_than_the_ci_history_are_left_out():
    fork = {**pr(7, "2026-10-04T10:00:00Z", ai=["claude"]), "cr": "2026-10-02T10:00:00Z", "ho": "someone", "head": "fix-x"}
    old = {**pr(8, "2026-08-01T10:00:00Z", ai=["claude"]), "cr": "2026-07-30T10:00:00Z"}
    ci = {"runs": [{"id": 5, "pr": [], "c": "failure", "att": 1, "ev": "pull_request", "cr": "2026-10-03T10:00:00Z",
                    "ho": "Someone", "br": "fix-x"}]}
    out = outcomes([(fork, phases(1, 1), None), (old, phases(1, 1), None)], ci, [], NOW, min_n=1)
    # The old PR merged before the first stored run: CI can say nothing about it.
    assert out["window"]["assisted"]["ci_failed_share"] == 1.0


def test_failed_deploys_count_only_small_deployments_where_an_incident_can_be_pinned_near_a_pr():
    big = {"id": "big", "finished": "2026-10-01T12:00:00Z"}
    rows = [(pr(20 + k, "2026-10-01T10:00:00Z"), phases(1, 1), big) for k in range(6)]
    out = outcomes(rows, {"runs": []}, [{"source": "issue", "number": 1, "created": "2026-10-02T00:00:00Z", "deployment": "big"}], NOW, min_n=1)
    assert out["window"]["others"]["failed_deploy_share"] is None


def test_a_deployment_that_ships_a_fix_naming_an_incident_issue_is_rework_too():
    fix = pr(30, "2026-10-05T10:00:00Z", title="Handle empty cache (fixes #77)")
    d3 = {"id": "d3", "finished": "2026-10-05T12:00:00Z"}
    incidents = [{"source": "issue", "number": 77, "created": "2026-10-04T00:00:00Z", "deployment": "d2"}]
    out = rework_rate([d3], [(fix, phases(1, 1), d3)], incidents, datetime(2026, 9, 1, tzinfo=timezone.utc), NOW)
    assert out["rework_deployments"] == 1


def test_the_digest_leaves_out_the_ci_comparison_when_ci_history_covers_too_few_prs():
    from stackvitals.core.digest import compose
    delivery = {"phases": {}, "deploy_source": "releases", "window_days": 90, "dora": {"deployments": 3},
                "ai": {"outcomes": {"coverage": {"marked_share": 0.1, "authors": 9, "authors_marking": 2},
                                    "matched": {"assisted": {"ci_failed": {"verdict": "too few", "gap": None},
                                                             "reverted": {"verdict": "no measurable difference", "gap": 0.0,
                                                                          "low": -0.1, "high": 0.1, "detectable": 0.12}}}}}}
    text, _ = compose("o/r", NOW, {"delivery": delivery}, None, [], None)
    assert "AI-assisted work" in text and "CI failures" not in text and "it could detect 12 points or more" in text
