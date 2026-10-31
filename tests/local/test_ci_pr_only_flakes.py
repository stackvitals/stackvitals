"""A test or job whose recent flakes all came from one pull request is that change's, not a known flake: a race the
pull request added fails now and then and passes on a re-run (Reddit feedback, 2026-10-31)."""
from datetime import timedelta

from ci_fake import T0, iso
from stackvitals.ci.analyze import analyze
from stackvitals.ci.feedback import classify_run

NOW = T0 + timedelta(days=30)


def trun(rid, att, day, c, tree="t1", ev="pull_request", br="fix", pr=(5,)):
    return {"t": "run", "id": rid, "att": att, "path": ".github/workflows/ci.yml", "wfn": "CI", "ev": ev, "br": br,
            "tree": tree, "pr": list(pr), "c": c, "cr": iso(T0 + timedelta(days=day))}


def rep(rid, att, failed=(), msg="boom"):
    return {"t": "tests", "run": rid, "att": att, "art": rid * 10 + att, "name": "test-results", "total": 50, "skipped": 0,
            "failed": [[t, "fp" + t, msg] for t in failed], "flaky": [], "slow": []}


def job(jid, rid, att, c, step="Run tests"):
    st = T0 + timedelta(days=20, seconds=jid)
    return {"t": "job", "run": rid, "att": att, "id": jid, "n": "test", "c": c, "cr": iso(st), "st": iso(st),
            "en": iso(st + timedelta(seconds=60)), "lb": ["ubuntu-latest"], "steps": [[3, step, c]]}


def tfind(result, tid):
    return next(t for t in result["tests"] if t["id"] == tid)


def test_history_names_the_one_pull_request_a_test_flaked_on():
    # Failed then passed on a re-run, twice, both on pull request 5; main ran it clean.
    data = {"runs": [trun(1, 1, 20, "failure"), trun(1, 2, 20, "success"), trun(2, 1, 21, "failure", tree="t2"),
                     trun(2, 2, 21, "success", tree="t2"), trun(3, 1, 19, "success", ev="push", br="main", pr=())],
            "jobs": [], "tests": [rep(1, 1, ["t::race"]), rep(1, 2), rep(2, 1, ["t::race"]), rep(2, 2), rep(3, 1)]}
    assert tfind(analyze(data, NOW, default_branch="main"), "t::race")["only_pr"] == 5


def test_a_test_that_flaked_on_two_pull_requests_or_on_main_has_no_single_one():
    two = {"runs": [trun(1, 1, 20, "failure"), trun(1, 2, 20, "success"),
                    trun(2, 1, 21, "failure", tree="t2", pr=(6,)), trun(2, 2, 21, "success", tree="t2", pr=(6,))],
           "jobs": [], "tests": [rep(1, 1, ["t::x"]), rep(1, 2), rep(2, 1, ["t::x"]), rep(2, 2)]}
    assert tfind(analyze(two, NOW, default_branch="main"), "t::x")["only_pr"] is None
    main = {"runs": [trun(1, 1, 20, "failure"), trun(1, 2, 20, "success"),
                     trun(2, 1, 21, "failure", tree="t2", ev="push", br="main", pr=()),
                     trun(2, 2, 21, "success", tree="t2", ev="push", br="main", pr=())],
            "jobs": [], "tests": [rep(1, 1, ["t::x"]), rep(1, 2), rep(2, 1, ["t::x"]), rep(2, 2)]}
    assert tfind(analyze(main, NOW, default_branch="main"), "t::x")["only_pr"] is None


def test_history_names_the_one_pull_request_a_job_flaked_on():
    data = {"runs": [trun(1, 1, 20, "failure"), trun(1, 2, 20, "success")],
            "jobs": [job(11, 1, 1, "failure"), job(12, 1, 2, "success")], "tests": []}
    j = next(j for j in analyze(data, NOW, default_branch="main")["jobs"] if j["job"] == "test")
    assert j["only_pr"] == 5 and j["flake_events"] == 1


# Pull request 5 fails again; history says how often each failure flaked, and where.
FAILING = {"runs": [trun(9, 1, 29, "failure")],
           "jobs": [job(91, 9, 1, "failure", step="Run lint") | {"n": "lint"}],
           "tests": [rep(9, 1, ["t::race"], msg="TimeoutError: waited 5s")]}
NET = "##[group]Run lint\nnpm ERR! getaddrinfo ENOTFOUND registry.npmjs.org\n##[error]Process completed with exit code 1."


def history(only_pr):
    return {"jobs": [{"workflow": ".github/workflows/ci.yml", "job": "lint", "state": "flaky", "flake_events": 4, "runs": 50,
                      "last_flake": "2026-10-28T00:00:00Z", "flake_steps": ["Run lint"], "only_pr": only_pr}],
            "tests": [{"id": "t::race", "state": "flaky", "flake_events": 4, "runs": 50, "last_flake": "2026-10-28T00:00:00Z",
                       "only_pr": only_pr}]}


def test_flakes_only_on_this_pull_request_read_new_not_likely_flaky():
    items = {i["name"]: i for i in classify_run(FAILING, history(5), 9, logs={91: NET})}
    for name in ("t::race", "CI / lint"):
        assert items[name]["verdict"] == "new", name
        assert "only on this pull request" in items[name]["detail"]


def test_flakes_on_another_pull_request_still_read_likely_flaky():
    items = {i["name"]: i for i in classify_run(FAILING, history(7), 9, logs={91: NET})}
    assert items["t::race"]["verdict"] == "known flaky" and items["CI / lint"]["verdict"] == "known flaky"


def test_history_from_before_this_rule_reads_as_before():
    old = history(None)
    for part in old.values():
        for e in part:
            del e["only_pr"]
    items = {i["name"]: i for i in classify_run(FAILING, old, 9, logs={91: NET})}
    assert items["t::race"]["verdict"] == "known flaky"


def test_one_earlier_flake_on_this_pull_request_stops_maybe_flaky():
    # A timeout once read "maybe flaky: re-run once to tell"; after this pull request already flaked, it is the change.
    result = {"jobs": [], "tests": [{"id": "t::race", "state": "suspect", "flake_events": 1, "runs": 20, "only_pr": 5}]}
    items = {i["name"]: i for i in classify_run({**FAILING, "jobs": []}, result, 9)}
    assert items["t::race"]["verdict"] == "new" and "only on this pull request" in items["t::race"]["detail"]


def test_history_counts_each_tests_runs_and_failures_on_main():
    runs = [trun(k, 1, 10 + k, "success", tree=f"m{k}", ev="push", br="main", pr=()) for k in range(1, 5)]
    tests = [rep(k, 1, ["t::shaky"] if k == 4 else []) for k in range(1, 5)]
    runs.append(trun(9, 1, 20, "failure", tree="p"))
    tests.append(rep(9, 1, ["t::shaky"]))
    t = tfind(analyze({"runs": runs, "jobs": [], "tests": tests}, NOW, default_branch="main"), "t::shaky")
    assert (t["main_runs"], t["main_failures"]) == (4, 1)


def test_history_counts_each_jobs_runs_and_failures_on_main():
    runs = [trun(k, 1, 10 + k, "success", tree=f"m{k}", ev="push", br="main", pr=()) for k in range(1, 4)]
    jobs = [job(100 + k, k, 1, "success") for k in range(1, 4)] + [job(200, 9, 1, "failure")]
    runs.append(trun(9, 1, 20, "failure", tree="p"))
    j = next(j for j in analyze({"runs": runs, "jobs": jobs, "tests": []}, NOW, default_branch="main")["jobs"] if j["job"] == "test")
    assert (j["main_runs"], j["main_failures"]) == (3, 0)


STABLE = {"jobs": [], "tests": [{"id": "t::race", "state": "ok", "flake_events": 0, "runs": 40,
                                 "main_runs": 30, "main_failures": 0}]}


def test_a_first_timeout_on_a_test_stable_on_main_says_so_and_is_remembered():
    items = classify_run({**FAILING, "jobs": []}, STABLE, 9)
    item = items[0]
    # Still "maybe flaky": on labelled data, never-flaked timeouts were mostly real flakes; the note asks for a look.
    assert item["verdict"] == "maybe flaky" and item.get("stable_on_main") == 30
    assert "passed all 30 runs on the default branch" in item["detail"]
    from stackvitals.ci.feedback import blamed_sha, render_comment
    assert blamed_sha(render_comment(items, "o/r", "abc1234")) == "abc1234"


def test_few_main_runs_or_a_main_failure_add_no_note():
    for main_runs, main_failures in ((5, 0), (30, 1)):
        result = {"jobs": [], "tests": [{**STABLE["tests"][0], "main_runs": main_runs, "main_failures": main_failures}]}
        item = classify_run({**FAILING, "jobs": []}, result, 9)[0]
        assert item["verdict"] == "maybe flaky" and "stable_on_main" not in item
        from stackvitals.ci.feedback import blamed_sha, render_comment
        assert blamed_sha(render_comment([item], "o/r", "abc1234")) is None


def test_a_green_re_run_of_a_suspect_commit_warns_and_any_other_green_just_says_passing():
    from stackvitals.ci.feedback import blamed_sha, green_note, render_comment
    sha = "abc1234"
    suspect = render_comment(classify_run({**FAILING, "jobs": []}, STABLE, 9), "o/r", sha)
    warned = green_note(suspect, sha)
    assert "a re-run turned this green" in warned and "before merging" in warned
    assert blamed_sha(warned) == sha  # a later green run on the same commit keeps the warning
    assert "CI is passing now" in green_note(suspect, "def5678")  # new code was pushed: nothing to warn about
    flaky_only = render_comment(classify_run({**FAILING, "jobs": []}, history(7), 9), "o/r", sha)
    assert "CI is passing now" in green_note(flaky_only, sha)


def test_a_likely_flake_shows_how_often_it_fails_on_main():
    # A change can make a flaky test fail far more often; the main rate beside it lets a reviewer compare.
    result = history(7)
    result["tests"][0] |= {"main_runs": 40, "main_failures": 2}
    item = {i["name"]: i for i in classify_run(FAILING, result, 9, logs={91: NET})}["t::race"]
    assert item["verdict"] == "known flaky" and "on the default branch it failed 2 of 40 runs (5%)" in item["detail"]


# A flaky check the change made worse: it fails on most of this pull request's runs, far above its rate on main.
def worse(runs_on_pr):
    """Pull request 5's runs before the failing run 9: (run id, test failed, lint failed) for each."""
    data = {"runs": [trun(9, 1, 29, "failure")], "jobs": [job(91, 9, 1, "failure", step="Run lint") | {"n": "lint"}],
            "tests": [rep(9, 1, ["t::race"], msg="TimeoutError: waited 5s")]}
    for rid, test_failed, lint_failed in runs_on_pr:
        data["runs"].append(trun(rid, 1, 20 + rid, "failure" if test_failed or lint_failed else "success", tree=f"p{rid}"))
        data["tests"].append(rep(rid, 1, ["t::race"] if test_failed else []))
        data["jobs"].append(job(rid * 10, rid, 1, "failure" if lint_failed else "success", step="Run lint") | {"n": "lint"})
    return data


def known(main_failures, main_runs=40):
    result = history(7)
    result["tests"][0] |= {"suite": "test-results", "main_runs": main_runs, "main_failures": main_failures}
    result["jobs"][0] |= {"main_runs": main_runs, "main_failures": main_failures}
    return result


def test_a_flaky_check_failing_far_more_on_this_pull_request_reads_new():
    items = {i["name"]: i for i in classify_run(worse([(7, True, True), (8, False, False)]), known(2), 9, logs={91: NET})}
    for name in ("t::race", "CI / lint"):
        assert items[name]["verdict"] == "new", name
        assert "failed 2 of 3 runs on this pull request" in items[name]["detail"]
        assert "2 of 40 (5%) on the default branch" in items[name]["detail"]


def test_one_failure_on_this_pull_request_is_too_few_to_tell():
    items = {i["name"]: i for i in classify_run(worse([(8, False, False)]), known(2), 9, logs={91: NET})}
    assert items["t::race"]["verdict"] == "known flaky" and items["CI / lint"]["verdict"] == "known flaky"


def test_a_check_that_fails_often_on_main_too_stays_likely_flaky():
    items = {i["name"]: i for i in classify_run(worse([(7, True, True), (8, False, False)]), known(16), 9, logs={91: NET})}
    assert items["t::race"]["verdict"] == "known flaky" and items["CI / lint"]["verdict"] == "known flaky"


def test_too_few_main_runs_give_no_rate_to_compare():
    items = {i["name"]: i for i in classify_run(worse([(7, True, True), (8, True, True)]), known(0, main_runs=5), 9,
                                                logs={91: NET})}
    assert items["t::race"]["verdict"] == "known flaky"
