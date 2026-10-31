from datetime import timedelta

from ci_fake import T0, iso
from stackvitals.ci.feedback import classify, classify_run, failed_on_default, same_error

WF = ".github/workflows/ci.yml"
SCCACHE = ("2026-10-19T14:36:04.1086637Z FAILED: [code=2] src/kj/array.c++.o\n"
           "2026-10-19T14:36:04.2Z sccache: error: Server startup failed: cache storage failed to read: status 503\n"
           "2026-10-19T14:36:04.3Z ninja: build stopped: subcommand failed.\n"
           "2026-10-19T14:36:04.4Z ##[error]Process completed with exit code 1.")
SCCACHE_AGAIN = SCCACHE.replace("src/kj/array.c++.o", "lib/Utils/unity_0.cxx.o").replace("14:36", "16:23")
COMPILE = ("2026-10-20T16:23:16Z test_mapping.cpp:4005:21: error: no matching function for call to 'build'\n"
           "2026-10-20T16:23:17Z ninja: build stopped: subcommand failed.\n"
           "2026-10-20T16:23:18Z ##[error]Process completed with exit code 1.")


def run(rid, day, c="failure", ev="push", br="main", pr=()):
    return {"t": "run", "id": rid, "att": 1, "path": WF, "wfn": "CI", "ev": ev, "br": br, "tree": f"t{rid}",
            "pr": list(pr), "c": c, "cr": iso(T0 + timedelta(days=day))}


def job(jid, rid, day, name="build", c="failure", step="Build"):
    st = T0 + timedelta(days=day)
    return {"t": "job", "run": rid, "att": 1, "id": jid, "n": name, "c": c, "cr": iso(st), "st": iso(st),
            "en": iso(st + timedelta(minutes=5)), "lb": ["ubuntu-latest"], "steps": [[2, step, c]]}


def report(rid, failed):
    return {"t": "tests", "run": rid, "att": 1, "art": 1, "name": "results", "total": 10, "skipped": 0,
            "failed": [[t, fp, "boom"] for t, fp in failed], "flaky": [], "slow": []}


PR = run(9, 29, ev="pull_request", br="fix", pr=(5,))
RESULT = {"default_branch": "main", "jobs": [{"workflow": WF, "job": "build", "state": "ok", "flake_events": 0, "runs": 40}],
          "tests": [{"id": "t::a", "state": "ok", "flake_events": 0, "runs": 40}]}
DATA = {"runs": [run(1, 28), PR], "jobs": [job(11, 1, 28), job(91, 9, 29)]}


def _item(data=DATA, result=RESULT, logs=None, kind="job", name="CI / build"):
    return {(i["kind"], i["name"]): i for i in classify_run(data, result, 9, logs=logs)}[(kind, name)]


def test_the_same_error_in_the_same_step_on_the_default_branch_just_before_reads_already_failing():
    item = _item(logs={91: SCCACHE_AGAIN, 11: SCCACHE})
    assert item["verdict"] == "already failing"
    assert "same error" in item["detail"] and "not caused by this change" in item["detail"]


def test_a_different_error_in_that_step_keeps_the_verdict_and_says_the_default_branch_failed_too():
    item = _item(logs={91: COMPILE, 11: SCCACHE})
    assert item["verdict"] == "new"
    assert "default branch failed in this step" in item["detail"] and "different error" in item["detail"]


def test_without_both_logs_the_step_alone_is_never_enough():
    item = _item(logs={91: SCCACHE_AGAIN})
    assert item["verdict"] == "new" and "default branch failed in this step" in item["detail"]
    assert "different error" not in item["detail"]


def test_same_error_needs_most_of_this_failures_error_lines():
    assert same_error(SCCACHE_AGAIN, SCCACHE)
    assert not same_error(COMPILE, SCCACHE)
    assert not same_error(None, SCCACHE) and not same_error("all good\n", SCCACHE)


def test_another_step_an_older_failure_or_a_later_one_does_not_count():
    for main_job, day in ((job(11, 1, 28, step="Test"), 28), (job(11, 1, 25), 25), (job(11, 1, 29.5), 29.5)):
        data = {"runs": [run(1, day), PR], "jobs": [main_job, job(91, 9, 29)]}
        item = _item(data, logs={91: SCCACHE_AGAIN, 11: SCCACHE})
        assert item["verdict"] == "new" and "default branch" not in item["detail"], (main_job["steps"], day)


def test_only_the_default_branch_counts_and_only_when_it_is_known():
    other = {"runs": [run(1, 28, br="feature"), PR], "jobs": [job(11, 1, 28), job(91, 9, 29)]}
    assert _item(other, logs={91: SCCACHE_AGAIN, 11: SCCACHE})["verdict"] == "new"
    assert _item(result={**RESULT, "default_branch": None}, logs={91: SCCACHE_AGAIN, 11: SCCACHE})["verdict"] == "new"


def test_a_test_that_failed_the_same_way_on_the_default_branch_reads_already_failing():
    data = {"runs": [run(1, 28), PR], "jobs": [job(11, 1, 28, name="test", step="Run tests"),
                                              job(91, 9, 29, name="test", step="Run tests")],
            "tests": [report(1, [("t::a", "fp1"), ("t::b", "fp2")]), report(9, [("t::a", "fp1"), ("t::b", "fp9"), ("t::c", "fp3")])]}
    got = {i["name"]: i for i in classify_run(data, RESULT, 9) if i["kind"] == "test"}
    assert got["t::a"]["verdict"] == "already failing" and "not caused by this change" in got["t::a"]["detail"]
    assert got["t::b"]["verdict"] == "new" and "failed differently on the default branch" in got["t::b"]["detail"]
    assert got["t::c"]["verdict"] == "new" and "default branch" not in got["t::c"]["detail"]


def test_failed_on_default_names_the_newest_such_run_and_its_job():
    data = {"runs": [run(1, 27), run(2, 28), PR], "jobs": [job(11, 1, 27), job(12, 2, 28), job(91, 9, 29)]}
    found = failed_on_default(data, PR, data["jobs"][2], "Build", "main")
    assert (found["run"], found["job"]) == (2, 12)


class FakeLogs:
    repo = "o/r"

    def __init__(self, logs):
        self.logs, self.asked = logs, []

    def _get(self, path, params=None, raw=False):
        if "/pulls/" in path:
            return []
        jid = int(path.split("/")[-2])
        self.asked.append(jid)
        return self.logs[jid].encode()


def test_classify_reads_the_default_branch_log_once_and_shares_it_across_runs():
    api, cache = FakeLogs({91: SCCACHE_AGAIN, 11: SCCACHE}), {}
    items = classify(api, DATA, RESULT, 9, cache)
    assert [i["verdict"] for i in items] == ["already failing"] and "main_job" not in items[0]
    classify(api, DATA, RESULT, 9, cache)
    assert sorted(api.asked) == [11, 91]
