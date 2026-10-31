"""Delivery as a whole: deployments found from what a repo already has (and the workflow names that only look like
shipping), DORA counted as DevLake's own dashboard SQL counts it on our DevLake-shaped export, and identity settings."""
from datetime import datetime, timedelta, timezone

import pytest

from stackvitals.core import delivery, export
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
CFG = parse("")[0]


def at(h):
    return (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, cr, mg, fa, mc=None, au="amy", ti="Fix", review_at=None, paths=()):
    ev = [["review", at(review_at), "bob", "APPROVED", "MEMBER", "User", False]] if review_at is not None else []
    return {"t": "pr", "n": n, "ti": ti, "draft": False, "st": "MERGED", "cr": at(cr), "up": at(1), "mg": at(mg), "cl": at(mg),
            "au": au, "at": "User", "as": "NONE", "base": "main", "head": f"b{n}", "ho": au, "add": 40, "del": 10, "ev": ev,
            "cm": [], "rq": [], "fa": at(fa), "mc": mc, "lb": [], "ai": [], "cmn": 0, "paths": list(paths)}


def test_workflow_names_that_only_look_like_shipping_never_count():
    # Real names from 45 public repos (2026-10-20); "latest" once matched "test" and hid a real publish.
    base = CFG["delivery"]["deploy_workflow"]
    for name, path in [("Preview release", "preview-release.yml"), ("Create Release PR", "create-release-pr.yml"),
                       ("Prepare Release", "prepare-release.yml"), ("Release Docs Check", "release-docs-check.yml"),
                       ("Sign release binaries", "sign-release-binaries.yml"), ("Publish Prerelease", "publish-prerelease.yml"),
                       ("Authorize Vercel Deploys", "authorize-vercel-deploys.yml"), ("pages-build-deployment", "pages-build-deployment"),
                       ("Release: Send version release notification", "release-version-release-notification.yml")]:
        assert delivery.deploy_kind(name, f".github/workflows/{path}", base) is None, name
    assert delivery.deploy_kind("Release: Set stable npm packages to latest", "x.yml", base) == "release"
    assert delivery.deploy_kind("Deploy bun.com", "deploy-site.yml", base) == "deploy"
    # Labelled repos (bench/accuracy/dora, 2026-10-22): a file named deploy.yml shipped every merge as "Check and Publish …".
    assert delivery.deploy_kind("Check and Publish Chemistry Note", ".github/workflows/deploy.yml", base) == "deploy"


def test_release_workflows_rank_after_releases_and_only_count_on_a_version():
    runs = [{"id": 1, "att": 1, "wfn": "Release", "path": ".github/workflows/release.yml", "ev": "push", "br": "v2.1.0",
             "sha": "t1", "c": "success", "up": at(11)},
            {"id": 2, "att": 1, "wfn": "Release", "path": ".github/workflows/release.yml", "ev": "push", "br": "main",
             "sha": "t2", "c": "success", "up": at(7)}]
    repo = {"default_branch": "main", "deployments": [], "releases": [{"tag": "v2.1.0", "at": at(10), "pre": False, "sha": "t1"}]}
    assert delivery.find_deployments(repo, {"runs": runs}, CFG)[1] == "releases"
    deps, source = delivery.find_deployments({**repo, "releases": []}, {"runs": runs}, CFG)
    assert source == "release workflows" and [d["sha"] for d in deps] == ["t1"]


@pytest.mark.parametrize("report", ["2023", "2021"])
def test_devlakes_own_dora_sql_on_our_export_gives_our_numbers(tmp_path, report):
    pytest.importorskip("duckdb")
    merged = [pr(100 + k, cr=24 * 80 - k * 46, mg=24 * 80 - k * 46 - 5 - k % 7, fa=24 * 80 - k * 46 + 3 + k % 5, mc=f"m{k}",
                 review_at=24 * 80 - k * 46 - 2) for k in range(40)]
    merged.append(pr(300, cr=24 * 30, mg=24 * 30 - 1, fa=24 * 30 + 1, ti='Revert "Add cache"', review_at=24 * 30 - 0.5))
    releases = [{"tag": f"v{k}", "at": at(24 * 79 - k * 24 * 6), "pre": False, "sha": f"m{3 * k}"} for k in range(13)]
    repo = {"default_branch": "main", "deployments": [], "releases": releases}
    issues = [{"t": "issue", "n": 9, "cr": at(24 * 50), "cl": at(24 * 49), "lb": ["incident"], "st": "CLOSED", "au": "zed"}]
    flow, cfg = {"closed": merged, "open": []}, parse(f'[delivery]\ndora_report = "{report}"\n')[0]
    ours = delivery.build(flow, repo, {"runs": []}, issues, NOW, 90, cfg)
    export.write(export.devlake_tables("o/r", flow, repo, {"runs": []}, issues, cfg), tmp_path)
    got = export.panels(tmp_path, NOW - timedelta(days=90), NOW, report, project="o/r")
    d = ours["dora"]
    unit = "week" if report == "2023" else "month"
    assert got["deployment_frequency"] == f"{d['deployment_days_per_' + unit]} deployment days per {unit}(high)"
    assert got["lead_time"] == f"{round(d['lead_time_minutes'] / 60, 1)}({d['lead_time_tier']})"
    assert got["change_failure_rate"] == f"{round(d['failed_deployments'] / d['deployments'] * 100, 1)}%({d['cfr_tier']})"
    minutes = d["recovery_minutes"] if report == "2023" else d["mttr_minutes"]
    assert got["recovery"] == f"{round(minutes / 60, 1)}({d['recovery_tier']})"
    assert got["monthly"] == [(m["month"], m["deployments"]) for m in d["monthly"]]
    assert [(str(m), round(float(h), 2)) for m, h in got["pr_cycle_time"]] == \
        [(c["month"], round(c["avg_hours"], 2)) for c in ours["devlake_pr_cycle"]]


def test_identity_settings_beat_the_name_rules_and_merge_old_logins():
    cfg = parse('[identity]\nbots = ["release-captain"]\npeople = ["build-bot-jane"]\naliases = { "amy-old" = "amy" }\n')[0]
    merged = [pr(100 + k, cr=200 + k, mg=150 + k, fa=210 + k, au="amy-old" if k % 2 else "amy", review_at=190 + k) for k in range(10)]
    merged += [pr(200, cr=100, mg=90, fa=101, au="release-captain", review_at=95),
               pr(201, cr=100, mg=90, fa=101, au="build-bot-jane", review_at=95)]
    out = delivery.build({"closed": merged, "open": []}, {"default_branch": "main"}, {"runs": []}, [], NOW, 90, cfg)
    assert out["prs"] == 11 and out["merge_frequency"] == round(11 / 2 / (90 / 7), 2)


def test_real_repo_shapes_pick_the_right_source():
    # Found on public repos (2026-10-20): Vercel's "Production – app" environments, a side worker's deploy workflow
    # next to releases (tauri), alpha tags not flagged as prereleases, and one commit released as many packages.
    vercel = {"default_branch": "main", "releases": [],
              "deployments": [{"env": "Production – kb", "at": at(10), "state": "SUCCESS", "sha": "k", "done": at(9)},
                              {"env": "Preview – kb", "at": at(8), "state": "SUCCESS", "sha": "p", "done": at(7)}]}
    assert [d["sha"] for d in delivery.find_deployments(vercel, {"runs": []}, CFG)[0]] == ["k"]
    pushes = [{"id": i, "att": 1, "wfn": "CI", "path": ".github/workflows/ci.yml", "ev": "push", "br": "main", "sha": f"s{i}",
               "c": "success", "up": at(100 - i)} for i in range(1, 41)]
    worker = pushes + [{**pushes[2], "id": 99, "wfn": "deploy schema worker", "path": ".github/workflows/deploy-schema-worker.yml"}]
    rels = [{"tag": "tauri-v3.0.0-alpha.5", "at": at(30), "pre": False, "sha": "a"},
            {"tag": "tauri-v2.1.0", "at": at(20), "pre": False, "sha": "c1"},
            {"tag": "@tauri-apps/cli-v2.1.0", "at": at(19), "pre": False, "sha": "c1"}]
    deps, source = delivery.find_deployments({"default_branch": "main", "deployments": [], "releases": rels}, {"runs": worker}, CFG)
    assert source == "releases" and [d["sha"] for d in deps] == ["c1"] and deps[0]["finished"] == at(19)


def test_peers_are_measured_the_crawls_way_and_placed_in_the_closest_group():
    from stackvitals.core import delivery_peers
    prs = [pr(100 + k, cr=200 + k, mg=158 + k, fa=201 + k, review_at=160 + k) for k in range(12)]  # pickup 40 h, review 2 h
    own = delivery_peers.own_metrics(prs, NOW)
    assert own["pickup_p75_hours"] == 40.0 and own["review_p75_hours"] == 2.0
    q = {"repos": 800, "p10": 1.0, "p25": 3.0, "p50": 9.5, "p75": 30.0, "p90": 90.0, "p50_low": 8.9, "p50_high": 10.2,
         "linearb": {"elite": 0.08, "good": 0.22, "fair": 0.55}}
    out = delivery_peers.compare(own, {"groups": {"Python|1k-10k": {"repos": 812, "pickup_p75_hours": q}}}, "Python", 2500)
    m = out["metrics"][0]
    assert m["typical"] == 9.5 and (m["low"], m["high"]) == (8.9, 10.2) and m["place"].startswith("slower than about")


def test_working_agreements_list_the_pull_requests_that_broke_them():
    """P11 M3: Swarmia-style team rules, off until set, judged with Delivery's own phases."""
    from stackvitals.core import agreements
    slow, unreviewed = pr(1, cr=100, mg=10, fa=101, review_at=40), pr(2, cr=30, mg=20, fa=31)
    rows = [(p, delivery.phases(p, None), None) for p in (slow, unreviewed)]
    assert agreements.check(rows, [], parse("")[0]["agreements"], NOW) is None
    out = agreements.check(rows, [], parse("[agreements]\nreview_within_hours = 24\nreview_before_merge = true\n")[0]["agreements"], NOW)
    assert {(e["pr"], e["rule"]) for e in out["exceptions"]} == {(1, "review_within_hours"), (2, "review_before_merge")}


def test_an_open_pr_with_only_a_bot_comment_is_still_waiting_for_a_review():
    """Sandbox finding (2026-10-21): StackVitals' own CI comment on a PR counted as its review."""
    from stackvitals.core import agreements
    waiting = {**pr(5, cr=72, mg=0, fa=73), "st": "OPEN", "mg": None, "cl": None,
               "cm": [[at(70), "github-actions[bot]", "NONE", "Bot", False]]}
    out = agreements.check([], [waiting], parse("[agreements]\nreview_within_hours = 24\n")[0]["agreements"], NOW)
    assert [e["pr"] for e in out["exceptions"]] == [5]


def test_ai_outcomes_match_fork_runs_by_branch_and_leave_release_sized_deployments_out():
    # Real-data finding (pytest, pip): fork PRs' runs name no PR, so CI failures read 0% until matched by head branch;
    # releases batch dozens of PRs, so every PR looked like it shipped in a failed deployment.
    from stackvitals.core.ai_outcomes import outcomes
    def merged(n, ai=(), **kw):
        return {"n": n, "mg": "2026-10-04T10:00:00Z", "cr": "2026-10-02T10:00:00Z", "ai": list(ai), "lb": [], "ti": f"Change {n}",
                "au": "dev", "add": 10, "del": 0, **kw}
    fork = merged(1, ai=["claude"], ho="someone", head="fix-x")
    ci = {"runs": [{"id": 5, "pr": [], "c": "failure", "att": 1, "ev": "pull_request", "cr": "2026-10-03T10:00:00Z",
                    "ho": "Someone", "br": "fix-x"}]}
    big = {"id": "big", "finished": "2026-10-05T00:00:00Z"}
    rows = [(fork, {"pickup": 1, "review": 1}, big)] + [(merged(10 + k), {"pickup": 1, "review": 1}, big) for k in range(5)]
    out = outcomes(rows, ci, [{"source": "issue", "number": 99, "created": "2026-10-06T00:00:00Z", "deployment": "big"}], NOW, min_n=1)
    assert out["window"]["assisted"]["ci_failed_share"] == 1.0 and out["window"]["assisted"]["failed_deploy_share"] is None


def test_merge_queue_removals_read_graphqls_lowercase_reasons_and_tie_flaky_ones():
    # Real-data finding (bevyengine/bevy): GraphQL spells reasons in lowercase (merged, merge_conflict, failed_checks).
    from stackvitals.core.merge_queue import health
    prs = [{"n": 1, "mg": "2026-10-10T12:00:00Z", "mq": [["add", "2026-10-10T10:00:00Z"], ["rm", "2026-10-10T12:09:00Z", "merged"]]},
           {"n": 2, "mg": None, "mq": [["add", "2026-10-11T10:00:00Z"], ["rm", "2026-10-11T10:40:00Z", "failed_checks"]]}]
    ci = {"runs": [{"id": 5, "att": 1, "ev": "merge_group", "br": "gh-readonly-queue/main/pr-2-abc", "c": "failure",
                    "cr": "2026-10-11T10:05:00Z", "path": "ci.yml"}], "jobs": [{"run": 5, "att": 1, "n": "e2e", "c": "failure"}]}
    out = health(prs, ci, {("ci.yml", "e2e"): "flaky"}, NOW, 30, min_n=1)
    assert out["removals"] == {"failed_checks": 1} and [x["pr"] for x in out["removed_by_flakes"]] == [2] and out["p50_h"] == 2.0


def test_where_the_work_went_reads_changelog_fragments_and_release_prs():
    # Real data (pip, pytest, aiohttp): 61-86% of merged PRs had no label or Conventional Commit title; their changelog
    # fragments brought that to 3-7%. A release PR gathers every fragment (pip "Release 26.2"), so its title decides.
    from stackvitals.core.investment import classify
    pr = lambda title, paths=(): {"ti": title, "lb": [], "paths": list(paths)}  # noqa: E731
    assert classify(pr("Fix broken pipe", ["src/x.py", "news/11608.bugfix.rst"])) == ("fix", "changelog fragment bugfix")
    assert classify(pr("Add a space", ["src/a.py", "changelog/14430.improvement.rst"]))[0] == "feature"
    assert classify(pr("Release 26.2", ["news/1.bugfix.rst", "news/2.feature.rst"])) == ("maintenance", "title release")
    assert classify(pr("dialects: (llvm) add ShuffleVectorOp"))[0] == "feature"


def test_the_deploy_dry_run_agrees_with_what_counts_and_says_why_the_rest_dont():
    from stackvitals.core.config import DELIVERY
    from stackvitals.core.delivery import explain_deployments, find_deployments
    cfg = {"delivery": {**DELIVERY, "source": "auto"}}
    repo = {"default_branch": "main",
            "deployments": [{"env": "Production", "at": "2026-10-02T10:00:00Z", "state": "SUCCESS", "sha": "a"},
                            {"env": "Preview", "at": "2026-10-03T10:00:00Z", "state": "SUCCESS", "sha": "b"}],
            "releases": [{"tag": "v1.0.0", "at": "2026-10-05T10:00:00Z", "pre": False, "sha": "d"}]}
    ci = {"runs": [{"id": 1, "att": 1, "wfn": "Deploy docs", "path": ".github/workflows/docs.yml", "ev": "push",
                    "br": "main", "c": "success", "sha": "s1", "up": "2026-10-01T10:00:00Z"}]}
    found, source = find_deployments(repo, ci, cfg)
    check = explain_deployments(repo, ci, cfg)
    assert (check["source"], check["deployments"]) == (source, len(found)) == ("deployments api", 1)
    assert {e["name"]: e["as"] for e in check["environments"]} == {"Production": "production", "Preview": "staging"}
    assert '"docs"' in check["workflows"][0]["why"]


def test_stages_of_one_commit_count_once_and_a_rollback_counts_again():
    # Phase 18: canary-then-full counted each stage; the first fix then merged A, B, back to A into two (review finding).
    dep = lambda sha, at, env="production": {"env": env, "at": at, "done": at, "state": "SUCCESS", "sha": sha}  # noqa: E731
    repo = {"default_branch": "main", "releases": [], "deployments": [
        dep("a", "2026-10-05T10:00:00Z", "production-canary"), dep("a", "2026-10-05T12:00:00Z"),
        dep("b", "2026-10-06T10:00:00Z"), dep("a", "2026-10-07T10:00:00Z")]}
    found, source = delivery.find_deployments(repo, {"runs": []}, CFG)
    assert source == "deployments api" and [(d["sha"], d["stages"]) for d in found] == [("a", 2), ("b", 1), ("a", 1)]


def test_every_merge_as_a_deployment_explains_its_source_without_crashing():
    # source = "merges" crashed the deploy dry run (KeyError), so the whole report failed; found in the Middleware run.
    from stackvitals.core import delivery
    from stackvitals.core.config import parse
    out = delivery.explain_deployments({"default_branch": "main"}, {}, parse('[delivery]\nsource = "merges"\n')[0])
    assert out["settings"]["source"] == "merges" and out["order_reason"] == 'source = "merges" in [delivery]'
