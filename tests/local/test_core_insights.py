"""The first cross-module insight: how long merged PRs sat with failing checks on their newest commit, joining CI Health's
runs to Team Flow's PRs, with every wait traced to the runs that started and ended it."""
from datetime import datetime, timedelta, timezone

from stackvitals.core.insights import red_ci, red_intervals
from stackvitals.core.joins import coverage_start, runs_by_pr

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
CI = ".github/workflows/ci.yml"


def at(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(rid, sha, cr, c, att=1, wf=1, path=CI, name="CI", pr=(), ho="amy", br="fix", ev="pull_request", up=None):
    return {"t": "run", "id": rid, "att": att, "wf": wf, "wfn": name, "path": path, "ev": ev, "br": br, "sha": sha,
            "tree": sha, "pr": list(pr), "ho": ho, "c": c, "cr": at(cr), "st": at(cr), "up": at(up if up is not None else cr)}


def job(jid, rid, name, c, en, att=1, start=None):
    return {"t": "job", "run": rid, "att": att, "id": jid, "n": name, "c": c, "cr": at(en + 0.1), "st": at(start or en + 0.05),
            "en": at(en), "lb": ["ubuntu-latest"], "steps": []}


def pr(n, cr, mg=None, cl=None, au="amy", ho="amy", head="fix", ev=(), draft=False, kind="User"):
    closed = cl if cl is not None else mg
    return {"t": "pr", "n": n, "ti": f"PR {n}", "draft": draft, "st": "MERGED" if mg is not None else ("CLOSED" if cl is not None else "OPEN"),
            "cr": at(cr), "up": at(1), "mg": at(mg) if mg is not None else None, "cl": at(closed) if closed is not None else None,
            "add": 10, "del": 1, "files": 1, "au": au, "at": kind, "as": "NONE", "head": head, "ho": ho, "rq": [], "ev": list(ev),
            "cm": [], "ci": "SUCCESS", "lc": at(cr)}


def test_runs_join_prs_by_number_or_by_head_owner_and_branch_inside_the_pr_lifetime():
    prs = [pr(1, 100, mg=90, ho="Amy", head="fix"), pr(2, 50, mg=40, ho="amy", head="fix"), pr(3, 30, ho="bob", head="docs")]
    runs = [run(10, "a", 99, "failure"),  # amy:fix while PR 1 was open
            run(11, "b", 45, "success"),  # amy:fix again, now PR 2 (the branch was reused)
            run(12, "c", 70, "success"),  # amy:fix between the two PRs: no PR open
            run(13, "d", 20, "success", ho="bob", br="docs"),
            run(14, "e", 25, "success", pr=[3], ho=None, br="docs"),  # a same-repo PR: GitHub gives the number
            run(15, "f", 25, "success", ev="push", br="main", ho=None)]
    found = runs_by_pr(runs, prs)
    assert sorted(found) == [1, 2, 3]
    assert [r["id"] for r in found[1]] == [10] and [r["id"] for r in found[2]] == [11]
    assert sorted(r["id"] for r in found[3]) == [13, 14]


def test_coverage_starts_at_the_oldest_unbroken_scanned_day():
    state = {"scanned": {"2026-10-20": "done", "2026-10-19": "partial", "2026-10-18": "done", "2026-10-16": "done"}}
    assert coverage_start(state, []) == "2026-10-18T00:00:00Z"
    assert coverage_start({}, [run(1, "a", 30, "success"), run(2, "b", 10, "success")]) == at(30)
    assert coverage_start({}, []) is None


def test_a_push_ends_a_red_wait_and_a_passing_rerun_ends_one_on_the_same_code():
    p = pr(1, 100, mg=90)
    runs = [run(10, "s1", 99, "failure"), run(11, "s2", 95, "success")]
    jobs = [job(100, 10, "tests", "failure", 98.5), job(110, 11, "tests", "success", 94.5)]
    waits = red_intervals(p, runs, jobs, {}, at(0))
    assert len(waits) == 1
    w = waits[0]
    assert (w["from"], w["to"], w["ended_by"], w["hours"]) == (at(98.5), at(95), "push", 3.5)
    assert w["failed"] == {"run": 10, "attempt": 1, "workflow": "CI", "jobs": ["tests"]} and w["cleared"] == {"sha": "s2", "run": 11}
    p2 = pr(2, 80, mg=70)
    runs = [run(20, "t1", 79, "failure"), run(20, "t1", 79, "success", att=2)]
    jobs = [job(200, 20, "e2e", "failure", 78), job(201, 20, "unit", "success", 78.2),
            job(202, 20, "e2e", "success", 76, att=2), job(203, 20, "unit", "success", 76.5, att=2)]
    waits = red_intervals(p2, runs, jobs, {}, at(0))
    assert [(w["ended_by"], w["hours"], w["failed"]["jobs"], w["cleared"]) for w in waits] == \
        [("rerun", 2.0, ["e2e"], {"run": 20, "attempt": 2})]


def test_what_is_not_red_cancelled_runs_approvals_pr_text_checks_and_draft_time():
    p = pr(3, 60, mg=50)
    runs = [run(30, "u1", 59, "failure", path=".github/workflows/title.yml", wf=2, name="Title"),
            run(31, "u1", 59, "cancelled", wf=3, name="Docs"), run(32, "u1", 59, "action_required", wf=4, name="Fork")]
    jobs = [job(300, 30, "check-title", "failure", 58.5), job(310, 31, "build", "cancelled", 58.4)]
    assert red_intervals(p, runs, jobs, {".github/workflows/title.yml": {"check-title"}}, at(0)) == []
    # A draft's failing checks are the author's work in progress: only the time after it asked for review counts.
    d = pr(4, 50, mg=40, draft=False, ev=[["ready", at(45)]])
    runs = [run(40, "v1", 49, "failure"), run(41, "v2", 44, "success")]
    jobs = [job(400, 40, "tests", "failure", 48), job(410, 41, "tests", "success", 43)]
    w = red_intervals(d, runs, jobs, {}, at(0))
    assert [(x["from"], x["to"], x["hours"]) for x in w] == [(at(45), at(44), 1.0)]


def test_red_until_every_failing_workflow_passes_or_the_pr_merges_red():
    p = pr(6, 22, mg=10)
    runs = [run(60, "w1", 21, "failure", wf=1, name="Tests"), run(61, "w1", 21, "success", wf=2, name="Lint"),
            run(62, "w2", 18, "success", wf=1, name="Tests"), run(63, "w2", 18, "failure", wf=2, name="Lint")]
    jobs = [job(600, 60, "py3.12", "failure", 20), job(610, 61, "ruff", "success", 19.5),
            job(620, 62, "py3.12", "success", 17), job(630, 63, "ruff", "failure", 16)]
    waits = red_intervals(p, runs, jobs, {}, at(0))
    # Red from the first failure until the push; red again when Lint fails on the new commit, until the merge.
    assert [(w["from"], w["to"], w["ended_by"]) for w in waits] == [(at(20), at(18), "push"), (at(16), at(10), "merged")]
    assert waits[1]["failed"]["workflow"] == "Lint"


def test_the_insight_counts_people_prs_inside_coverage_with_n_ranges_and_evidence():
    prs = [pr(1, 100, mg=90), pr(2, 80, mg=70, head="b2"), pr(7, 300, mg=60, head="old"),  # 7 opened before coverage
           pr(8, 40, mg=35, head="c8"), pr(9, 30, mg=25, au="dependabot[bot]", kind="Bot", head="dep"),
           pr(11, 20, mg=15, head="nochecks"), pr(12, 12, head="open")]
    runs = [run(10, "s1", 99, "failure"), run(11, "s2", 95, "success"),
            run(20, "t1", 79, "failure", br="b2"), run(20, "t1", 79, "success", att=2, br="b2"),
            run(70, "o1", 61, "success", br="old"), run(80, "c1", 39, "success", br="c8"),
            run(90, "d1", 29, "failure", br="dep"), run(120, "x1", 11, "failure", br="open")]
    jobs = [job(100, 10, "tests", "failure", 98.5), job(110, 11, "tests", "success", 94.5),
            job(200, 20, "e2e", "failure", 78), job(202, 20, "e2e", "success", 76, att=2),
            job(700, 70, "tests", "success", 60.5), job(800, 80, "tests", "success", 38),
            job(900, 90, "tests", "failure", 28), job(1200, 120, "tests", "failure", 10)]
    out = red_ci(prs, {"runs": runs, "jobs": jobs, "tests": []}, NOW, since=at(200))
    # People's merged PRs opened inside the CI history that ran checks: 1, 2 and 8 (7 is too old, 9 a bot, 11 ran none).
    assert out["prs"] == 3 and out["without_checks"] == 1 and out["red_prs"] == 2
    share = out["measures"]["insight.red_ci_share"]
    # Three PRs are too few for a share: the counts are given, the measure says so.
    assert share["value"] is None and share["n"] == 3 and share["note"] == "not enough data (n=3, needs 10)"
    hours = out["measures"]["insight.red_ci_hours"]
    assert hours["n"] == 2 and out["red_hours_total"] == 5.5 and out["rerun_hours_total"] == 2.0
    # Each flaky job keeps the run attempts whose failure started a wait, as evidence for its finding.
    assert out["rerun_jobs"] == [{"workflow": "CI", "job": "e2e", "hours": 2.0, "prs": 1, "runs": [[20, 1]]}]
    assert [e["pr"] for e in out["top"]] == [1, 2] and out["top"][0]["waits"][0]["failed"]["run"] == 10
    assert out["since"] == at(200) and out["definition"].startswith("Time a ready pull request")
    # The open PR is red right now and listed, but is not part of the merged numbers.
    assert out["open_red"] == [{"pr": 12, "since": at(10), "hours": 10.0}]


def test_a_summary_job_that_only_reports_the_others_is_not_blamed():
    # pip's and pytest's "check" job waits for every other job and fails when any did (real finding, 2026-10-20).
    p = pr(13, 30, mg=20)
    runs = [run(130, "z1", 29, "failure"), run(130, "z1", 29, "success", att=2)]
    jobs = [job(1300, 130, "tests / windows", "failure", 28, start=28.6), job(1301, 130, "check", "failure", 27.9, start=27.95),
            job(1302, 130, "tests / windows", "success", 26, att=2, start=26.5), job(1303, 130, "check", "success", 25.9, att=2, start=25.95)]
    waits = red_intervals(p, runs, jobs, {}, at(0))
    assert waits[0]["failed"]["jobs"] == ["tests / windows"]
    # Alone, a failing job is always named, whatever its timing.
    jobs = [job(1300, 130, "check", "failure", 28), job(1302, 130, "check", "success", 26, att=2)]
    assert red_intervals(p, runs, jobs, {}, at(0))[0]["failed"]["jobs"] == ["check"]


def test_red_starts_when_the_first_job_fails_not_when_the_run_ends():
    # Real finding (pip #14324, 2026-10-20): GitHub shows the PR red as soon as one job fails; a long run ends later.
    p = pr(14, 30, mg=10)
    runs = [run(140, "q1", 29, "failure"), run(141, "q2", 27, "success")]
    jobs = [job(1400, 140, "tests / windows", "failure", 28.5), job(1401, 140, "tests / linux", "success", 26.5),
            job(1410, 141, "tests / windows", "success", 25)]
    waits = red_intervals(p, runs, jobs, {}, at(0))
    # Red from the first failure (28.5 h ago) until the push at 27 h ago, although the run only ended 26.5 h ago.
    assert [(w["from"], w["to"], w["ended_by"]) for w in waits] == [(at(28.5), at(27), "push")]


def test_time_spent_back_in_draft_is_not_red_time():
    # Real finding (guidellm #1246, 2026-10-20): turned into a draft 22 s after opening, red the whole time it stayed one.
    p = pr(15, 40, mg=10, ev=[["draft", at(39.9)], ["ready", at(20)]])
    runs = [run(150, "r1", 39, "failure"), run(151, "r2", 25, "success")]
    jobs = [job(1500, 150, "tests", "failure", 38), job(1510, 151, "tests", "success", 24)]
    assert red_intervals(p, runs, jobs, {}, at(0)) == []
    # Ready, then a draft for a while, then ready again: only the ready parts of a wait count.
    p = pr(16, 40, mg=10, ev=[["draft", at(30)], ["ready", at(26)]])
    runs = [run(160, "k1", 39, "failure"), run(161, "k2", 22, "success")]
    jobs = [job(1600, 160, "tests", "failure", 38), job(1610, 161, "tests", "success", 21)]
    waits = red_intervals(p, runs, jobs, {}, at(0))
    assert [(w["from"], w["to"], w["hours"]) for w in waits] == [(at(38), at(22), 12.0)]


def test_hours_lost_to_re_runs_are_charged_to_the_flaky_tests_that_failed():
    p = pr(17, 80, mg=70)
    runs = [run(170, "t1", 79, "failure"), run(170, "t1", 79, "success", att=2)]
    jobs = [job(1700, 170, "e2e", "failure", 78, start=78.5), job(1702, 170, "e2e", "success", 76, att=2, start=77)]
    tests = [{"t": "tests", "run": 170, "att": 1, "art": 1, "name": "junit", "total": 9, "skipped": 0, "flaky": [], "slow": [],
              "failed": [["web::login", "k1", "boom", "c1", "src/login.ts", "Error", 10],
                         ["web::cart", "k2", "boom", "c1", "src/login.ts", "Error", 10]]}]
    out = red_ci([p], {"runs": runs, "jobs": jobs, "tests": tests}, NOW, since=at(200))
    assert out["rerun_hours_total"] == 2.0
    assert out["rerun_tests"] == [{"test": "web::cart", "hours": 1.0, "prs": 1, "pr_list": [17], "runs": [[170, 1]]},
                                  {"test": "web::login", "hours": 1.0, "prs": 1, "pr_list": [17], "runs": [[170, 1]]}]
