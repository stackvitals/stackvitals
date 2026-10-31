import json
import subprocess
from datetime import timedelta

import httpx
from ci_fake import NET_LOG, T0, FakeGitHub, Run, job
from stackvitals.ci.action import run_action
from stackvitals.ci.api import ActionsAPI

DAY = T0 + timedelta(days=1)


def at(hours):
    return DAY + timedelta(hours=hours)


def pr_run(rid, pr, hours, conclusion="failure", name="lint", sha="a", path=".github/workflows/ci.yml", fork=None):
    return Run(rid, at(hours), [(conclusion, [job(rid * 10 + 1, name, conclusion, at(hours), 30)])], event="pull_request",
               pr=pr, branch="fix", sha=sha, tree=f"t{sha}", path=path, fork_owner=fork)


def setup(tmp_path, runs, logs=None):
    fake = FakeGitHub(runs, logs=logs)
    comments, reruns = {}, []

    def handler(request):
        path = request.url.path
        if path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main"})
        if path == "/repos/o/r/pulls":
            return httpx.Response(200, json=[{"number": 12}] if request.url.params["head"] == "alice:fix" else [])
        if path.startswith("/repos/o/r/issues/") and path.endswith("/comments"):
            pr = int(path.split("/")[5])
            if request.method == "POST":
                comments.setdefault(pr, []).append({"id": pr * 100, "body": json.loads(request.content)["body"]})
                return httpx.Response(201, json=comments[pr][-1])
            return httpx.Response(200, json=comments.get(pr, []))
        if path.startswith("/repos/o/r/issues/comments/") and request.method == "PATCH":
            cid = int(path.rsplit("/", 1)[1])
            comments[cid // 100][0]["body"] = json.loads(request.content)["body"]
            return httpx.Response(200, json=comments[cid // 100][0])
        if path.endswith("/rerun-failed-jobs"):
            reruns.append(int(path.split("/")[6]))
            return httpx.Response(201, json={})
        return fake.handle(request)

    def make_api(token, repo, **kw):
        return ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None, **kw)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return fake, make_api, comments, reruns, bare.as_uri()


def env_for(tmp_path, url, trigger=None):
    e = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": url,
         "RUNNER_TEMP": str(tmp_path / "tmp")}
    if trigger:
        event = tmp_path / f"event{trigger['id']}.json"
        event.write_text(json.dumps({"workflow_run": trigger}))
        e |= {"GITHUB_EVENT_NAME": "workflow_run", "GITHUB_EVENT_PATH": str(event)}
    return e


def wr(rid, pr, conclusion="failure", event="pull_request", attempt=1):
    return {"id": rid, "event": event, "conclusion": conclusion, "run_attempt": attempt, "head_branch": "fix",
            "pull_requests": [{"number": pr}] if pr else []}


def test_runs_whose_queued_trigger_github_cancelled_still_get_their_pr_comment(tmp_path):
    fake, make_api, comments, _, url = setup(tmp_path, [Run(1, at(0), [("success", [job(11, "lint", "success", at(0), 30)])])])
    run_action(env_for(tmp_path, url), now=at(0.5), make_api=make_api)
    # Two PR runs fail close together; GitHub cancelled the queued run for PR 12, only PR 13's trigger runs.
    fake.runs[5], fake.runs[6] = pr_run(5, 12, 1), pr_run(6, 13, 1.2, sha="b")
    run_action(env_for(tmp_path, url, wr(6, 13)), now=at(2), make_api=make_api)
    assert set(comments) == {12, 13} and all(len(c) == 1 for c in comments.values())


def test_the_first_run_comments_only_on_its_trigger(tmp_path):
    _, make_api, comments, _, url = setup(tmp_path, [pr_run(5, 12, 1), pr_run(6, 13, 1.2, sha="b")])
    run_action(env_for(tmp_path, url, wr(6, 13)), now=at(2), make_api=make_api)
    assert set(comments) == {13}


def test_one_comment_covers_every_failing_workflow_of_the_prs_newest_code(tmp_path):
    runs = [pr_run(5, 12, 1, name="lint", sha="a"), pr_run(7, 12, 2, name="unit tests", sha="b"),
            pr_run(8, 12, 2, name="build docs", sha="b", path=".github/workflows/docs.yml")]
    _, make_api, comments, _, url = setup(tmp_path, runs)
    run_action(env_for(tmp_path, url, wr(8, 12)), now=at(3), make_api=make_api)
    body = comments[12][0]["body"]
    assert "unit tests" in body and "build docs" in body and "lint" not in body


def test_fork_pr_runs_found_from_history_get_a_comment(tmp_path):
    fake, make_api, comments, _, url = setup(tmp_path, [Run(1, at(0), [("success", [job(11, "lint", "success", at(0), 30)])])])
    run_action(env_for(tmp_path, url), now=at(0.5), make_api=make_api)
    fake.runs[5] = pr_run(5, None, 1, fork="alice")
    run_action(env_for(tmp_path, url), now=at(2), make_api=make_api)
    assert len(comments[12]) == 1


def test_a_known_flake_is_rerun_once_even_when_two_runs_see_it(tmp_path):
    t = lambda d: T0 + timedelta(days=d)
    runs = [Run(k, t(k), [("failure", [job(k * 10 + 1, "e2e", "failure", t(k), 30)]),
                          ("success", [job(k * 10 + 2, "e2e", "success", t(k) + timedelta(minutes=10), 30, attempt=2)])],
                tree=f"x{k}") for k in (1, 2, 3)]
    runs.append(Run(9, t(4), [("failure", [job(91, "e2e", "failure", t(4), 30)])], tree="x9"))
    _, make_api, _, reruns, url = setup(tmp_path, runs, logs={91: NET_LOG})
    trigger = wr(9, None, event="push")
    run_action(env_for(tmp_path, url, trigger), now=t(4) + timedelta(minutes=15), make_api=make_api, rerun_flaky=True)
    run_action(env_for(tmp_path, url), now=t(4) + timedelta(minutes=20), make_api=make_api, rerun_flaky=True)
    assert reruns == [9]
