from test_ci_feedback import FB_DATA, FB_RESULT

from stackvitals.ci.automation import quarantine_list
from stackvitals.ci.feedback import SAFE_FLAKES, classify_run, verdict_payload


def _result(flakes: int) -> dict:
    tests = [{**t, "flake_events": flakes} if t["id"] == "t::flaky_one" else t for t in FB_RESULT["tests"]]
    return {**FB_RESULT, "tests": tests}


def _test_item(flakes: int) -> dict:
    return next(i for i in classify_run(FB_DATA, _result(flakes), 9) if i["name"] == "t::flaky_one")


def test_a_test_that_flaked_once_is_not_called_safe_to_rerun():
    item = _test_item(1)
    assert item["verdict"] == "flaked before"
    assert "check whether this change caused it" in item["detail"] and "step" not in item["detail"]


def test_a_test_needs_as_many_flakes_as_a_job_to_be_known_flaky():
    assert _test_item(SAFE_FLAKES - 1)["verdict"] == "flaked before"
    assert _test_item(SAFE_FLAKES)["verdict"] == "known flaky"


def test_a_test_that_flaked_once_blocks_the_verdict_check():
    payload = verdict_payload([_test_item(1)], green=False)
    assert payload["conclusion"] != "success"


def test_auto_quarantine_takes_only_tests_with_enough_flakes_and_keeps_peoples_choices():
    result = {"tests": [{"id": "a", "state": "flaky", "flake_events": SAFE_FLAKES},
                        {"id": "b", "state": "flaky", "flake_events": 1},
                        {"id": "c", "state": "broken", "flake_events": 5}]}
    settings = {"ci": {"quarantine": {"always": ["b"]}}}
    assert quarantine_list(result) == ["a"]
    assert quarantine_list(result, settings) == ["a", "b"]
    decisions = {"test:c": {"kind": "test", "id": "c", "verb": "quarantine"}}
    assert quarantine_list(result, None, decisions) == ["a", "c"]


def test_a_recently_fixed_test_with_no_flakes_says_so_plainly():
    tests = [{**t, "state": "fixed", "flake_events": 0} if t["id"] == "t::flaky_one" else t for t in FB_RESULT["tests"]]
    item = next(i for i in classify_run(FB_DATA, {**FB_RESULT, "tests": tests}, 9) if i["name"] == "t::flaky_one")
    assert item["verdict"] == "flaked before" and "0 times" not in item["detail"] and "recent fix" in item["detail"]
