import json
from datetime import timedelta

import httpx
from ci_fake import T0, iso
from stackvitals.ci.api import ActionsAPI
from stackvitals.ci.feedback import classify_run, find_pr, render_comment, upsert_comment

NOW = T0 + timedelta(days=30)


def frun(rid, att, day, c, ev="pull_request", pr=(5,)):
    return {"t": "run", "id": rid, "att": att, "path": ".github/workflows/ci.yml", "wfn": "CI", "ev": ev, "br": "fix",
            "tree": f"t{rid}", "pr": list(pr), "c": c, "cr": iso(T0 + timedelta(days=day))}


def fjb(jid, rid, att, name, c, start=0, secs=60):
    st = T0 + timedelta(days=29, seconds=start)
    return {"t": "job", "run": rid, "att": att, "id": jid, "n": name, "c": c, "cr": iso(st), "st": iso(st),
            "en": iso(st + timedelta(seconds=secs)), "lb": ["ubuntu-latest"], "steps": []}


FB_DATA = {"runs": [frun(9, 1, 29, "failure")],
        "jobs": [fjb(91, 9, 1, "test", "failure"), fjb(92, 9, 1, "lint", "failure") | {"steps": [[2, "Run lint", "failure"]]},
                 fjb(93, 9, 1, "all checks", "failure", start=200, secs=3)],
        "tests": [{"t": "tests", "run": 9, "att": 1, "art": 1, "name": "test-results", "total": 40, "skipped": 0,
                   "failed": [["t::flaky_one", "fp1", "TimeoutError <3s>"], ["t::new_one", "fp2", "assert <a> == 2"],
                              ["t::broken_one", "fp3", "ImportError"]], "flaky": [], "slow": []}]}
# A network error in the job's log: the sign a known flake needs (pre-registered 2026-10-28).
NET = "##[group]Run lint\nnpm ERR! getaddrinfo ENOTFOUND registry.npmjs.org\n##[error]Process completed with exit code 1."
FB_RESULT = {"jobs": [{"workflow": ".github/workflows/ci.yml", "job": "test", "state": "ok", "flake_events": 0, "runs": 50},
                   {"workflow": ".github/workflows/ci.yml", "job": "lint", "state": "flaky", "flake_events": 4, "runs": 50,
                    "last_flake": "2026-10-20T00:00:00Z", "flake_steps": ["Run lint"]}],
          "tests": [{"id": "t::flaky_one", "state": "flaky", "flake_events": 6, "runs": 80, "last_flake": "2026-10-28T00:00:00Z"},
                    {"id": "t::broken_one", "state": "broken", "flake_events": 0, "runs": 80, "last_flake": None}]}


def test_each_failure_is_called_known_flaky_already_failing_or_new():
    items = classify_run(FB_DATA, FB_RESULT, 9, logs={92: NET})
    verdicts = {(i["kind"], i["name"]): i["verdict"] for i in items}
    assert verdicts == {("test", "t::flaky_one"): "known flaky", ("test", "t::new_one"): "new",
                        ("test", "t::broken_one"): "already failing", ("job", "CI / lint"): "known flaky"}
    # The gatekeeper failed only because the others failed, so it is not listed.
    assert ("job", "CI / all checks") not in verdicts
    # The job that holds the failing tests is summed up by its tests, not listed again as new.
    assert ("job", "CI / test") not in verdicts


def fake_github():
    state = {"comments": [], "posted": 0, "edited": 0}

    def handler(request):
        path = request.url.path
        if path == "/repos/o/r/pulls" and request.method == "GET":
            assert request.url.params["head"] == "forker:fix"
            return httpx.Response(200, json=[{"number": 5}])
        if path == "/repos/o/r/issues/5/comments" and request.method == "GET":
            return httpx.Response(200, json=state["comments"])
        if path == "/repos/o/r/issues/5/comments" and request.method == "POST":
            state["posted"] += 1
            state["comments"].append({"id": 77, "body": json.loads(request.content)["body"]})
            return httpx.Response(201, json=state["comments"][-1])
        if path == "/repos/o/r/issues/comments/77" and request.method == "PATCH":
            state["edited"] += 1
            state["comments"][0]["body"] = json.loads(request.content)["body"]
            return httpx.Response(200, json=state["comments"][0])
        return httpx.Response(404, json={})
    api = ActionsAPI("tok", "o/r", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    return api, state


def test_a_flaky_job_whose_test_step_failed_on_new_tests_is_not_called_safe_to_rerun():
    # Sandbox finding: job "test" had flaked before, but this time it failed because test_add broke.
    data = {"runs": [frun(9, 1, 29, "failure")],
            "jobs": [fjb(91, 9, 1, "test", "failure") | {"steps": [[1, "Set up job", "success", None, None],
                                                                  [4, "Run python -m pytest --junitxml=out.xml", "failure", None, None]]},
                     fjb(92, 9, 1, "lint", "failure") | {"steps": [[3, "Run ruff check", "failure", None, None]]}],
            "tests": [{"t": "tests", "run": 9, "att": 1, "art": 1, "name": "test-results", "total": 4, "skipped": 0,
                       "failed": [["tests.test_calc::test_add", "fp", "assert -1 == 5"]], "flaky": [], "slow": []}]}
    result = {"jobs": [{"workflow": ".github/workflows/ci.yml", "job": "test", "state": "suspect", "flake_events": 1, "runs": 7,
                        "last_flake": "2026-10-16T00:00:00Z"},
                       {"workflow": ".github/workflows/ci.yml", "job": "lint", "state": "flaky", "flake_events": 3, "runs": 7,
                        "last_flake": "2026-10-16T00:00:00Z", "flake_steps": ["Run ruff check"]}], "tests": []}
    verdicts = {(i["kind"], i["name"]): i["verdict"] for i in classify_run(data, result, 9, logs={92: NET})}
    assert verdicts == {("test", "tests.test_calc::test_add"): "new", ("job", "CI / lint"): "known flaky"}
    once = classify_run(data | {"tests": []}, result, 9)
    assert "flaked once in 7 runs" in next(i["detail"] for i in once if i["name"] == "CI / test")
