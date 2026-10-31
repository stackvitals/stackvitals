"""The repo's settings file reaches CI Health: its mutes keep alerts and issues quiet, its quarantine
overrides decide the list, and test status records with a change log live in the data branch."""
import json
import subprocess
from datetime import timedelta

import httpx
from ci_fake import T0, FakeGitHub, Run, job

from stackvitals.ci.action import run_action
from stackvitals.ci.api import ActionsAPI
from stackvitals.ci.automation import new_flakes, quarantine_list
from stackvitals.core.config import parse


def test_quarantine_overrides_and_mutes():
    result = {"tests": [{"id": "a", "state": "flaky", "flake_events": 3}, {"id": "b", "state": "flaky", "flake_events": 3},
                        {"id": "c", "state": "ok"}, {"id": "m", "state": "flaky", "flake_events": 3, "muted_until": "2026-12-01"}],
              "jobs": []}
    cfg = parse('[ci.quarantine]\nalways = ["c"]\nnever = ["b"]\n')[0]
    assert quarantine_list(result, cfg) == ["a", "c", "m"]
    assert quarantine_list(result) == ["a", "b", "m"]
    old = {"tests": [], "jobs": []}
    assert new_flakes(old, result) == ["test a", "test b"]  # the muted test never alerts


def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare


def show(bare, path):
    return subprocess.run(["git", "show", f"stackvitals-data:{path}"], cwd=bare, capture_output=True, text=True).stdout


def test_the_action_keeps_status_records_and_logs_changes(tmp_path):
    report = (b'<testsuite><testcase classname="t" name="flaky_one"><failure message="boom">boom</failure></testcase>'
              b'<testcase classname="t" name="fine"/></testsuite>')
    passed = b'<testsuite><testcase classname="t" name="flaky_one"/><testcase classname="t" name="fine"/></testsuite>'
    runs = [Run(1, T0, [("failure", [job(11, "tests", "failure", T0, 60)]),
                        ("success", [job(12, "tests", "success", T0 + timedelta(minutes=10), 60, attempt=2)])]),
            Run(2, T0 + timedelta(hours=5), [("failure", [job(21, "tests", "failure", T0 + timedelta(hours=5), 60)]),
                                            ("success", [job(22, "tests", "success", T0 + timedelta(hours=5, minutes=9), 60, attempt=2)])],
                tree="t2", sha="s2")]
    def zipped(xml):
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("junit.xml", xml)
        return buf.getvalue()
    artifacts = {1: [(101, "test-results", zipped(report), T0 + timedelta(minutes=2)),
                     (102, "test-results", zipped(passed), T0 + timedelta(minutes=12))],
                 2: [(201, "test-results", zipped(report), T0 + timedelta(hours=5, minutes=2)),
                     (202, "test-results", zipped(passed), T0 + timedelta(hours=5, minutes=11))]}
    fake = FakeGitHub(runs, artifacts=artifacts)

    def handler(request):
        if request.url.path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main"})
        if request.url.path.endswith("/contents/.github/stackvitals.toml"):
            return httpx.Response(404, json={"message": "Not Found"})
        return fake.handle(request)
    make = lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),  # noqa: E731
                                                sleep=lambda s: None, **kw)
    bare = remote(tmp_path)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}
    run_action(env, now=T0 + timedelta(days=1), make_api=make, pr_comments=False)
    status = json.loads(show(bare, "ci/status.json"))
    assert status["t::flaky_one"]["state"] == "flaky" and status["t::flaky_one"]["monitors"] == ["pass_on_retry"]
    changes = [json.loads(x) for x in show(bare, f"ci/transitions/{(T0 + timedelta(days=1)):%Y-%m-%d}.ndjson").splitlines()]
    assert [(c["id"], c["from"], c["to"]) for c in changes] == [("t::flaky_one", "ok", "flaky")]
    data = json.loads(show(bare, "docs/data.json"))
    assert data["tests"][0]["since"] == status["t::flaky_one"]["since"]
