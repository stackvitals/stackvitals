import json
import subprocess
from datetime import datetime, timedelta, timezone

import httpx

from mergescout.github.graphql import GraphQLError, GraphQLResult
from stackvitals.ci.api import ActionsAPI
from stackvitals.community.action import run_community_action

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def at(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr_node(n, login, hours_ago, merged=False):
    return {"number": n, "title": "Fix", "isDraft": False, "state": "MERGED" if merged else "OPEN", "createdAt": at(hours_ago),
            "updatedAt": at(hours_ago - 1), "mergedAt": at(hours_ago - 1) if merged else None,
            "closedAt": at(hours_ago - 1) if merged else None, "additions": 1, "deletions": 1, "changedFiles": 1,
            "author": {"__typename": "User", "login": login}, "authorAssociation": "NONE", "baseRefName": "main",
            "headRefName": "x", "headRepositoryOwner": {"login": login}, "commits": {"nodes": []},
            "reviewRequests": {"nodes": []}, "events": {"filteredCount": 0, "nodes": []}, "talk": {"filteredCount": 0, "nodes": []}}


def issue_node(n, login, hours_ago):
    return {"number": n, "state": "OPEN", "createdAt": at(hours_ago), "updatedAt": at(hours_ago), "closedAt": None,
            "author": {"__typename": "User", "login": login}, "authorAssociation": "NONE", "comments": {"totalCount": 0, "nodes": []}}


class Fake:
    """Answers the PR, issue and repo-detail queries apart, and counts each kind."""

    def __init__(self, issues_refused=False):
        self.kinds, self.issues_refused = [], issues_refused

    def query(self, query, variables=None, **kw):
        kind = "issues" if "issues(first" in query else "prs" if "pullRequests(first" in query else "other"
        self.kinds.append(kind)
        if kind == "issues" and self.issues_refused:
            raise GraphQLError("Resource not accessible by integration")
        repo = {"issues": {"pageInfo": {"hasNextPage": False}, "nodes": [issue_node(5, "newbie", 30)]}} if kind == "issues" else \
            {"pullRequests": {"pageInfo": {"hasNextPage": False}, "nodes": [pr_node(1, "fresh", 50), pr_node(2, "amy", 900, True)]}} \
            if kind == "prs" else {"defaultBranchRef": {"name": "main"}, "primaryLanguage": {"name": "Python"}, "stargazerCount": 10}
        return GraphQLResult(data={"repository": repo}, cost=1, remaining=999, reset_at=at(0))


def rest(traffic_status=200):
    def handler(request):
        path = request.url.path
        if path.endswith("/stargazers/history"):
            start = int(NOW.timestamp()) // 604800 * 604800
            return httpx.Response(200, json=[{"week": start - i * 604800, "total": 2, "days": []} for i in range(14)])
        if "/traffic/" in path:
            if traffic_status != 200:
                return httpx.Response(traffic_status, json={"message": "Resource not accessible by integration"})
            if path.endswith("/views") or path.endswith("/clones"):
                key = path.rsplit("/", 1)[1]
                return httpx.Response(200, json={key: [{"timestamp": "2026-10-18T00:00:00Z", "count": 4, "uniques": 2}]})
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={})
    return lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),
                                                sleep=lambda s: None, **kw)


def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare


def show(bare, path):
    return subprocess.run(["git", "show", f"stackvitals-data:{path}"], cwd=bare, capture_output=True, text=True).stdout


def env_for(tmp_path, bare, event="schedule", **extra):
    return {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(), "GITHUB_EVENT_NAME": event,
            "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md"), **extra}


def test_the_action_keeps_issues_and_stars_and_publishes_the_page_and_badges(tmp_path):
    bare, gql = remote(tmp_path), Fake()
    out = run_community_action(env_for(tmp_path, bare), now=NOW, make_gql=lambda tok: gql, make_api=rest())
    assert out["pushed"] and out["issues"] == 1 and "prs" in gql.kinds  # Team Flow didn't run, so PRs are read here
    assert "Community" in show(bare, "docs/community.html") and json.loads(show(bare, "community/issues/open.json"))[0]["n"] == 5
    assert json.loads(show(bare, "docs/community-score.json"))["schemaVersion"] == 1
    assert len(json.loads(show(bare, "community/stars.json"))["weeks"]) == 14
    summary = (tmp_path / "s.md").read_text(encoding="utf-8")
    assert "PR \\#1: waiting 2 days" in summary and "Issue \\#5: waiting 1 day\n" in summary
    assert "Traffic is off" in summary and "growth" not in summary  # a 10-star repo gets no growth percentage


def test_after_team_flow_the_prs_it_saved_are_reused_not_read_again(tmp_path):
    bare, gql = remote(tmp_path), Fake()
    run_community_action(env_for(tmp_path, bare), now=NOW, make_gql=lambda tok: gql, make_api=rest(), flow_ran=True)
    assert "prs" not in gql.kinds


def test_traffic_is_kept_with_a_token_that_may_read_it_and_explained_without_one(tmp_path):
    bare = remote(tmp_path)
    run_community_action(env_for(tmp_path, bare, STACKVITALS_TRAFFIC_TOKEN="app-token"), now=NOW,
                         make_gql=lambda tok: Fake(), make_api=rest())
    assert json.loads(show(bare, "community/traffic.json"))["views"] == {"2026-10-18": [4, 2]}
    bare2 = remote(tmp_path / "b")
    run_community_action(env_for(tmp_path, bare2, STACKVITALS_TRAFFIC_TOKEN="weak"), now=NOW, make_gql=lambda tok: Fake(),
                         make_api=rest(traffic_status=403))
    assert "Administration" in (tmp_path / "s.md").read_text(encoding="utf-8")


def test_a_token_that_cannot_read_issues_says_what_to_add_and_the_run_goes_on(tmp_path):
    bare = remote(tmp_path)
    out = run_community_action(env_for(tmp_path, bare), now=NOW, make_gql=lambda tok: Fake(issues_refused=True), make_api=rest())
    assert out["pushed"] and "issues: read" in (tmp_path / "s.md").read_text(encoding="utf-8")


def test_ci_triggered_and_pull_request_runs_leave_community_alone(tmp_path):
    for event in ("workflow_run", "pull_request"):
        assert run_community_action(env_for(tmp_path, remote(tmp_path / event), event), now=NOW,
                                    make_gql=lambda tok: Fake(), make_api=rest()) is None


def test_the_action_runs_community_after_team_flow_and_tells_it_so(tmp_path, monkeypatch, capsys):
    import stackvitals.ci.cli as cli
    import stackvitals.community.action as ca
    seen = {}
    monkeypatch.setattr(cli, "run_flow_action", lambda env, **k: {"prs": 1, "points": 1, "queue": 0, "pushed": True})
    monkeypatch.setattr(ca, "run_community_action", lambda env, **k: (seen.update(k), {"issues": 3, "points": 2, "waiting": 1,
                                                                                         "score": 61, "pushed": True})[1])
    bare = remote(tmp_path)
    for key, value in (("GITHUB_EVENT_NAME", "schedule"), ("GITHUB_REPOSITORY", "o/r"), ("STACKVITALS_TOKEN", "tok"),
                       ("STACKVITALS_REMOTE", bare.as_uri()), ("RUNNER_TEMP", str(tmp_path / "tmp"))):
        monkeypatch.setenv(key, value)
    # One job: Team Flow's result sits in the shared workspace when Community runs, so it knows the PRs are fresh.
    assert cli.action_main(["--modules", "flow,community"]) == 0 and seen["workspace"].results.get("Team Flow") is not None
    # The data is saved because Delivery writes its first page after both modules.
    assert "Community: 3 issues read (2 points), 1 newcomer waiting, score 61/100, data saved." in capsys.readouterr().out
    assert cli.action_main(["--modules", "community"]) == 0 and seen["workspace"].results.get("Team Flow") is None


def test_the_template_and_action_carry_community_with_issue_access_and_an_optional_traffic_token():
    from pathlib import Path

    from stackvitals.ci.cli import workflow_template
    text = workflow_template("o/a@v0", ["CI"])
    assert "modules: ci,flow,deps,community" in text and "issues: write" in text and "traffic-token" in text
    action = Path(__file__).parents[2].joinpath("action.yml").read_text(encoding="utf-8")
    assert "traffic-token:" in action and "STACKVITALS_TRAFFIC_TOKEN: ${{ inputs.traffic-token }}" in action
