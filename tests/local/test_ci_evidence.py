from datetime import timedelta

from ci_fake import T0, iso
from stackvitals.ci.analyze import analyze
from stackvitals.ci.report import render_html

NOW = T0 + timedelta(days=2)


def r(rid, att, c, tree="t1"):
    return {"t": "run", "id": rid, "att": att, "path": ".github/workflows/ci.yml", "wfn": "CI", "ev": "push", "br": "main",
            "sha": "s", "tree": tree, "pr": [], "c": c, "cr": iso(T0), "st": iso(T0), "up": iso(T0 + timedelta(minutes=5))}


def j(jid, rid, att, c):
    st = T0 + timedelta(minutes=10 * att)
    return {"t": "job", "run": rid, "att": att, "id": jid, "n": "test", "c": c, "cr": iso(st), "st": iso(st),
            "en": iso(st + timedelta(minutes=2)), "lb": ["ubuntu-latest"], "steps": [[3, "Run tests", c, iso(st), iso(st)]]}


def test_each_flake_keeps_the_runs_that_prove_it():
    data = {"runs": [r(1, 1, "failure"), r(1, 2, "success")], "jobs": [j(11, 1, 1, "failure"), j(12, 1, 2, "success")],
            "tests": [{"t": "tests", "run": 1, "att": 1, "art": 5, "name": "test-results", "total": 2, "skipped": 0,
                       "failed": [["t::a", "fp", "boom"]], "flaky": [], "slow": []},
                      {"t": "tests", "run": 1, "att": 2, "art": 6, "name": "test-results", "total": 2, "skipped": 0,
                       "failed": [], "flaky": [], "slow": []}]}
    result = analyze(data, NOW, default_branch="main")
    assert result["jobs"][0]["evidence"] == [{"run": 1, "att": 1, "job": 11, "kind": "retry"}]
    assert result["tests"][0]["evidence"] == [{"run": 1, "att": 1, "kind": "retry"}]
    assert "https://github.com/o/r/actions/runs/1/attempts/1" in render_html(result, "o/r")


def test_a_run_that_needed_two_reruns_is_one_test_flake_like_one_job_flake():
    data = {"runs": [r(1, 1, "failure"), r(1, 2, "failure"), r(1, 3, "success")],
            "jobs": [j(11, 1, 1, "failure"), j(12, 1, 2, "failure"), j(13, 1, 3, "success")],
            "tests": [{"t": "tests", "run": 1, "att": a, "art": 5 + a, "name": "test-results", "total": 2, "skipped": 0,
                       "failed": [["t::a", "fp", "boom"]] if a < 3 else [], "flaky": [], "slow": []} for a in (1, 2, 3)]}
    result = analyze(data, NOW, default_branch="main")
    assert result["jobs"][0]["flake_events"] == 1 and result["tests"][0]["flake_events"] == 1
