import json
import subprocess
from datetime import timedelta

import httpx
from ci_fake import NET_LOG, T0, FakeGitHub, Run, job
from stackvitals.ci.action import run_action
from stackvitals.ci.api import ActionsAPI

PR_NOW = T0 + timedelta(days=2)


def pr_remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare.as_uri()


def pr_setup(tmp_path, conclusion):
    pr_run = Run(5, T0 + timedelta(days=1), [(conclusion, [job(51, "lint", conclusion, T0 + timedelta(days=1), 30)])],
                 event="pull_request", pr=12, branch="fix")
    fake = FakeGitHub([pr_run])
    comments = []

    def handler(request):
        path = request.url.path
        if path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main"})
        if path == "/repos/o/r/issues/12/comments":
            if request.method == "POST":
                comments.append({"id": len(comments) + 1, "body": json.loads(request.content)["body"]})
                return httpx.Response(201, json=comments[-1])
            return httpx.Response(200, json=comments)
        if path.startswith("/repos/o/r/issues/comments/") and request.method == "PATCH":
            comments[0]["body"] = json.loads(request.content)["body"]
            return httpx.Response(200, json=comments[0])
        return fake.handle(request)

    def make_api(token, repo, **kw):
        return ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None, **kw)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"workflow_run": {"id": 5, "event": "pull_request", "conclusion": conclusion,
                                                  "pull_requests": [{"number": 12}], "head_branch": "fix"}}))
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": pr_remote(tmp_path),
           "GITHUB_EVENT_NAME": "workflow_run", "GITHUB_EVENT_PATH": str(event), "RUNNER_TEMP": str(tmp_path / "tmp")}
    return env, make_api, comments


def test_a_failed_pr_run_gets_one_comment(tmp_path):
    env, make_api, comments = pr_setup(tmp_path, "failure")
    out = run_action(env, now=PR_NOW, make_api=make_api)
    assert out["comment"] == "created" and len(comments) == 1
    assert "lint" in comments[0]["body"] and "New" in comments[0]["body"]


def test_a_passing_pr_run_never_starts_a_new_comment(tmp_path):
    env, make_api, comments = pr_setup(tmp_path, "success")
    out = run_action(env, now=PR_NOW, make_api=make_api)
    assert out["comment"] is None and comments == []


def flaky_history_setup(tmp_path, quarantine):
    t = lambda d: T0 + timedelta(days=d)
    runs = [Run(k, t(k), [("failure", [job(k * 10 + 1, "e2e", "failure", t(k), 30)]),
                          ("success", [job(k * 10 + 2, "e2e", "success", t(k) + timedelta(minutes=10), 30, attempt=2)])],
                tree=f"x{k}") for k in (1, 2, 3)]
    runs.append(Run(9, t(4), [("failure", [job(91, "e2e", "failure", t(4), 30)])], tree="x9"))
    fake = FakeGitHub(runs, logs={91: NET_LOG})
    reruns = []

    def handler(request):
        if request.url.path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main"})
        if request.url.path == "/repos/o/r/actions/runs/9/rerun-failed-jobs":
            reruns.append(request.method)
            return httpx.Response(201, json={})
        return fake.handle(request)

    def make_api(token, repo, **kw):
        return ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None, **kw)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"workflow_run": {"id": 9, "event": "push", "conclusion": "failure", "run_attempt": 1}}))
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": pr_remote(tmp_path),
           "GITHUB_EVENT_NAME": "workflow_run", "GITHUB_EVENT_PATH": str(event), "RUNNER_TEMP": str(tmp_path / "tmp")}
    return env, make_api, reruns


def test_a_run_failing_only_on_a_known_flaky_job_is_rerun_once(tmp_path):
    env, make_api, reruns = flaky_history_setup(tmp_path, quarantine=False)
    out = run_action(env, now=T0 + timedelta(days=5), make_api=make_api, rerun_flaky=True)
    assert out["rerun"] and reruns == ["POST"]


def test_the_quarantine_list_is_in_the_data_branch_only_while_quarantine_is_on(tmp_path):
    env, make_api, _ = flaky_history_setup(tmp_path, quarantine=True)
    run_action(env, now=T0 + timedelta(days=5), make_api=make_api, quarantine=True)
    check = tmp_path / "check"
    subprocess.run(["git", "clone", "-q", "--branch", "stackvitals-data", env["STACKVITALS_REMOTE"], str(check)], check=True)
    assert json.loads((check / "ci" / "quarantine.json").read_text()) == []
    run_action(env, now=T0 + timedelta(days=5, hours=1), make_api=make_api, quarantine=False)
    again = tmp_path / "again"
    subprocess.run(["git", "clone", "-q", "--branch", "stackvitals-data", env["STACKVITALS_REMOTE"], str(again)], check=True)
    assert not (again / "ci" / "quarantine.json").exists()
