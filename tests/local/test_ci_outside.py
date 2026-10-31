"""Phase 13 M6 iteration: at the moment a job fails for the first time, its log can show an outside failure (a registry,
a cache, the runner); StackVitals said "likely from this change" for 8 of 20 head-to-head items that were flakes."""
from datetime import timedelta

from ci_fake import T0, iso
from stackvitals.ci.automation import should_rerun
from stackvitals.ci.feedback import classify_run, outside_signature, render_comment, verdict_payload

PATH = ".github/workflows/ci.yml"


def _data():
    st = T0 + timedelta(days=29)
    run = {"t": "run", "id": 9, "att": 1, "path": PATH, "wfn": "CI", "ev": "pull_request", "br": "fix", "tree": "t9",
           "pr": [5], "c": "failure", "cr": iso(st)}
    jobs = [{"t": "job", "run": 9, "att": 1, "id": 90 + k, "n": n, "c": "failure", "cr": iso(st), "st": iso(st),
             "en": iso(st + timedelta(seconds=60)), "lb": ["ubuntu-latest"], "steps": [[1, "Install", "failure"]]}
            for k, n in enumerate(("build", "lint"))]
    return {"runs": [run], "jobs": jobs, "tests": []}


def test_a_new_failure_whose_log_shows_an_outside_service_failing_says_so():
    logs = {90: "npm install\nnpm ERR! request to https://registry.npmjs.org/x failed, reason: getaddrinfo ENOTFOUND registry.npmjs.org\n"
                "##[error]Process completed with exit code 1."}
    items = {i["name"]: i for i in classify_run(_data(), {"jobs": [], "tests": []}, 9, logs=logs)}
    assert items["CI / build"]["verdict"] == "outside failure" and "ENOTFOUND" in items["CI / build"]["detail"]
    assert items["CI / lint"]["verdict"] == "new"  # no log, no change in what it says


def test_a_dependency_that_fails_to_build_is_not_an_outside_failure():
    assert outside_signature("error: Failed to download and build `rootfilespec @ git+https://x`\n##[error]exit 1") is None
    assert outside_signature("Error response from daemon: toomanyrequests: You have reached your pull rate limit") is not None
    assert outside_signature("sccache: error: Server startup failed: <Code>ServerBusy</Code>") is not None


def test_outside_failures_still_block_the_verdict_check_but_may_be_re_run():
    logs = {90: "ECONNRESET", 91: "##[error]The runner has received a shutdown signal."}
    items = classify_run(_data(), {"jobs": [], "tests": []}, 9, logs=logs)
    assert [i["verdict"] for i in items] == ["outside failure", "outside failure"]
    assert verdict_payload(items, green=False)["conclusion"] == "failure"
    assert should_rerun(items, 1)
    assert "re-run" in render_comment(items, "o/r").splitlines()[2]


def test_failed_logs_reads_each_failed_job_once_and_stops_quietly_at_the_budget():
    from stackvitals.ci.api import OutOfBudget
    from stackvitals.ci.feedback import failed_logs

    class Api:
        repo, calls = "o/r", []

        def _get(self, path, params=None, raw=False):
            self.calls.append(path)
            if len(self.calls) > 1:
                raise OutOfBudget("budget")
            return b"ENOTFOUND"
    api, cache = Api(), {}
    got = failed_logs(api, _data(), 9, cache)
    assert got == {90: "ENOTFOUND"} and api.calls == ["/repos/o/r/actions/jobs/90/logs", "/repos/o/r/actions/jobs/91/logs"]
    assert failed_logs(api, _data(), 9, cache) == got and len(api.calls) == 2  # read once per run


def test_only_the_failing_steps_section_counts_and_failing_tests_are_never_excused():
    # Review finding: a test the change broke can log "Connection refused"; an earlier step can retry a reset and pass.
    broke_server = ("##[group]Run pytest\ntests/test_api.py::test_get FAILED\nE   ConnectionRefusedError: [Errno 111] Connection refused\n"
                    "1 failed, 20 passed\n##[error]Process completed with exit code 1.")
    assert outside_signature(broke_server) is None
    earlier_step = ("##[group]Run pip install -r requirements.txt\nWARNING: Retrying after connection broken by "
                    "'Connection reset by peer'\nSuccessfully installed x\n##[endgroup]\n##[group]Run ruff check .\n"
                    "src/a.py:1:1: F401 unused import\n##[error]Process completed with exit code 1.")
    assert outside_signature(earlier_step) is None
    warned = "##[group]Run npm ci\n##[warning]ECONNRESET retrying\nnpm ERR! code E401\n##[error]Process completed with exit code 1."
    assert outside_signature(warned) is None
    registry = "##[group]Run npm ci\nnpm ERR! getaddrinfo ENOTFOUND registry.npmjs.org\n##[error]Process completed with exit code 1."
    assert outside_signature(registry) == "ENOTFOUND"


def test_a_build_tools_failed_line_after_a_cache_outage_is_still_an_outside_failure():
    # Real data (munich-quantum-toolkit/core): sccache's server was busy, so ninja printed "FAILED: [code=2] ...".
    log = ("##[group]Run cmake --build build\nsccache: error: Server startup failed: <Code>ServerBusy</Code>\n"
           "FAILED: [code=2] mlir/lib/unity_0_cxx.cxx.o\n##[error]Process completed with exit code 2.")
    assert outside_signature(log) == "ServerBusy"
