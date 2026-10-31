import json
from datetime import datetime, timedelta, timezone

import anyio
import httpx
from ci_fake import T0, FakeGitHub, Run, job
from mcp import Client
from stackvitals.ci.api import ActionsAPI
from stackvitals.mcp_server import build_server

from mergescout.mcp_server import App

MCP_RESULT = {"window_days": 30, "generated": "2026-10-16T00:00:00Z", "runs": 90, "rerun_share": 0.05, "infra_events": 0,
          "queue": {"median_s": 4, "p95_s": 30}, "minutes": {"linux": 100, "windows": 0, "macos": 0, "other": 0},
          "has_test_reports": True, "test_outages": 0, "slow_tests": [],
          "jobs": [{"workflow": ".github/workflows/ci.yml", "job": "e2e (chrome)", "state": "flaky", "flake_events": 5,
                    "runs": 60, "flake_rate": 0.08, "rate_low": 0.03, "rate_high": 0.18, "failures": 6,
                    "last_flake": "2026-10-15T00:00:00Z", "top_step": "Run tests", "retry_minutes": 30,
                    "prs_affected": [], "median_s": 300, "p95_s": 400, "slower": None}],
          "tests": [{"id": "tests/test_upload.py::test_retry", "suite": "test-results", "runs": 80, "failures": 4,
                     "flake_events": 4, "flake_rate": 0.05, "rate_low": 0.02, "rate_high": 0.12, "state": "flaky",
                     "last_flake": "2026-10-14T00:00:00Z", "message": "ConnectionResetError", "prs_affected": []}]}


class NoRel:
    def list_releases(self):
        raise OSError("offline")


def server_with(handler, tmp_path):
    def make_api(token, repo, **kw):
        return ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None, **kw)
    app = App(root=tmp_path / "home", releases=NoRel(), live=None, log=lambda *a: None)
    return build_server(app, ci_api=make_api, ci_home=tmp_path / "svhome", ci_token="tok")


def mcp_call(server, name, args):
    async def run():
        async with Client(server) as c:
            r = await c.call_tool(name, args)
            return json.loads(r.content[0].text)
    return anyio.run(run)


def installed(request):
    # The repo already runs StackVitals: its findings are one file in the data branch.
    if request.url.path == "/repos/o/r/contents/docs/data.json":
        assert request.url.params["ref"] == "stackvitals-data"
        return httpx.Response(200, content=json.dumps(MCP_RESULT).encode())
    return httpx.Response(404, json={"message": "Not Found"})


def test_the_suite_server_adds_ci_tools_to_mergescouts(tmp_path):
    async def names():
        async with Client(server_with(installed, tmp_path)) as c:
            return {t.name for t in (await c.list_tools()).tools}
    tools = anyio.run(names)
    assert {"find_issues", "ci_health", "is_known_flake", "ci_failure", "ci_slowest", "repo_brief"} <= tools


def test_ci_health_without_stackvitals_installed_reads_recent_history(tmp_path):
    # The server reads the real last days, so the fake run is dated yesterday.
    t = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=1)
    fake = FakeGitHub([Run(1, t, [("failure", [job(11, "lint", "failure", t, 30)]),
                                  ("success", [job(12, "lint", "success", t + timedelta(minutes=10), 30, attempt=2)])])])

    def handler(request):
        if request.url.path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main"})
        if request.url.path.endswith("/contents/docs/data.json"):
            return httpx.Response(404, json={"message": "Not Found"})
        return fake.handle(request)
    out = mcp_call(server_with(handler, tmp_path), "ci_health", {"repo": "o/r", "days": 7})
    assert out["source"].startswith("read live") and out["flaky_jobs"][0]["job"] == "lint"


def test_ci_failure_explains_a_failed_run_by_its_url(tmp_path):
    t = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=3)
    failed = Run(77, t, [("failure", [job(771, "e2e (chrome)", "failure", t, 60)])], tree="z")

    def handler(request):
        path = request.url.path
        if path == "/repos/o/r/actions/runs/77":
            return httpx.Response(200, json=failed.body())
        if path.endswith("/actions/runs/77/artifacts"):
            return httpx.Response(200, json={"artifacts": []})
        return installed(request) if "contents" in path else FakeGitHub([failed]).handle(request)
    out = mcp_call(server_with(handler, tmp_path), "ci_failure", {"run": "https://github.com/o/r/actions/runs/77"})
    # One earlier flake is too little to call this one safe (Phase 13 masking check): it says to look first.
    assert out["failures"][0]["verdict"] == "flaked before" and "flaked before" in out["summary"]


# Real use (2026-10-16): each MCP question re-read GitHub and took 30 s; a copy read within the hour is reused.
def test_a_second_question_within_the_hour_does_not_read_github_again(tmp_path):
    t = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=1)
    fake = FakeGitHub([Run(1, t, [("success", [job(11, "lint", "success", t, 30)])])])

    def handler(request):
        if request.url.path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main"})
        if request.url.path.endswith("/contents/docs/data.json"):
            return httpx.Response(404, json={"message": "Not Found"})
        return fake.handle(request)
    server = server_with(handler, tmp_path)
    mcp_call(server, "ci_health", {"repo": "o/r", "days": 7})
    before = len(fake.calls)
    out = mcp_call(server, "ci_slowest", {"repo": "o/r"})
    # No run or job is read again; only the small benchmark file may be looked up (it is cached once it exists).
    assert not any("/actions/" in c for c in fake.calls[before:]) and "within the hour" in out["source"]


def test_ci_health_tells_an_agent_how_the_repo_compares(tmp_path):
    cmp = {"group": "Python repos", "repos": 412, "metrics": [
        {"name": "Time from push to all checks done", "kind": "time", "you": 450, "typical": 300,
         "place": "slower than about 80%"}]}

    def handler(request):
        if request.url.path == "/repos/o/r/contents/docs/data.json":
            return httpx.Response(200, content=json.dumps({**MCP_RESULT, "benchmark": cmp}).encode())
        return httpx.Response(404, json={"message": "Not Found"})
    out = mcp_call(server_with(handler, tmp_path), "ci_health", {"repo": "o/r"})
    assert out["compared_with_similar_repos"]["group"] == "Python repos"
    assert mcp_call(server_with(installed, tmp_path), "ci_health", {"repo": "o/r"})["compared_with_similar_repos"] is None


def test_pr_queue_reads_the_data_branch_or_collects_live(tmp_path):
    from mergescout.github.graphql import GraphQLResult
    flow = {"window_days": 90, "generated": "2026-10-17T00:00:00Z", "open": 3, "drafts": 0, "merged": 10, "closed_unmerged": 1,
            "stale": 2, "merged_without_review": 1, "stages": {k: {"median_s": 7200, "p90_s": 9000, "n": 10}
                                                               for k in ("pickup", "review", "merge", "cycle")},
            "groups": {g: {"merged": 5, "closed_unmerged": 0, "merge_rate": 1.0, "pickup": {"median_s": 3600, "p90_s": 3600, "n": 5}}
                       for g in ("insider", "outsider")},
            "queue": [{"n": 7, "title": "Fix", "author": "alice", "outsider": True, "actor": "reviewers", "who": ["carol"],
                       "why": "review requested", "since": "2026-10-15T00:00:00Z", "step": "pickup", "waiting_s": 172800,
                       "usual_s": 36000, "stale": False, "slow": True}], "load": [], "monthly": [], "bots": {"open": 0, "closed": 0},
            "baselines": {}}

    def handler(request):
        if request.url.path == "/repos/o/r/contents/docs/flow.json":
            return httpx.Response(200, content=json.dumps(flow).encode())
        return httpx.Response(404, json={"message": "Not Found"})
    out = mcp_call(server_with(handler, tmp_path), "pr_queue", {"repo": "o/r"})
    assert out["source"] == "stackvitals-data branch" and out["waiting"][0]["pr"] == 7 and out["waiting"][0]["overdue"]
    assert out["stale"] == 2
    health = mcp_call(server_with(handler, tmp_path), "flow_health", {"repo": "o/r"})
    assert health["stages"]["pickup"]["median_hours"] == 2.0 and health["outsiders"]["merge_rate"] == 1.0

    class OnePR:
        def query(self, query, variables=None, **kw):
            node = {"number": 3, "title": "Add", "isDraft": False, "state": "OPEN", "createdAt": "2026-10-10T00:00:00Z",
                    "updatedAt": "2026-10-16T00:00:00Z", "mergedAt": None, "closedAt": None, "additions": 1, "deletions": 0,
                    "changedFiles": 1, "author": {"__typename": "User", "login": "dan"}, "authorAssociation": "NONE",
                    "commits": {"nodes": []}, "reviewRequests": {"nodes": []}, "events": {"nodes": []}, "talk": {"nodes": []}}
            data = {"rateLimit": {"cost": 1, "remaining": 999, "resetAt": "2026-10-17T00:00:00Z"},
                    "repository": {"pullRequests": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [node]}}}
            return GraphQLResult(data=data, cost=1, remaining=999, reset_at="2026-10-17T00:00:00Z")

    def nothing(request):
        return httpx.Response(404, json={"message": "Not Found"})

    def make_api(token, repo, **kw):
        return ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(nothing)), sleep=lambda s: None, **kw)
    app = App(root=tmp_path / "home2", releases=NoRel(), live=None, log=lambda *a: None)
    live = build_server(app, ci_api=make_api, ci_home=tmp_path / "sv2", ci_token="tok", flow_gql=lambda tok: OnePR())
    out = mcp_call(live, "pr_queue", {"repo": "o/r"})
    assert out["source"].startswith("read live") and out["waiting"][0]["pr"] == 3


def test_who_should_review_names_people_who_know_the_changed_area(tmp_path):
    from mergescout.github.graphql import GraphQLResult

    def pr_node(n, state, au, assoc, paths, reviews=(), when="2026-10-10T00:00:00Z"):
        return {"number": n, "title": "x", "isDraft": False, "state": state, "createdAt": when, "updatedAt": when,
                "mergedAt": when if state == "MERGED" else None, "closedAt": when if state == "MERGED" else None,
                "additions": 1, "deletions": 0, "changedFiles": 1, "author": {"__typename": "User", "login": au},
                "authorAssociation": assoc, "files": {"nodes": [{"path": p} for p in paths]}, "commits": {"nodes": []},
                "reviewRequests": {"nodes": []}, "talk": {"nodes": []},
                "events": {"nodes": [{"__typename": "PullRequestReview", "submittedAt": when, "state": "APPROVED",
                                      "author": {"__typename": "User", "login": r}, "authorAssociation": "MEMBER"} for r in reviews]}}
    nodes = [pr_node(9, "OPEN", "zed", "NONE", ["src/db/new.py"], when="2026-10-16T00:00:00Z")]
    nodes += [pr_node(k, "MERGED", "dana", "MEMBER", ["src/db/pool.py"], reviews=["erin"], when=f"2026-10-0{k}T00:00:00Z")
              for k in range(1, 6)]

    class Repo:
        def query(self, query, variables=None, **kw):
            body = {"pullRequests": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}
            data = {"rateLimit": {"cost": 1, "remaining": 999, "resetAt": "2026-10-17T00:00:00Z"}, "repository": body}
            return GraphQLResult(data=data, cost=1, remaining=999, reset_at="2026-10-17T00:00:00Z")

    def nothing(request):
        return httpx.Response(404, json={"message": "Not Found"})

    def make_api(token, repo, **kw):
        return ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(nothing)), sleep=lambda s: None, **kw)
    app = App(root=tmp_path / "h", releases=NoRel(), live=None, log=lambda *a: None)
    server = build_server(app, ci_api=make_api, ci_home=tmp_path / "sv", ci_token="tok", flow_gql=lambda tok: Repo())
    out = mcp_call(server, "who_should_review", {"repo": "o/r", "pr": 9})
    assert [s["login"] for s in out["suggested"]][:2] == ["dana", "erin"] and "src/db" in out["suggested"][0]["why"]


def test_is_known_flake_asks_a_test_with_one_flake_to_be_checked_first(tmp_path, monkeypatch):
    once = {**MCP_RESULT, "tests": [{**MCP_RESULT["tests"][0], "flake_events": 1}]}

    def handler(request):
        if request.url.path == "/repos/o/r/contents/docs/data.json":
            return httpx.Response(200, content=json.dumps(once).encode())
        return httpx.Response(404, json={"message": "Not Found"})
    out = mcp_call(server_with(handler, tmp_path), "is_known_flake", {"repo": "o/r", "name": "test_retry"})
    assert out["verdict"] == "flaked before"
    out = mcp_call(server_with(installed, tmp_path), "is_known_flake", {"repo": "o/r", "name": "test_retry"})
    assert out["verdict"] == "known flaky"


def test_ci_failure_checks_the_default_branch_and_hands_the_agent_its_evidence(tmp_path):
    # Agents re-checked everything live (259 calls with StackVitals, 214 without): the answer now carries the error
    # lines, links, what was already checked and how often each verdict has been right.
    t = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
    pr = Run(77, t, [("failure", [job(771, "build", "failure", t, 60)])], tree="z", event="pull_request", branch="fix", pr=5)
    main = Run(70, t - timedelta(hours=5), [("failure", [job(701, "build", "failure", t - timedelta(hours=5), 60)])], tree="m")
    error = "2026-10-22T10:00:00.0000000Z sccache: error: Server startup failed: cache storage failed to read: 503\n" \
            "2026-10-22T10:00:01.0000000Z ##[error]Process completed with exit code 1."
    asked = []

    def handler(request):
        path = request.url.path
        asked.append(path)
        if path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main"})
        if path == "/repos/o/r/actions/runs":
            assert request.url.params["branch"] == "main" and request.url.params["status"] == "failure"
            return httpx.Response(200, json={"workflow_runs": [main.body()]})
        if path in ("/repos/o/r/actions/jobs/771/logs", "/repos/o/r/actions/jobs/701/logs"):
            return httpx.Response(200, content=error.encode())
        if path == "/repos/o/r/actions/runs/77":
            return httpx.Response(200, json=pr.body())
        if path.endswith("/artifacts"):
            return httpx.Response(200, json={"artifacts": []})
        if "contents" in path:
            return installed(request)
        return FakeGitHub([pr, main]).handle(request)
    out = mcp_call(server_with(handler, tmp_path), "ci_failure", {"run": "https://github.com/o/r/actions/runs/77"})
    item = out["failures"][0]
    assert item["verdict"] == "already failing"
    assert item["url"] == "https://github.com/o/r/actions/runs/77/job/771"
    assert any("sccache: error" in line for line in item["errors"])
    assert item["right_so_far"] and "of" in item["right_so_far"]
    assert any("default branch" in c for c in out["checked"]) and any("log" in c for c in out["checked"])
