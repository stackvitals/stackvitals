"""`stackvitals ci upload`: test reports from any CI (Jenkins, GitLab, CircleCI, Buildkite) join the same history in the
repo's data branch, so the same flaky-test detection, groups and pages work without GitHub Actions."""
import json
import subprocess
from datetime import datetime, timedelta, timezone

from stackvitals.ci.analyze import analyze
from stackvitals.ci.store import DataStore
from stackvitals.ci.upload import main, records

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
FAIL = (b'<testsuite><testcase classname="api.Login" name="works" time="1.2">'
        b'<failure type="AssertionError" message="expected 200">AssertionError: expected 200\n'
        b'    at login (/builds/acme/web/src/login.js:12:5)</failure></testcase>'
        b'<testcase classname="api.Login" name="logout" time="0.1"/></testsuite>')
PASS = b'<testsuite><testcase classname="api.Login" name="works" time="1.1"/><testcase classname="api.Login" name="logout"/></testsuite>'


def test_records_describe_one_external_run_with_its_reports(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_bytes(FAIL)
    recs = records([str(report)], sha="abc123", branch="main", run_id="jenkins-41", job="unit", event="push", attempt=1,
                   provider="jenkins", now=NOW)
    run, job, tests = recs
    assert run["t"] == "run" and run["id"] < 0 and run["sha"] == "abc123" and run["tree"] == "abc123" and run["c"] == "failure"
    assert run["wfn"] == "jenkins" and run["path"] == "upload:jenkins" and run["ev"] == "push" and run["cr"] == "2026-10-20T12:00:00Z"
    assert job["t"] == "job" and job["n"] == "unit" and job["c"] == "failure" and job["run"] == run["id"]
    assert tests["t"] == "tests" and tests["run"] == run["id"] and tests["failed"][0][0] == "api.Login::works"
    assert tests["failed"][0][4] == "src/login.js:login"
    again = records([str(report)], sha="abc123", branch="main", run_id="jenkins-41", job="unit", event="push", attempt=1,
                    provider="jenkins", now=NOW)
    assert again[0]["id"] == run["id"]  # the same external run always gets the same id


def test_uploads_land_in_the_data_branch_and_a_rerun_on_the_same_code_shows_a_flaky_test(tmp_path, capsys):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    fail, ok = tmp_path / "fail.xml", tmp_path / "ok.xml"
    fail.write_bytes(FAIL)
    ok.write_bytes(PASS)
    env = {"GITHUB_REPOSITORY": "acme/web", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}
    args = ["--sha", "abc123", "--branch", "main", "--run-id", "41", "--job", "unit", "--provider", "gitlab"]
    assert main([*args, str(fail)], env=env, now=NOW) == 0
    assert main([*args, "--attempt", "2", str(ok)], env=env, now=NOW + timedelta(minutes=5)) == 0
    out = capsys.readouterr().out
    assert "1 failed of 2" in out and "0 failed of 2" in out
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--branch", "stackvitals-data", bare.as_uri(), str(clone)], check=True)
    data = DataStore(clone).load()
    assert len(data["runs"]) == 2 and {r["att"] for r in data["runs"]} == {1, 2}
    result = analyze(data, NOW + timedelta(hours=1), 30, default_branch="main")
    t = {x["id"]: x for x in result["tests"]}["api.Login::works"]
    assert t["flake_events"] == 1 and t["evidence"][0]["kind"] == "retry"
    assert main(["--sha", "abc", "--branch", "main", str(tmp_path / "missing.xml")], env=env, now=NOW) == 2


def test_an_uploaded_failure_shows_on_the_page_with_its_group(tmp_path):
    from stackvitals.ci.report import render_html
    report = tmp_path / "junit.xml"
    report.write_bytes(FAIL)
    run, job, tests = records([str(report)], sha="abc", branch="main", run_id="7", job="unit", event="push", attempt=1,
                              provider="jenkins", now=NOW)
    run2, job2, tests2 = records([str(report)], sha="abc", branch="main", run_id="7", job="unit", event="push", attempt=2,
                                 provider="jenkins", now=NOW + timedelta(minutes=3))
    tests2["failed"], run2["c"], job2["c"] = [], "success", "success"
    result = analyze({"runs": [run, run2], "jobs": [job, job2], "tests": [tests, tests2]}, NOW + timedelta(hours=1), 30,
                     default_branch="main")
    page = render_html(result, "acme/web")
    assert "api.Login::works" in page and "one flake seen" in page
