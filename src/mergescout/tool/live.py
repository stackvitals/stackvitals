import math
import re
from datetime import datetime, timedelta, timezone

import httpx

from mergescout.labels import has_opportunity, norm_label
from mergescout.signals.rules import (BOT_NAME_PATTERN, CLAIM_PATTERN, HUMAN_BOT_NAMES, KNOWN_BOTS, RULES,
                                      TRIAGE_LABEL_PATTERN, UNKNOWN_LOGINS, WAIT_LABEL_PATTERN, WAIT_PATTERN)

API = "https://api.github.com"
INSIDER = {"OWNER", "MEMBER", "COLLABORATOR"}
FIELDS = """
fragment S on Issue {
  title state stateReason updatedAt
  assignees(first: 5) { totalCount }
  labels(first: 20) { nodes { name } }
  closedByPullRequestsReferences(first: 5, includeClosedPrs: false) { nodes { number state } }
  timelineItems(last: 30, itemTypes: [CROSS_REFERENCED_EVENT]) { nodes { ... on CrossReferencedEvent {
    source { __typename ... on PullRequest { number state author { __typename login } repository { nameWithOwner } } } } } }
  comments(last: 10) { nodes { createdAt authorAssociation author { __typename login } bodyText } }
}"""
STATUS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) { issue(number: $number) { ...S } }
}""" + FIELDS
# "Could you try the build from draft PR #1106?" points at work in progress the issue does not link.
PR_MENTION = re.compile(r"(?:\bpr\s*#|\bpull request\s*#|/pull/)(\d+)", re.I)
BATCH = 25


class LiveError(RuntimeError):
    pass


def _time(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def _bot(login: str, typ: str | None) -> bool:
    return (typ == "Bot" or login in KNOWN_BOTS or login in UNKNOWN_LOGINS or login.endswith("[bot]")
            or bool(re.search(BOT_NAME_PATTERN, login) and not re.search(HUMAN_BOT_NAMES, login)))


def classify_comments(comments: list[dict], now: datetime) -> tuple[list, list, list]:
    # Claims older than the claim window do not block, but a user should still see them before starting.
    claims, waits, older = [], [], []
    for c in comments:
        login = (c.get("login") or "").lower()
        if not login or _bot(login, c.get("type")):
            continue
        text, at = (c.get("body") or "").lower(), _time(c.get("created_at"))
        item = {"by": c.get("login"), "at": c.get("created_at"), "text": (c.get("body") or "")[:160]}
        if c.get("association") in INSIDER:
            if re.search(WAIT_PATTERN, text):
                waits.append(item)
        elif re.search(CLAIM_PATTERN, text):
            (claims if at and now - at <= timedelta(days=RULES.claim_days) else older).append(item)
    return claims, waits, older


def _graphql_errors(body: dict) -> list[dict]:
    errors = body.get("errors") or []
    if any(e.get("type") == "RATE_LIMITED" or "rate limit" in (e.get("message") or "").lower() for e in errors):
        raise LiveError("GitHub's rate limit is reached for this token; try again in a few minutes.")
    return errors


def _from_graphql(issue: dict, repo: str) -> tuple[dict, list[dict]]:
    comments = [{"login": (c.get("author") or {}).get("login"), "type": (c.get("author") or {}).get("__typename"),
                 "association": c.get("authorAssociation"), "body": c.get("bodyText"), "created_at": c.get("createdAt")}
                for c in (issue.get("comments") or {}).get("nodes") or [] if c]
    linked = [p["number"] for p in issue["closedByPullRequestsReferences"]["nodes"] if p and p["state"] == "OPEN"]
    # Real data (2026-10-16): open PRs often say "related to #N" without the closing keyword GitHub links.
    mentions = []
    for ev in (issue.get("timelineItems") or {}).get("nodes") or []:
        src = (ev or {}).get("source") or {}
        author = src.get("author") or {}
        if (src.get("__typename") == "PullRequest" and src.get("state") == "OPEN"
                and (src.get("repository") or {}).get("nameWithOwner", "").lower() == repo.lower()
                and src.get("number") not in linked and src.get("number") not in mentions
                and not _bot((author.get("login") or "").lower(), author.get("__typename"))):
            mentions.append(src["number"])
    return ({"state": issue["state"], "title": issue["title"], "assignees": issue["assignees"]["totalCount"],
             "linked_open_prs": len(linked), "open_prs_mentioning": mentions,
             "labels": [lb["name"] for lb in issue["labels"]["nodes"] if lb], "updated_at": issue["updatedAt"],
             "source": "github graphql"}, comments)


def _finish(status: dict, comments: list[dict], now: datetime) -> dict:
    claims, waits, older = classify_comments(comments, now)
    not_ready = [lb for lb in status["labels"] if re.search(WAIT_LABEL_PATTERN, norm_label(lb))]
    untriaged = [lb for lb in status["labels"] if re.search(TRIAGE_LABEL_PATTERN, norm_label(lb))]
    invited = has_opportunity(status["labels"])
    mentioning = status.get("open_prs_mentioning") or []
    reasons = [r for r, hit in (("closed", status["state"] != "OPEN"), ("assigned", status["assignees"] > 0),
                                ("open PR", bool(status["linked_open_prs"])),
                                (f"open PR mentions it ({', '.join(f'#{n}' for n in mentioning)})", bool(mentioning)),
                                ("claimed recently", bool(claims)), ("maintainer asked to wait", bool(waits)),
                                (f"label says not ready ({', '.join(not_ready)})", bool(not_ready)),
                                (f"label says not settled yet ({', '.join(untriaged)})", bool(untriaged) and not invited))
               if hit]
    mentioned = list(dict.fromkeys(int(n) for c in comments for n in PR_MENTION.findall(c.get("body") or "")))
    notes = [status["note"]] if status.get("note") else []
    if mentioned and not reasons:
        notes.append(f"comments mention PR {', '.join(f'#{n}' for n in mentioned)}; check it is not already fixing this")
    if untriaged and invited and not reasons:
        notes.append(f"also labelled '{untriaged[0]}': a maintainer may not have confirmed it yet; ask before starting")
    out = {**status, "claims": claims, "waits": waits, "older_claims": older, "mentioned_prs": mentioned,
           "available": not reasons, "reasons": reasons, "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    if notes:
        out["note"] = "; ".join(notes)
    return out


class GitHubLive:
    def __init__(self, token: str | None = None, client: httpx.Client | None = None):
        self.token = (token or "").strip() or None
        # Renamed repos and moved issues answer with redirects.
        self.client = client or httpx.Client(timeout=30, follow_redirects=True)
        self.headers = {"Accept": "application/vnd.github+json", "User-Agent": "mergescout"}
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

    def _get(self, path: str, params=None) -> httpx.Response:
        resp = self.client.get(f"{API}{path}", headers=self.headers, params=params)
        if resp.status_code == 404:
            raise LiveError("GitHub says this issue or repo does not exist (or is private).")
        if resp.status_code in (401, 403, 429):
            raise LiveError(f"GitHub refused the live check (HTTP {resp.status_code}); set MERGESCOUT_TOKEN for more calls.")
        resp.raise_for_status()
        return resp

    def _post(self, query: str, variables: dict) -> dict:
        resp = self.client.post(f"{API}/graphql", headers=self.headers, json={"query": query, "variables": variables})
        if resp.status_code == 401:
            raise LiveError("GitHub rejected the token (401).")
        if resp.status_code >= 400:
            raise LiveError(f"GitHub could not answer the live check (HTTP {resp.status_code}).")
        return resp.json()

    def issue_status(self, owner: str, name: str, number: int) -> dict:
        now = datetime.now(timezone.utc)
        if self.token:
            body = self._post(STATUS_QUERY, {"owner": owner, "name": name, "number": number})
            errors = _graphql_errors(body)
            issue = ((body.get("data") or {}).get("repository") or {}).get("issue")
            if issue is None:
                if errors and not all(e.get("type") == "NOT_FOUND" for e in errors):
                    raise LiveError("GitHub could not answer: " + "; ".join(e.get("message", "?") for e in errors))
                raise LiveError("GitHub says this issue does not exist (or is a pull request).")
            status, comments = _from_graphql(issue, f"{owner}/{name}")
        else:
            base = self._get(f"/repos/{owner}/{name}/issues/{number}").json()
            if "pull_request" in base:
                raise LiveError("That number is a pull request, not an issue.")
            last = max(1, math.ceil((base.get("comments") or 0) / 100))
            raw = self._get(f"/repos/{owner}/{name}/issues/{number}/comments", {"per_page": 100, "page": last}).json()
            comments = [{"login": (c.get("user") or {}).get("login"), "type": (c.get("user") or {}).get("type"),
                         "association": c.get("author_association"), "body": c.get("body"), "created_at": c.get("created_at")}
                        for c in raw[-10:]]
            status = {"state": base["state"].upper(), "title": base["title"], "assignees": len(base.get("assignees") or []),
                      "linked_open_prs": None, "labels": [lb["name"] for lb in base.get("labels") or []],
                      "updated_at": base.get("updated_at"), "source": "github rest",
                      "note": "linked PRs unknown without a token (set MERGESCOUT_TOKEN to check them)"}
        return _finish(status, comments, now)

    def issue_statuses(self, keys: list[tuple[str, str, int]]) -> dict[tuple[str, str, int], dict | None]:
        # One GraphQL call per 25 issues, so a whole result list is checked for about one rate-limit point.
        if not self.token:
            raise LiveError("checking many issues at once needs MERGESCOUT_TOKEN")
        now, out = datetime.now(timezone.utc), {}
        for start in range(0, len(keys), BATCH):
            chunk = keys[start:start + BATCH]
            args = ", ".join(f"$o{n}: String!, $n{n}: String!, $k{n}: Int!" for n in range(len(chunk)))
            parts = " ".join(f"i{n}: repository(owner: $o{n}, name: $n{n}) {{ issue(number: $k{n}) {{ ...S }} }}"
                             for n in range(len(chunk)))
            variables = {}
            for n, (owner, name, number) in enumerate(chunk):
                variables.update({f"o{n}": owner, f"n{n}": name, f"k{n}": number})
            body = self._post(f"query({args}) {{ rateLimit {{ cost remaining }} {parts} }}" + FIELDS, variables)
            _graphql_errors(body)
            data = body.get("data") or {}
            if not data:
                raise LiveError("GitHub could not answer the live check.")
            for n, key in enumerate(chunk):
                issue = (data.get(f"i{n}") or {}).get("issue")
                out[key] = _finish(*_from_graphql(issue, f"{key[0]}/{key[1]}"), now) if issue else None
        return out

    def fresh_issues(self, language: str | None, since: datetime, limit: int = 20) -> list[dict]:
        # Issues opened after the snapshot was built: one search call.
        q = f'is:issue is:open no:assignee label:"good first issue","help wanted" created:>={since:%Y-%m-%dT%H:%M:%SZ}'
        if language:
            q += f' language:"{language}"' if " " in language else f" language:{language}"
        items = self._get("/search/issues", {"q": q, "sort": "created", "order": "desc",
                                             "per_page": max(1, min(limit * 3, 100))}).json().get("items") or []
        return [{"repo": it["repository_url"].split("/repos/", 1)[1], "number": it["number"], "title": it["title"],
                 "labels": [lb["name"] for lb in it.get("labels") or []], "created_at": it["created_at"],
                 "url": it["html_url"], "fresh": True} for it in items]
