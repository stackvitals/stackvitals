"""Bitbucket Cloud and Azure DevOps pull requests (and Bitbucket Pipelines deployments) in the shapes Delivery reads for
GitHub, as DevLake's plugins bring them in, with no server: read-only REST, public projects need no token.

    stackvitals delivery workspace/repo --bitbucket          # BITBUCKET_TOKEN for private ones
    stackvitals delivery org/project/repo --azure            # AZURE_DEVOPS_TOKEN (a PAT) for private ones

Each merged pull request's activity tells when someone else first answered and when it was approved; its merge commit
links it to the deployment that shipped it. Azure DevOps keeps deployments in release pipelines, outside the Git API:
send them with `stackvitals record`, or count merges (source = "merges")."""
import base64
import os
from datetime import datetime, timedelta

import httpx

from stackvitals.ci.api import APIError

BITBUCKET = "https://api.bitbucket.org/2.0"
AZURE = "https://dev.azure.com"
MAX_PRS = 400


def _iso(s: str | None) -> str | None:
    if not s:
        return None
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(n: int, title: str, created: str, merged: str, author: str, base: str, head: str, sha: str | None,
            events: list, talk: list, draft: bool = False) -> dict:
    """One pull request as Team Flow's record (the shape GitHub's and GitLab's take)."""
    return {"t": "pr", "n": n, "ti": (title or "")[:200], "draft": draft, "st": "MERGED", "cr": _iso(created), "up": _iso(merged),
            "mg": _iso(merged), "cl": _iso(merged), "au": author, "at": "User", "as": "MEMBER", "base": base, "head": head,
            "mc": sha, "lb": [], "paths": [], "rq": [], "ev": sorted(events, key=lambda e: e[1] or ""), "cm": talk,
            "fa": None, "nc": None}


class Client:
    """A read-only GET with an optional token, a request budget and plain errors."""
    def __init__(self, base: str, headers: dict | None = None, client: httpx.Client | None = None, budget: int = 900):
        self.base, self.headers, self.budget, self.requests = base.rstrip("/"), headers or {}, budget, 0
        self.client = client or httpx.Client(timeout=60, follow_redirects=True)

    def get(self, url: str, params: dict | None = None) -> dict:
        if self.requests >= self.budget:
            raise APIError(f"stopped after {self.requests} requests (budget)")
        self.requests += 1
        resp = self.client.get(url if url.startswith("http") else f"{self.base}{url}", params=params, headers=self.headers)
        if resp.status_code >= 400:
            raise APIError(f"GET {url.split('?')[0][-80:]}: HTTP {resp.status_code}")
        return resp.json()


def bitbucket(repo: str, now: datetime, days: int = 90, client: Client | None = None) -> tuple[dict, dict]:
    """(flow, repo facts) for a Bitbucket Cloud repo: merged PRs of the window with their activity, and deployments."""
    tok = os.environ.get("BITBUCKET_TOKEN")
    c = client or Client(BITBUCKET, {"Authorization": f"Bearer {tok}"} if tok else {})
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    info = c.get(f"/repositories/{repo}")
    closed, url = [], f"/repositories/{repo}/pullrequests"
    params = {"state": "MERGED", "pagelen": 50, "q": f'updated_on > {since}', "sort": "-updated_on"}
    while url and len(closed) < MAX_PRS:
        page = c.get(url, params)
        for p in page.get("values") or []:
            author = (p.get("author") or {}).get("nickname") or (p.get("author") or {}).get("display_name")
            events, talk, merged = [], [], None
            try:
                for a in c.get(f"/repositories/{repo}/pullrequests/{p['id']}/activity", {"pagelen": 50}).get("values") or []:
                    if a.get("approval"):
                        who = (a["approval"].get("user") or {}).get("nickname")
                        events.append(["review", _iso(a["approval"].get("date")), who, "APPROVED", "MEMBER", "User", False])
                    elif a.get("comment") and ((a["comment"].get("user") or {}).get("nickname")) != author:
                        talk.append([_iso(a["comment"].get("created_on")), (a["comment"].get("user") or {}).get("nickname"), "MEMBER", "User", False])
                    elif (a.get("update") or {}).get("state") == "MERGED":
                        merged = a["update"].get("date")
            except APIError:
                pass  # no activity: the phases end at the merge
            merged = merged or p.get("updated_on")
            events.append(["merged", _iso(merged), (p.get("closed_by") or {}).get("nickname")])
            closed.append(_record(p["id"], p.get("title"), p.get("created_on"), merged, author,
                                  ((p.get("destination") or {}).get("branch") or {}).get("name"),
                                  ((p.get("source") or {}).get("branch") or {}).get("name"),
                                  (p.get("merge_commit") or {}).get("hash"), events, talk, bool(p.get("draft"))))
        url, params = page.get("next"), None
    envs = {}
    try:
        envs = {e["uuid"]: e.get("name") for e in c.get(f"/repositories/{repo}/environments", {"pagelen": 100}).get("values") or []}
    except APIError:
        pass
    deps = []
    try:
        for d in c.get(f"/repositories/{repo}/deployments", {"pagelen": 100, "sort": "-state.started_on"}).get("values") or []:
            state = ((d.get("state") or {}).get("status") or {}).get("name")
            deps.append({"env": envs.get((d.get("environment") or {}).get("uuid")) or "", "at": _iso((d.get("state") or {}).get("started_on")),
                         "sha": ((d.get("release") or {}).get("commit") or {}).get("hash"),
                         "state": {"SUCCESSFUL": "SUCCESS", "FAILED": "FAILURE"}.get(state),
                         "done": _iso((d.get("state") or {}).get("completed_on"))})
    except APIError:
        pass
    facts = {"default_branch": (info.get("mainbranch") or {}).get("name"), "private": bool(info.get("is_private")),
             "deployments": [d for d in deps if d["state"] and d["at"]], "releases": []}
    return {"closed": closed, "open": []}, facts


def azure(path: str, now: datetime, days: int = 90, client: Client | None = None) -> tuple[dict, dict]:
    """(flow, repo facts) for an Azure DevOps repo (org/project/repo): completed PRs of the window with their threads."""
    org, project, repo = path.split("/", 2)
    tok = os.environ.get("AZURE_DEVOPS_TOKEN")
    auth = {"Authorization": "Basic " + base64.b64encode(f":{tok}".encode()).decode()} if tok else {}
    c = client or Client(f"{AZURE}/{org}/{project}/_apis/git", auth)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    info = c.get(f"/repositories/{repo}", {"api-version": "7.1"})
    closed, skip = [], 0
    while len(closed) < MAX_PRS:
        page = c.get(f"/repositories/{repo}/pullrequests", {"searchCriteria.status": "completed", "searchCriteria.minTime": since,
                                                            "searchCriteria.queryTimeRangeType": "closed", "$top": 100, "$skip": skip,
                                                            "api-version": "7.1"}).get("value") or []
        for p in page:
            # Anonymous reads of a public project leave out uniqueName; the display name still tells people apart.
            who_of = lambda x: (x or {}).get("uniqueName") or (x or {}).get("displayName")  # noqa: E731
            author = who_of(p.get("createdBy"))
            events, talk = [], []
            try:
                threads = c.get(f"/repositories/{repo}/pullRequests/{p['pullRequestId']}/threads", {"api-version": "7.1"}).get("value") or []
            except APIError:
                threads = []
            for th in threads:
                vote = ((th.get("properties") or {}).get("CodeReviewThreadType") or {}).get("$value") == "VoteUpdate"
                for cm in th.get("comments") or []:
                    who, at = who_of(cm.get("author")), _iso(cm.get("publishedDate"))
                    if vote and "approved" in (cm.get("content") or "").lower():
                        events.append(["review", at, who, "APPROVED", "MEMBER", "User", False])
                    elif cm.get("commentType") == "text" and who and who != author:
                        talk.append([at, who, "MEMBER", "User", False])
            events.append(["merged", _iso(p.get("closedDate")), who_of(p.get("closedBy"))])
            closed.append(_record(p["pullRequestId"], p.get("title"), p.get("creationDate"), p.get("closedDate"), author,
                                  (p.get("targetRefName") or "").removeprefix("refs/heads/"),
                                  (p.get("sourceRefName") or "").removeprefix("refs/heads/"),
                                  (p.get("lastMergeCommit") or {}).get("commitId"), events, talk, bool(p.get("isDraft"))))
        if len(page) < 100:
            break
        skip += 100
    facts = {"default_branch": (info.get("defaultBranch") or "").removeprefix("refs/heads/") or None,
             "private": (info.get("project") or {}).get("visibility") != "public", "deployments": [], "releases": []}
    return {"closed": closed, "open": []}, facts
