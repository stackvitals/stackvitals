"""Discourse: a project's forum, read from its public JSON (no key): each topic of the last 180 days, when anyone first
replied, when the team first did (forum staff, the usernames under `team`, or members of the `groups`), and whether it
was solved. Only times and flags are kept: no usernames, titles or post text."""
import time
from datetime import datetime, timedelta

import httpx

from stackvitals.connectors.base import BACKFILL_DAYS, ConnectorError, json_of, utc
from stackvitals.core import stats

NAME = "discourse"
LIST_PAGES, TOPICS = 10, 120  # a run reads at most 10 list pages and 120 topics; the next run carries on
PAUSE, MAX_WAIT = 0.25, 60

__all__ = ["ConnectorError", "configured", "pull", "answers"]


def configured(env: dict, cfg: dict) -> bool:
    return bool(((cfg.get("connectors") or {}).get(NAME) or {}).get("url"))


def _get(client: httpx.Client, path: str, sleep=time.sleep, **params) -> dict:
    for attempt in (1, 2):
        sleep(PAUSE)  # a public forum, read politely: well under Discourse's anonymous limit
        try:
            resp = client.get(path, params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise ConnectorError(f"The forum could not be reached ({type(exc).__name__}); the next run tries again.") from None
        if resp.status_code != 429:
            break
        wait = float(resp.headers.get("retry-after", MAX_WAIT))
        if attempt == 2 or wait > MAX_WAIT:
            raise ConnectorError("The forum's rate limit was reached; what was read is kept and the next run carries on.")
        sleep(wait)
    if resp.status_code != 200:
        raise ConnectorError(f"The forum answered {resp.status_code} for {path}; check url under [connectors.discourse].")
    return json_of(resp, "The forum")


def _record(topic: dict, posts: list[dict], team: set[str], groups: set[str]) -> dict:
    def ours(p):
        return bool(p.get("staff")) or (p.get("username") or "").lower() in team or (p.get("primary_group_name") or "").lower() in groups
    # Only people's regular posts are replies: moderator notes ("closed", "moved") and the system account's aren't.
    posts = [p for p in posts if p.get("post_type", 1) == 1 and p.get("username") != "system"]
    first, replies = posts[0] if posts else {}, posts[1:]
    reply = next((p for p in replies if p.get("username") != first.get("username")), None)
    team_reply = next((p for p in replies if ours(p) and p.get("username") != first.get("username")), None)
    return {"t": "topic", "src": NAME, "id": f"{NAME}:{topic['id']}", "created": utc(topic.get("created_at")),
            "updated": utc(topic.get("last_posted_at") or topic.get("created_at")), "by_team": ours(first),
            "first_reply": utc((reply or {}).get("created_at")), "first_team_reply": utc((team_reply or {}).get("created_at")),
            "solved": bool(topic.get("has_accepted_answer")), "closed": bool(topic.get("closed"))}


def pull(store, env: dict, cfg: dict, now: datetime, client: httpx.Client | None = None, pages: int = LIST_PAGES,
         sleep=time.sleep) -> dict:
    c = cfg["connectors"][NAME]
    team, groups = {x.lower() for x in c["team"]}, {x.lower() for x in c["groups"]}
    since = utc((now - timedelta(days=BACKFILL_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    known = {r["id"]: r for r in store.load().get("topic") or []}
    own = client is None
    client = client or httpx.Client(base_url=c["url"].rstrip("/"), timeout=30, follow_redirects=False)
    read, complete, fresh = 0, True, []
    try:
        for page in range(pages):
            listing = (_get(client, "/latest.json", sleep, order="created", page=page).get("topic_list") or {})
            topics = listing.get("topics") or []
            old = False
            for t in topics:
                created = utc(t.get("created_at"))
                if not created or created < since:
                    old = True
                    continue
                stored = known.get(f"{NAME}:{t['id']}")
                # A topic is read again only when it has new posts and is not settled yet.
                if stored and stored["updated"] >= (utc(t.get("last_posted_at")) or "") or (stored and stored["first_team_reply"]):
                    continue
                if read >= TOPICS:
                    complete = False
                    break
                posts = (_get(client, f"/t/{t['id']}.json", sleep).get("post_stream") or {}).get("posts") or []
                fresh.append(_record(t, posts, team, groups))
                read += 1
            if old or not topics or not listing.get("more_topics_url") or not complete:
                break
        else:
            complete = False
    finally:
        if own:
            client.close()
        store.add(fresh, now.date().isoformat())  # kept even when a later request failed
    return {"read": read, "complete": complete}


def answers(topics: list[dict], now: datetime, days: int = 90) -> dict | None:
    """Topics opened by people outside the team in the last `days`: how fast the team first replied (topics still
    waiting stay in the median), how often anyone replied first, and the share solved."""
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mine = [t for t in topics if not t.get("by_team") and (t.get("created") or "") >= since]
    if not mine:
        return None

    def hours(a, b):
        return (datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds() / 3600
    end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    # A topic closed without a team reply stops the clock at its last post; only open ones are still waiting.
    km = stats.km_median([hours(t["created"], t["first_team_reply"] or (t.get("updated") if t.get("closed") else None) or end)
                          for t in mine], [bool(t["first_team_reply"]) for t in mine])
    waits = sorted(hours(t["created"], t["first_team_reply"]) for t in mine if t["first_team_reply"])
    mid = len(waits) // 2
    median = (waits[mid] if len(waits) % 2 else (waits[mid - 1] + waits[mid]) / 2) if waits else None
    return {"days": days, "topics": len(mine), "km": km, "median_hours": round(median, 2) if median is not None else None,
            "team_answered": round(len(waits) / len(mine), 4),
            "anyone_answered": round(sum(1 for t in mine if t["first_reply"]) / len(mine), 4),
            # Chat has no solved mark: None there, not zero.
            "solved_share": round(sum(1 for t in mine if t["solved"]) / len(mine), 4)
            if any(t.get("solved") is not None for t in mine) else None}
