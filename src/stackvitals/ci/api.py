import os
import threading
import time
from collections.abc import Callable, Iterator
from urllib.parse import quote

import httpx

# GitHub Enterprise Server: Actions sets GITHUB_API_URL and GITHUB_GRAPHQL_URL for every job there.
API = (os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
GRAPHQL = os.environ.get("GITHUB_GRAPHQL_URL") or f"{API}/graphql"


class OutOfBudget(RuntimeError):
    pass


class APIError(RuntimeError):
    pass


class NotFound(APIError):
    pass


class ActionsAPI:
    # REST reads of Actions runs, attempts and jobs; stops cleanly before the token's limit is used up.
    def __init__(self, token: str | None, repo: str, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep, max_requests: int | None = None, reserve: int = 50,
                 etags: dict | None = None, cacheable: Callable[[str], bool] | None = None):
        self.repo, self.sleep, self.max_requests, self.reserve = repo, sleep, max_requests, reserve
        # Conditional reads: a 304 answer reuses the kept body and doesn't count against GitHub's hourly limit.
        self.etags, self.cacheable, self.unchanged = etags, cacheable, 0
        self.client = client or httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True)
        self.headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "stackvitals"}
        if token and token.strip():
            self.headers["Authorization"] = f"Bearer {token.strip()}"
        self.requests = 0
        self._lock = threading.Lock()

    def _get(self, path: str, params: dict | None = None, raw: bool = False):
        for attempt in range(4):
            # Requests run in parallel threads; the count and the budget check must not race.
            with self._lock:
                if self.max_requests is not None and self.requests - self.unchanged >= self.max_requests:
                    raise OutOfBudget(f"stopped after {self.requests} requests (budget)")
                self.requests += 1
            key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
            kept = self.etags.get(key) if self.etags is not None and not raw and self.cacheable and self.cacheable(path) else None
            headers = {**self.headers, "If-None-Match": kept[0]} if kept else self.headers
            try:
                resp = self.client.get(f"{API}{path}", headers=headers, params=params)
            except httpx.TransportError:
                # Dropped connections happen on long collections; try again after a short pause.
                self.sleep(2 * (attempt + 1))
                continue
            if resp.status_code in (403, 429) and ("retry-after" in resp.headers or "secondary" in resp.text.lower()):
                # Secondary limits ask for a pause; waiting is the only allowed answer.
                self.sleep(min(float(resp.headers.get("retry-after", 60)), 300))
                continue
            if resp.status_code in (403, 429) and resp.headers.get("x-ratelimit-remaining") == "0":
                raise OutOfBudget("GitHub's hourly limit for this token is used up")
            if resp.status_code >= 500 and attempt < 3:
                # GitHub answers some heavy job lists with 502 now and then; a short pause usually fixes it.
                self.sleep(3 * (attempt + 1))
                continue
            if resp.status_code == 304 and kept:
                with self._lock:
                    self.unchanged += 1
                return kept[1]
            if resp.status_code >= 400:
                raise APIError(f"GET {path}: HTTP {resp.status_code} {resp.text[:200]}")
            small = len(resp.content) < 20000
            if self.etags is not None and not raw and self.cacheable and self.cacheable(path) and resp.headers.get("etag") and small:
                self.etags[key] = [resp.headers["etag"], resp.json()]
            left = resp.headers.get("x-ratelimit-remaining")
            if left is not None and int(left) <= self.reserve:
                raise OutOfBudget(f"only {left} requests left this hour; keeping a reserve")
            return resp.content if raw else resp.json()
        raise OutOfBudget("GitHub kept asking to slow down")

    def get_if_changed(self, path: str, params: dict | None, etag: str | None) -> tuple[dict | None, str | None]:
        """(body, etag), or (None, etag) when GitHub says nothing changed since `etag` (which costs no hourly limit)."""
        with self._lock:
            if self.max_requests is not None and self.requests - self.unchanged >= self.max_requests:
                raise OutOfBudget(f"stopped after {self.requests} requests (budget)")
            self.requests += 1
        headers = {**self.headers, "If-None-Match": etag} if etag else self.headers
        try:
            resp = self.client.get(f"{API}{path}", headers=headers, params=params)
        except httpx.TransportError as exc:
            raise APIError(f"GET {path}: {type(exc).__name__}") from None
        if resp.status_code == 304:
            with self._lock:
                self.unchanged += 1
            return None, etag
        # A limit answer stops the caller (it keeps what it had), never reads as "not available".
        if resp.status_code in (403, 429) and ("retry-after" in resp.headers or "secondary" in resp.text.lower()
                                               or resp.headers.get("x-ratelimit-remaining") == "0"):
            raise OutOfBudget("GitHub asked to slow down or the hourly limit is used up")
        if resp.status_code >= 400:
            raise APIError(f"GET {path}: HTTP {resp.status_code} {resp.text[:200]}")
        left = resp.headers.get("x-ratelimit-remaining")
        if left is not None and int(left) <= self.reserve:
            raise OutOfBudget(f"only {left} requests left this hour; keeping a reserve")
        return resp.json(), resp.headers.get("etag")

    def fetch(self, path: str) -> tuple[int, bytes]:
        """(status, body) for endpoints whose status says something, like 202 while a report is being made. Redirects are
        followed; httpx drops the token when one leaves api.github.com."""
        with self._lock:
            if self.max_requests is not None and self.requests - self.unchanged >= self.max_requests:
                raise OutOfBudget(f"stopped after {self.requests} requests (budget)")
            self.requests += 1
        try:
            resp = self.client.get(f"{API}{path}", headers=self.headers)
        except httpx.TransportError as exc:
            raise APIError(f"GET {path}: {type(exc).__name__}") from None
        if resp.status_code >= 400:
            raise APIError(f"GET {path}: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.status_code, resp.content

    def send(self, method: str, path: str, body: dict | None = None) -> dict:
        # Writes (PR comments, re-runs) are counted against the same budget and never retried blindly.
        if os.environ.get("STACKVITALS_READ_ONLY"):
            # A run on someone's machine (`stackvitals ui --collect`) reads GitHub and never writes to it.
            raise APIError(f"{method} {path}: read-only local run, nothing is written to GitHub")
        with self._lock:
            self.requests += 1
        resp = self.client.request(method, f"{API}{path}", headers=self.headers, json=body)
        if resp.status_code >= 400:
            raise APIError(f"{method} {path}: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json() if resp.content else {}

    def runs_on_day(self, day: str) -> Iterator[dict]:
        # Filtered run lists stop at 1,000 results, so callers ask one day at a time.
        for page in range(1, 11):
            body = self._get(f"/repos/{self.repo}/actions/runs",
                             {"created": day, "status": "completed", "per_page": 100, "page": page})
            runs = body.get("workflow_runs") or []
            yield from runs
            if len(runs) < 100:
                return

    def file(self, path: str, ref: str | None, repo: str | None = None) -> bytes:
        # One file from a branch, raw (used to read a repo's stackvitals-data findings in one request); Portal reads other repos.
        with self._lock:
            if self.max_requests is not None and self.requests - self.unchanged >= self.max_requests:
                raise OutOfBudget(f"stopped after {self.requests} requests (budget)")
            self.requests += 1
        # Paths come from PRs: "#" or "?" in a folder name would otherwise cut the URL short.
        for attempt in range(3):
            try:
                resp = self.client.get(f"{API}/repos/{repo or self.repo}/contents/{quote(path, safe='/')}",
                                       params={"ref": ref} if ref else None,
                                       headers={**self.headers, "Accept": "application/vnd.github.raw"})
                break
            except httpx.TransportError:
                # A dropped connection is retried, then reported like any refusal: it must never stop a run.
                if attempt == 2:
                    raise APIError(f"GET contents/{path}@{ref}: network error")
                self.sleep(2 * (attempt + 1))
        if resp.status_code == 404:
            raise NotFound(f"GET contents/{path}@{ref}: HTTP 404")
        if resp.status_code >= 400:
            raise APIError(f"GET contents/{path}@{ref}: HTTP {resp.status_code}")
        return resp.content

    def file_if_changed(self, path: str, ref: str | None = None, etag: str | None = None) -> tuple[bytes | None, str | None]:
        """(content, etag) of a file, or (None, etag) when it still matches `etag`: GitHub doesn't count a 304 against the
        hourly limit, so a file read on every run costs nothing while it stays the same. No ref means the default branch."""
        with self._lock:
            if self.max_requests is not None and self.requests - self.unchanged >= self.max_requests:
                raise OutOfBudget(f"stopped after {self.requests} requests (budget)")
            self.requests += 1
        headers = {**self.headers, "Accept": "application/vnd.github.raw", **({"If-None-Match": etag} if etag else {})}
        for attempt in range(3):
            try:
                resp = self.client.get(f"{API}/repos/{self.repo}/contents/{quote(path, safe='/')}",
                                       params={"ref": ref} if ref else None, headers=headers)
            except httpx.TransportError:
                if attempt == 2:
                    raise APIError(f"GET contents/{path}: network error")
                self.sleep(2 * (attempt + 1))
                continue
            if resp.status_code >= 500 and attempt < 2:
                self.sleep(2 * (attempt + 1))
                continue
            break
        if resp.status_code == 304:
            return None, resp.headers.get("etag") or etag
        if resp.status_code == 404:
            raise NotFound(f"GET contents/{path}: HTTP 404")
        if resp.status_code >= 400:
            raise APIError(f"GET contents/{path}: HTTP {resp.status_code}")
        return resp.content, resp.headers.get("etag")

    def artifacts(self, run_id: int) -> list[dict]:
        body = self._get(f"/repos/{self.repo}/actions/runs/{run_id}/artifacts", {"per_page": 100})
        return body.get("artifacts") or []

    def download(self, artifact_id: int) -> bytes:
        # GitHub answers with a redirect to storage; httpx drops the token when it leaves github.com.
        return self._get(f"/repos/{self.repo}/actions/artifacts/{artifact_id}/zip", raw=True)

    def attempt(self, run_id: int, n: int) -> dict:
        return self._get(f"/repos/{self.repo}/actions/runs/{run_id}/attempts/{n}")

    def jobs(self, run_id: int, n: int) -> list[dict]:
        out, page = [], 1
        while True:
            body = self._get(f"/repos/{self.repo}/actions/runs/{run_id}/attempts/{n}/jobs", {"per_page": 100, "page": page})
            batch = body.get("jobs") or []
            out.extend(batch)
            if len(batch) < 100:
                return out
            page += 1
