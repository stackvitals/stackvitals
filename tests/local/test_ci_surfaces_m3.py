"""Monitors and failure groups on every surface: the CI page, the job summary, the CLI route and two MCP tools."""
import json

import httpx

from stackvitals.ci.report import render_html, render_markdown

GROUP = {"id": "c0ffee123456", "type": "java.net.UnknownHostException", "where": "io.netty.dns.Ctx.finish<script>",
         "message": "Failed to resolve 'x'", "failures": 20, "tests": 9, "runs": 3, "first": "2026-10-01T00:00:00Z",
         "last": "2026-10-19T00:00:00Z", "top_tests": ["a::t1"], "examples": [{"run": 77, "att": 1, "test": "a::t1"}]}
TEST = {"id": "a::t1", "suite": "junit", "runs": 40, "failures": 6, "flake_events": 4, "flake_rate": 0.1, "rate_low": 0.04,
        "rate_high": 0.23, "state": "flaky", "monitors": ["pass_on_retry", "failure_rate"], "labels": ["slow"],
        "since": "2026-10-05T00:00:00Z", "failure_rate": 0.15, "last_flake": "2026-10-19T00:00:00Z", "message": "boom",
        "prs_affected": [], "evidence": [], "group": "c0ffee123456", "muted_until": "2026-11-01"}


def result():
    return {"window_days": 30, "generated": "2026-10-20T00:00:00Z", "runs": 90, "rerun_share": 0.05, "infra_events": 0,
            "queue": {"median_s": 4, "p95_s": 30}, "minutes": {"linux": 100, "windows": 0, "macos": 0, "other": 0},
            "has_test_reports": True, "test_outages": 0, "slow_tests": [], "jobs": [], "tests": [TEST],
            "failure_groups": [GROUP], "pushes": {}, "weekly": [], "history": {"jobs": {}, "tests": {}}}


def test_the_page_shows_why_since_when_mutes_and_failure_groups_safely():
    page = render_html(result(), "o/r")
    assert "Failure groups" in page and "9 tests" in page and "java.net.UnknownHostException" in page
    assert "Ctx.finish<script>" not in page and "Ctx.finish&lt;script&gt;" in page
    assert "since 2026-10-05" in page and "pass on retry" in page and "failure rate 15%" in page and "slow" in page
    assert "muted until 2026-11-01" in page
    assert "https://github.com/o/r/actions/runs/77/attempts/1" in page


def test_the_summary_names_the_biggest_group():
    md = render_markdown(result(), "o/r")
    assert "same failure in 9 tests" in md and "UnknownHostException" in md


def test_ci_upload_is_reached_from_the_ci_command(monkeypatch):
    import stackvitals.ci.cli as ci_cli
    import stackvitals.ci.upload as upload
    seen = []
    monkeypatch.setattr(upload, "main", lambda argv: seen.append(argv) or 0)
    assert ci_cli.main(["upload", "--sha", "a", "--branch", "main", "r.xml"]) == 0 and seen == [["--sha", "a", "--branch", "main", "r.xml"]]


def test_mcp_tools_answer_test_status_and_failure_groups(tmp_path):
    import anyio
    from mcp import Client
    from stackvitals.ci.api import ActionsAPI
    from stackvitals.mcp_server import build_server
    from mergescout.mcp_server import App

    def handler(request):
        if request.url.path == "/repos/o/r/contents/docs/data.json":
            return httpx.Response(200, content=json.dumps(result()).encode())
        return httpx.Response(404, json={"message": "Not Found"})

    class NoRel:
        def list_releases(self):
            raise OSError("offline")
    make = lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),  # noqa: E731
                                                sleep=lambda s: None, **kw)
    server = build_server(App(root=tmp_path / "h", releases=NoRel(), live=None, log=lambda *a: None), ci_api=make,
                          ci_home=tmp_path / "sv", ci_token="tok")

    async def call(name, args):
        async with Client(server) as c:
            r = await c.call_tool(name, args)
            return json.loads(r.content[0].text)
    status = anyio.run(call, "test_status", {"repo": "o/r", "test": "t1"})
    m = status["matches"][0]
    assert m["state"] == "flaky" and m["since"] == "2026-10-05T00:00:00Z" and m["monitors"] == ["pass_on_retry", "failure_rate"]
    assert m["muted_until"] == "2026-11-01" and m["group"]["tests"] == 9
    groups = anyio.run(call, "failure_group", {"repo": "o/r"})
    assert groups["groups"][0]["id"] == "c0ffee123456" and groups["groups"][0]["examples"][0]["url"].endswith("/runs/77/attempts/1")
    one = anyio.run(call, "failure_group", {"repo": "o/r", "group": "c0ffee"})
    assert len(one["groups"]) == 1
