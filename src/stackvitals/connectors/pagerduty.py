"""PagerDuty: incidents of the chosen services and urgencies, read with a REST API key (v2 List incidents). Incidents are
found by when they began, so each pull reads the last two weeks again to catch the ones resolved since."""
from datetime import datetime, timedelta

import httpx

from stackvitals.connectors.base import BACKFILL_DAYS, PAGES, ConnectorError, request, utc
from stackvitals.core.time import iso, parse

NAME, TOKEN_ENV = "pagerduty", "STACKVITALS_PAGERDUTY_TOKEN"
URL = "https://api.pagerduty.com/incidents"
PAGE = 100
REREAD = timedelta(days=14)
CHUNK = timedelta(days=90)  # PagerDuty takes at most six months per query
CATEGORY = {"triggered": "TODO", "acknowledged": "IN_PROGRESS", "resolved": "DONE"}

__all__ = ["ConnectorError", "configured", "extract", "pull"]


def configured(env: dict, cfg: dict) -> bool:
    return bool((env.get(TOKEN_ENV) or "").strip())


def scope(cfg: dict) -> str | None:
    """Said on the Integrations page while every service's incidents count for this repo."""
    if not cfg["connectors"]["pagerduty"]["services"]:
        return "reads every service in the account; list this repo's under services in [connectors.pagerduty] to count only those"
    return None


def _get(client: httpx.Client, key: str, params: list, sleep=None) -> dict:
    return request(client, "GET", URL, "PagerDuty", refused="check the PAGERDUTY_API_KEY secret",
                   bad=lambda r: f"PagerDuty answered {r.status_code}; check services and urgencies under [connectors.pagerduty].",
                   params=params, headers={"Authorization": f"Token token={key}",
                                           "Accept": "application/vnd.pagerduty+json;version=2"},
                   **({"sleep": sleep} if sleep else {}))


def _record(i: dict) -> dict:
    status = i.get("status")
    resolved = utc(i.get("resolved_at") or (i.get("last_status_change_at") if status == "resolved" else None))
    service = (i.get("service") or {}).get("summary")
    return {"t": "issue", "src": NAME, "id": f"pagerduty:{i['id']}", "key": f"PD-{i.get('incident_number')}",
            "title": i.get("title"), "type": "INCIDENT", "original_type": None, "status": status,
            "cat": CATEGORY.get(status, "TODO"), "created": utc(i.get("created_at")), "updated": utc(i.get("updated_at")),
            "resolved": resolved if status == "resolved" else None, "points": None, "priority": i.get("urgency"),
            "labels": [x for x in (i.get("urgency"), service) if x], "sprints": [], "incident": True, "canceled": False,
            "url": i.get("html_url")}


def extract(kind: str, ctx: dict, body: dict) -> list[dict]:
    """The records in one kept answer (a page of incidents)."""
    return [_record(i) for i in body.get("incidents") or []]


def pull(store, env: dict, cfg: dict, now: datetime, client: httpx.Client | None = None, pages: int = PAGES) -> dict:
    c = cfg["connectors"]["pagerduty"]
    key = env.get(TOKEN_ENV, "").strip()
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        state = store.state()
        floor = now - timedelta(days=BACKFILL_DAYS)
        if state.get("since"):
            # A capped pass carries on from the last incident it read; only a finished one reads two weeks again.
            since = parse(state["since"])
            start = max(since if state.get("catching_up") else since - REREAD, floor)
        else:
            start = floor
        read, used, day = 0, 0, now.date().isoformat()
        while start < now and used < pages:
            end, last = min(start + CHUNK, now), None
            for offset in range(0, PAGE * (pages - used), PAGE):
                params = [("since", iso(start)), ("until", iso(end)), ("time_zone", "UTC"), ("sort_by", "created_at:asc"),
                          ("limit", PAGE), ("offset", offset), *(("service_ids[]", s) for s in c["services"]),
                          *(("urgencies[]", u) for u in c["urgencies"])]
                body = _get(client, key, params)
                used += 1
                found = body.get("incidents") or []
                store.keep("incidents", {}, body, day)
                store.add(extract("incidents", {}, body), day)
                read += len(found)
                last = max([last or "", *(utc(i.get("created_at")) or "" for i in found)]) or last
                if not body.get("more"):
                    break
            else:
                # Capped inside a chunk: the next run starts at the newest incident read, always a little further on.
                start = max(parse(last), start + timedelta(seconds=1)) if last else start
                break
            start = end
        complete = start >= now
        store.save_state({"since": iso(now)} if complete else {"since": iso(start), "catching_up": True})
        return {"read": read, "incidents": read, "complete": complete}
    finally:
        if own:
            client.close()
