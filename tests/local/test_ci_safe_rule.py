"""Phase 22 M1: "known flaky" needs the history, a flake's sign in the failing step's log, and no error naming a file the
pull request changed (pre-registered in bench/accuracy/flaky/README.md, 2026-10-28)."""
from test_ci_already_failing import PR, WF, job

from stackvitals.ci.automation import should_rerun
from stackvitals.ci.feedback import (BLAMED, classify, classify_run, failure_summary, named_files, render_comment,
                                     verdict_payload)

KNOWN = {"default_branch": "main", "tests": [],
         "jobs": [{"workflow": WF, "job": "build", "state": "flaky", "flake_events": 4, "runs": 40,
                   "last_flake": "2026-10-20T00:00:00Z", "flake_steps": ["Build"]}]}
NETWORK = "##[group]Run npm ci\nnpm ERR! getaddrinfo ENOTFOUND registry.npmjs.org\n##[error]Process completed with exit code 1."
COMPILE = ("##[group]Run ./gradlew build\nsrc/main/kotlin/SettingsPageSupport.kt:12:3 Unresolved reference 'scope'\n"
           "##[error]Process completed with exit code 1.")
ASSERT = "##[group]Run make check\nexpected 'dormant' but got 'active'\n##[error]Process completed with exit code 1."
TIMED_TEST = ("##[group]Run npm test\n  1) cache\n     Error: Timeout of 2000ms exceeded.\n  1 failing\n"
              "##[error]Process completed with exit code 1.")
DATA = {"runs": [PR], "jobs": [job(91, 9, 29)]}


def _item(log, changed=None):
    return next(i for i in classify_run(DATA, KNOWN, 9, logs={91: log} if log else None, changed=changed)
                if i["kind"] == "job")


def test_history_and_a_flakes_sign_in_the_log_make_a_known_flake_with_its_evidence():
    item = _item(NETWORK, changed=["src/app.ts"])
    assert item["verdict"] == "known flaky"
    assert "flaked 4 times" in item["detail"] and "ENOTFOUND" in item["detail"]
    assert "names none of the 1 file" in item["detail"]
    assert "safe" not in item["detail"]


def test_a_known_flaky_job_whose_log_shows_no_flake_sign_reads_flaked_before():
    item = _item(ASSERT)
    assert item["verdict"] == "flaked before"
    assert "no sign of a flake" in item["detail"] and "check whether this change caused it" in item["detail"]


def test_no_log_means_no_known_flake():
    assert _item(None)["verdict"] == "flaked before"


def test_a_timeout_inside_a_failing_test_is_not_a_known_flake():
    # Held-out finding: a test's own wait running out was the change's failure; a failing test is never excused.
    assert _item(TIMED_TEST)["verdict"] == "flaked before"


def test_an_error_naming_a_file_the_pull_request_changed_reads_maybe_yours_and_blocks():
    item = _item(COMPILE, changed=["src/main/kotlin/SettingsPageSupport.kt", "README.md"])
    assert item["verdict"] == "maybe yours" and "maybe yours" in BLAMED
    assert "SettingsPageSupport.kt" in item["detail"] and "this pull request changed" in item["detail"]
    assert verdict_payload([item], green=False)["conclusion"] == "failure"
    assert not should_rerun([item], 1)
    assert "Maybe yours" in render_comment([item], "o/r")
    assert "look" in failure_summary([item])


def test_a_flakes_sign_with_a_changed_file_named_is_maybe_yours_not_known_flaky():
    log = NETWORK.replace("registry.npmjs.org", "registry.npmjs.org (from src/fetchClient.ts)")
    assert _item(log, changed=["src/fetchClient.ts"])["verdict"] == "maybe yours"


def test_file_names_match_by_name_or_a_long_stem_never_a_short_common_one():
    text = "error in src/parser.go: undefined: parseConfigFile\nat main.go"
    assert named_files(text, ["pkg/parser.go"]) == ["parser.go"]
    assert named_files(text, ["internal/parseConfigFile.go"]) == ["parseConfigFile.go"]
    assert named_files(text, ["cmd/main.go", "docs/index.md"]) == []  # stems under 5 characters never count


def test_a_known_flaky_test_needs_a_flakes_sign_in_its_message():
    result = {**KNOWN, "tests": [{"id": t, "state": "flaky", "flake_events": 3, "runs": 30} for t in ("t::slow", "t::real", "t::mine")]}
    data = {**DATA, "tests": [{"t": "tests", "run": 9, "att": 1, "art": 1, "name": "r", "total": 3, "skipped": 0,
                               "failed": [["t::slow", "fp1", "Error: Timeout of 2000ms exceeded."],
                                          ["t::real", "fp2", "assert 3 == 4"],
                                          ["t::mine", "fp3", "deadline exceeded in src/cacheLayer.py"]],
                               "flaky": [], "slow": []}]}
    got = {i["name"]: i["verdict"] for i in classify_run(data, result, 9, changed=["src/cacheLayer.py"]) if i["kind"] == "test"}
    assert got == {"t::slow": "known flaky", "t::real": "flaked before", "t::mine": "maybe yours"}


def test_classify_reads_the_pull_requests_files_once_per_run():
    class Api:
        repo, calls = "o/r", []

        def _get(self, path, params=None, raw=False):
            self.calls.append(path)
            if path.endswith("/logs"):
                return COMPILE.encode()
            return [{"filename": "src/main/kotlin/SettingsPageSupport.kt"}]
    api, cache = Api(), {}
    items = classify(api, DATA, KNOWN, 9, cache)
    assert items[0]["verdict"] == "maybe yours"
    classify(api, DATA, KNOWN, 9, cache)
    assert api.calls.count("/repos/o/r/pulls/5/files") == 1
