"""The org's repos and what is known about each: settings, custom properties, branch rules, and the suite's own module
results read from each repo's stackvitals-data branch (where the suite runs)."""
import json
import re
from datetime import datetime, timedelta

import httpx

from stackvitals.ci.api import APIError
from stackvitals.core.actors import INSIDER_ASSOC, People, kind_of
from stackvitals.core.store import accept
from stackvitals.portal import descriptor
from stackvitals.portal.github import NA, REFUSED, read, read_file

DATA_BRANCH = "stackvitals-data"
FILES = ("readme", "license", "contributing", "code_of_conduct")
SCORECARD_API = "https://api.scorecard.dev/projects/github.com/"


def _repo(r: dict) -> dict:
    return {"name": r["full_name"], "private": bool(r.get("private")), "archived": bool(r.get("archived")),
            "fork": bool(r.get("fork")), "language": r.get("language"), "pushed": r.get("pushed_at"),
            "default_branch": r.get("default_branch"), "topics": r.get("topics") or [], "stars": r.get("stargazers_count"),
            "license": (r.get("license") or {}).get("key")}


def list_repos(api, org: str, mode: str, max_pages: int = 50) -> list[dict]:
    """Private mode: every repo the org's App is installed on. Public mode: the org's public repos (or a user's)."""
    found = []
    for page in range(1, max_pages + 1):
        if mode == "private":
            body = read(api, "/installation/repositories", {"per_page": 100, "page": page})
            batch = [] if body is NA else body.get("repositories") or []
        else:
            # Local runs list what the user's own token can see; the Action's public mode lists public repos only.
            body = read(api, f"/orgs/{org}/repos", {"type": "all" if mode == "local" else "public", "per_page": 100, "page": page})
            if body is NA and page == 1:
                body = read(api, f"/users/{org}/repos", {"type": "owner", "per_page": 100, "page": page})
            batch = [] if body is NA else body
        found += [_repo(r) for r in batch if isinstance(r, dict) and r.get("full_name")]
        if len(batch) < 100:
            break
    return sorted({r["name"]: r for r in found}.values(), key=lambda r: r["name"].lower())


def custom_properties(api, org: str) -> dict:
    # Tier, lifecycle, system: GitHub's own repo metadata, read rather than rebuilt (one paged call for the whole org).
    out = {}
    for page in range(1, 51):
        body = read(api, f"/orgs/{org}/properties/values", {"per_page": 100, "page": page})
        if body is NA or not isinstance(body, list):
            return out
        for r in body:
            out[r.get("repository_full_name")] = {p.get("property_name"): p.get("value") for p in r.get("properties") or []}
        if len(body) < 100:
            return out
    return out


def branch_rules(api, repo: str, branch: str | None) -> list[str] | None:
    # The rules that apply to the default branch, from rulesets and branch protection alike.
    body = read(api, f"/repos/{repo}/rules/branches/{branch}") if branch else NA
    return None if body is NA else sorted({r.get("type") for r in body if isinstance(r, dict) and r.get("type")})


def _json(api, repo: str, path: str) -> dict | None:
    text = read_file(api, repo, path, DATA_BRANCH)
    try:
        data = json.loads(text) if text is not NA else None
    except ValueError:
        return None
    return accept(data)


def module_facts(api, repo: str, pre: dict | None = None) -> dict | None:
    """The suite's results for this repo, or None where the suite doesn't run (no data branch)."""
    if (not pre["data_branch"]) if pre else read(api, f"/repos/{repo}/branches/{DATA_BRANCH}") is NA:
        return None
    # Since Phase 11 one file holds every fact as a number; older installs keep the three files below.
    app = None
    if pre and pre.get("app"):
        try:
            app = accept(json.loads(pre["app"]))
        except ValueError:
            app = None
    f = (app or _json(api, repo, "docs/app.json") or {}).get("facts")
    if isinstance(f, dict):
        share, score = f.get("ci_first_try"), f.get("community_score")
        return {"ci_first_try": f"{share:.0%}" if isinstance(share, (int, float)) else None, "ci_first_try_share": share,
                "flow": {"open": f.get("open_prs"), "stale": f.get("stale_prs"),
                         "first_review_median_s": f.get("first_review_median_s")} if f.get("open_prs") is not None else None,
                "community_score": f"{score}/100" if isinstance(score, (int, float)) else None,
                # Every number the repo publishes, for the org view.
                "facts": {k: v for k, v in f.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}}
    ci, flow, community = _json(api, repo, "docs/badge.json"), _json(api, repo, "docs/flow.json"), \
        _json(api, repo, "docs/community-score.json")
    pickup = ((flow or {}).get("stages") or {}).get("pickup") or {}
    return {"ci_first_try": (ci or {}).get("message"),
            "flow": {"open": flow.get("open"), "stale": flow.get("stale"), "first_review_median_s": pickup.get("median_s")}
            if flow else None,
            "community_score": (community or {}).get("message")}


def repo_files(api, repo: dict, pre: dict | None = None) -> dict:
    """README, licence, contributing guide and code of conduct: True, False, or None when nobody could check."""
    if pre:
        return pre["files"]
    body = read(api, f"/repos/{repo['name']}/community/profile")
    if body is not NA and isinstance(body, dict) and isinstance(body.get("files"), dict):
        files = body["files"]
        owner = repo["name"].split("/")[0].lower()
        # GitHub fills gaps from the org's .github repo; the evidence says so.
        defaults = [k for k in FILES if isinstance(files.get(k), dict)
                    and f"/{owner}/.github/" in (files[k].get("html_url") or "").lower()]
        return {**{k: bool(files.get(k)) or (k == "license" and bool(repo.get("license"))) for k in FILES}, "org_defaults": defaults}
    # Private repos may refuse the profile: the README is asked for directly and the licence comes from the repo itself.
    return {"readme": read(api, f"/repos/{repo['name']}/readme") is not NA, "license": bool(repo.get("license")),
            "contributing": None, "code_of_conduct": None}


def descriptor_for(api, repo: dict, pre: dict | None = None) -> dict:
    """The repo's catalog-info.yaml as typed entities and their problems (one request), or present: False."""
    if pre:
        text = pre["descriptor"] if pre["descriptor"] is not None else NA
    else:
        text = read_file(api, repo["name"], descriptor.FILE, repo.get("default_branch"))
    if text is NA:
        return {"present": False}
    entities, problems = descriptor.parse(text)
    return {"present": True, "entities": entities, "problems": problems}


def file_facts(api, repo: dict, rules: list[dict], pre: dict | None = None) -> dict:
    """For portal.toml's file rules: whether each file is there and whether its patterns match (one request per file).
    Only these yes/no answers are kept, never the file's text."""
    out = {}
    for path in dict.fromkeys(r["path"] for r in rules):
        if pre and path in pre["rule_files"]:
            text = pre["rule_files"][path] if pre["rule_files"][path] is not None else NA
        else:
            text = read_file(api, repo["name"], path, repo.get("default_branch"))
        if text is NA:
            out[path] = {"present": False}
            continue
        found = {"present": True}
        for r in rules:
            for key in ("contains", "lacks"):
                if r["path"] == path and r.get(key):
                    found[f"{key}:{r[key]}"] = bool(re.search(r[key], text[:descriptor.MAX_BYTES], re.M))
        out[path] = found
    return out


def scorecard_checks(client: httpx.Client, name: str, previous: dict | None, now: datetime) -> dict | None:
    """OpenSSF Scorecard single checks for a public repo, from its public API (results change weekly, so read once a week)."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if previous and (previous.get("fetched") or "") >= (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"):
        return previous
    try:
        # The API matches names case-sensitively and lists them in lower case.
        resp = client.get(SCORECARD_API + name.lower(), timeout=20)
    except httpx.HTTPError:
        return previous
    if resp.status_code == 404:
        return {"fetched": stamp, "date": None, "checks": None}
    if resp.status_code != 200:
        return previous
    try:
        body = resp.json()
    except ValueError:
        return previous
    return {"fetched": stamp, "date": body.get("date"),
            "checks": {c["name"]: c.get("score") for c in body.get("checks") or [] if isinstance(c, dict) and c.get("name")}}


def push_ci(api, repo: str, now: datetime, days: int = 30, previous: dict | None = None) -> dict | None:
    """First-try green and time to green for the newest 50 push runs, measured exactly like the crawl's CI benchmark,
    for repos where CI Health doesn't run (one request; free when no run happened since the last check, which then
    keeps the last check's numbers)."""
    from mergescout.bench.ci import PAGE, repo_stats
    path, params = f"/repos/{repo}/actions/runs", {"event": "push", "per_page": PAGE, "exclude_pull_requests": "true"}
    tag = None
    if hasattr(api, "get_if_changed"):
        try:
            body, tag = api.get_if_changed(path, params, (previous or {}).get("etag"))
        except APIError as exc:
            if not any(code in str(exc) for code in REFUSED):
                raise
            body = NA
        if body is None:
            return previous
    else:
        body = read(api, path, params)
    runs = (body or {}).get("workflow_runs") if body is not NA and isinstance(body, dict) else None
    if not runs:
        return None
    stats = repo_stats(runs, now - timedelta(days=days), page_full=len(runs) >= PAGE)
    return {**{k: stats[k] for k in ("first_try_share", "pushes", "median_s")}, **({"etag": tag} if tag else {})} if stats else None


REVIEW_QUERY = """
query($owner:String!,$name:String!) {
  rateLimit { cost remaining resetAt }
  repository(owner:$owner,name:$name) {
    pullRequests(last:50, orderBy:{field:CREATED_AT, direction:ASC}) {
      nodes { createdAt author { __typename login } authorAssociation
              reviews(first:10) { nodes { submittedAt author { login } authorAssociation } } }
    }
  }
}"""
MAINTAINERS = INSIDER_ASSOC


def _review_records(nodes: list[dict]) -> list[dict]:
    # The newest PRs as the shared role rule reads them (author, label, reviews); no merge events in this query.
    out = []
    for p in nodes:
        author = p.get("author") or {}
        out.append({"au": author.get("login"), "at": author.get("__typename"), "as": p.get("authorAssociation"),
                    "ev": [["review", r.get("submittedAt"), (r.get("author") or {}).get("login"), None, r.get("authorAssociation"), None]
                           for r in (p.get("reviews") or {}).get("nodes") or [] if r], "cm": []})
    return out


def review_stats(gql, repo: str, now: datetime, days: int = 90, min_prs: int = 10) -> dict | None:
    """Median time to the first review by a maintainer other than the author, for people's PRs of the last 90 days among
    the newest 50 (the crawl benchmark's definition), where Team Flow doesn't run (one GraphQL point)."""
    from mergescout.github.graphql import GraphQLError, RateLimited
    owner, name = repo.split("/", 1)
    try:
        data = gql.query(REVIEW_QUERY, {"owner": owner, "name": name}).data
    except (GraphQLError, RateLimited):
        return None
    nodes = ((data.get("repository") or {}).get("pullRequests") or {}).get("nodes") or []
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    prs = [p for p in nodes if p and (p.get("createdAt") or "") >= since
           and kind_of((p.get("author") or {}).get("login"), (p.get("author") or {}).get("__typename")) == "person"]
    if len(prs) < min_prs:
        return None
    people = People(_review_records(prs))
    waits, reviewers = [], {}
    for p in prs:
        author = (p.get("author") or {}).get("login")
        for r in (p.get("reviews") or {}).get("nodes") or []:
            who = (r or {}).get("author") and r["author"].get("login")
            if who and who != author and people.is_insider(who):
                reviewers[who] = reviewers.get(who, 0) + 1
        first = min((r["submittedAt"] for r in (p.get("reviews") or {}).get("nodes") or []
                     if r and r.get("submittedAt") and people.is_insider((r.get("author") or {}).get("login"))
                     and (r.get("author") or {}).get("login") != author), default=None)
        if first:
            waits.append((datetime.fromisoformat(first.replace("Z", "+00:00"))
                          - datetime.fromisoformat(p["createdAt"].replace("Z", "+00:00"))).total_seconds())
    waits.sort()
    mid = len(waits) // 2
    median = (waits[mid] if len(waits) % 2 else (waits[mid - 1] + waits[mid]) / 2) if waits else None
    return {"first_review_median_s": median, "prs": len(prs),
            "reviewers": [w for w, _ in sorted(reviewers.items(), key=lambda kv: (-kv[1], kv[0]))][:3]}


def branch_protected(api, repo: str, branch: str | None) -> bool | None:
    # Classic branch protection isn't in the rules endpoint; whether it requires reviews needs an admin token.
    body = read(api, f"/repos/{repo}/branches/{branch}") if branch else NA
    return bool(body.get("protected")) if body is not NA and isinstance(body, dict) else None
