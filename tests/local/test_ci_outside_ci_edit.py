from test_ci_feedback import FB_RESULT, fjb, frun

from stackvitals.ci.feedback import classify, classify_run

# A guard that withheld "outside failure" when the pull request edits CI files was measured on 633 fresh failures and
# dropped (2026-10-22): it caught none of the change-caused cases and took the excuse from 4 real outages.
LOG = "##[group]Run tests\nnpm ERR! code ECONNRESET\nnpm ERR! network request failed\n##[error]Process completed with exit code 1."
DATA = {"runs": [frun(9, 1, 29, "failure")], "jobs": [fjb(91, 9, 1, "build", "failure") | {"steps": [[3, "Run tests", "failure"]]}],
        "tests": []}


def test_an_outside_error_in_the_failing_step_is_called_an_outside_failure():
    assert classify_run(DATA, FB_RESULT, 9, logs={91: LOG})[0]["verdict"] == "outside failure"


def test_classify_reads_each_runs_logs_once_and_asks_for_nothing_else():
    calls = []

    class Api:
        repo = "o/r"

        def _get(self, path, params=None, raw=False):
            calls.append(path)
            return LOG.encode()
    cache = {}
    assert classify(Api(), DATA, FB_RESULT, 9, cache)[0]["verdict"] == "outside failure"
    classify(Api(), DATA, FB_RESULT, 9, cache)
    assert len(calls) == 1 and calls[0].endswith("/logs")
