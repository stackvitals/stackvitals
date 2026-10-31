import json

from stackvitals.ci.collect import TEST_REPORTS
from stackvitals.ci.testreports import parse_report

GO = "\n".join(json.dumps(e) for e in [
    {"Action": "start", "Package": "example.com/shop"},
    {"Action": "output", "Package": "example.com/shop", "Output": "-test.shuffle 1697800000\n"},
    {"Action": "run", "Package": "example.com/shop", "Test": "TestAdd"},
    {"Action": "pass", "Package": "example.com/shop", "Test": "TestAdd", "Elapsed": 0.01},
    {"Action": "run", "Package": "example.com/shop", "Test": "TestTable"},
    {"Action": "run", "Package": "example.com/shop", "Test": "TestTable/case_1"},
    {"Action": "output", "Package": "example.com/shop", "Test": "TestTable/case_1", "Output": "=== RUN   TestTable/case_1\n"},
    {"Action": "output", "Package": "example.com/shop", "Test": "TestTable/case_1",
     "Output": "    table_test.go:22: got 3, want 4\n"},
    {"Action": "fail", "Package": "example.com/shop", "Test": "TestTable/case_1", "Elapsed": 0.02},
    {"Action": "run", "Package": "example.com/shop", "Test": "TestTable/case_2"},
    {"Action": "pass", "Package": "example.com/shop", "Test": "TestTable/case_2", "Elapsed": 0.01},
    {"Action": "fail", "Package": "example.com/shop", "Test": "TestTable", "Elapsed": 0.03},
    {"Action": "skip", "Package": "example.com/shop", "Test": "TestSlow", "Elapsed": 0},
    # gotestsum --rerun-fails: the same test ran again in the same stream and passed.
    {"Action": "run", "Package": "example.com/shop", "Test": "TestNet"},
    {"Action": "fail", "Package": "example.com/shop", "Test": "TestNet", "Elapsed": 1.2},
    {"Action": "run", "Package": "example.com/shop", "Test": "TestNet"},
    {"Action": "pass", "Package": "example.com/shop", "Test": "TestNet", "Elapsed": 0.4},
    {"Action": "fail", "Package": "example.com/shop", "Elapsed": 0.5}]) + "\n"

JEST = json.dumps({"numTotalTests": 4, "testResults": [{
    "name": "/home/runner/work/app/app/src/cart.test.ts",
    "assertionResults": [
        {"ancestorTitles": ["cart"], "fullName": "cart adds items", "title": "adds items", "status": "passed", "duration": 5,
         "failureMessages": []},
        {"ancestorTitles": ["cart"], "fullName": "cart totals", "title": "totals", "status": "failed", "duration": 7,
         "failureMessages": ["Error: expect(received).toBe(expected)\n\nExpected: 4\nReceived: 3\n"
                             "    at Object.<anonymous> (/home/runner/work/app/app/src/cart.test.ts:12:5)"]},
        {"ancestorTitles": ["cart"], "fullName": "cart retries", "title": "retries", "status": "passed", "duration": 9,
         "failureMessages": [], "invocations": 2},
        {"ancestorTitles": [], "fullName": "later", "title": "later", "status": "pending", "failureMessages": []}]}]})

VITEST = json.dumps({"numTotalTests": 1, "testResults": [{
    "name": "D:\\a\\web\\web\\test\\sync.test.ts",
    "assertionResults": [{"ancestorTitles": ["sync"], "fullName": "sync waits", "title": "waits", "status": "passed",
                          "duration": 30, "failureMessages": [], "retryReasons": ["Error: Test timed out in 5000ms."]}]}]})

TRX = """<?xml version="1.0" encoding="utf-8"?>
<TestRun id="r1" xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <Results>
    <UnitTestResult executionId="e1" testId="t1" testName="Adds" outcome="Passed" duration="00:00:00.0100000" />
    <UnitTestResult executionId="e2" testId="t2" testName="Totals(3, 4)" outcome="Failed" duration="00:00:01.5000000">
      <Output><ErrorInfo><Message>Assert.Equal() Failure: Expected 4, Actual 3</Message>
        <StackTrace>   at Shop.Tests.CartTests.Totals(Int32 a, Int32 b) in /src/CartTests.cs:line 12</StackTrace></ErrorInfo></Output>
    </UnitTestResult>
    <UnitTestResult executionId="e3" testId="t3" testName="Later" outcome="NotExecuted" duration="00:00:00" />
    <UnitTestResult executionId="e4" testId="t4" testName="Retry" outcome="Failed" duration="00:00:00.2000000" />
    <UnitTestResult executionId="e5" testId="t4" testName="Retry" outcome="Passed" duration="00:00:00.1000000" />
  </Results>
  <TestDefinitions>
    <UnitTest id="t1" name="Adds"><TestMethod className="Shop.Tests.CartTests" name="Adds" /></UnitTest>
    <UnitTest id="t2" name="Totals(3, 4)"><TestMethod className="Shop.Tests.CartTests" name="Totals" /></UnitTest>
    <UnitTest id="t3" name="Later"><TestMethod className="Shop.Tests.CartTests" name="Later" /></UnitTest>
    <UnitTest id="t4" name="Retry"><TestMethod className="Shop.Tests.NetTests" name="Retry" /></UnitTest>
  </TestDefinitions>
</TestRun>"""

SUREFIRE = """<testsuite name="com.acme.CartTest" tests="1"><properties>
<property name="surefire.runOrder.random.seed" value="424242"/></properties>
<testcase classname="com.acme.CartTest" name="adds" time="0.01"/></testsuite>"""


def test_go_test_json_counts_leaf_tests_keeps_subtests_apart_and_reads_the_shuffle_seed():
    got = parse_report("go-test.json", GO.encode())
    assert got["total"] == 5 and got["skipped"] == 1
    assert [f[0] for f in got["failed"]] == ["example.com/shop::TestTable/case_1"]
    assert got["failed"][0][2] == "table_test.go:22: got 3, want 4"
    assert got["flaky"] == ["example.com/shop::TestNet"]
    assert got["seed"] == "1697800000"


def test_jest_json_names_tests_by_file_and_full_name_and_sees_retries():
    got = parse_report("jest-results.json", JEST.encode())
    assert got["total"] == 4 and got["skipped"] == 1
    assert [f[0] for f in got["failed"]] == ["src/cart.test.ts::cart totals"]
    assert got["failed"][0][2] == "Error: expect(received).toBe(expected)"
    assert got["flaky"] == ["src/cart.test.ts::cart retries"]


def test_vitest_json_on_windows_runners_is_read_the_same_way():
    got = parse_report("vitest.json", VITEST.encode())
    assert got["flaky"] == ["test/sync.test.ts::sync waits"] and not got["failed"]


def test_trx_reads_results_with_their_class_and_parameters():
    got = parse_report("results.trx", TRX.encode())
    assert got["total"] == 4 and got["skipped"] == 1
    assert [f[0] for f in got["failed"]] == ["Shop.Tests.CartTests::Totals(3, 4)"]
    assert got["failed"][0][2].startswith("Assert.Equal() Failure")
    assert got["flaky"] == ["Shop.Tests.NetTests::Retry"]
    assert got["slow"][0] == ["Shop.Tests.CartTests::Totals(3, 4)", 1500]


def test_a_trx_without_its_extension_is_still_recognised_and_hostile_xml_is_refused():
    assert parse_report("report.xml", TRX.encode())["total"] == 4
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><TestRun><Results/></TestRun>'
    assert parse_report("evil.trx", bomb) is None


def test_junit_keeps_a_random_order_seed_when_the_runner_records_one():
    assert parse_report("TEST-com.acme.CartTest.xml", SUREFIRE.encode())["seed"] == "424242"


def test_junit_and_ctrf_still_parse_and_other_json_is_not_a_report():
    assert parse_report("a.xml", b'<testsuite><testcase classname="c" name="n"/></testsuite>')["total"] == 1
    ctrf = {"results": {"tests": [{"name": "t", "status": "failed", "message": "boom"}]}}
    assert parse_report("ctrf.json", json.dumps(ctrf).encode())["failed"][0][0] == "t"
    assert parse_report("package.json", b'{"name": "app", "version": "1.0.0"}') is None


def test_artifacts_named_for_these_runners_are_downloaded():
    import re
    for name in ("vitest-results", "trx", "go-test-report", "xunit", "nunit-results", "mstest"):
        assert re.search(TEST_REPORTS, name, re.I), name


def test_a_failing_test_from_a_random_order_run_names_the_seed_to_replay_it():
    from test_ci_already_failing import PR, RESULT, job
    from stackvitals.ci.feedback import classify_run
    data = {"runs": [PR], "jobs": [job(91, 9, 29, name="test", step="Run tests")],
            "tests": [{"t": "tests", "run": 9, "att": 1, "art": 1, "name": "results", "total": 2, "skipped": 0, "seed": "424242",
                       "failed": [["t::a", "fp1", "assert 3 == 4"]], "flaky": [], "slow": []}]}
    item = next(i for i in classify_run(data, RESULT, 9) if i["kind"] == "test")
    assert "seed 424242" in item["detail"]
