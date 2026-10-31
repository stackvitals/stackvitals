"""GitLab CI, read-only: a project's pipelines and jobs in the same shapes as GitHub Actions runs, so the same flaky-job
detection, reports and pages work. A retried GitLab job becomes a re-run attempt (attempt N holds each job's Nth try, or
its last one), like GitHub's "re-run failed jobs"; merge request pipelines count as pull requests.

    stackvitals ci gitlab group/project [--days 14] [--json]

Public projects need no token (GITLAB_TOKEN is used when set, for private ones and higher limits)."""
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

from stackvitals.ci.api import APIError, OutOfBudget

API = "https://gitlab.com/api/v4"
STATUS = {"success": "success", "failed": "failure", "canceled": "cancelled", "skipped": "skipped", "manual": "skipped"}
EVENTS = {"merge_request_event": "pull_request", "push": "push", "schedule": "schedule", "web": "workflow_dispatch",
          "api": "workflow_dispatch", "trigger": "workflow_dispatch", "pipeline": "workflow_run"}


class GitLab:
    def __init__(self, project: str, token: str | None = None, base: str = API, client: httpx.Client | None = None,
                 max_requests: int = 600, sleep=time.sleep):
        self.project, self.base, self.max_requests, self.requests, self.sleep = project, base.rstrip("/"), max_requests, 0, sleep
        self.client = client or httpx.Client(timeout=60, follow_redirects=True)
        self.headers = {"PRIVATE-TOKEN": token} if token else {}

    def get(self, path: str, params: dict | None = None):
        for attempt in range(3):
            if self.requests >= self.max_requests:
                raise OutOfBudget(f"stopped after {self.requests} requests (budget)")
            self.requests += 1
            resp = self.client.get(f"{self.base}/projects/{quote(self.project, safe='')}{path}", params=params,
                                   headers=self.headers)
            if resp.status_code == 429:
                self.sleep(min(float(resp.headers.get("retry-after", 30)), 120))
                continue
            if resp.status_code >= 400:
                raise APIError(f"GET {path}: HTTP {resp.status_code} {resp.text[:200]}")
            return resp.json()
        raise OutOfBudget("GitLab kept asking to slow down")

    def send(self, method: str, path: str, body: dict) -> dict:
        """One write (a merge request note); needs a token with the api scope."""
        self.requests += 1
        resp = self.client.request(method, f"{self.base}/projects/{quote(self.project, safe='')}{path}", json=body,
                                   headers=self.headers)
        if resp.status_code >= 400:
            raise APIError(f"{method} {path}: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json() if resp.content else {}

    def pages(self, path: str, params: dict, limit: int = 50):
        for page in range(1, limit + 1):
            batch = self.get(path, {**params, "per_page": 100, "page": page}) or []
            yield from batch
            if len(batch) < 100:
                return


def records(pipeline: dict, jobs: list[dict]) -> list[dict]:
    """One pipeline and its jobs (retries included) as run and job records, one run record per attempt."""
    tries = defaultdict(list)
    for j in sorted(jobs, key=lambda j: (j.get("created_at") or "", j["id"])):
        if j.get("status") in STATUS:
            tries[j.get("name") or "?"].append(j)
    attempts = max((len(t) for t in tries.values()), default=1)
    ev = EVENTS.get(pipeline.get("source"), pipeline.get("source") or "push")
    # Pipeline answers carry the merge request only in their ref (refs/merge-requests/<iid>/head).
    found = re.match(r"refs/merge-requests/(\d+)/", pipeline.get("ref") or "")
    mr = pipeline.get("merge_request_iid") or (int(found[1]) if found else None)
    # The pipeline's own result counts when it was cancelled, or failed before any job ran (bad YAML).
    own = STATUS.get(pipeline.get("status"))
    out = []
    for n in range(1, attempts + 1):
        mine = [t[min(n, len(t)) - 1] for t in tries.values()]
        failed = any(STATUS[j["status"]] == "failure" and not j.get("allow_failure") for j in mine)
        c = ("failure" if failed else "cancelled" if n == attempts and own == "cancelled"
             else own if not mine and own else "success")
        out.append({"t": "run", "id": pipeline["id"], "att": n, "wf": 0, "wfn": "GitLab CI", "path": ".gitlab-ci.yml",
                    "ev": ev, "br": pipeline.get("ref"), "sha": pipeline.get("sha"), "tree": pipeline.get("sha"),
                    "pr": [mr] if mr and ev == "pull_request" else [], "c": c,
                    "cr": pipeline.get("created_at"), "st": pipeline.get("started_at") or pipeline.get("created_at"),
                    "up": pipeline.get("updated_at")})
        for j in mine:
            c = STATUS[j["status"]]
            if j.get("allow_failure") and c == "failure":
                c = "neutral"  # allowed to fail: shown, never a failure of the pipeline
            out.append({"t": "job", "run": pipeline["id"], "att": n, "id": j["id"], "n": j.get("name"), "c": c,
                        "cr": j.get("created_at"), "st": j.get("started_at"), "en": j.get("finished_at"),
                        "lb": list(j.get("tag_list") or []) or ["gitlab"],
                        # GitLab jobs have no steps; the stage stands in for the step that failed.
                        "steps": [[1, j.get("stage") or "job", c, j.get("started_at"), j.get("finished_at")]]})
    return out


def collect(lab: GitLab, store, now: datetime, days: int = 14) -> dict:
    """Every finished pipeline updated in the last `days` days, with its jobs, into the store; pipelines read before are
    skipped. Returns how many were read and whether the budget stopped it."""
    seen = {r["id"] for r in store.load()["runs"]}
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    read, stopped = 0, None
    try:
        info = lab.get("")
        store.save_state({**store.state(), "default_branch": info.get("default_branch"), "gitlab": lab.project})
        for p in lab.pages("/pipelines", {"updated_after": since, "order_by": "updated_at", "sort": "desc"}):
            if p["id"] in seen or p.get("status") not in ("success", "failed", "canceled"):
                continue
            jobs = list(lab.pages(f"/pipelines/{p['id']}/jobs", {"include_retried": "true"}, limit=5))
            store.add(records(p, jobs), (p.get("created_at") or since)[:10])
            read += 1
    except OutOfBudget as exc:
        stopped = str(exc)
    return {"pipelines": read, "stopped": stopped}


def token() -> str | None:
    return os.environ.get("GITLAB_TOKEN") or None
