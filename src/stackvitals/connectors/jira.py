"""Jira Cloud: issues in the scope query, their status and sprint changes, and their sprints, read with the account's email
and an API token (REST v3 enhanced search), resuming from the newest update read last time."""
import base64
import re
from datetime import datetime, timedelta

import httpx

from stackvitals.connectors.base import BACKFILL_DAYS, PAGES, ConnectorError, request, std_type, utc
from stackvitals.core.time import iso, parse

NAME, TOKEN_ENV, EMAIL_ENV = "jira", "STACKVITALS_JIRA_TOKEN", "STACKVITALS_JIRA_EMAIL"
# What is asked for: 2 adds the assignee, so answers kept before it are read again, not rebuilt.
ASKED = 2
PAGE = 100
# JQL reads dates in the account's own time zone, so each pull starts a day early; records seen twice just win again.
OVERLAP = timedelta(days=1)
SPRINT_FIELD = "com.pyxis.greenhopper.jira:gh-sprint"
POINTS_FIELDS = {"com.pyxis.greenhopper.jira:jsw-story-points", "com.atlassian.jira.plugin.system.customfieldtypes:float"}
CATEGORY = {"new": "TODO", "indeterminate": "IN_PROGRESS", "done": "DONE"}
NOT_DONE = {"won't do", "won't fix", "duplicate", "cannot reproduce", "declined", "rejected"}

__all__ = ["ConnectorError", "configured", "extract", "pull"]


def configured(env: dict, cfg: dict) -> bool:
    return bool((env.get(TOKEN_ENV) or "").strip())


def _bad(resp) -> str | None:
    if resp.status_code != 400:
        return None
    try:
        said = "; ".join((resp.json() or {}).get("errorMessages") or [])[:200]
    except (ValueError, AttributeError):
        said = ""
    return f"Jira could not run the query ({said or 'bad request'}): check scope_jql and incident_jql under [connectors.jira]."


def _get(client: httpx.Client, path: str, params: dict | None, auth: str):
    return request(client, "GET", path, "Jira", kinds=(dict, list), bad=_bad, params=params,
                   refused="check the JIRA_EMAIL and JIRA_API_TOKEN secrets and that the token has not expired",
                   headers={"Authorization": auth, "Accept": "application/json"})


def _ids(text: str | None) -> list[str]:
    return [f"jira:sprint:{x}" for x in re.findall(r"\d+", text or "")]


def _epic(parent) -> dict:
    # The epic an issue belongs to is its parent when that parent is an epic (a sub-task's parent is a story).
    f = (parent or {}).get("fields") or {}
    if not parent or "epic" not in ((f.get("issuetype") or {}).get("name") or "").lower():
        return {}
    return {"epic": parent.get("key"), "epic_title": f.get("summary")}


def _text(value) -> str | None:
    """A custom field's value as text: an option's value, a team's or user's name, or the first of a list."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("value") or value.get("name") or value.get("title") or value.get("displayName")
    return str(value)[:100] if value not in (None, "") else None


def field_id(fields: list[dict], wanted: str) -> str | None:
    """The id of the field the settings name, by its id or its name (any case)."""
    w = (wanted or "").strip().lower()
    return next((f["id"] for f in fields if w and w in ((f.get("id") or "").lower(), (f.get("name") or "").lower())), None)


def _records(raw: dict, site: str, sprint_f: str | None, points_f: str | None, incident: bool, extra: dict | None = None) -> list[dict]:
    f = raw.get("fields") or {}
    status = f.get("status") or {}
    kind = (f.get("issuetype") or {}).get("name") or ""
    sprints = [s for s in (f.get(sprint_f) or [] if sprint_f else []) if isinstance(s, dict) and s.get("id") is not None]
    points = f.get(points_f) if points_f else None
    iid = f"jira:{raw['id']}"
    histories = (raw.get("changelog") or {}).get("histories") or []
    cat = CATEGORY.get((status.get("statusCategory") or {}).get("key"), "TODO")
    resolved = utc(f.get("resolutiondate"))
    if not resolved and cat == "DONE":
        # A workflow that never sets a resolution: done when it last moved into the status it is in.
        resolved = max((utc(h.get("created")) or "" for h in histories for item in h.get("items") or []
                        if (item.get("field") or "").lower() == "status" and item.get("toString") == status.get("name")),
                       default=None) or None
    out = [{"t": "issue", "src": NAME, "id": iid, "key": raw["key"], "title": f.get("summary"),
            "type": std_type(kind), "original_type": kind, "status": status.get("name"),
            "cat": cat, "created": utc(f.get("created")), "updated": utc(f.get("updated")), "resolved": resolved,
            "points": points if isinstance(points, (int, float)) and not isinstance(points, bool) else None,
            "priority": (f.get("priority") or {}).get("name"), "labels": [str(x) for x in f.get("labels") or []],
            "sprints": [f"jira:sprint:{s['id']}" for s in sprints], "incident": False,
            "canceled": ((f.get("resolution") or {}).get("name") or "").lower() in NOT_DONE,
            "url": f"{site}/browse/{raw['key']}", **_epic(f.get("parent")),
            # The fields the settings map (team_field, severity_field), as text.
            **{k: v for k, fid in (extra or {}).items() if fid and (v := _text(f.get(fid)))},
            # Who it is assigned to, for [identity] aliases to name the GitHub login; never kept on a public repo.
            **({"assignee": f"jira:{f['assignee']['accountId']}", "assignee_email": f["assignee"].get("emailAddress"),
                "assignee_name": f["assignee"].get("displayName")}
               if (f.get("assignee") or {}).get("accountId") else {})}]
    for h in histories:
        for k, item in enumerate(h.get("items") or []):
            field = (item.get("field") or "").lower()
            if field == "status":
                out.append({"t": "change", "src": NAME, "id": f"{iid}:{h.get('id')}:{k}", "issue": iid, "field": "status",
                            "from": item.get("fromString"), "to": item.get("toString"), "at": utc(h.get("created"))})
            elif field == "sprint":
                out.append({"t": "change", "src": NAME, "id": f"{iid}:{h.get('id')}:{k}", "issue": iid, "field": "sprint",
                            "from": _ids(item.get("from")), "to": _ids(item.get("to")), "at": utc(h.get("created"))})
    if incident:
        # Both queries write the issue alike; this mark makes it an incident at load while it is as new as the issue.
        out.append({"t": "mark", "src": NAME, "id": f"{iid}:incident", "issue": iid, "updated": utc(f.get("updated"))})
    for s in sprints:
        out.append({"t": "sprint", "src": NAME, "id": f"jira:sprint:{s['id']}", "name": s.get("name"),
                    "state": str(s.get("state") or "").upper(), "start": utc(s.get("startDate")),
                    "end": utc(s.get("endDate")), "complete": utc(s.get("completeDate"))})
    return out


def finish(got: dict) -> dict:
    """An issue is an incident while the incident query's mark is as new as the issue's latest update."""
    marks = {m["issue"]: m.get("updated") or "" for m in got.get("mark") or []}
    for i in got.get("issue") or []:
        if i["id"] in marks and marks[i["id"]] >= (i.get("updated") or ""):
            i["incident"], i["type"] = True, "INCIDENT"
    return got


def extract(kind: str, ctx: dict, body: dict) -> list[dict]:
    """The records in one kept answer (a page of the scope or incident search)."""
    return [r for raw in body.get("issues") or [] for r in _records(raw, ctx["site"], ctx["sprint_f"], ctx["points_f"], ctx["incident"], ctx.get("extra"))]


def _search(client, store, jql: str, wanted: list[str], auth: str, site: str, sprint_f, points_f, incident: bool,
            pages: int, day: str, extra: dict | None = None) -> tuple[int, str | None, str | None, bool]:
    """(issues read, newest update in UTC, that update as Jira wrote it in the account's zone, finished)."""
    read, newest, local, token = 0, None, None, None
    for _ in range(pages):
        body = _get(client, "/rest/api/3/search/jql", {"jql": jql, "fields": ",".join(wanted), "expand": "changelog",
                                                        "maxResults": PAGE, **({"nextPageToken": token} if token else {})}, auth)
        issues = body.get("issues") or []
        ctx = {"site": site, "sprint_f": sprint_f, "points_f": points_f, "incident": incident, "extra": extra or {}}
        store.keep("search", ctx, body, day)
        store.add(extract("search", ctx, body), day)
        read += len(issues)
        for raw in issues:
            stamp = (raw.get("fields") or {}).get("updated")
            if (utc(stamp) or "") > (newest or ""):
                newest, local = utc(stamp), stamp
        token = body.get("nextPageToken")
        if body.get("isLast") or not token:
            return read, newest, local, True
    return read, newest, local, False


def _minute(text: str, add: int = 0) -> str:
    return f"{datetime.strptime(text, '%Y/%m/%d %H:%M') + timedelta(minutes=add):%Y/%m/%d %H:%M}"


def pull(store, env: dict, cfg: dict, now: datetime, client: httpx.Client | None = None, pages: int = PAGES) -> dict:
    c = cfg["connectors"]["jira"]
    if not c["url"]:
        raise ConnectorError("Set url under [connectors.jira] in .github/stackvitals.toml to your Jira Cloud site "
                             "(https://<name>.atlassian.net).")
    email = (env.get(EMAIL_ENV) or "").strip() or c["email"]
    if not email:
        raise ConnectorError("Jira needs the account's email: the JIRA_EMAIL secret, or email under [connectors.jira].")
    auth = "Basic " + base64.b64encode(f"{email}:{env.get(TOKEN_ENV, '').strip()}".encode()).decode()
    own = client is None
    client = client or httpx.Client(base_url=c["url"], timeout=30, follow_redirects=False)
    try:
        fields = _get(client, "/rest/api/3/field", None, auth)
        custom = lambda f: (f.get("schema") or {}).get("custom")  # noqa: E731
        sprint_f = next((f["id"] for f in fields if custom(f) == SPRINT_FIELD), None)
        points_f = next((f["id"] for f in fields if custom(f) in POINTS_FIELDS
                         and re.fullmatch(r"(?i)story points?( estimate)?", f.get("name") or "")), None)
        extra = {k: field_id(fields, c.get(f"{k}_field") or "") for k in ("team", "severity")}
        wanted = ["summary", "issuetype", "status", "created", "updated", "resolutiondate", "resolution", "priority", "labels", "parent",
                  "assignee",
                  *(x for x in (sprint_f, points_f, *extra.values()) if x)]
        state, day = store.state(), now.date().isoformat()
        new, got, notes = dict(state), {}, []
        # Sleuth's way for teams with no pager tool: the issues the incident query finds are the incidents.
        queries = [("", c["scope_jql"].strip(), False)]
        if c["incident_jql"].strip():
            queries.append(("incident_", c["incident_jql"].strip(), True))
        for prefix, jql, incident in queries:
            since = state.get(prefix + "since") or iso(now - timedelta(days=BACKFILL_DAYS))
            # A capped pass carries on from the minute it reached, in the account's zone; a finished one reads a day again.
            start = state.get(prefix + "resume") or f"{parse(since) - OVERLAP:%Y/%m/%d %H:%M}"
            where = f'updated >= "{start}" ORDER BY updated ASC'
            read, newest, local, done = _search(client, store, f"({jql}) AND {where}" if jql else where, wanted, auth, c["url"],
                                                sprint_f, points_f, incident, pages, day, extra)
            new[prefix + "since"] = max(since, newest or since)
            new.pop(prefix + "resume", None)
            if not done and local:
                resume = f"{datetime.fromisoformat(local):%Y/%m/%d %H:%M}"
                if resume <= start:
                    resume = _minute(start, 1)
                    notes.append(f"more issues changed in one minute ({start}) than one run reads ({PAGE * pages:,}); "
                                 "the rest of that minute was skipped.")
                new[prefix + "resume"] = resume
            got[prefix] = (read, done)
        store.save_state(new)
        return {"read": got[""][0], "incidents": got.get("incident_", (0, True))[0], "complete": all(d for _r, d in got.values()),
                **({"note": " ".join(notes)} if notes else {})}
    finally:
        if own:
            client.close()
