from test_ci_already_failing import PR, RESULT, job, run

from stackvitals.ci.automation import should_rerun
from stackvitals.ci.feedback import classify_run, flaky_signature, render_comment, verdict_payload

# Real shapes from labelled public CI logs (bench/accuracy/flaky): each was a flake the history couldn't know yet.
SELENIUM = "[ERROR] Tests run: 9, Failures: 1\nTimeout Expected condition failed: waiting for element to be clickable (tried for 10 second(s))"
MOCHA = "  1) cache\n     Error: Timeout of 2000ms exceeded. For async tests and hooks, ensure \"done()\" is called\n  1 failing"
GO = "--- FAIL: TestSync (30.00s)\n    sync_test.go:88: context deadline exceeded\nFAIL"
BENCH = "Benchmark SQLInjectionDetection regressed: 24.6% slower than the baseline (threshold 10%)"
LIVE = "Check Mailbox is Setup Failed: Retries 20 exhausted (8/10)\nFAILED tests/test_live.py::test_mailbox"
REAL = "FAILED tests/test_calc.py::test_add - AssertionError: assert 3 == 4\n1 failed, 40 passed"


def _job_item(log):
    data = {"runs": [PR], "jobs": [job(91, 9, 29, name="test", step="Run tests")]}
    return next(i for i in classify_run(data, RESULT, 9, logs={91: log}) if i["kind"] == "job")


def test_a_first_failure_that_looks_like_a_flake_reads_maybe_flaky_and_asks_for_one_rerun():
    for log in (SELENIUM, MOCHA, GO, BENCH, LIVE):
        item = _job_item(log)
        assert item["verdict"] == "maybe flaky", log
        assert "re-run it once" in item["detail"] and "if it fails again" in item["detail"]


def test_a_plain_assertion_failure_is_still_likely_the_change():
    assert flaky_signature(REAL) is None and _job_item(REAL)["verdict"] == "new"


def test_maybe_flaky_still_blocks_the_verdict_and_is_never_rerun_automatically():
    item = _job_item(MOCHA)
    assert verdict_payload([item], green=False)["conclusion"] == "failure"
    assert not should_rerun([item], 1)
    assert "Maybe flaky" in render_comment([item], "o/r")


def test_a_test_whose_message_looks_like_a_flake_reads_maybe_flaky_too():
    data = {"runs": [PR], "jobs": [job(91, 9, 29, name="test", step="Run tests")],
            "tests": [{"t": "tests", "run": 9, "att": 1, "art": 1, "name": "results", "total": 3, "skipped": 0,
                       "failed": [["t::slow", "fp1", "Error: Timeout of 2000ms exceeded."], ["t::real", "fp2", "assert 3 == 4"]],
                       "flaky": [], "slow": []}]}
    got = {i["name"]: i["verdict"] for i in classify_run(data, RESULT, 9) if i["kind"] == "test"}
    assert got == {"t::slow": "maybe flaky", "t::real": "new"}


def test_history_still_wins_over_the_log():
    known = {**RESULT, "jobs": [{"workflow": ".github/workflows/ci.yml", "job": "test", "state": "flaky", "flake_events": 5,
                                 "runs": 40, "flake_steps": ["Run tests"]}]}
    data = {"runs": [PR], "jobs": [job(91, 9, 29, name="test", step="Run tests")]}
    item = next(i for i in classify_run(data, known, 9, logs={91: SELENIUM}) if i["kind"] == "job")
    assert item["verdict"] == "known flaky"
    # A timeout beside a failing test ("1 failing") is no flake's sign, so history alone can't call it known.
    item = next(i for i in classify_run(data, known, 9, logs={91: MOCHA}) if i["kind"] == "job")
    assert item["verdict"] == "flaked before"
