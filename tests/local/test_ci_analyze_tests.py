from datetime import timedelta

from ci_fake import T0, iso
from stackvitals.ci.analyze import analyze

NOW = T0 + timedelta(days=30)


def trun(rid, att, day, c, tree="t1", ev="push", pr=()):
    return {"t": "run", "id": rid, "att": att, "path": ".github/workflows/ci.yml", "wfn": "CI", "ev": ev, "br": "main",
            "tree": tree, "pr": list(pr), "c": c, "cr": iso(T0 + timedelta(days=day))}


def rep(art, rid, att, failed=(), flaky=(), total=50, slow=(), name="test-results"):
    return {"t": "tests", "run": rid, "att": att, "art": art, "name": name, "total": total, "skipped": 0,
            "failed": [[t, "fp" + t, f"{t} broke"] for t in failed], "flaky": list(flaky), "slow": [list(s) for s in slow]}


def tfind(result, tid):
    return next(t for t in result["tests"] if t["id"] == tid)


def test_a_test_retried_inside_one_job_counts_too():
    data = {"runs": [trun(1, 1, 20, "success")], "jobs": [], "tests": [rep(1, 1, 1, flaky=["t::b", "t::b2"])]}
    result = analyze(data, NOW, default_branch="main")
    assert tfind(result, "t::b")["flake_events"] == 1 and tfind(result, "t::b2")["flake_events"] == 1


def test_the_same_code_passing_in_another_run_marks_the_test_flaky():
    data = {"runs": [trun(1, 1, 10, "failure", tree="a"), trun(2, 1, 11, "success", tree="a")], "jobs": [],
            "tests": [rep(1, 1, 1, failed=["t::c"]), rep(2, 2, 1)]}
    assert tfind(analyze(data, NOW, default_branch="main"), "t::c")["flake_events"] == 1


def test_a_report_where_most_tests_fail_is_an_outage():
    many = [f"t::m{i}" for i in range(45)]
    data = {"runs": [trun(1, 1, 20, "failure"), trun(1, 2, 20, "success")], "jobs": [],
            "tests": [rep(1, 1, 1, failed=many), rep(2, 1, 2)]}
    result = analyze(data, NOW, default_branch="main")
    assert all(t["flake_events"] == 0 for t in result["tests"]) and result["test_outages"] == 1


def test_a_test_failing_every_run_is_broken():
    runs, tests = [], []
    for k in range(4):
        runs.append(trun(k, 1, 20 + k, "failure", tree=f"x{k}"))
        tests.append(rep(100 + k, k, 1, failed=["t::e"]))
    t = tfind(analyze({"runs": runs, "jobs": [], "tests": tests}, NOW, default_branch="main"), "t::e")
    assert t["state"] == "broken" and t["flake_events"] == 0


def test_slow_tests_and_slowdowns():
    runs, tests = [], []
    for k in range(20):
        day, ms = (5 + k, 4000) if k < 14 else (10 + k, 9000)
        runs.append(trun(k, 1, day, "success", tree=f"y{k}"))
        tests.append(rep(200 + k, k, 1, slow=[("t::slow", ms), ("t::quick", 50)]))
    result = analyze({"runs": runs, "jobs": [], "tests": tests}, NOW, default_branch="main")
    top = result["slow_tests"][0]
    assert top["id"] == "t::slow" and top["median_ms"] == 4000 and top["slower"]["after_ms"] == 9000
