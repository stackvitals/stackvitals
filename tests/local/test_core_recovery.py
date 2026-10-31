"""A missed or repeated trigger may delay processing, never lose events: the same event twice changes nothing, a run that
dies before its commit leaves nothing behind and the next run catches up, and a backfill overlapping a short run ends in
the union of both."""
import json
import subprocess
from datetime import timedelta

import httpx
from ci_fake import T0, FakeGitHub, Run, job

from stackvitals.ci.action import run_action
from stackvitals.ci.api import ActionsAPI

NOW = T0 + timedelta(days=2, hours=3)


def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout.strip()


def fake_api(runs):
    fake = FakeGitHub(runs)

    def handler(request):
        if request.url.path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main", "private": False})
        return fake.handle(request)
    return lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),
                                                sleep=lambda s: None, **kw)


def runs():
    return [Run(1, T0, [("failure", [job(11, "test", "failure", T0, 60)]),
                        ("success", [job(12, "test", "success", T0 + timedelta(minutes=10), 60, attempt=2)])]),
            Run(2, T0 + timedelta(days=1), [("success", [job(21, "test", "success", T0 + timedelta(days=1), 60)])])]


def env_for(tmp_path, bare):
    return {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
            "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_EVENT_NAME": "workflow_run"}


def data_json(bare):
    return json.loads(git("show", "stackvitals-data:docs/data.json", cwd=bare))


def test_the_same_event_processed_twice_changes_nothing(tmp_path):
    bare = remote(tmp_path)
    first = run_action(env_for(tmp_path, bare), now=NOW, make_api=fake_api(runs()), pr_comments=False)
    tree = git("rev-parse", "stackvitals-data^{tree}", cwd=bare)
    second = run_action(env_for(tmp_path, bare), now=NOW, make_api=fake_api(runs()), pr_comments=False)
    assert first["pushed"] and second["unchanged"] and git("rev-parse", "stackvitals-data^{tree}", cwd=bare) == tree
    assert git("rev-list", "--count", "stackvitals-data", cwd=bare) == "1"


def test_a_run_that_dies_before_its_commit_leaves_nothing_and_the_next_run_catches_up(tmp_path, monkeypatch):
    import stackvitals.ci.action as action
    bare = remote(tmp_path)
    real = action.write_outputs
    calls = []

    def dying(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("runner killed")
        return real(*args, **kwargs)
    monkeypatch.setattr(action, "write_outputs", dying)
    try:
        run_action(env_for(tmp_path, bare), now=NOW, make_api=fake_api(runs()), pr_comments=False)
    except OSError:
        pass
    assert git("rev-list", "--count", "stackvitals-data", cwd=bare) in ("", "0")  # nothing half-written reached the branch
    out = run_action(env_for(tmp_path, bare), now=NOW, make_api=fake_api(runs()), pr_comments=False)
    assert out["pushed"] and data_json(bare)["runs"] == 2


def test_a_backfill_overlapping_a_short_run_ends_in_the_union(tmp_path):
    bare = remote(tmp_path)
    run_action(env_for(tmp_path, bare), now=NOW, days=1, make_api=fake_api(runs()), pr_comments=False)
    assert data_json(bare)["runs"] == 1  # one day read: only the newest run
    run_action(env_for(tmp_path, bare), now=NOW, days=90, make_api=fake_api(runs()), pr_comments=False)
    assert data_json(bare)["runs"] == 2
    # And the other way round: a long read followed by a short one keeps everything.
    other = remote(tmp_path / "b")
    run_action(env_for(tmp_path / "b", other), now=NOW, days=90, make_api=fake_api(runs()), pr_comments=False)
    run_action(env_for(tmp_path / "b", other), now=NOW, days=1, make_api=fake_api(runs()), pr_comments=False)
    assert data_json(other)["runs"] == 2
