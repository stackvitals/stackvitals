"""Coverage from the reports CI already uploads (Cobertura, LCOV, JaCoCo): each run's total, and on pull requests the
share of added lines that ran ("patch coverage"), from the PR's own diff."""
from stackvitals.ci import coverage

COBERTURA = b"""<?xml version="1.0" ?>
<coverage line-rate="0.75" lines-covered="3" lines-valid="4" version="7.4">
 <sources><source>/home/runner/work/r/r/src</source></sources>
 <packages><package name="pkg"><classes>
  <class filename="pkg/mod.py" name="mod.py" line-rate="0.75"><lines>
   <line number="1" hits="1"/><line number="2" hits="1"/><line number="3" hits="0"/><line number="4" hits="2"/>
  </lines></class>
 </classes></package></packages>
</coverage>"""

LCOV = b"""TN:
SF:src/app/cart.ts
DA:1,1
DA:2,0
DA:3,4
LF:3
LH:2
end_of_record
SF:src/app/util.ts
DA:10,0
LF:1
LH:0
end_of_record
"""

JACOCO = b"""<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE report PUBLIC "-//JACOCO//DTD Report 1.1//EN" "report.dtd">
<report name="acme"><package name="com/acme"><sourcefile name="Cart.java">
 <line nr="12" mi="0" ci="3" mb="0" cb="0"/><line nr="13" mi="2" ci="0" mb="0" cb="0"/>
 <counter type="LINE" missed="1" covered="1"/></sourcefile>
 <counter type="LINE" missed="1" covered="1"/></package>
 <counter type="LINE" missed="1" covered="1"/></report>"""


def test_each_format_gives_a_total_and_line_hits_per_file():
    c = coverage.parse("coverage.xml", COBERTURA)
    assert (c["lines"], c["covered"], c["format"]) == (4, 3, "cobertura") and c["files"]["pkg/mod.py"] == {1: 1, 2: 1, 3: 0, 4: 2}
    l = coverage.parse("lcov.info", LCOV)
    assert (l["lines"], l["covered"]) == (4, 2) and l["files"]["src/app/cart.ts"][2] == 0
    j = coverage.parse("jacoco.xml", JACOCO)
    assert (j["lines"], j["covered"]) == (2, 1) and j["files"]["com/acme/Cart.java"] == {12: 3, 13: 0}
    # A JUnit file is not a coverage report.
    assert coverage.parse("results.xml", b"<testsuite><testcase name='x'/></testsuite>") is None


def test_unsafe_or_broken_files_are_skipped():
    bomb = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><coverage line-rate="1">&lol;</coverage>'
    assert coverage.parse("coverage.xml", bomb) is None and coverage.parse("coverage.xml", b"<coverage") is None


PATCH = """@@ -1,3 +1,5 @@
 import os
+import sys
+x = 1
 def f():
@@ -10,2 +12,3 @@
 a
+b
 c"""


def test_added_lines_come_from_the_diff_hunks():
    assert coverage.added_lines(PATCH) == [2, 3, 13]


def test_patch_coverage_counts_added_lines_the_report_knows_and_matches_paths_by_their_end():
    cov = {"files": {"/home/runner/work/r/r/src/pkg/mod.py": {2: 1, 3: 0, 13: 4, 40: 0}, "other.py": {1: 1}}}
    files = [{"filename": "src/pkg/mod.py", "patch": PATCH, "status": "modified"},
             {"filename": "README.md", "patch": "@@ -1 +1,2 @@\n a\n+b", "status": "modified"}]
    out = coverage.patch(cov, files)
    # Line 2 ran, line 3 didn't, line 13 ran; README lines are not code the report knows, so they don't count.
    assert out == {"lines": 3, "covered": 2, "missed": {"src/pkg/mod.py": [3]}}
    assert coverage.patch(cov, [{"filename": "docs/x.md", "patch": "@@ -0,0 +1 @@\n+x"}]) == {"lines": 0, "covered": 0, "missed": {}}


def _zip(name, data):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, data)
    return buf.getvalue()


def test_collect_keeps_each_runs_total_and_a_pull_requests_patch_coverage(tmp_path):
    from datetime import timedelta

    import httpx
    from ci_fake import T0, FakeGitHub, Run, job
    from stackvitals.ci.api import ActionsAPI
    from stackvitals.ci.collect import collect
    from stackvitals.ci.store import DataStore
    push = Run(1, T0, [("success", [job(11, "test", "success", T0, 60)])])
    pr_run = Run(2, T0 + timedelta(hours=1), [("success", [job(21, "test", "success", T0 + timedelta(hours=1), 60)])],
                 event="pull_request", branch="feature", pr=5, sha="s2")
    arts = {1: [(101, "coverage", _zip("coverage.xml", COBERTURA), T0 + timedelta(minutes=2)),
                (102, "coverage-html", b"PK-not-a-report", T0 + timedelta(minutes=2))],
            2: [(201, "coverage-report", _zip("lcov.info", LCOV), T0 + timedelta(hours=1, minutes=2))]}
    fake = FakeGitHub([push, pr_run], artifacts=arts)
    files = [{"filename": "src/app/cart.ts", "status": "added", "patch": "@@ -0,0 +1,3 @@\n+a\n+b\n+c"}]

    def handle(request):
        if request.url.path == "/repos/o/r/pulls/5/files":
            fake.calls.append(str(request.url))
            return httpx.Response(200, json=files)
        return fake.handle(request)
    api = ActionsAPI("tok", "o/r", client=httpx.Client(transport=httpx.MockTransport(handle)), sleep=lambda s: None)
    collect(api, DataStore(tmp_path), T0 + timedelta(days=1), days=3, tests=True)
    reports = {r["run"]: r for r in DataStore(tmp_path).load()["tests"]}
    assert reports[1]["cov"] == {"format": "cobertura", "lines": 4, "covered": 3} and "patch" not in reports[1]
    assert reports[2]["cov"]["lines"] == 4 and reports[2]["patch"] == {"pr": 5, "lines": 3, "covered": 2, "missed": {"src/app/cart.ts": [2]}}
    assert not any("/artifacts/102/" in c for c in fake.calls)
    assert all("files" not in r["cov"] for r in reports.values())


def test_the_analysis_shows_the_trend_the_latest_total_and_each_pull_requests_patch():
    from ci_fake import T0, iso
    from datetime import timedelta
    from stackvitals.ci.analyze import analyze
    from test_ci_analyze_tests import NOW, rep, trun
    runs = [trun(k, 1, 20 + k, "success", tree=f"x{k}") for k in range(4)]
    runs.append({**trun(9, 1, 25, "success", tree="p", ev="pull_request", pr=[5]), "br": "feature"})
    tests = [{**rep(100 + k, k, 1), "cov": {"format": "lcov", "lines": 100, "covered": 70 + k}} for k in range(4)]
    tests.append({**rep(200, 9, 1), "cov": {"format": "lcov", "lines": 100, "covered": 71},
                  "patch": {"pr": 5, "lines": 4, "covered": 3, "missed": {"a.py": [9]}}})
    out = analyze({"runs": runs, "jobs": [], "tests": tests}, NOW, default_branch="main")["coverage"]
    assert out["latest"]["pct"] == 0.73 and [v for _, v in out["trend"]] == [0.7, 0.71, 0.72, 0.73]
    assert out["prs"] == [{"pr": 5, "lines": 4, "covered": 3, "pct": 0.75, "missed": {"a.py": [9]}, "at": iso(T0 + timedelta(days=25))}]


def test_a_minimum_patch_coverage_blocks_the_verdict_and_says_by_how_much():
    from stackvitals.ci.feedback import verdict_payload
    from stackvitals.core.config import parse
    low = {"pr": 5, "lines": 20, "covered": 12, "missed": {}}
    out = verdict_payload([], True, patch=low, min_patch=0.8)
    assert out["conclusion"] == "failure" and "60%" in out["output"]["title"] and "80%" in out["output"]["title"]
    assert "12 of 20" in out["output"]["summary"]
    assert verdict_payload([], True, patch=low, min_patch=0.0)["conclusion"] == "success"
    assert verdict_payload([], True, patch={"pr": 5, "lines": 0, "covered": 0, "missed": {}}, min_patch=0.8)["conclusion"] == "success"
    assert verdict_payload([], True, patch=None, min_patch=0.8)["conclusion"] == "success"
    cfg, notes = parse("[ci.coverage]\nmin_patch = 0.8\n")
    assert cfg["ci"]["coverage"]["min_patch"] == 0.8 and notes == []
    assert parse("[ci.coverage]\nmin_patch = 2\n")[1]
