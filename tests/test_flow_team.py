import json
import subprocess
from datetime import datetime, timedelta, timezone

from mergescout.github.graphql import GraphQLResult
from stackvitals.flow.action import run_flow_action
from stackvitals.flow.analyze import analyze, stages, who_acts_next
from stackvitals.flow.collect import collect
from stackvitals.flow.report import render_html, render_markdown
from stackvitals.flow.store import FlowStore

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def at(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, ev=(), st="OPEN", cr=100, mg=None, au="alice", assoc="CONTRIBUTOR", rq=(), cm=(), ci="SUCCESS", lc=90, draft=False):
    return {"t": "pr", "n": n, "ti": f"PR {n}", "draft": draft, "st": st, "cr": at(cr), "up": at(1),
            "mg": at(mg) if mg is not None else None, "cl": at(mg) if mg is not None else None, "add": 10, "del": 1,
            "files": 1, "au": au, "at": "User", "as": assoc, "rq": list(rq), "ev": list(ev), "cm": list(cm), "ci": ci,
            "lc": at(lc)}


def rv(hours, who, state="APPROVED", kind="User", assoc="MEMBER"):
    return ["review", at(hours), who, state, assoc, kind]


def test_stages_follow_githubs_boundaries_and_skip_bots_and_the_author():
    p = pr(1, st="MERGED", cr=100, mg=68, ev=[["ready", at(98)], ["req", at(97), "bob"], rv(96, "sourcery-ai", kind="Bot"),
                                               rv(95, "alice", "COMMENTED", assoc="CONTRIBUTOR"), rv(90, "bob", "COMMENTED"),
                                               rv(70, "bob"), ["merged", at(68), "bob"]])
    s = stages(p)
    assert s["pickup"] == 8 * 3600 and s["review"] == 20 * 3600 and s["merge"] == 2 * 3600 and s["cycle"] == 30 * 3600


def test_who_acts_next_names_the_person_and_the_event_that_put_the_ball_there():
    w = who_acts_next(pr(2, ev=[["req", at(50), "carol"]], rq=["carol"]), NOW)
    assert w["actor"] == "reviewers" and w["who"] == ["carol"] and w["since"] == at(50)
    w = who_acts_next(pr(3, ev=[rv(30, "bob", "CHANGES_REQUESTED")], lc=40), NOW)
    assert w["actor"] == "author" and "bob" in w["why"]
    w = who_acts_next(pr(4, ev=[rv(30, "bob", "CHANGES_REQUESTED")], lc=20), NOW)
    assert w["actor"] == "reviewers" and w["who"] == ["bob"] and w["since"] == at(20)
    w = who_acts_next(pr(5, ev=[rv(30, "bob")]), NOW)
    assert w["actor"] == "maintainers" and "approved" in w["why"]
    assert who_acts_next(pr(7, ci="FAILURE", rq=["carol"]), NOW)["actor"] == "author"


# Real findings on astral-sh/uv: a passer-by's "request changes" blocked a PR; stacked PRs were blamed on reviewers.
def test_only_maintainers_reviews_decide_and_stacked_prs_wait_for_their_parent():
    assert who_acts_next(pr(1, ev=[rv(30, "passerby", "CHANGES_REQUESTED", assoc="NONE")]), NOW)["actor"] == "maintainers"
    parent = pr(1, ev=[["req", at(50), "carol"]], rq=["carol"]) | {"head": "feat-a", "ho": "o", "base": "main"}
    child = pr(2, ev=[["req", at(40), "carol"]], rq=["carol"]) | {"head": "feat-b", "ho": "o", "base": "feat-a"}
    assert [q["n"] for q in analyze({"open": [parent, child], "closed": []}, NOW, owner="o")["queue"]] == [1]


# Real findings on poetry and vite: minute-level "usual" waits flagged everything, ancient PRs buried today's work,
# and outsiders' PRs were judged against insiders' speed.
def test_overdue_needs_a_day_old_waits_are_backlog_and_outsiders_are_compared_with_outsiders():
    quick = [pr(100 + k, st="MERGED", cr=500 + k, mg=494.9 + k, ev=[rv(495 + k, "bob"), ["merged", at(494.9 + k), "bob"]])
             for k in range(10)]
    out = analyze({"open": [pr(1, ev=[rv(2, "bob")]), pr(2, cr=24 * 60, ev=[["req", at(24 * 50), "carol"]], rq=["carol"]),
                            pr(3, ev=[["req", at(50), "carol"]], rq=["carol"])], "closed": quick}, NOW)
    q = {i["n"]: i for i in out["queue"]}
    assert not q[1]["slow"] and q[3]["slow"] and q[2]["stale"] and [i["n"] for i in out["queue"]] == [3, 1, 2]
    fast_insiders = [pr(200 + k, st="MERGED", cr=900 + k, mg=880 + k, assoc="MEMBER",
                        ev=[rv(899 + k, "bob"), ["merged", at(880 + k), "bob"]]) for k in range(30)]
    slow_outsiders = [pr(300 + k, st="MERGED", cr=900 + k, mg=800 + k, au="newbie", assoc="NONE",
                         ev=[rv(840 + k, "bob"), ["merged", at(800 + k), "bob"]]) for k in range(10)]
    out = analyze({"open": [pr(1, au="newbie", assoc="NONE", cr=40, ev=[["req", at(40), "bob"]], rq=["bob"])],
                   "closed": fast_insiders + slow_outsiders}, NOW)
    assert out["queue"][0]["slow"] is False


class Pages:
    def __init__(self, nodes):
        self.nodes = sorted(nodes, key=lambda x: x["updatedAt"], reverse=True)

    def query(self, query, variables=None, **kw):
        start = int(variables.get("cursor") or 0)
        data = {"rateLimit": {"cost": 1, "remaining": 999, "resetAt": at(0)},
                "repository": {"pullRequests": {"pageInfo": {"hasNextPage": start + 2 < len(self.nodes), "endCursor": str(start + 2)},
                                                "nodes": self.nodes[start:start + 2]}}}
        return GraphQLResult(data=data, cost=1, remaining=999, reset_at=at(0))


def node(n, state="OPEN", updated=1, title="Fix it", reviews=()):
    return {"number": n, "title": title, "isDraft": False, "state": state, "createdAt": at(100), "updatedAt": at(updated),
            "mergedAt": at(updated) if state == "MERGED" else None, "closedAt": at(updated) if state != "OPEN" else None,
            "additions": 1, "deletions": 0, "changedFiles": 1, "author": {"__typename": "User", "login": "alice"},
            "authorAssociation": "NONE", "commits": {"nodes": []}, "reviewRequests": {"nodes": []},
            "events": {"nodes": [{"__typename": "PullRequestReview", "submittedAt": at(h), "state": "APPROVED",
                                  "author": {"__typename": "User", "login": w}, "authorAssociation": "MEMBER"} for h, w in reviews]},
            "talk": {"nodes": []}}


def test_closed_prs_are_kept_once_and_a_reopened_pr_counts_as_open_only(tmp_path):
    store = FlowStore(tmp_path)
    collect(Pages([node(9, "CLOSED", updated=10), node(8, updated=5)]), store, "o", "r", NOW)
    collect(Pages([node(9, "OPEN", updated=1)]), store, "o", "r", NOW + timedelta(hours=1))
    data = store.load()
    assert sorted(p["n"] for p in data["open"]) == [8, 9] and data["closed"] == []


def test_the_public_page_never_shows_peoples_answer_times_and_ci_runs_skip_flow(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "GITHUB_EVENT_NAME": "schedule", "RUNNER_TEMP": str(tmp_path / "tmp")}
    nodes = [node(1), node(2, "MERGED", updated=50, reviews=[(90, "bob")])]
    assert run_flow_action(env, now=NOW, make_gql=lambda tok: Pages(nodes))["pushed"]
    page = subprocess.run(["git", "show", "stackvitals-data:docs/flow.json"], cwd=bare, capture_output=True, text=True).stdout
    assert "responders" not in json.loads(page)
    assert run_flow_action(env | {"GITHUB_EVENT_NAME": "workflow_run"}, now=NOW, make_gql=lambda tok: Pages(nodes)) is None


def test_pr_titles_from_strangers_are_escaped():
    evil = '<img src=x onerror=alert(1)> | `x`'
    out = analyze({"open": [pr(1) | {"ti": evil}], "closed": []}, NOW)
    assert "<img" not in render_html(out, "o/r") and "<img" not in render_markdown(out, "o/r")


# Sandbox finding: without checks/statuses read access the built-in token can't read check results; flow must still run.
def test_without_checks_permission_flow_still_runs(tmp_path):
    from mergescout.github.graphql import GraphQLError

    class NoStatus(Pages):
        def query(self, query, variables=None, **kw):
            if "statusCheckRollup" in query:
                raise GraphQLError("Resource not accessible by integration")
            return super().query(query, variables, **kw)
    out = collect(NoStatus([node(5)]), FlowStore(tmp_path), "o", "r", NOW)
    assert out["complete"] and out["no_checks"]


def test_without_deployments_permission_flow_still_runs(tmp_path):
    # Sandbox: every scheduled run failed from 2026-10-17 because the repo query asked for deployments.
    from mergescout.github.graphql import GraphQLError

    class NoDeployments(Pages):
        def query(self, query, variables=None, **kw):
            if "deployments(" in query:
                raise GraphQLError("Resource not accessible by integration")
            return super().query(query, variables, **kw)
    out = collect(NoDeployments([node(5)]), FlowStore(tmp_path), "o", "r", NOW)
    assert out["complete"] and out["no_deployments"]


def mpr(n, au, paths, days, reviewers=(), assoc="MEMBER", title="Change", head="feat"):
    when = (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    before = (NOW - timedelta(days=days + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ev = [["review", before, r, "APPROVED", "MEMBER", "User"] for r in reviewers] + [["merged", when, "x"]]
    return {"t": "pr", "n": n, "ti": title, "st": "MERGED", "cr": before, "mg": when, "cl": when, "au": au, "at": "User",
            "as": assoc, "rq": [], "ev": ev, "cm": [], "paths": list(paths), "add": 10, "del": 0, "head": head}


def team_history():
    return ([mpr(k, "dana", ["src/db/pool.py"], 10 + k, reviewers=["erin"]) for k in range(6)]
            + [mpr(60 + k, "visitor", ["src/db/y.py"], 5 + k, assoc="NONE") for k in range(5)]
            + [mpr(80 + k, "dana", ["Cargo.lock", "uv.lock"], 3 + k) for k in range(5)])


# Real findings: poetry suggested outside contributors; uv's busiest "area" was its lock files.
def test_suggestions_are_people_who_can_review_and_lock_files_are_not_areas():
    from stackvitals.flow.knowledge import expertise, knowledge_map, suggest_reviewers
    ex = expertise(team_history(), NOW)
    picks = suggest_reviewers({"n": 1, "au": "zed", "paths": ["src/db/z.py"]}, ex, {}, {})
    assert [p["login"] for p in picks] == ["dana", "erin"] and "answers in" not in picks[0]["why"]
    km = knowledge_map(team_history(), NOW)
    assert all(a["area"] != "(root)" for a in km["areas"]) and km["hotspots"][0]["area"] == "src/db"


def test_codeowners_last_matching_rule_wins():
    from stackvitals.flow.knowledge import codeowners_for
    text = "* @root-team\n/src/db/ @erin\n*.md @docs-team\n"
    assert codeowners_for("src/db/pool.py", text) == ["erin"] and codeowners_for("README.md", text) == ["docs-team"]
    assert codeowners_for("src/web/a.py", text) == ["root-team"]


def test_a_release_followed_by_a_revert_counts_as_a_labelled_failure():
    from stackvitals.flow.knowledge import delivery
    rel = [{"tag": f"v1.{k}", "at": (NOW - timedelta(days=60 - 7 * k)).strftime("%Y-%m-%dT%H:%M:%SZ"), "pre": False} for k in range(8)]
    prs = [mpr(1, "dana", ["a"], 30), mpr(3, "dana", ["a"], 28.5, title='Revert "Change"', head="revert-2-feat")]
    d = delivery(prs, rel, NOW, window_days=90)
    assert d["change_fail"] == {"failed": 1, "of": 8, "rate": 0.125, "proxy": True}


# Milestone 3: pre-flight habits, peer numbers, triage.
def test_preflight_lists_local_habits_and_what_a_change_is_missing():
    from stackvitals.flow.preflight import gaps, norms
    prs = [mpr(n, "dana", ["src/db/a.py", "tests/test_a.py"], 10) for n in range(1, 18)] + \
          [mpr(n, "dana", ["src/db/b.py"], 10) for n in range(20, 23)]
    habits = norms(prs, ["src/db/new.py"], NOW)
    assert habits["scope"] == "src/db" and habits["include"]["tests"] == 0.85
    assert [g["what"] for g in gaps({"paths": ["src/db/new.py"], "add": 5, "del": 0}, habits)] == ["tests"]


# Real finding: a review timed before the PR's opening crashed the peer numbers.
def test_peer_numbers_skip_times_out_of_order():
    from stackvitals.flow.peers import own_metrics
    prs = [mpr(n, "dana", ["a"], 5 + n) for n in range(12)]
    prs[0]["ev"] = [["review", (NOW - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ"), "erin", "APPROVED", "MEMBER", "User"]]
    assert own_metrics(prs, NOW)["merge_hours"] is not None


def test_triage_model_learns_directions_and_is_calibrated_on_unseen_rows():
    import math
    import random

    from mergescout.signals.triage_math import FEATURES, calibration, fit

    def rows(seed):
        rng, out = random.Random(seed), []
        for _ in range(4000):
            f = {name: rng.choice(values) for name, values in FEATURES.items()}
            # Effects add up on the logistic scale, the model's own shape, so calibration tests the fitting code.
            z = -0.4 + (1.3 if f["history"] == "3+" else 0) - (1.1 if f["repo_rate"] == "<30%" else 0)
            out.append({**f, "merged": rng.random() < 1 / (1 + math.exp(-z)), "repo": rng.randrange(300)})
        return out
    model = fit(rows(1))
    cal = calibration(model, rows(2))
    assert model["coef"]["history=3+"] > 0.5 and model["coef"]["repo_rate=<30%"] < -0.5
    assert all(abs(d["predicted"] - d["actual"]) <= 0.06 for d in cal["deciles"]) and cal["brier"] < cal["baseline_brier"]


def test_triage_training_knows_only_what_was_known_before_each_pr():
    import duckdb

    from mergescout.signals.triage import training_rows
    con = duckdb.connect()
    con.execute("""CREATE TABLE pr_class (repo_id BIGINT, number INT, created_at TIMESTAMPTZ, merged_at TIMESTAMPTZ,
        author_login VARCHAR, author_class VARCHAR, author_association VARCHAR, additions INT, deletions INT,
        closing_issue_numbers INT[])""")
    day = lambda d: NOW - timedelta(days=d)  # noqa: E731
    con.executemany("INSERT INTO pr_class VALUES (?,?,?,?,?,?,?,?,?,?)", [
        [1, 1, day(200), day(199), "ann", "outsider", "CONTRIBUTOR", 5, 0, []],
        [1, 2, day(100), day(98), "ann", "outsider", "CONTRIBUTOR", 5, 0, [3]],
        [1, 3, day(80), day(35), "cat", "outsider", "CONTRIBUTOR", 5, 0, []],
        [1, 4, day(10), day(9), "dan", "outsider", "CONTRIBUTOR", 5, 0, []],
        [1, 5, day(100), day(99), "maint", "insider", "MEMBER", 5, 0, []]])
    out = {r["number"]: r for r in training_rows(con, NOW)}
    assert out[2]["here_merged"] == 1 and out[1]["here_merged"] == 0 and out[2]["merged"] and out[2]["linked_issue"]
    assert out[3]["merged"] is False and 4 not in out and 5 not in out
    # GitHub reports the association when asked, so a merged first-timer reads CONTRIBUTOR: history decides instead.
    assert out[1]["first_timer"] is True and out[2]["first_timer"] is False


def test_triage_repo_rate_uses_only_earlier_prs_with_known_outcomes():
    import duckdb

    from mergescout.signals.triage import training_rows
    con = duckdb.connect()
    con.execute("""CREATE TABLE pr_class (repo_id BIGINT, number INT, created_at TIMESTAMPTZ, merged_at TIMESTAMPTZ,
        author_login VARCHAR, author_class VARCHAR, author_association VARCHAR, additions INT, deletions INT,
        closing_issue_numbers INT[])""")
    day = lambda d: NOW - timedelta(days=d)  # noqa: E731
    con.executemany("INSERT INTO pr_class VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [[1, k, day(400 - k * 10), day(399 - k * 10) if k % 2 else None, f"u{k}", "outsider", "NONE", 5, 0, []]
                     for k in range(30)])
    out = {r["number"]: r for r in training_rows(con, NOW)}
    # PR 25 opened 150 days ago: only PRs opened 180+ days ago (k 0-22) count, 11 of 23 merged.
    assert abs(out[25]["repo_rate"] - 11 / 23) < 1e-9


def test_preflight_note_cannot_ping_people_or_make_links():
    from stackvitals.flow.action import _preflight_targets
    merged = [mpr(n, "dana", ["src/core/a.py", "tests/test_a.py"], 10) for n in range(1, 13)]
    evil = pr(99, au="zed", assoc="NONE", cr=1) | {"paths": ["src/core/b.py", "x/@victim/y.py", "www.evil.example/z.py"], "add": 5, "del": 0}
    body = _preflight_targets({"open": [evil], "closed": merged}, at(2), set(), NOW)[0][1]
    assert "@victim" not in body and "www.evil" not in body and "src/core" in body


def test_a_failing_benchmark_step_never_stops_the_daily_snapshot(tmp_path, monkeypatch):
    import duckdb

    import mergescout.signals.flow_bench as fb
    from mergescout.snapshot.__main__ import write_extras

    def boom(*a, **k):
        raise RuntimeError("bad crawl batch")
    monkeypatch.setattr(fb, "flow_benchmarks", boom)
    said = []
    write_extras(duckdb.connect(), tmp_path, NOW, log=said.append)
    assert any("flow benchmarks skipped" in s for s in said) and not (tmp_path / "flow-benchmarks.json").exists()


# Hand-check of 51 real open PRs (34 right, 10 wrong, 7 debatable): one guard per pattern found.
def test_handcheck_rules_conflicts_approval_waits_and_required_checks():
    assert who_acts_next(pr(1, rq=["carol"], ev=[["req", at(50), "carol"]]) | {"mgs": "CONFLICTING"}, NOW)["actor"] == "author"
    waiting = {"failing": [["docs", True]], "awaiting": True, "required_any": True}
    assert who_acts_next(pr(2, ci="FAILURE") | {"chk": waiting}, NOW)["actor"] == "maintainers"
    flaky = {"failing": [["Build&Test", False]], "awaiting": False, "required_any": True}
    assert who_acts_next(pr(3, ci="FAILURE", rq=["bluwy"], ev=[["req", at(50), "bluwy"]]) | {"chk": flaky}, NOW)["actor"] == "reviewers"
    shared = {"failing": [["docs/readthedocs.org:tox", True]], "awaiting": False, "required_any": True}
    prs = [pr(k, ci="FAILURE", rq=["gab"], ev=[["req", at(20), "gab"]], au=f"a{k}") | {"chk": shared} for k in range(1, 4)]
    assert {q["actor"] for q in analyze({"open": prs, "closed": []}, NOW)["queue"]} == {"reviewers"}


def test_handcheck_rules_rebases_re_requests_questions_and_maintainer_authors():
    assert who_acts_next(pr(1, ev=[rv(30, "bob", "CHANGES_REQUESTED")], lc=5) | {"la": at(60)}, NOW)["actor"] == "author"
    assert who_acts_next(pr(2, rq=["carol"], ev=[["req", at(200), "carol"], ["req", at(20), "carol"]]), NOW)["since"] == at(20)
    assert who_acts_next(pr(3, cm=[[at(20), "bob", "MEMBER", "User", False]]), NOW)["actor"] == "maintainers"
    assert who_acts_next(pr(4, cm=[[at(20), "bob", "MEMBER", "User", True]]), NOW)["actor"] == "author"
    w = who_acts_next(pr(5, assoc="MEMBER", au="zanieb", ev=[rv(30, "konstin")]), NOW)
    assert w["actor"] == "author" and w["who"] == ["zanieb"]


# Fresh held-out check (25 PRs in 5 untouched repos): one guard per wrong-party pattern found.
def test_heldout_rules_breakage_in_its_own_time_and_points_raised_after_approval():
    def failing(n, hours):
        return pr(n, ci="FAILURE", au=f"a{n}", lc=hours) | {"chk": {"failing": [["test", True]], "awaiting": False,
                                                                    "required_any": True, "ran": ["test"]}}
    passing = [pr(10 + k, au=f"b{k}", lc=48 + k) | {"chk": {"failing": [], "awaiting": False, "required_any": True, "ran": ["test"]}}
               for k in range(3)]
    # Broken for every PR pushed in late September, fixed since: today's green PRs must not make it the author's.
    old = [failing(k, 600 + k) for k in range(1, 5)]
    assert {q["actor"] for q in analyze({"open": old + passing, "closed": []}, NOW)["queue"] if q["n"] < 10} == {"maintainers"}
    later = rv(20, "JukkaL", "COMMENTED") + [True]
    assert who_acts_next(pr(5, ev=[rv(90, "hauntsaninja"), later], lc=100), NOW)["actor"] == "author"


# Second held-out check (30 PRs in 5 more repos): first answers, others' merge commits and status labels.
def test_heldout_rules_first_answer_others_commits_and_status_labels():
    cr = ["review", at(100), "edison", "CHANGES_REQUESTED", "MEMBER", "User", True]
    fixed = pr(1, ev=[cr], cm=[[at(20), "alice", "NONE", "User", False]], lc=80) | {"cmt": [[at(80), at(80), "alice", False]]}
    assert who_acts_next(fixed, NOW)["since"] == at(80)
    merged_main = pr(2, ev=[cr], lc=99) | {"cmt": [[at(300), at(300), "alice", False], [at(99), at(99), "edison", True]]}
    assert who_acts_next(merged_main, NOW)["actor"] == "author"
    waiting = pr(3) | {"lb": ["S-waiting-on-author"], "lbe": [[at(50), "+", "S-waiting-on-author"]]}
    assert who_acts_next(waiting, NOW)["actor"] == "author"
    ready = pr(4, ci="FAILURE") | {"lb": ["ready to merge"], "lbe": [[at(30), "+", "ready to merge"]]}
    assert who_acts_next(ready, NOW)["actor"] == "maintainers"


# Third held-out check (30 PRs in 5 more repos): assigned reviewers, label hand-overs and conflict dates.
def test_heldout_rules_assigned_reviewers_label_handovers_and_conflict_dates():
    assigned = pr(1) | {"asg": ["llogiq"], "lb": ["S-waiting-on-review"],
                        "lbe": [[at(500), "+", "S-waiting-on-review"], [at(100), "-", "S-waiting-on-community-reviews"]]}
    w = who_acts_next(assigned, NOW)
    assert w["actor"] == "reviewers" and w["who"] == ["llogiq"] and w["since"] == at(100)
    conflict = pr(2, lc=3000) | {"mgs": "CONFLICTING", "lb": ["needs_rebase"], "lbe": [[at(20), "+", "needs_rebase"]]}
    assert who_acts_next(conflict, NOW)["since"] == at(20)


# Real finding (astronomer-cosmos, 2026-10-20): two maintainers show as CONTRIBUTOR but merge others' PRs; with GitHub's
# label alone they were counted as outsiders and the repo's outside merge rate read 83% instead of 63%.
def test_one_role_rule_people_who_merge_are_insiders_everywhere_and_bots_are_never_people():
    from stackvitals.community import analyze as community
    from stackvitals.core.actors import People
    from stackvitals.flow.peers import own_metrics
    closed = [pr(k, st="MERGED", cr=300 + k, mg=280 + k, au="newcomer", assoc="NONE",
                 ev=[rv(290 + k, "quietlead", assoc="CONTRIBUTOR"), ["merged", at(280 + k), "quietlead"]]) for k in range(1, 10)]
    closed += [pr(10, st="MERGED", cr=200, mg=190, au="quietlead", ev=[["merged", at(190), "quietlead"]]),
               pr(11, st="MERGED", cr=150, mg=140, au="bors", ev=[["merged", at(140), "bors"]]),  # a known bot typed as a user
               pr(12, st="CLOSED", cr=120, au="devin-ai-integration", assoc="NONE"),  # a coding agent typed as a user
               pr(13, st="CLOSED", cr=90, au="drive-by", assoc="NONE")]
    for p in closed:
        p["cl"] = p["mg"] or at(85)
    waiting = pr(20, cr=30, ev=[rv(20, "quietlead", "CHANGES_REQUESTED", assoc="CONTRIBUTOR")])
    out = analyze({"open": [waiting], "closed": closed}, NOW)
    q = {x["n"]: x for x in out["queue"]}[20]
    assert q["actor"] == "author" and "quietlead" in q["why"]
    assert out["groups"]["insider"]["merged"] == 1 and out["groups"]["outsider"]["merged"] == 9 and out["bots"]["closed"] == 2
    m = out["measures"]["flow.outsider_merge_rate"]
    assert m["value"] == 0.9 and m["n"] == 10 and m["low"] < m["value"] < m["high"] and m["as_of"] == at(0)
    assert community.insiders(closed, []) == {"quietlead"} and People(closed).role("bors") == "bot"
    assert own_metrics(closed, NOW, window_days=365)["outsider_merge_rate"] == 0.9


def test_identity_settings_shape_team_flow_and_the_summary_table(tmp_path):
    """Trust guard (P11 audit): [identity] reached only Delivery, so Team Flow and the summary tables ignored it."""
    from stackvitals.core.config import parse
    from stackvitals.core.workspace import run_job
    from stackvitals.flow.action import flow_step
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "GITHUB_EVENT_NAME": "schedule", "RUNNER_TEMP": str(tmp_path / "tmp")}
    prs = [node(1), node(2, "MERGED", updated=50, reviews=[(90, "bob")])]
    run_job(env, [("Team Flow", lambda ws: flow_step(ws, env, NOW, make_gql=lambda tok: Pages(prs)))], NOW,
            prepare=lambda ws: ws.cache.update(settings=parse('[identity]\nbots = ["bob"]\n[identity.aliases]\nalice = "al"\n')[0]))
    show = lambda path: subprocess.run(["git", "show", f"stackvitals-data:{path}"], cwd=bare, capture_output=True, text=True).stdout
    assert {json.loads(line)["author"] for line in show("summary/prs.jsonl").splitlines()} == {"al"}
    assert json.loads(show("docs/flow.json"))["stages"]["pickup"]["n"] == 0


def test_team_automation_is_off_until_turned_on_then_asks_once_and_labels_by_size_and_docs():
    from stackvitals.core.config import parse
    from stackvitals.flow.automate import DOCS_LABEL, plan
    assert plan([], [], parse("")[0]["automation"], {})[0] == []
    switches = parse("[automation]\nreview_requests = true\nsize_labels = true\ndocs_label = true\n")[0]["automation"]
    prs = [{"n": 1, "add": 600, "del": 0, "paths": ["src/a.py"], "lb": [], "draft": False, "au": "ann", "rq": []},
           {"n": 2, "add": 3, "del": 1, "paths": ["docs/guide.md"], "lb": [], "draft": False, "au": "bo", "rq": []}]
    queue = [{"n": 1, "suggested": [{"login": "cy"}]}]
    acts, state = plan(prs, queue, switches, {})
    assert {"kind": "review", "n": 1, "body": {"reviewers": ["cy"]}} in acts
    assert {"kind": "label", "n": 1, "body": {"labels": ["size/L"]}} in acts
    assert {"kind": "label", "n": 2, "body": {"labels": [DOCS_LABEL]}} in acts
    assert not [a for a in plan(prs, queue, switches, state)[0] if a["kind"] == "review"]
    off = parse("[automation]\nreview_requests = false\nsize_labels = false\ndocs_label = false\n")[0]["automation"]
    assert plan(prs, queue, off, {})[0] == []


def test_published_folder_habits_equal_what_the_cli_preflight_says_for_that_folder(tmp_path):
    # The app's planned-PR check reads these; they must be the CLI's own numbers, not a second copy of the rule.
    from stackvitals.flow.action import write_flow_outputs
    from stackvitals.flow.build import build
    from stackvitals.flow.preflight import gaps, norms, preflight

    def merged(n, paths, lines):
        return {**pr(n, st="MERGED", mg=24 * (n % 200 + 1)), "paths": paths, "add": lines, "del": 0}
    closed = [merged(n, ["src/app/a.ts"] + (["src/app/a.test.ts"] if n % 3 else []), 15 * n) for n in range(1, 16)]
    closed += [merged(n, ["lib/core/b.py", "CHANGELOG.md"], 40) for n in range(20, 32)]
    closed += [merged(n, ["tools/x.sh"], 5) for n in range(40, 44)]
    asks = {n: [["tests", "src/app"]] for n in range(1, 13)}
    write_flow_outputs(tmp_path, build({"open": [], "closed": closed}, {}, NOW, owner="o", asks=asks), "o/r")
    folders = json.loads((tmp_path / "docs" / "flow.json").read_text(encoding="utf-8"))["habits"]["folders"]
    assert "tools" not in {f["area"] for f in folders}
    for f in folders:
        paths = ["new.py" if f["area"] == "(root)" else f"{f['area']}/new.py"]
        cli = norms(closed, paths, NOW)
        assert {k: f[k] for k in ("merged_prs", "include", "size")} == {k: cli[k] for k in ("merged_prs", "include", "size")}
        assert gaps({"paths": paths, "add": 400}, {**f, "scope": f["area"]}) == gaps({"paths": paths, "add": 400}, cli)
        asked = preflight(closed, asks, paths, NOW)
        assert f["asks"] == (asked["asks"][:3] if asked["scope"] != "whole repo" else [])
