"""A fake GitHub Actions API for CI Health tests: runs, attempts and jobs served from plain dicts."""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def step(n, name, conclusion, start, secs):
    return {"number": n, "name": name, "status": "completed", "conclusion": conclusion,
            "started_at": iso(start), "completed_at": iso(start + timedelta(seconds=secs))}


def job(jid, name, conclusion, start, secs, attempt=1, failing_step="Run tests", labels=("ubuntu-latest",), queue=5):
    created = start - timedelta(seconds=queue)
    steps = [step(1, "Set up job", "success", start, 2),
             step(2, "Install dependencies", "failure" if conclusion == "failure" and failing_step == "Install dependencies" else "success",
                  start + timedelta(seconds=2), 20),
             step(3, "Run tests", "failure" if conclusion == "failure" and failing_step == "Run tests" else "success",
                  start + timedelta(seconds=22), max(secs - 22, 1))]
    return {"id": jid, "run_attempt": attempt, "name": name, "status": "completed", "conclusion": conclusion,
            "created_at": iso(created), "started_at": iso(start), "completed_at": iso(start + timedelta(seconds=secs)),
            "labels": list(labels), "runner_name": "GitHub Actions 1", "steps": steps}


class Run:
    """One workflow run with its attempts; attempts[i] = (conclusion, [jobs])."""

    def __init__(self, rid, created, attempts, tree="t1", sha="s1", event="push", branch="main", pr=None,
                 path=".github/workflows/ci.yml", name="CI", fork_owner=None):
        self.rid, self.created, self.attempts, self.fork_owner = rid, created, attempts, fork_owner
        self.tree, self.sha, self.event, self.branch, self.pr, self.path, self.name = tree, sha, event, branch, pr, path, name

    def body(self, attempt=None):
        n = attempt or len(self.attempts)
        return {"id": self.rid, "name": self.name, "path": self.path, "workflow_id": 7, "event": self.event,
                "status": "completed", "conclusion": self.attempts[n - 1][0], "head_branch": self.branch,
                "head_sha": self.sha, "run_attempt": n, "run_number": self.rid, "created_at": iso(self.created),
                "run_started_at": iso(self.created + timedelta(minutes=10 * (n - 1))),
                "updated_at": iso(self.created + timedelta(minutes=10 * n)),
                "head_commit": {"id": self.sha, "tree_id": self.tree},
                "head_repository": {"owner": {"login": self.fork_owner or "o"}},
                # GitHub lists no PRs for fork PR runs, and unrelated ones on some other runs.
                "pull_requests": [] if self.fork_owner else [{"number": self.pr}] if self.pr else [{"number": 999}]}


class FakeGitHub:
    def __init__(self, runs, remaining=5000, fail_first=0, drop_first=0, broken_runs=(), flaky_5xx=0, artifacts=None, logs=None):
        self.runs = {r.rid: r for r in runs}
        # logs: {job_id: log text}; other jobs' logs are not found.
        self.logs = logs or {}
        self.calls, self.remaining, self.fail_first, self.drop_first = [], remaining, fail_first, drop_first
        self.broken_runs, self.flaky_5xx = set(broken_runs), flaky_5xx
        # artifacts: {run_id: [(artifact_id, name, zip_bytes, created_at datetime)]}
        self.artifacts = artifacts or {}

    def transport(self):
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        if self.drop_first:
            self.drop_first -= 1
            raise httpx.RemoteProtocolError("peer closed connection without sending complete message body")
        if self.fail_first:
            self.fail_first -= 1
            return httpx.Response(403, headers={"retry-after": "0"}, json={"message": "You have exceeded a secondary rate limit"})
        self.remaining -= 1
        headers = {"x-ratelimit-remaining": str(self.remaining), "x-ratelimit-reset": "9999999999"}
        path, q = request.url.path, parse_qs(request.url.query.decode())
        if m := re.fullmatch(r"/repos/o/r/actions/runs", path):
            day = q["created"][0]
            lo, hi = (day.split("..") + [day])[:2]
            found = [r.body() for r in sorted(self.runs.values(), key=lambda r: r.created, reverse=True)
                     if lo <= r.created.strftime("%Y-%m-%d") <= hi]
            page, per = int(q.get("page", ["1"])[0]), int(q["per_page"][0])
            return httpx.Response(200, headers=headers,
                                  json={"total_count": len(found), "workflow_runs": found[(page - 1) * per:page * per]})
        if m := re.fullmatch(r"/repos/o/r/actions/runs/(\d+)/attempts/(\d+)/jobs", path):
            if int(m[1]) in self.broken_runs:
                return httpx.Response(502, json={"message": "Server Error"})
            if self.flaky_5xx:
                self.flaky_5xx -= 1
                return httpx.Response(502, json={"message": "Server Error"})
            run, n = self.runs[int(m[1])], int(m[2])
            jobs = run.attempts[n - 1][1]
            return httpx.Response(200, headers=headers, json={"total_count": len(jobs), "jobs": jobs})
        if m := re.fullmatch(r"/repos/o/r/actions/runs/(\d+)/artifacts", path):
            arts = [{"id": a, "name": n, "size_in_bytes": len(z), "expired": False, "created_at": iso(c)}
                    for a, n, z, c in self.artifacts.get(int(m[1]), [])]
            return httpx.Response(200, headers=headers, json={"total_count": len(arts), "artifacts": arts})
        if m := re.fullmatch(r"/repos/o/r/actions/artifacts/(\d+)/zip", path):
            for arts in self.artifacts.values():
                for a, n, z, c in arts:
                    if a == int(m[1]):
                        return httpx.Response(200, headers=headers, content=z)
            return httpx.Response(410, json={"message": "Artifact has expired"})
        if (m := re.fullmatch(r"/repos/o/r/actions/jobs/(\d+)/logs", path)) and int(m[1]) in self.logs:
            return httpx.Response(200, headers=headers, content=self.logs[int(m[1])].encode())
        if m := re.fullmatch(r"/repos/o/r/actions/runs/(\d+)/attempts/(\d+)", path):
            return httpx.Response(200, headers=headers, json=self.runs[int(m[1])].body(int(m[2])))
        return httpx.Response(404, json={"message": "Not Found"})


# A registry outage in a failing step's log: what a known flake needs besides its history (pre-registered 2026-10-28).
NET_LOG = "##[group]Run tests\nnpm ERR! getaddrinfo ENOTFOUND registry.npmjs.org\n##[error]Process completed with exit code 1."
