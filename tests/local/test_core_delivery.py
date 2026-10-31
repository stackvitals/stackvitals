"""Delivery intelligence with LinearB's six phases and DevLake's DORA counting and tiers, from Team Flow's PRs, CI Health's
runs, the repo's deployments and releases, and Community's issues."""
from datetime import datetime, timedelta, timezone

from stackvitals.core import delivery
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
CFG = parse("")[0]


def at(h):
    return (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, cr, mg=None, fa=None, ev=(), cm=(), au="amy", kind="User", base="main", mc=None, ti="Fix", lb=(), add=40, dele=10,
       draft=False, rq=(), ai=(), cmn=None, paths=()):
    return {"t": "pr", "n": n, "ti": ti, "draft": draft, "st": "MERGED" if mg is not None else "OPEN", "cr": at(cr),
            "up": at(1), "mg": at(mg) if mg is not None else None, "cl": at(mg) if mg is not None else None, "au": au, "at": kind,
            "as": "NONE", "base": base, "head": f"b{n}", "ho": au, "add": add, "del": dele, "ev": list(ev), "cm": list(cm),
            "rq": list(rq), "fa": at(fa) if fa is not None else None, "mc": mc, "lb": list(lb), "ai": list(ai),
            "cmn": cmn if cmn is not None else len(cm), "paths": list(paths)}


def review(h, who="bob", state="APPROVED", kind="User"):
    return ["review", at(h), who, state, "MEMBER", kind, False]


def comment(h, who="bob", kind="User"):
    return [at(h), who, "MEMBER", kind, False]


def test_six_phases_follow_linearb_and_the_devlake_cycle_is_kept_too():
    p = pr(1, cr=100, mg=60, fa=130, ev=[review(95, "amy", "COMMENTED"), review(90, "renovate[bot]", "COMMENTED", kind="Bot"),
                                       review(80, "bob", "COMMENTED"), review(70, "carol", "APPROVED")],
           cm=[comment(85, "dependabot[bot]", "Bot"), comment(88, "bob")])
    ph = delivery.phases(p, deployed_at=at(50))
    # coding: first commit to opened; pickup: opened to the first other person's comment or review (bob's comment, 12 h);
    # review: that to merge; approve: first activity to first approval; merge: approval to merge; deploy: merge to deployed.
    assert ph["coding"] == 30 and ph["pickup"] == 12 and ph["review"] == 28 and ph["approve"] == 18 and ph["merge"] == 10
    assert ph["deploy"] == 10 and ph["cycle"] == 30 + 12 + 28 + 10
    assert ph["devlake_cycle"] == 30 + 40 + 10  # coding + opened-to-merged + deploy, DevLake's pr_cycle_time


def test_drafts_count_from_ready_and_a_pr_merged_without_any_review_waits_until_its_merge():
    d = pr(2, cr=100, mg=50, fa=100, ev=[["ready", at(80)], review(70)])
    ph = delivery.phases(d)
    assert ph["pickup"] == 10 and ph["deploy"] is None and ph["cycle"] is None and ph["cycle_to_merge"] == 0 + 10 + 20
    solo = delivery.phases(pr(3, cr=30, mg=20, fa=31))
    assert solo["pickup"] == 10 and solo["review"] == 0 and solo["approve"] is None and solo["reviewed"] is False


def test_deployments_come_from_the_deployments_api_then_deploy_workflows_then_releases():
    repo = {"default_branch": "main",
            "deployments": [{"env": "Production", "at": at(10), "state": "SUCCESS", "sha": "d1", "done": at(9)},
                            {"env": "staging", "at": at(8), "state": "SUCCESS", "sha": "d2", "done": at(7)},
                            {"env": "production", "at": at(6), "state": "FAILURE", "sha": "d3", "done": at(5)},
                            {"env": "production", "at": at(4), "state": "INACTIVE", "sha": "d4", "done": at(1)}],
            "releases": [{"tag": "v1", "at": at(20), "pre": False, "sha": "r1"}]}
    deps, source = delivery.find_deployments(repo, {"runs": []}, CFG)
    assert source == "deployments api" and [d["sha"] for d in deps] == ["d1", "d4"] and deps[1]["finished"] == at(4)
    runs = [{"id": 5, "att": 1, "wfn": "Deploy to prod", "path": ".github/workflows/deploy.yml", "ev": "push", "br": "main",
             "sha": "w1", "c": "success", "cr": at(12), "up": at(11)},
            {"id": 6, "att": 1, "wfn": "Deploy to prod", "path": ".github/workflows/deploy.yml", "ev": "push", "br": "main",
             "sha": "w2", "c": "failure", "cr": at(8), "up": at(7)},
            {"id": 7, "att": 1, "wfn": "CI", "path": ".github/workflows/ci.yml", "ev": "push", "br": "main",
             "sha": "w3", "c": "success", "cr": at(8), "up": at(7)}]
    deps, source = delivery.find_deployments({**repo, "deployments": []}, {"runs": runs}, CFG)
    assert source == "deploy workflows" and [d["sha"] for d in deps] == ["w1"]
    deps, source = delivery.find_deployments({**repo, "deployments": []}, {"runs": []}, CFG)
    assert source == "releases" and deps[0]["sha"] == "r1"


def test_workflow_names_that_prepare_check_or_preview_never_count_as_shipping():
    base = CFG["delivery"]["deploy_workflow"]
    for name, path in [("Preview release", "preview-release.yml"), ("Release Docs Check", "release-docs-check.yml"),
                       ("Create Release PR", "create-release-pr.yml"), ("Sign release binaries", "sign-release-binaries.yml"),
                       ("Verify release packages", "release-verify-packages.yml"), ("post_publish", "post_publish.yml"),
                       ("start_release", "start_release.yml"), ("Release review gate", "release-review-gate.yml"),
                       ("Temporary smoke3 release smoke", "smoke3-scratch.yml"), ("Deploy Storybook", "deploy-storybook.yml"),
                       ("npm - release to dev/integration", "release-ci.yml"), ("publish-mirror", "publish-mirror.yml"),
                       ("Update examples to latest", "update-examples-on-release.yml"), ("Publish Prerelease", "publish-prerelease.yml"),
                       ("release-bump", "release-bump.yml"), ("Deploy contributor doc", "contributor-doc.yml")]:
        assert delivery.deploy_kind(name, f".github/workflows/{path}", base) is None, name
    assert delivery.deploy_kind("Release: Set stable npm packages to latest", "x.yml", base) == "release"
    assert delivery.deploy_kind("Deploy bun.com", "deploy-site.yml", base) == "deploy"
    assert delivery.deploy_kind("Publish to crates.io", "publish-crates.yml", base) == "release"


def test_release_workflows_count_only_for_repos_without_releases_and_only_on_a_version():
    runs = [{"id": 1, "att": 1, "wfn": "Release", "path": ".github/workflows/release.yml", "ev": "push", "br": "v2.1.0",
             "sha": "t1", "c": "success", "cr": at(12), "up": at(11)},
            {"id": 2, "att": 1, "wfn": "Release", "path": ".github/workflows/release.yml", "ev": "push", "br": "main",
             "sha": "t2", "c": "success", "cr": at(8), "up": at(7)}]
    with_releases = {"default_branch": "main", "deployments": [], "releases": [{"tag": "v2.1.0", "at": at(10), "pre": False, "sha": "t1"}]}
    deps, source = delivery.find_deployments(with_releases, {"runs": runs}, CFG)
    assert source == "releases" and [d["sha"] for d in deps] == ["t1"]
    deps, source = delivery.find_deployments({**with_releases, "releases": []}, {"runs": runs}, CFG)
    assert source == "release workflows" and [d["sha"] for d in deps] == ["t1"]


def test_a_pr_ships_with_the_deployment_of_its_merge_commit_or_the_first_one_after_its_merge():
    deps = [{"id": "a", "sha": "x", "finished": at(30)}, {"id": "b", "sha": "m1", "finished": at(5)},
            {"id": "c", "sha": "y", "finished": at(8)}]
    assert delivery.deployment_of(pr(1, 50, mg=40, mc="m1"), deps)["id"] == "b"  # direct: its merge commit
    assert delivery.deployment_of(pr(2, 50, mg=20, mc="zz"), deps)["id"] == "c"  # by time: the first one after the merge
    assert delivery.deployment_of(pr(3, 10, mg=2, mc="zz"), deps) is None


def test_incidents_link_to_the_last_deployment_before_them_and_feed_dora():
    deps = [{"id": "d1", "sha": "a", "finished": at(100)}, {"id": "d2", "sha": "b", "finished": at(50)}]
    issues = [{"t": "issue", "n": 9, "cr": at(40), "cl": at(30), "lb": ["incident"], "st": "CLOSED"},
              {"t": "issue", "n": 10, "cr": at(20), "cl": None, "lb": ["bug"], "st": "OPEN"}]
    prs = [pr(11, 45, mg=44, ti='Revert "Add cache"'), pr(12, 120, mg=110, lb=["hotfix"])]
    incidents = delivery.find_incidents(prs, issues, deps, CFG)
    by = {(i["source"], i["number"]): i for i in incidents}
    assert set(by) == {("issue", 9), ("revert", 11), ("hotfix", 12)}
    assert by[("issue", 9)]["deployment"] == "d2" and by[("issue", 9)]["hours_to_restore"] == 20
    assert by[("hotfix", 12)]["deployment"] is None  # nothing was deployed before it


def test_dora_uses_devlakes_counting_lower_median_and_both_tier_tables():
    assert delivery.devlake_median([1, 2, 3, 4]) == 2 and delivery.devlake_median([5, 1, 3]) == 3
    start, end = datetime(2026, 9, 21, tzinfo=timezone.utc), datetime(2026, 10, 19, tzinfo=timezone.utc)  # 4 Mondays
    days = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-29", "2026-10-06", "2026-10-07", "2026-10-13"]
    deps = [{"id": f"d{i}", "sha": "s", "finished": f"{d}T10:00:00Z"} for i, d in enumerate(days)]
    deps += [{"id": "dx", "sha": "s", "finished": "2026-09-21T12:00:00Z"}]  # a second deployment that day counts once
    lead = {"d0": 30 * 60, "d1": 10 * 60, "d3": 2 * 24 * 60}  # PR cycle minutes by deployment
    incidents = [{"deployment": "d1", "created": "2026-09-22T12:00:00Z", "resolved": "2026-09-22T14:00:00Z"}]
    out = delivery.dora(deps, [{"deployment": d, "cycle_min": m} for d, m in lead.items()], incidents, start, end, "2023")
    assert out["deployment_days_per_week"] == 1 and out["frequency_tier"] == "high"
    assert out["lead_time_hours"] == 30 and out["lead_time_tier"] == "high"
    # Two deployments on one day are one deployment day but two deployments for the failure rate (DevLake).
    assert out["deployments"] == 8 and out["change_failure_rate"] == 0.125 and out["cfr_tier"] == "medium"
    assert out["recovery_hours"] == 4 and out["recovery_tier"] == "high" and out["mttr_hours"] == 2
    old = delivery.dora(deps, [{"deployment": d, "cycle_min": m} for d, m in lead.items()], incidents, start, end, "2021")
    assert old["frequency_tier"] == "high" and old["cfr_tier"] == "elite" and old["lead_time_tier"] == "high"


def test_dora_follows_devlakes_sql_to_the_minute_and_the_day():
    start, end = datetime(2026, 7, 22, 12, tzinfo=timezone.utc), datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
    deps = [{"id": "s", "sha": "a", "finished": "2026-07-22T15:00:00Z"},  # the start's own day is outside DevLake's calendar
            {"id": "m", "sha": "b", "finished": "2026-08-10T09:00:00Z"}, {"id": "e", "sha": "c", "finished": "2026-10-20T08:00:00Z"}]
    incidents = [{"deployment": "m", "created": "2026-08-10T10:00:00Z", "resolved": "2026-08-10T11:30:59Z"},
                 {"deployment": "s", "created": "2026-07-22T16:00:00Z", "resolved": "2026-10-21T18:00:00Z"}]
    out = delivery.dora(deps, [{"deployment": "m", "cycle_min": 61}], incidents, start, end, "2023")
    assert out["deployment_days"] == 2 and out["deployments"] == 3
    # Recovery runs from the deployment's finish in whole minutes (TIMESTAMPDIFF), for incidents resolved in the window.
    assert out["recovery_minutes"] == 150 and out["recovery_n"] == 1
    assert out["monthly"] == [{"month": "26/07", "deployments": 1}, {"month": "26/08", "deployments": 1},
                              {"month": "26/09", "deployments": 0}, {"month": "26/10", "deployments": 1}]
    # DevLake's frequency tier needs six months of data below one deployment day a month; with less it says N/A.
    assert out["deployment_days_per_month"] == 0 and out["frequency_tier"] is None
    assert delivery.dora(deps, [], [], start, end, "2023")["cfr_tier"] is None  # no incidents at all: N/A, not elite


def test_devlake_cycle_time_sums_whole_minutes_rounded_up():
    p = pr(1, cr=10, mg=5, fa=10.001)
    ph = delivery.phases(p, deployed_at=at(4.999))
    # coding 3.6 s, opened to merged 5 h, deploy 3.6 s: each rounded up to a whole minute, as DevLake does.
    assert ph["devlake_cycle_min"] == 1 + 300 + 1


def test_build_reports_phases_with_n_outliers_stuck_prs_sizes_and_ai_aggregates():
    merged = [pr(100 + k, cr=200 + k, mg=150 + k, fa=210 + k, ev=[review(190 + k)], add=30 + k, dele=0) for k in range(12)]
    merged.append(pr(300, cr=24 * 70, mg=24 * 69, fa=24 * 140, ev=[review(24 * 69.5)]))  # 71 days from first commit: outlier
    merged.append(pr(301, cr=100, mg=90, fa=101, ai=["claude"], ev=[review(95)]))
    merged.append(pr(302, cr=100, mg=99.8, fa=100, ev=[review(99.9)]))  # merged 6 minutes after the first review: lightning
    merged.append(pr(303, cr=100, mg=96, fa=100, au="copilot-swe-agent[bot]", kind="Bot", ev=[review(97)]))
    open_prs = [pr(1, cr=24 * 40, ev=[["req", at(24 * 39), "bob"]], rq=["bob"]),  # long-lived and hanging
                pr(2, cr=24 * 5, ev=[["req", at(24 * 4), "bob"]], rq=["bob"], cmn=12),  # hanging, high interaction
                pr(3, cr=10)]
    repo = {"default_branch": "main", "deployments": [], "releases": [{"tag": "v1", "at": at(140), "pre": False, "sha": "r"}]}
    out = delivery.build({"closed": merged, "open": open_prs}, repo, {"runs": [], "jobs": []}, [], NOW, 90, CFG)
    ph = out["phases"]
    assert ph["pickup"]["n"] == 14 and ph["pickup"]["p50_h"] is not None and ph["pickup"]["p75_h"] >= ph["pickup"]["p50_h"]
    assert out["outliers"] == {"over_60_days": 1, "over_p98": 0}
    assert out["deploy_source"] == "releases" and out["dora"]["deployments"] == 1
    stuck = {k: [x["pr"] for x in v] for k, v in out["stuck"].items()}
    assert stuck["hanging_review"] == [1, 2] and stuck["long_lived"] == [1] and stuck["high_interaction"] == [2]
    assert [x["pr"] for x in out["merged_flags"]["lightning"]] == [302]
    assert out["sizes"]["under_100"] == 14 and out["sizes"]["n"] == 14
    ai = out["ai"]
    assert ai["agent_prs"]["merged"] == 1 and ai["assisted_prs"]["n"] == 1 and ai["assisted_prs"]["tools"] == {"claude": 1}
    assert "linearb_band" in ph["pickup"]


def test_identity_settings_fix_who_is_a_bot_merge_aliases_and_group_cycle_time_by_team():
    cfg = parse('[identity]\nbots = ["release-captain"]\npeople = ["build-bot-jane"]\n'
                'aliases = { "amy-old" = "amy" }\n[identity.teams]\nweb = ["amy", "build-bot-jane"]\n')[0]
    merged = [pr(100 + k, cr=200 + k, mg=150 + k, fa=210 + k, ev=[review(190 + k)], au="amy-old" if k % 2 else "amy",
                 paths=["web/app.js"]) for k in range(10)]
    merged += [pr(200, cr=100, mg=90, fa=101, au="release-captain", ev=[review(95)], paths=["web/x.js"]),
               pr(201, cr=100, mg=90, fa=101, au="build-bot-jane", ev=[review(95)], paths=["api/y.py"])]
    repo = {"default_branch": "main", "deployments": [], "releases": [], "codeowners": "/web/ @o/web-team\n/api/ @carol\n"}
    out = delivery.build({"closed": merged, "open": []}, repo, {"runs": []}, [], NOW, 90, cfg)
    assert out["prs"] == 11  # release-captain is a bot by the settings; build-bot-jane a person
    assert out["merge_frequency"] == round(11 / 2 / (90 / 7), 2)  # amy-old counts as amy: two authors
    assert out["by_team"]["web"]["n"] == 11 and out["by_team"]["web"]["cycle_to_merge"]["p75_h"] is not None
    # Code owners group by owning team; single people are left out of the published numbers (D5).
    assert set(out["by_owner"]) == {"@o/web-team"} and out["by_owner"]["@o/web-team"]["n"] == 10


def test_under_ten_prs_a_phase_shows_its_n_and_not_enough_data():
    merged = [pr(100 + k, cr=200 + k, mg=150 + k, fa=210 + k, ev=[review(190 + k)]) for k in range(9)]
    out = delivery.build({"closed": merged, "open": []}, {"default_branch": "main"}, {"runs": []}, [], NOW, 90, CFG)
    assert out["phases"]["pickup"]["n"] == 9 and out["phases"]["pickup"]["p75_h"] is None
    assert out["phases"]["pickup"]["enough"] is False


def test_vercel_style_production_environments_count():
    repo = {"default_branch": "main", "releases": [],
            "deployments": [{"env": "Production – kb", "at": at(10), "state": "SUCCESS", "sha": "k", "done": at(9)},
                            {"env": "Preview – kb", "at": at(8), "state": "SUCCESS", "sha": "p", "done": at(7)},
                            {"env": "production-eu", "at": at(6), "state": "SUCCESS", "sha": "e", "done": at(5)},
                            {"env": "productions-test", "at": at(4), "state": "SUCCESS", "sha": "x", "done": at(3)}]}
    deps, source = delivery.find_deployments(repo, {"runs": []}, CFG)
    assert source == "deployments api" and [d["sha"] for d in deps] == ["k", "e"]


def test_a_deploy_workflow_on_few_main_branch_commits_is_a_side_service_and_releases_win():
    def run(i, name, sha):
        return {"id": i, "att": 1, "wfn": name, "path": f".github/workflows/{name.lower().replace(' ', '-')}.yml", "ev": "push",
                "br": "main", "sha": sha, "c": "success", "up": at(100 - i)}
    ci_runs = [run(i, "CI", f"s{i}") for i in range(1, 41)]
    side = ci_runs + [run(100, "Deploy schema worker", "s3")]
    repo = {"default_branch": "main", "deployments": [], "releases": [{"tag": "v1", "at": at(5), "pre": False, "sha": "s9"}]}
    assert delivery.find_deployments(repo, {"runs": side}, CFG)[1] == "releases"  # ran on 1 of 40 commits
    continuous = ci_runs + [run(200 + i, "Deploy app", f"s{i}") for i in range(1, 41, 2)]
    assert delivery.find_deployments(repo, {"runs": continuous}, CFG)[1] == "deploy workflows"  # half the commits
    assert delivery.find_deployments({**repo, "releases": []}, {"runs": side}, CFG)[1] == "deploy workflows"


def test_releases_skip_semver_prereleases_and_packages_shipped_from_one_commit_count_once():
    rels = [{"tag": "tauri-v3.0.0-alpha.5", "at": at(30), "pre": False, "sha": "a"},
            {"tag": "v2.1.0", "at": at(20), "pre": False, "sha": "c1"},
            {"tag": "@scope/cli-v2.1.0", "at": at(19), "pre": False, "sha": "c1"},
            {"tag": "tauri-utils-v2.1.0", "at": at(18), "pre": False, "sha": "c1"},
            {"tag": "v2.2.0-rc.1", "at": at(10), "pre": False, "sha": "r"},
            {"tag": "v2.2.0", "at": at(5), "pre": False, "sha": "c2"}]
    deps, source = delivery.find_deployments({"default_branch": "main", "deployments": [], "releases": rels}, {"runs": []}, CFG)
    assert source == "releases" and [d["sha"] for d in deps] == ["c1", "c2"]
    assert deps[0]["finished"] == at(18) and deps[0]["name"] == "v2.1.0 +2"


def test_the_result_says_how_sure_the_deployment_source_is_and_what_was_counted():
    runs = [{"id": i, "att": 1, "wfn": "Deploy app", "path": ".github/workflows/deploy.yml", "ev": "push", "br": "main",
             "sha": f"s{i}", "c": "success", "up": at(50 - i)} for i in range(1, 6)]
    out = delivery.build({"closed": [], "open": []}, {"default_branch": "main", "deployments": [], "releases": []},
                         {"runs": runs}, [], NOW, 90, CFG)
    assert out["deploy_source"] == "deploy workflows" and out["deploy_confidence"] == "low"
    assert out["deploy_names"] == [{"name": "Deploy app", "n": 5}]
    rel = {"default_branch": "main", "deployments": [], "releases": [{"tag": "v1", "at": at(5), "pre": False, "sha": "x"}]}
    assert delivery.build({"closed": [], "open": []}, rel, {"runs": []}, [], NOW, 90, CFG)["deploy_confidence"] == "medium"


def test_the_published_incidents_are_the_windows_own():
    old = pr(9710, cr=24 * 400, mg=24 * 399, fa=24 * 401, ti='Revert "Old change"')
    new = pr(14597, cr=24 * 10, mg=24 * 9, fa=24 * 11, ti='Revert "New change"')
    out = delivery.build({"closed": [old, new], "open": []}, {"default_branch": "main", "deployments": [], "releases": []},
                         {"runs": []}, [], NOW, 90, CFG)
    assert [i["number"] for i in out["incidents"]] == [14597]
