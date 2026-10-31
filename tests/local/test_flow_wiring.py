import json
import subprocess
from datetime import datetime, timedelta, timezone

from mergescout.github.graphql import GraphQLResult
from stackvitals.flow.action import run_flow_action
from stackvitals.flow.cli import main

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def at(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def node(n, state="OPEN", updated=1, reviews=(), requests=(), merged=None, title="Fix it", assoc="NONE"):
    return {"number": n, "title": title, "isDraft": False, "state": state, "createdAt": at(100), "updatedAt": at(updated),
            "mergedAt": at(merged) if merged is not None else None, "closedAt": at(merged) if merged is not None else None,
            "additions": 5, "deletions": 1, "changedFiles": 1, "author": {"__typename": "User", "login": "alice"},
            "authorAssociation": assoc, "baseRefName": "main", "headRefName": "fix", "headRepositoryOwner": {"login": "alice"},
            "commits": {"nodes": [{"commit": {"committedDate": at(99), "statusCheckRollup": {"state": "SUCCESS"}}}]},
            "reviewRequests": {"nodes": [{"requestedReviewer": {"__typename": "User", "login": r}} for r in requests]},
            "events": {"filteredCount": 0, "nodes": [
                *({"__typename": "ReviewRequestedEvent", "createdAt": at(98), "requestedReviewer": {"__typename": "User", "login": r}}
                  for r in requests),
                *({"__typename": "PullRequestReview", "submittedAt": at(h), "state": "APPROVED",
                   "author": {"__typename": "User", "login": who}, "authorAssociation": "MEMBER"} for h, who in reviews)]},
            "talk": {"filteredCount": 0, "nodes": []}}


class Pages:
    def __init__(self, nodes):
        self.nodes = sorted(nodes, key=lambda x: x["updatedAt"], reverse=True)

    def query(self, query, variables=None, **kw):
        start = int(variables.get("cursor") or 0)
        data = {"rateLimit": {"cost": 1, "remaining": 999, "resetAt": at(0)},
                "repository": {"pullRequests": {"pageInfo": {"hasNextPage": start + 25 < len(self.nodes), "endCursor": str(start + 25)},
                                                "nodes": self.nodes[start:start + 25]}}}
        return GraphQLResult(data=data, cost=1, remaining=999, reset_at=at(0))


def history():
    return [node(1, requests=["carol"]), node(2, "MERGED", updated=50, merged=50, reviews=[(90, "bob")])]


def test_local_report_shows_the_queue_and_private_answer_times(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("STACKVITALS_HOME", str(tmp_path / "home"))
    assert main(["report", "o/r"], now=NOW, make_gql=lambda tok: Pages(history()), tok="tok") == 0
    out = capsys.readouterr().out
    assert "Who acts next" in out and "#1" in out and "carol" in out and "Answer times" in out
    assert main(["report", "o/r", "--json"], now=NOW, make_gql=lambda tok: Pages(history()), tok="tok") == 0
    assert json.loads(capsys.readouterr().out)["queue"][0]["n"] == 1


def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare


def show(bare, path):
    return subprocess.run(["git", "show", f"stackvitals-data:{path}"], cwd=bare, capture_output=True, text=True).stdout


def test_the_action_keeps_flow_history_and_a_public_page_without_peoples_speed(tmp_path):
    bare = remote(tmp_path)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "GITHUB_EVENT_NAME": "schedule", "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md")}
    out = run_flow_action(env, now=NOW, make_gql=lambda tok: Pages(history()))
    assert out["pushed"] and out["prs"] == 2
    page = json.loads(show(bare, "docs/flow.json"))
    assert page["queue"][0]["n"] == 1 and "responders" not in page
    assert "Who acts next" in show(bare, "docs/flow.html") and json.loads(show(bare, "flow/open.json"))[0]["n"] == 1
    assert "Team Flow" in (tmp_path / "s.md").read_text(encoding="utf-8")


def test_the_action_leaves_flow_alone_on_ci_triggered_runs(tmp_path):
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": remote(tmp_path).as_uri(),
           "GITHUB_EVENT_NAME": "workflow_run", "RUNNER_TEMP": str(tmp_path / "tmp")}
    assert run_flow_action(env, now=NOW, make_gql=lambda tok: Pages(history())) is None


def test_the_action_runs_each_module_asked_for_and_refuses_unknown_ones(monkeypatch, tmp_path):
    from stackvitals.ci import cli as ci_cli
    called = []
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    for key, value in (("GITHUB_EVENT_NAME", "schedule"), ("GITHUB_REPOSITORY", "o/r"), ("STACKVITALS_TOKEN", "tok"),
                       ("STACKVITALS_REMOTE", bare.as_uri()), ("RUNNER_TEMP", str(tmp_path / "tmp"))):
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ci_cli, "run_action", lambda env, **kw: called.append("ci") or
                        {"collect": {"runs": 0, "requests": 0}, "flaky": 0, "pushed": False})
    monkeypatch.setattr(ci_cli, "run_flow_action", lambda env, **kw: called.append("flow") or
                        {"prs": 3, "points": 1, "complete": True, "pushed": True, "queue": 1})
    assert ci_cli.action_main(["--modules", "ci,flow"]) == 0 and called == ["ci", "flow"]
    assert ci_cli.action_main(["--modules", "flow,nope"]) == 2


def test_the_suite_command_reaches_team_flow(monkeypatch):
    from stackvitals import cli
    seen = []
    monkeypatch.setattr("stackvitals.flow.cli.main", lambda argv: seen.append(argv) or 0)
    assert cli.main(["flow", "report", "o/r"]) == 0 and seen == [["report", "o/r"]]


def test_the_workflow_template_runs_every_3_hours_with_both_modules():
    from stackvitals.ci.cli import workflow_template
    text = workflow_template("o/a@v0", ["CI"])
    assert 'cron: "17 */3 * * *"' in text and "modules: ci,flow" in text


def test_the_ci_page_links_to_team_flow_once_that_page_exists(tmp_path):
    from stackvitals.ci.action import write_outputs
    result = {"window_days": 30, "generated": "2026-10-17T00:00:00Z", "runs": 0}
    write_outputs(tmp_path, result, "o/r")
    assert "flow.html" not in (tmp_path / "docs" / "ci.html").read_text(encoding="utf-8")
    (tmp_path / "docs" / "flow.html").write_text("x", encoding="utf-8")
    write_outputs(tmp_path, result, "o/r")
    assert "flow.html" in (tmp_path / "docs" / "ci.html").read_text(encoding="utf-8")


def test_opt_in_preflight_comments_once_on_new_outside_prs_that_miss_local_habits(tmp_path):
    import httpx
    from stackvitals.ci.api import ActionsAPI
    posted = []

    def handler(request):
        if request.method == "POST" and request.url.path.endswith("/comments"):
            posted.append((int(request.url.path.split("/")[5]), json.loads(request.content)["body"]))
            return httpx.Response(201, json={})
        return httpx.Response(404, json={})
    make_api = lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),  # noqa: E731
                                                    sleep=lambda s: None, **kw)

    def with_files(nd, paths):
        return nd | {"files": {"nodes": [{"path": p} for p in paths]}}
    history = [with_files(node(100 + k, "MERGED", updated=200 + k, merged=200 + k), ["src/db/a.py", "tests/test_a.py"])
               for k in range(12)]
    old_pr = with_files(node(1, updated=150), ["src/db/x.py"])
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": remote(tmp_path).as_uri(),
           "GITHUB_EVENT_NAME": "schedule", "RUNNER_TEMP": str(tmp_path / "tmp")}
    run_flow_action(env, now=NOW, make_gql=lambda tok: Pages(history + [old_pr]), make_api=make_api, preflight_comments=True)
    assert posted == []  # the first run never comments on PRs that were already open
    new_pr = with_files(node(2, updated=-1) | {"createdAt": at(-1)}, ["src/db/y.py"])
    # One login is one person: the insider PR comes from a member, not from alice under another label.
    insider_pr = with_files(node(3, updated=-1, assoc="MEMBER") | {"createdAt": at(-1), "author": {"__typename": "User", "login": "maint"}},
                            ["src/db/z.py"])
    later = NOW + timedelta(hours=3)
    run_flow_action(env, now=later, make_gql=lambda tok: Pages(history + [old_pr, new_pr, insider_pr]), make_api=make_api,
                    preflight_comments=True)
    assert [n for n, _ in posted] == [2] and "stackvitals:preflight" in posted[0][1] and "test files" in posted[0][1]
    run_flow_action(env, now=later + timedelta(hours=3), make_gql=lambda tok: Pages(history + [old_pr, new_pr]),
                    make_api=make_api, preflight_comments=True)
    assert len(posted) == 1
