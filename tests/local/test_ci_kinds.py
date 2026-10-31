from test_ci_already_failing import PR, RESULT, job

from stackvitals.ci.feedback import classify_run, flake_kind

KNOWN = {**RESULT, "jobs": [{"workflow": ".github/workflows/ci.yml", "job": "e2e", "state": "flaky", "flake_events": 5,
                             "runs": 40, "flake_steps": ["Run tests"]}]}


def test_each_kind_reads_from_the_log_and_infrastructure_wins_over_network():
    assert flake_kind("Error: Timeout of 2000ms exceeded.") == "timing"
    assert flake_kind("npm ERR! getaddrinfo ENOTFOUND registry.npmjs.org") == "network"
    assert flake_kind("##[error]Failed to FinalizeArtifact: Unable to make request: ETIMEDOUT") == "infrastructure"
    assert flake_kind('Post "http://127.0.0.1:18021": dial tcp 127.0.0.1:18021: connect: connection refused') == "infrastructure"
    assert flake_kind("WARNING: DATA RACE\nRead at 0x00c000") == "concurrency"
    assert flake_kind("AssertionError: assert 3 == 4") is None


def test_a_known_flaky_job_says_what_kind_of_flake_it_looks_like():
    data = {"runs": [PR], "jobs": [job(91, 9, 29, name="e2e", step="Run tests")]}
    item = next(i for i in classify_run(data, KNOWN, 9, logs={91: "Error: Timeout of 2000ms exceeded."}) if i["kind"] == "job")
    assert item["verdict"] == "known flaky" and item["flake"] == "timing" and "looks like a timing flake" in item["detail"]


def test_a_failure_likely_from_the_change_gets_no_kind():
    data = {"runs": [PR], "jobs": [job(91, 9, 29, name="build", step="Build")]}
    item = next(i for i in classify_run(data, RESULT, 9, logs={91: "error: cannot find symbol"}) if i["kind"] == "job")
    assert item["verdict"] == "new" and "flake" not in item


def test_a_flaky_test_in_the_ci_result_carries_the_kind_its_failures_look_like():
    from test_ci_began import _history, NOW
    from stackvitals.ci.analyze import analyze
    data = _history(5, [6, 8])
    data["tests"] = [{"t": "tests", "run": r["id"], "att": r["att"], "art": r["id"] * 10 + r["att"], "name": "unit", "total": 5,
                      "skipped": 0, "failed": [["t::sync", "fp", "Error: Timeout of 2000ms exceeded."]] if r["c"] == "failure" else [],
                      "flaky": [], "slow": []} for r in data["runs"]]
    test = next(t for t in analyze(data, NOW, window_days=40, default_branch="main")["tests"] if t["id"] == "t::sync")
    assert test["flake"] == "timing"
