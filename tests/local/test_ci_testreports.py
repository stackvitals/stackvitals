import io
import json
import zipfile

from stackvitals.ci.fingerprint import analyse
from stackvitals.ci.testreports import parse_archive, parse_report

PYTEST = b"""<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4" failures="1" errors="1" skipped="1" time="3.2">
<testcase classname="tests.test_api" name="test_get" file="tests/test_api.py" time="0.120"/>
<testcase classname="tests.test_api" name="test_retry[3]" file="tests/test_api.py" time="2.500">
  <failure message="AssertionError: assert 502 == 200">E   AssertionError: assert 502 == 200
tests/test_api.py:41: AssertionError</failure></testcase>
<testcase classname="tests.test_db" name="test_pool" time="0.4"><error message="TimeoutError: timed out after 30.0s at 0x7f3a2c"/></testcase>
<testcase classname="tests.test_db" name="test_skip" time="0"><skipped message="no db"/></testcase>
</testsuite></testsuites>"""

SUREFIRE = b"""<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="com.acme.CartTest" tests="2" failures="0" errors="0" skipped="0" flakes="1">
<testcase name="addsItem" classname="com.acme.CartTest" time="0.05">
  <flakyFailure message="expected:&lt;1&gt; but was:&lt;0&gt;" type="java.lang.AssertionError"/>
</testcase>
<testcase name="removesItem" classname="com.acme.CartTest" time="0.01"/>
</testsuite>"""

CTRF = {"results": {"tool": {"name": "playwright"}, "tests": [
    {"name": "checkout works", "status": "passed", "duration": 5300, "filePath": "e2e/checkout.spec.ts", "retries": 1,
     "flaky": True},
    {"name": "login", "status": "failed", "duration": 1200, "filePath": "e2e/login.spec.ts",
     "message": "Timeout 30000ms exceeded."},
    {"name": "old", "status": "skipped", "duration": 0, "filePath": "e2e/old.spec.ts"}]}}

BOMB = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>
<testsuite><testcase name="x" classname="y"><failure message="&lol2;"/></testcase></testsuite>"""


def test_pytest_junit_gives_failures_skips_durations_and_stable_ids():
    r = parse_report("results.xml", PYTEST)
    assert r["total"] == 4 and r["skipped"] == 1
    assert [f[0] for f in r["failed"]] == ["tests/test_api.py::tests.test_api::test_retry[3]", "tests.test_db::test_pool"]
    assert r["slow"][0] == ["tests/test_api.py::tests.test_api::test_retry[3]", 2500]


def test_surefire_reruns_that_passed_are_flaky_within_the_run():
    r = parse_report("TEST-com.acme.CartTest.xml", SUREFIRE)
    assert r["failed"] == [] and r["flaky"] == ["com.acme.CartTest::addsItem"]


def test_ctrf_json_from_playwright_and_others():
    r = parse_report("ctrf-report.json", json.dumps(CTRF).encode())
    assert r["flaky"] == ["e2e/checkout.spec.ts::checkout works"]
    assert [f[0] for f in r["failed"]] == ["e2e/login.spec.ts::login"] and r["total"] == 3


def test_fingerprints_ignore_numbers_addresses_and_durations():
    a = analyse(None, "TimeoutError: timed out after 30.0s at 0x7f3a2c (port 51234)", "").cause
    b = analyse(None, "TimeoutError: timed out after 12.5s at 0x11ff00 (port 40001)", "").cause
    assert a == b and a != analyse(None, "ConnectionError: refused", "").cause


def test_an_artifact_zip_is_read_with_size_limits():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("junit/results.xml", PYTEST)
        z.writestr("ctrf/ctrf-report.json", json.dumps(CTRF))
        z.writestr("notes/readme.txt", "not a report")
        z.writestr("huge.xml", b"<a>" + b" " * 2_000_000 + b"</a>")
    out = parse_archive(buf.getvalue(), max_file_bytes=1_000_000)
    assert out["total"] == 7 and len(out["failed"]) == 3 and out["flaky"] == ["e2e/checkout.spec.ts::checkout works"]
    assert out["skipped_files"] == 1
