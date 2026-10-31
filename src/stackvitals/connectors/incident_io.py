"""incident.io: real incidents (declined, canceled and merged ones are kept as not-incidents), read with an API key (v2 List
incidents), resuming from the newest update read; the resolve time is the incident's "Resolved at" timestamp."""
from datetime import datetime, timedelta

import httpx

from stackvitals.connectors.base import (
    BACKFILL_DAYS,
    PAGES,
    ConnectorError,
    json_of,
    utc,
)
from stackvitals.core.time import iso, parse

NAME, TOKEN_ENV = "incident_io", "STACKVITALS_INCIDENT_IO_TOKEN"
URL = "https://api.incident.io/v2/incidents"
PAGE = 250
OVERLAP = timedelta(hours=1)
CATEGORY = {"triage": "TODO", "live": "IN_PROGRESS", "paused": "IN_PROGRESS", "learning": "DONE", "closed": "DONE"}
NOT_INCIDENTS = {"declined", "canceled", "merged"}
NOT_REAL = {"test", "tutorial"}

__all__ = ["ConnectorError", "configured", "pull"]


def configured(env: dict, cfg: dict) -> bool:
    return bool((env.get(TOKEN_ENV) or "").strip())


def scope(cfg: dict) -> str | None:
    """Said on the Integrations page while every incident type counts for this repo."""
    if not cfg["connectors"]["incident_io"]["incident_types"]:
        return ("counts every incident type; list this repo's under incident_types in [connectors.incident_io] to count "
                "only those")
    return None


def _get(client: httpx.Client, key: str, params: dict) -> dict:
    try:
        resp = client.get(URL, params=params, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise ConnectorError(f"incident.io could not be reached ({type(exc).__name__}); the next run tries again.") from None
    if resp.status_code in (401, 403):
        raise ConnectorError(f"incident.io refused the key ({resp.status_code}): check the INCIDENT_IO_API_KEY secret.")
    if resp.status_code == 429:
        raise ConnectorError("incident.io's limit for listing incidents (60 a minute) was reached; the next run carries on.")
    if resp.status_code in (400, 404, 422) and "after" in params:
        return None  # the saved place in a pass is no longer known
    if resp.status_code != 200:
        raise ConnectorError(f"incident.io answered {resp.status_code}; the next run tries again.")
    return json_of(resp, "incident.io")


def _resolved(i: dict) -> str | None:
    for stamp in i.get("incident_timestamp_values") or []:
        if ((stamp.get("incident_timestamp") or {}).get("name") or "").lower() == "resolved at":
            return utc((stamp.get("value") or {}).get("value"))
    return None


def _record(i: dict, types: set[str]) -> dict:
    category = (i.get("incident_status") or {}).get("category")
    cat = CATEGORY.get(category, "TODO")
    return {"t": "issue", "src": NAME, "id": f"incident_io:{i['id']}", "key": i.get("reference"), "title": i.get("name"),
            "type": "INCIDENT", "original_type": None, "status": (i.get("incident_status") or {}).get("name"), "cat": cat,
            "created": utc(i.get("created_at")), "updated": utc(i.get("updated_at")), "resolved": _resolved(i) if cat == "DONE" else None,
            "points": None, "priority": (i.get("severity") or {}).get("name"),
            "labels": [x for x in ((i.get("severity") or {}).get("name"),) if x], "sprints": [], "incident": True,
            "canceled": False, "url": i.get("permalink"),
            # One declined or merged after it was read stays stored, but no longer as an incident; so do test runs and
            # (when incident_types is set) other teams' types.
            **({"incident": False, "canceled": True} if category in NOT_INCIDENTS or i.get("mode") in NOT_REAL
               or types and ((i.get("incident_type") or {}).get("name") or "").lower() not in types else {})}


def pull(store, env: dict, cfg: dict, now: datetime, client: httpx.Client | None = None, pages: int = PAGES) -> dict:
    key = env.get(TOKEN_ENV, "").strip()
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        types = {t.lower() for t in cfg["connectors"]["incident_io"]["incident_types"]}
        state = store.state()
        since = state.get("since") or iso(now - timedelta(days=BACKFILL_DAYS))
        params = {"page_size": PAGE, "updated_at[gte]": iso(parse(since) - OVERLAP), "sort_by": "created_at_oldest_first"}
        # Sorted by creation, not update, so a capped pass keeps its place and only a finished one moves `since` on.
        after, newest = state.get("after"), state.get("newest") or since
        read, complete, day = 0, False, now.date().isoformat()
        for _ in range(pages):
            body = _get(client, key, {**params, **({"after": after} if after else {})})
            if body is None:
                after, newest = None, since
                continue
            found = body.get("incidents") or []
            store.add([_record(i, types) for i in found], day)
            read += len(found)
            newest = max([newest, *(utc(i.get("updated_at")) or "" for i in found)])
            after = (body.get("pagination_meta") or {}).get("after")
            if not after:
                complete = True
                break
        store.save_state({"since": newest} if complete else {"since": since, **({"after": after, "newest": newest} if after else {})})
        return {"read": read, "incidents": read, "complete": complete}
    finally:
        if own:
            client.close()
