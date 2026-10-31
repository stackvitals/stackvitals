"""What Community adds to Team Flow's PR history: issues with their first replies, the weekly star history and, when the
user set up a token that may read it, traffic (GitHub deletes it after 14 days)."""
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from mergescout.github.graphql import GraphQLError, RateLimited
from stackvitals.flow.store import FlowStore

ISSUES_QUERY = """
query($owner:String!,$name:String!,$cursor:String,$n:Int!,$since:DateTime) {
  rateLimit { cost remaining resetAt }
  repository(owner:$owner,name:$name) {
    issues(first:$n, after:$cursor, orderBy:{field:UPDATED_AT, direction:DESC}, filterBy:{since:$since}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number state createdAt updatedAt closedAt author { __typename login } authorAssociation
        labels(first:10) { nodes { name } }
        comments(first:10) { totalCount nodes { createdAt author { __typename login } authorAssociation } }
        closer: timelineItems(last:1, itemTypes:[CLOSED_EVENT]) { nodes { ... on ClosedEvent { createdAt actor { login } } } }
        triage: timelineItems(first:5, itemTypes:[LABELED_EVENT, ASSIGNED_EVENT, MARKED_AS_DUPLICATE_EVENT]) {
          nodes { ... on LabeledEvent { createdAt actor { __typename login } } ... on AssignedEvent { createdAt actor { __typename login } }
                  ... on MarkedAsDuplicateEvent { createdAt actor { __typename login } } } }
      }
    }
  }
}"""
SCHEMA = 3  # 3: who triaged each issue (labels, assignments, duplicates)
OVERLAP = timedelta(hours=1)
# Discussions: questions answered there instead of in issues (no `since` filter, so pages stop at the last read).
DISCUSSIONS_QUERY = """
query($owner:String!,$name:String!,$cursor:String,$n:Int!) {
  rateLimit { cost remaining resetAt }
  repository(owner:$owner,name:$name) {
    discussions(first:$n, after:$cursor, orderBy:{field:UPDATED_AT, direction:DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number createdAt updatedAt closed closedAt answerChosenAt author { __typename login } authorAssociation
        category { name isAnswerable }
        comments(first:10) { totalCount nodes { createdAt author { __typename login } authorAssociation } }
      }
    }
  }
}"""


def issue_record(node: dict, now: datetime) -> dict:
    """One issue as a compact record: who opened it and when the first replies came (their text is never read)."""
    author = node.get("author") or {}
    talk = [[c.get("createdAt"), (c.get("author") or {}).get("login"), c.get("authorAssociation"),
             (c.get("author") or {}).get("__typename")]
            for c in (node.get("comments") or {}).get("nodes") or [] if c and c.get("createdAt")]
    return {"t": "issue", "n": node["number"], "st": node.get("state"), "cr": node.get("createdAt"),
            "up": node.get("updatedAt"), "cl": node.get("closedAt"), "au": author.get("login"), "at": author.get("__typename"),
            "as": node.get("authorAssociation"), "cm": sorted(talk, key=lambda c: c[0]),
            "cmn": (node.get("comments") or {}).get("totalCount"),
            # Who closed it: an author closing their own issue is not an answer.
            "clb": (((((node.get("closer") or {}).get("nodes") or [None])[-1]) or {}).get("actor") or {}).get("login"),
            # Who labelled, assigned or marked it a duplicate: on GitHub only people with triage rights can, on others' issues.
            "tr": sorted({((e.get("actor") or {}).get("login"), e.get("createdAt")) for e in ((node.get("triage") or {}).get("nodes") or [])
                          if e and e.get("createdAt") and (e.get("actor") or {}).get("__typename") == "User"
                          and (e.get("actor") or {}).get("login") not in (None, author.get("login"))}),
            # Labels say which issues are incidents (Delivery's change failure rate).
            "lb": [x["name"] for x in (node.get("labels") or {}).get("nodes") or [] if x and x.get("name")],
            "f": now.strftime("%Y-%m-%dT%H:%M:%SZ")}


def discussion_record(node: dict, now: datetime) -> dict:
    """A discussion kept like an issue (the same answer rule reads both), with its category and when an answer was chosen."""
    rec = issue_record({**node, "state": "CLOSED" if node.get("closed") else "OPEN"}, now)
    cat = node.get("category") or {}
    return {**rec, "t": "discussion", "cat": cat.get("name"), "qa": bool(cat.get("isAnswerable")), "ans": node.get("answerChosenAt")}


def collect_discussions(gql, store: FlowStore, owner: str, name: str, now: datetime, months: int = 12, page: int = 50,
                        max_pages: int = 40) -> dict:
    """Discussions updated since the last run (or the last `months`), newest first, stopping at what was already read."""
    state = store.state()
    floor = (datetime.fromisoformat(state["synced_up_to"].replace("Z", "+00:00")) - OVERLAP if state.get("synced_up_to")
             else now - timedelta(days=30 * months)).strftime("%Y-%m-%dT%H:%M:%SZ")
    opened, closed = store.open(), defaultdict(list)
    cursor, newest, count, cost, complete, pages = None, None, 0, 0, True, 0
    while pages < max_pages:
        try:
            result = gql.query(DISCUSSIONS_QUERY, {"owner": owner, "name": name, "cursor": cursor, "n": page})
        except RateLimited:
            complete = False
            break
        except GraphQLError as exc:
            # Discussions off, or the token can't read them: nothing to keep, and the run goes on.
            return {"discussions": 0, "points": cost, "complete": False, "refused": "not accessible" in str(exc).lower()}
        pages += 1
        cost += result.cost
        block = (result.data.get("repository") or {}).get("discussions") or {"nodes": [], "pageInfo": {}}
        stop = False
        for node in block["nodes"]:
            if not node:
                continue
            if node["updatedAt"] < floor:
                stop = True
                break
            newest = newest or node["updatedAt"]
            rec = discussion_record(node, now)
            count += 1
            if rec["st"] == "OPEN":
                opened[rec["n"]] = rec
            else:
                opened.pop(rec["n"], None)
                closed[(rec["cl"] or rec["up"])[:10]].append(rec)
        if stop or not (block.get("pageInfo") or {}).get("hasNextPage"):
            break
        cursor = block["pageInfo"]["endCursor"]
    else:
        complete = False
    for day, recs in closed.items():
        store.put(recs, day)
    store.save_open(opened)
    if complete:
        state["synced_up_to"] = max(filter(None, [newest, state.get("synced_up_to")]), default=None)
    store.save_state(state)
    return {"discussions": count, "points": cost, "complete": complete}


def collect_issues(gql, store: FlowStore, owner: str, name: str, now: datetime, months: int = 12, page: int = 50,
                   max_pages: int = 200) -> dict:
    """Issues updated since the last run (or the last `months` on the first), about 1 point per 50 issues."""
    state = store.state()
    synced = state.get("synced_up_to") if state.get("schema", 0) >= SCHEMA else None
    floor = (datetime.fromisoformat(synced.replace("Z", "+00:00")) - OVERLAP if synced
             else now - timedelta(days=30 * months)).strftime("%Y-%m-%dT%H:%M:%SZ")
    opened, closed = store.open(), defaultdict(list)
    cursor, newest, count, cost, complete, pages = None, None, 0, 0, True, 0
    while pages < max_pages:
        try:
            result = gql.query(ISSUES_QUERY, {"owner": owner, "name": name, "cursor": cursor, "n": page, "since": floor})
        except RateLimited:
            complete = False
            break
        except GraphQLError as exc:
            text = str(exc).lower()
            # The workflow lacks `issues: read`: said in the summary, and the rest of the run goes on.
            if "not accessible" in text:
                return {"issues": 0, "points": cost, "complete": False, "refused": True}
            # Issues turned off in this repo: nothing to read.
            if "disabled" in text:
                break
            raise
        pages += 1
        cost += result.cost
        block = (result.data.get("repository") or {}).get("issues") or {"nodes": [], "pageInfo": {}}
        stop = False
        for node in block["nodes"]:
            if not node:
                continue
            # The filter keeps older issues out; this guards against GitHub returning one anyway.
            if node["updatedAt"] < floor:
                stop = True
                break
            newest = newest or node["updatedAt"]
            rec = issue_record(node, now)
            count += 1
            if rec["st"] == "OPEN":
                opened[rec["n"]] = rec
            else:
                opened.pop(rec["n"], None)
                closed[(rec["cl"] or rec["up"])[:10]].append(rec)
        if stop or not (block.get("pageInfo") or {}).get("hasNextPage"):
            break
        cursor = block["pageInfo"]["endCursor"]
    else:
        complete = False
    for day, recs in closed.items():
        store.put(recs, day)
    store.save_open(opened)
    if complete:
        state["synced_up_to"] = max(filter(None, [newest, synced]), default=None)
        state["schema"] = SCHEMA
    state["last_collect"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    store.save_state(state)
    store.compress(now.date().isoformat())
    return {"issues": count, "points": cost, "complete": complete}


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8", newline="\n")


def collect_stars(api, folder: Path, now: datetime, max_pages: int = 100) -> dict:
    """GitHub's weekly star counts (no stargazer names): all of it the first time, then the newest 30 weeks once a day."""
    path = Path(folder) / "stars.json"
    old = _read(path)
    weeks = {str(k): v for k, v in (old.get("weeks") or {}).items()}
    if (old.get("fetched") or "")[:10] == now.strftime("%Y-%m-%d"):
        return {"requests": 0, "weeks": len(weeks)}
    requests = 0
    for page in range(1, (1 if weeks else max_pages) + 1):
        rows = api._get(f"/repos/{api.repo}/stargazers/history", {"per_page": 30, "page": page})
        requests += 1
        if not isinstance(rows, list) or not rows:
            break
        for r in rows:
            if isinstance(r, dict) and isinstance(r.get("week"), int):
                weeks[str(r["week"])] = int(r.get("total") or 0)
        if len(rows) < 30:
            break
    _write(path, {"weeks": weeks, "fetched": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return {"requests": requests, "weeks": len(weeks)}


def collect_traffic(api, folder: Path, now: datetime, keep_days: int = 400) -> dict:
    """Views and clones per day kept past GitHub's 14 days; the top referrers and paths as a dated snapshot.
    Needs a token with Administration read (the user's own GitHub App), which the built-in token can't have."""
    path = Path(folder) / "traffic.json"
    out = {k: dict(_read(path).get(k) or {}) for k in ("views", "clones", "referrers", "paths")}
    for key in ("views", "clones"):
        body = api._get(f"/repos/{api.repo}/traffic/{key}", {"per": "day"})
        for x in body.get(key) or []:
            if isinstance(x, dict) and x.get("timestamp"):
                # The newest answer wins: today's count grows during the day.
                out[key][x["timestamp"][:10]] = [int(x.get("count") or 0), int(x.get("uniques") or 0)]
    day = now.strftime("%Y-%m-%d")
    refs = api._get(f"/repos/{api.repo}/traffic/popular/referrers")
    out["referrers"][day] = [[r.get("referrer"), r.get("count"), r.get("uniques")] for r in refs or [] if isinstance(r, dict)][:10]
    # Page titles are text anyone can set; only the paths are kept.
    paths = api._get(f"/repos/{api.repo}/traffic/popular/paths")
    out["paths"][day] = [[p.get("path"), p.get("count"), p.get("uniques")] for p in paths or [] if isinstance(p, dict)][:10]
    oldest = (now - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    for key in ("referrers", "paths"):
        out[key] = {d: v for d, v in out[key].items() if d >= oldest}
    _write(path, out)
    return {"requests": 4, "days": len(out["views"])}
