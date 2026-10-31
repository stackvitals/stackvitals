from stackvitals.ci.collect import _distrust


def test_a_fork_report_cannot_mark_a_test_flaky_or_set_coverage():
    rec = {"flaky": ["auth::test_login"], "failed": [["a::b", "fp", "msg"]], "cov": {"lines": 10, "covered": 10},
           "patch": {"pr": 7, "lines": 2, "covered": 1}}
    _distrust(rec, own=False)
    assert rec["flaky"] == [] and "cov" not in rec
    # Its own failures and its own PR's patch coverage still show on that PR.
    assert rec["failed"] and rec["patch"]["pr"] == 7


def test_the_repos_own_reports_are_kept_whole():
    rec = {"flaky": ["auth::test_login"], "cov": {"lines": 10, "covered": 9}}
    _distrust(rec, own=True)
    assert rec == {"flaky": ["auth::test_login"], "cov": {"lines": 10, "covered": 9}}
