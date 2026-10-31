"""Phase 13 M3 iteration: a job that flaked before is called safe to re-run only on strong evidence, since 10 of 22
labelled pull-request failures of such jobs were caused by the change (the masking rate)."""
from datetime import timedelta

from ci_fake import T0, iso
from stackvitals.ci.feedback import classify_run, render_comment, verdict_payload

PATH = ".github/workflows/ci.yml"


def _data(step):
    st = T0 + timedelta(days=29)
    run = {"t": "run", "id": 9, "att": 1, "path": PATH, "wfn": "CI", "ev": "pull_request", "br": "fix", "tree": "t9",
           "pr": [5], "c": "failure", "cr": iso(st)}
    job = {"t": "job", "run": 9, "att": 1, "id": 91, "n": "build", "c": "failure", "cr": iso(st), "st": iso(st),
           "en": iso(st + timedelta(seconds=60)), "lb": ["ubuntu-latest"],
           "steps": [[1, "Set up job", "success"], [2, step, "failure"]]}
    return {"runs": [run], "jobs": [job], "tests": []}


def _result(flakes, steps):
    return {"jobs": [{"workflow": PATH, "job": "build", "state": "flaky", "flake_events": flakes, "runs": 60,
                      "last_flake": "2026-10-20T00:00:00Z", "flake_steps": steps}], "tests": []}


def test_strong_evidence_in_the_same_step_reads_known_flaky_but_still_needs_a_re_run():
    log = "##[group]Run npm ci\nnpm ERR! code ECONNRESET\n##[error]Process completed with exit code 1."
    items = classify_run(_data("Download deps"), _result(3, ["Download deps"]), 9, logs={91: log})
    assert [i["verdict"] for i in items] == ["known flaky"] and "re-run it" in items[0]["detail"]
    assert verdict_payload(items, green=False)["conclusion"] == "failure"


def test_a_failure_in_another_step_is_not_the_known_flake():
    items = classify_run(_data("Run tests"), _result(5, ["Download deps"]), 9)
    assert [i["verdict"] for i in items] == ["flaked before"]
    assert "likely a flake" not in items[0]["detail"] and "Run tests" in items[0]["detail"]
    assert verdict_payload(items, green=False)["conclusion"] == "failure"


def test_one_or_two_flakes_are_too_few_to_call_a_failure_safe():
    items = classify_run(_data("Download deps"), _result(2, ["Download deps"]), 9)
    assert [i["verdict"] for i in items] == ["flaked before"]
    assert "check whether this change caused it" in items[0]["detail"]
    assert "need a look" in render_comment(items, "o/r") or "None of these" in render_comment(items, "o/r")


def test_the_detector_lists_the_steps_a_job_flaked_in():
    from stackvitals.ci.analyze import analyze
    st = T0 + timedelta(days=20)
    runs = [{"t": "run", "id": 1, "att": a, "path": PATH, "wfn": "CI", "ev": "push", "br": "main", "tree": "t1", "pr": [],
             "c": c, "cr": iso(st)} for a, c in ((1, "failure"), (2, "success"))]
    jobs = [{"t": "job", "run": 1, "att": a, "id": 10 + a, "n": "build", "c": c, "cr": iso(st), "st": iso(st),
             "en": iso(st + timedelta(seconds=60)), "lb": [], "steps": [[1, "Download deps", c]]}
            for a, c in ((1, "failure"), (2, "success"))]
    out = analyze({"runs": runs, "jobs": jobs, "tests": []}, T0 + timedelta(days=30), default_branch="main")
    assert next(j for j in out["jobs"] if j["job"] == "build")["flake_steps"] == ["Download deps"]
