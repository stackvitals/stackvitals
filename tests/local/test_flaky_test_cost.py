"""What each flaky test costs: the minutes of the attempts it flaked in (shared when several flaked together), and the
pull requests it got in the way of (Trunk's and Datadog's per-test impact)."""
from stackvitals.ci import cost


def job(run, att, c, minutes, labels=("ubuntu-latest",)):
    return {"run": run, "att": att, "c": c, "st": "2026-10-20T10:00:00Z", "en": f"2026-10-20T10:{minutes:02d}:00Z", "lb": list(labels)}


def test_each_attempt_is_charged_to_the_tests_that_flaked_in_it():
    data = {"jobs": [job(1, 1, "failure", 10), job(1, 2, "success", 10), job(2, 1, "failure", 6), job(3, 1, "failure", 4)]}
    tests = [{"id": "a::t1", "suite": "s", "_attempts": [[1, 1], [2, 1]], "prs_affected": [5, 6]},
             {"id": "a::t2", "suite": "s", "_attempts": [[2, 1]], "prs_affected": []},
             {"id": "a::t3", "suite": "s", "_attempts": [], "prs_affected": []}]
    got = cost.flaky_tests(data, tests, private=True)
    assert [(x["id"], x["minutes"], x["flakes"], x["prs"]) for x in got] == [("a::t1", 13.0, 2, 2), ("a::t2", 3.0, 1, 0)]
    assert got[0]["usd"] == round(13 * 0.006, 2)
    assert cost.flaky_tests(data, tests, private=False)[0]["usd"] == 0.0
