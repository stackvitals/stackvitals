import json
import subprocess
from datetime import timedelta

import httpx
from ci_fake import T0, FakeGitHub, Run, job
from stackvitals.ci.action import DataBranch, run_action
from stackvitals.ci.api import ActionsAPI

ACTION_NOW = T0 + timedelta(days=2)


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def remote(tmp_path):
    bare = tmp_path / "remote.git"
    git("init", "-q", "--bare", str(bare))
    return bare.as_uri()


def fake_api(runs):
    fake = FakeGitHub(runs)
    repo_info = {"default_branch": "main", "private": False}

    def handler(request):
        if request.url.path == "/repos/o/r":
            return httpx.Response(200, json=repo_info)
        return fake.handle(request)
    return lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),
                                                sleep=lambda s: None, **kw)


def runs():
    return [Run(1, T0, [("failure", [job(11, "test", "failure", T0, 60)]),
                        ("success", [job(12, "test", "success", T0 + timedelta(minutes=10), 60, attempt=2)])]),
            Run(2, T0 + timedelta(days=1), [("success", [job(21, "test", "success", T0 + timedelta(days=1), 60)])],
                path=".github/workflows/stackvitals.yml", name="StackVitals")]


def env(tmp_path, url):
    summary = tmp_path / "summary.md"
    return {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": url,
            "GITHUB_WORKFLOW_REF": "o/r/.github/workflows/stackvitals.yml@refs/heads/main",
            "GITHUB_STEP_SUMMARY": str(summary), "RUNNER_TEMP": str(tmp_path / "tmp")}, summary


def test_a_second_run_adds_only_new_data(tmp_path):
    url = remote(tmp_path)
    e, _ = env(tmp_path, url)
    run_action(e, now=ACTION_NOW, make_api=fake_api(runs()))
    out = run_action(e, now=ACTION_NOW, make_api=fake_api(runs()))
    # Nothing new: no fetches of old attempts and no empty commit.
    assert out["collect"]["runs"] == 0 and out["unchanged"]
    log = git("log", "--oneline", "stackvitals-data", cwd=tmp_path / "remote.git")
    assert len(log.strip().splitlines()) == 1
