"""One CI Health reader for MCP, the CLI and the brief: the repo's published file, else a fresh local copy, else a live
read that includes test reports, the benchmark and the same budget."""
import json
from datetime import datetime, timedelta, timezone

import httpx
from ci_fake import FakeGitHub, Run, job

from stackvitals.core import services
from stackvitals.ci.api import ActionsAPI

PUBLISHED = {"window_days": 30, "generated": "2026-10-16T00:00:00Z", "runs": 9, "jobs": [], "tests": [], "pushes": {}}


def make_api(handler):
    def make(token, repo, **kw):
        return ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None, **kw)
    return make


def test_a_repo_running_stackvitals_answers_from_its_published_file(tmp_path):
    def handler(request):
        if request.url.path == "/repos/o/r/contents/docs/data.json":
            return httpx.Response(200, content=json.dumps(PUBLISHED).encode())
        return httpx.Response(404, json={"message": "Not Found"})
    result, source = services.ci_result("o/r", 14, "tok", tmp_path, make_api=make_api(handler))
    assert result["runs"] == 9 and source == "stackvitals-data branch"


def test_a_live_read_includes_test_reports_and_the_benchmark_and_is_reused_within_the_hour(tmp_path, monkeypatch):
    t = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=1)
    fake = FakeGitHub([Run(1, t, [("failure", [job(11, "lint", "failure", t, 30)]),
                                  ("success", [job(12, "lint", "success", t + timedelta(minutes=10), 30, attempt=2)])])])

    def handler(request):
        if request.url.path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main", "language": "Python", "stargazers_count": 500})
        if request.url.path.endswith("/contents/docs/data.json"):
            return httpx.Response(404, json={"message": "Not Found"})
        return fake.handle(request)
    seen = {}
    real_collect = services.collect

    def spy(api, store, now, **kw):
        seen.update(kw)
        return real_collect(api, store, now, **kw)
    monkeypatch.setattr(services, "collect", spy)
    result, source = services.ci_result("o/r", 7, "tok", tmp_path, make_api=make_api(handler))
    assert source.startswith("read live from GitHub, last 7 days") and seen["tests"] is True and seen["days"] == 7
    assert result["jobs"][0]["job"] == "lint" and "benchmark" in result
    calls = len(fake.calls)
    again, source2 = services.ci_result("o/r", 7, "tok", tmp_path, make_api=make_api(handler))
    # No run or job is read again within the hour (the benchmark file may still be looked up once).
    assert source2 == "local copy read within the hour" and not any("/actions/" in c for c in fake.calls[calls:])
    assert "benchmark" in again and again["jobs"][0]["job"] == "lint"
    assert services.DEFAULT_BUDGET == 1500
