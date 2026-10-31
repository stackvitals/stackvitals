"""Retry only the failed tests in the same job, never ones the data branch calls broken."""
from types import SimpleNamespace

from stackvitals.ci.retry import broken_tests, retry


def junit(path, results):
    cases = "".join(f'<testcase classname="t" name="{n}">' + ("" if ok else '<failure message="x"/>') + "</testcase>"
                    for n, ok in results.items())
    path.write_text(f"<testsuite>{cases}</testsuite>", encoding="utf-8")


def test_a_flaky_failure_is_retried_and_a_broken_one_is_not(tmp_path):
    report = tmp_path / "r.xml"
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd == ["suite"]:
            junit(report, {"test_racy": False, "test_ok": True})
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)
    code, out = retry(["suite"], ["suite", "--lf"], [str(tmp_path / "*.xml")], 2, set(), run=run)
    assert code == 0 and out["passed_on_retry"] == ["t::test_racy"] and calls == [["suite"], ["suite", "--lf"]]
    calls.clear()
    code, out = retry(["suite"], ["suite", "--lf"], [str(tmp_path / "*.xml")], 2, {"t::test_racy"}, run=run)
    assert code == 1 and "known broken" in out["why"] and calls == [["suite"]]


def test_still_failing_after_the_retries_keeps_the_suite_code(tmp_path):
    report = tmp_path / "r.xml"

    def run(cmd, **kw):
        junit(report, {"test_bad": False})
        return SimpleNamespace(returncode=1)
    code, out = retry(["suite"], ["again"], [str(tmp_path / "*.xml")], 3, set(), run=run)
    assert code == 1 and out["retried"] == 3 and out["why"].startswith("still failing")
    assert broken_tests(run=lambda c, **k: SimpleNamespace(returncode=0, stdout=b'{"tests": [{"id": "a", "state": "broken"}]}')) == {"a"}
