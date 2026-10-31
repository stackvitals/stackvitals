"""Linear: issues of the chosen teams, their state and cycle changes, and the teams' cycles, read with a personal API key
over GraphQL. A pass reads everything updated in a fixed span; a capped pass carries on from its cursor next run."""
from datetime import datetime, timedelta

import httpx

from stackvitals.connectors.base import BACKFILL_DAYS, PAGES, ConnectorError, std_type, utc
from stackvitals.core.time import iso

NAME, TOKEN_ENV = "linear", "STACKVITALS_LINEAR_TOKEN"
URL = "https://api.linear.app/graphql"
# What is asked for: 2 adds the assignee and 3 its name, so answers kept before are read again, not rebuilt.
ASKED = 3
CATEGORY = {"triage": "TODO", "backlog": "TODO", "unstarted": "TODO", "started": "IN_PROGRESS", "completed": "DONE",
            "canceled": "DONE"}
PRIORITY = {0: None, 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}
ISSUES = """query Issues($filter: IssueFilter, $after: String) {
  issues(first: 50, after: $after, orderBy: updatedAt, includeArchived: true, filter: $filter) {
    nodes { id identifier title url priority estimate createdAt updatedAt startedAt completedAt canceledAt
      state { name type } team { key } labels(first: 10) { nodes { name } } cycle { id } project { id name } assignee { id email name }
      history(first: 30) { nodes { createdAt fromState { name } toState { name } fromCycleId toCycleId } } }
    pageInfo { hasNextPage endCursor } } }"""
CYCLES = """query Cycles($filter: CycleFilter, $after: String) {
  cycles(first: 50, after: $after, filter: $filter) {
    nodes { id number name startsAt endsAt completedAt team { key } }
    pageInfo { hasNextPage endCursor } } }"""

__all__ = ["ConnectorError", "configured", "pull"]


def configured(env: dict, cfg: dict) -> bool:
    return bool((env.get(TOKEN_ENV) or "").strip())


def _post(client: httpx.Client, key: str, query: str, variables: dict) -> dict:
    try:
        resp = client.post(URL, json={"query": query, "variables": variables},
                           headers={"Authorization": key, "Content-Type": "application/json"})
    except httpx.HTTPError as exc:
        raise ConnectorError(f"Linear could not be reached ({type(exc).__name__}); the next run tries again.") from None
    try:
        body = resp.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    errors = body.get("errors") or []
    codes = {str((e.get("extensions") or {}).get("code") or "") for e in errors}
    if resp.status_code in (401, 403) or "AUTHENTICATION_ERROR" in codes:
        raise ConnectorError(f"Linear refused the key ({resp.status_code}): check the LINEAR_API_KEY secret.")
    if resp.status_code == 429 or "RATELIMITED" in codes:
        raise ConnectorError("Linear's hourly limit for this key is used up; the next run carries on.")
    if errors or resp.status_code != 200:
        said = "; ".join(str(e.get("message") or "") for e in errors)[:200]
        raise ConnectorError(f"Linear could not run the query ({said or resp.status_code}); check teams under [connectors.linear].")
    return body.get("data") or {}


def _issue_records(n: dict, incident_labels: set[str]) -> list[dict]:
    state = n.get("state") or {}
    labels = [x.get("name") or "" for x in (n.get("labels") or {}).get("nodes") or []]
    low = {x.lower() for x in labels}
    incident = bool(low & incident_labels)
    iid = f"linear:{n['id']}"
    history = (n.get("history") or {}).get("nodes") or []
    # The cycles an issue was ever in: its current one and every one its history moved it into or out of.
    cycles = {c for c in [(n.get("cycle") or {}).get("id"), *(h.get(k) for h in history for k in ("fromCycleId", "toCycleId"))] if c}
    out = [{"t": "issue", "src": NAME, "id": iid, "key": n["identifier"], "title": n.get("title"),
            "type": "INCIDENT" if incident else next((std_type(x) for x in labels if std_type(x) != "TASK"), "TASK"),
            "original_type": None, "status": state.get("name"), "cat": CATEGORY.get(state.get("type"), "TODO"),
            "created": utc(n.get("createdAt")), "updated": utc(n.get("updatedAt")),
            "resolved": utc(n.get("completedAt") or n.get("canceledAt")),
            "points": n.get("estimate") if isinstance(n.get("estimate"), (int, float)) else None,
            "priority": PRIORITY.get(n.get("priority")), "labels": labels,
            "sprints": sorted(f"linear:cycle:{c}" for c in cycles), "incident": incident,
            "canceled": state.get("type") == "canceled", "url": n.get("url"),
            # Who it is assigned to, for [identity] aliases to name the GitHub login; never kept on a public repo.
            **({"assignee": f"linear:{n['assignee']['id']}", "assignee_email": n["assignee"].get("email"),
                "assignee_name": n["assignee"].get("name")}
               if (n.get("assignee") or {}).get("id") else {}),
            # A Linear project stands for the epic: what a body of work belongs to.
            **({"epic": f"linear:project:{n['project']['id']}", "epic_title": n["project"].get("name")}
               if (n.get("project") or {}).get("id") else {})}]
    for k, h in enumerate(history):
        if h.get("fromState") or h.get("toState"):
            out.append({"t": "change", "src": NAME, "id": f"{iid}:{h.get('createdAt')}:{k}:status", "issue": iid,
                        "field": "status", "from": (h.get("fromState") or {}).get("name"),
                        "to": (h.get("toState") or {}).get("name"), "at": utc(h.get("createdAt"))})
        if h.get("fromCycleId") or h.get("toCycleId"):
            out.append({"t": "change", "src": NAME, "id": f"{iid}:{h.get('createdAt')}:{k}:cycle", "issue": iid,
                        "field": "sprint", "from": [f"linear:cycle:{h['fromCycleId']}"] if h.get("fromCycleId") else [],
                        "to": [f"linear:cycle:{h['toCycleId']}"] if h.get("toCycleId") else [], "at": utc(h.get("createdAt"))})
    return out


def _cycle_record(c: dict, now: datetime) -> dict:
    start = utc(c.get("startsAt"))
    state = "CLOSED" if c.get("completedAt") else "ACTIVE" if start and start <= iso(now) else "FUTURE"
    return {"t": "sprint", "src": NAME, "id": f"linear:cycle:{c['id']}", "name": c.get("name") or f"Cycle {c.get('number')}",
            "state": state, "start": start, "end": utc(c.get("endsAt")), "complete": utc(c.get("completedAt"))}


def pull(store, env: dict, cfg: dict, now: datetime, client: httpx.Client | None = None, pages: int = PAGES) -> dict:
    c = cfg["connectors"]["linear"]
    key = env.get(TOKEN_ENV, "").strip()
    teams = {"team": {"key": {"in": list(c["teams"])}}} if c["teams"] else {}
    labels = {x.lower() for x in c["incident_labels"]}
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        state = store.state()
        since = state.get("since") or iso(now - timedelta(days=BACKFILL_DAYS))
        until = state.get("until") or iso(now)
        cursor, day = state.get("cursor"), now.date().isoformat()
        # Every cycle that ended inside the window or is still to come, page by page.
        after, floor = None, iso(now - timedelta(days=BACKFILL_DAYS))
        for _ in range(pages):
            cycles = _post(client, key, CYCLES, {"filter": {**teams, "endsAt": {"gte": floor}}, "after": after}).get("cycles") or {}
            store.add([_cycle_record(x, now) for x in cycles.get("nodes") or []], day)
            info = cycles.get("pageInfo") or {}
            after = info.get("endCursor") if info.get("hasNextPage") else None
            if after is None:
                break
        read, complete = 0, False
        for _ in range(pages):
            found = _post(client, key, ISSUES, {"filter": {"updatedAt": {"gte": since, "lte": until}, **teams},
                                                "after": cursor}).get("issues") or {}
            nodes = found.get("nodes") or []
            store.add([r for n in nodes for r in _issue_records(n, labels)], day)
            read += len(nodes)
            info = found.get("pageInfo") or {}
            cursor = info.get("endCursor") if info.get("hasNextPage") else None
            if cursor is None:
                complete = True
                break
        # A finished pass moves on to whatever changed after it began; a capped one keeps its span and cursor.
        store.save_state({"since": until} if complete else {"since": since, "until": until, "cursor": cursor})
        return {"read": read, "incidents": 0, "complete": complete}
    finally:
        if own:
            client.close()
