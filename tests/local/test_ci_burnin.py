from types import SimpleNamespace

from stackvitals.ci.burnin import burn_in, changed_tests


def junit(path, outcomes):
    cases = "".join(f'<testcase classname="t" name="{n}">' + ("<failure message=\"boom\"/>" if not ok else "") + "</testcase>"
                    for n, ok in outcomes.items())
    path.write_text(f"<testsuite>{cases}</testsuite>", encoding="utf-8")


def test_only_added_or_changed_test_files_are_picked():
    out = "src/cart.py\ntests/test_cart.py\nweb/cart.test.ts\npkg/sync_test.go\nsrc/test/java/com/a/CartTest.java\nREADME.md\n"
    def run(cmd, **kw):
        assert cmd[:4] == ["git", "diff", "--name-only", "--diff-filter=AM"] and cmd[4] == "origin/main...HEAD"
        return SimpleNamespace(returncode=0, stdout=out)
    assert changed_tests("origin/main", run) == ["tests/test_cart.py", "web/cart.test.ts", "pkg/sync_test.go",
                                                 "src/test/java/com/a/CartTest.java"]


def test_a_test_that_passes_and_fails_across_repeats_is_caught_before_merge(tmp_path):
    report, calls = tmp_path / "out.xml", []

    def run(cmd, **kw):
        calls.append(cmd)
        n = len(calls)
        junit(report, {"test_steady": True, "test_racy": n % 3 != 0, "test_broken": False})
        return SimpleNamespace(returncode=0 if n % 3 else 1)
    code, out = burn_in(["pytest", "{files}"], [str(tmp_path / "*.xml")], 5, ["tests/test_cart.py"], run=run)
    assert code == 1 and len(calls) == 5 and calls[0] == ["pytest", "tests/test_cart.py"]
    assert out["flaky"] == ["t::test_racy"] and out["always_failed"] == ["t::test_broken"] and out["tests"] == 3


def test_with_no_changed_tests_nothing_runs_and_steady_tests_pass(tmp_path):
    calls = []
    code, out = burn_in(["pytest", "{files}"], [str(tmp_path / "*.xml")], 5, [], run=lambda c, **k: calls.append(c))
    assert code == 0 and not calls and out["runs"] == 0
    report = tmp_path / "out.xml"

    def steady(cmd, **kw):
        junit(report, {"a": True})
        return SimpleNamespace(returncode=0)
    assert burn_in(["go", "test", "./..."], [str(report)], 3, ["x_test.go"], run=steady)[0] == 0


def test_a_run_that_writes_no_report_says_so_instead_of_passing(tmp_path):
    code, out = burn_in(["pytest", "{files}"], [str(tmp_path / "*.xml")], 2, ["tests/test_a.py"],
                        run=lambda c, **k: SimpleNamespace(returncode=0))
    assert code == 2 and "no test report" in out["problem"]


def test_the_last_repeats_reports_stay_for_the_steps_after_it(tmp_path):
    report = tmp_path / "out.xml"

    def steady(cmd, **kw):
        junit(report, {"a": True})
        return SimpleNamespace(returncode=0)
    burn_in(["pytest", "{files}"], [str(tmp_path / "*.xml")], 3, ["tests/test_a.py"], run=steady)
    assert report.exists()  # an upload-artifact step after burn-in still finds them


def test_only_new_fails_just_for_tests_the_default_branch_never_ran(tmp_path):
    report = tmp_path / "out.xml"
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        junit(report, {"test_old_racy": len(calls) % 2 == 0, "test_new": True, "test_new_racy": len(calls) % 3 != 0})
        return SimpleNamespace(returncode=0)
    known = {"t::test_old_racy"}
    code, out = burn_in(["pytest", "{files}"], [str(tmp_path / "*.xml")], 4, ["tests/t.py"], run=run, known=known, only_new=True)
    assert out["new"] == ["t::test_new", "t::test_new_racy"] and out["new_flaky"] == ["t::test_new_racy"] and code == 1
    calls.clear()
    code, out = burn_in(["pytest", "{files}"], [str(tmp_path / "*.xml")], 4, ["tests/t.py"], run=run,
                        known={"t::test_old_racy", "t::test_new_racy", "t::test_new"}, only_new=True)
    assert code == 0 and out["flaky"]


def test_known_tests_come_from_the_data_branch():
    import gzip
    import json

    from stackvitals.ci.burnin import known_tests
    blob = gzip.compress(json.dumps(["a::b"]).encode())
    assert known_tests(run=lambda cmd, **k: SimpleNamespace(returncode=0, stdout=blob)) == {"a::b"}
    assert known_tests(run=lambda cmd, **k: SimpleNamespace(returncode=128, stdout=b"")) is None


def test_a_known_flaky_test_that_passes_every_repeat_shows_its_fix():
    from stackvitals.ci.burnin import proofs
    got = proofs({"a::fixed", "a::meh"}, set(), 10, {"a::fixed": 0.4, "a::meh": 0.05})
    assert [(p["id"], p["shown"]) for p in got] == [("a::fixed", True), ("a::meh", False)]
    assert got[0]["chance"] == round(0.6 ** 10, 4)
