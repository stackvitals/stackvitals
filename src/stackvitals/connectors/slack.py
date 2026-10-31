"""Slack: support channels read with a bot token the user installs (channels:history, groups:history): each top-level
message, when anyone first replied in its thread and when the team did (the user ids under `team`). The first pull reads
180 days, later ones the last 30 (where new replies land); what was read is kept even when a later call fails. Only
times and flags are kept: no text and no user ids."""
import time
from datetime import datetime, timedelta, timezone

import httpx

from stackvitals.connectors.base import BACKFILL_DAYS, PAGES, ConnectorError, json_of
from stackvitals.core import identity

NAME, TOKEN_ENV = "slack", "STACKVITALS_SLACK_TOKEN"
API = "https://slack.com/api"
THREADS = 150  # thread reads a run; the next run carries on
RECENT_DAYS = 30
MAX_WAIT = 60

__all__ = ["ConnectorError", "configured", "pull"]


def configured(env: dict, cfg: dict) -> bool:
    return bool((env.get(TOKEN_ENV) or "").strip())


def _iso(ts: str | None) -> str | None:
    return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None


def _call(client: httpx.Client, key: str, method: str, sleep, **params) -> dict:
    for attempt in (1, 2):
        try:
            resp = client.get(f"{API}/{method}", params=params, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Slack could not be reached ({type(exc).__name__}); the next run tries again.") from None
        if resp.status_code == 429:
            wait = float(resp.headers.get("retry-after", MAX_WAIT))
            if attempt == 1 and wait <= MAX_WAIT:
                sleep(wait)  # Slack says how long; one wait, then the run carries on next time
                continue
            raise ConnectorError("Slack's rate limit was reached; what was read is kept and the next run carries on.")
        body = json_of(resp, "Slack")
        if not body.get("ok"):
            raise ConnectorError(f"Slack refused {method} ({body.get('error')}): the bot needs channels:history and to be "
                                 "in each channel under [connectors.slack] channels.")
        return body
    raise ConnectorError("Slack's rate limit was reached; the next run carries on.")


def _people(messages: list[dict]) -> list[dict]:
    return [m for m in messages if m.get("user") and not m.get("bot_id") and m.get("subtype") in (None, "thread_broadcast")]


def pull(store, env: dict, cfg: dict, now: datetime, client: httpx.Client | None = None, pages: int = PAGES,
         sleep=time.sleep) -> dict:
    c = cfg["connectors"][NAME]
    # Team members are the ids listed here, plus those [identity] aliases map to a team member.
    key, team = env.get(TOKEN_ENV, "").strip(), set(c["team"]) | identity.tool_ids(cfg.get("identity"), NAME)
    state = store.state()
    days = RECENT_DAYS if state.get("backfilled") else BACKFILL_DAYS
    oldest = f"{(now - timedelta(days=days)).timestamp():.6f}"
    known = {r["id"]: r for r in store.load().get("topic") or []}
    own = client is None
    client = client or httpx.Client(timeout=30)
    fresh, threads, complete, failed = [], 0, True, []
    try:
        for channel in c["channels"]:
            try:
                cursor = None
                for _ in range(pages):
                    body = _call(client, key, "conversations.history", sleep, channel=channel, oldest=oldest, limit=200,
                                 **({"cursor": cursor} if cursor else {}))
                    for m in _people(body.get("messages") or []):
                        if m.get("thread_ts") not in (None, m["ts"]):
                            continue  # a reply shown in the channel
                        rid = f"{NAME}:{channel}:{m['ts']}"
                        stored = known.get(rid)
                        if stored and (stored["first_team_reply"] or not m.get("reply_count")):
                            continue
                        replies = []
                        if m.get("reply_count"):
                            if threads >= THREADS:
                                complete = False
                                continue
                            threads += 1
                            got = _call(client, key, "conversations.replies", sleep, channel=channel, ts=m["ts"])
                            replies = [r for r in _people(got.get("messages") or []) if r["ts"] != m["ts"] and r["user"] != m["user"]]
                        team_reply = next((r for r in replies if r["user"] in team), None)
                        fresh.append({"t": "topic", "src": NAME, "id": rid, "created": _iso(m["ts"]), "by_team": m["user"] in team,
                                      "first_reply": _iso(replies[0]["ts"]) if replies else None,
                                      "first_team_reply": _iso(team_reply["ts"]) if team_reply else None,
                                      "solved": None, "closed": False})
                    cursor = (body.get("response_metadata") or {}).get("next_cursor")
                    if not body.get("has_more") or not cursor:
                        break
                else:
                    complete = False
            except ConnectorError as exc:
                # One channel's trouble (the bot not in it, a limit) is said; the other channels go on.
                failed.append(f"{channel}: {exc}")
                complete = False
    finally:
        if own:
            client.close()
        store.add(fresh, now.date().isoformat())
    if len(failed) == len(c["channels"]) and failed:
        raise ConnectorError(failed[0])
    if complete:
        store.save_state({**store.state(), "backfilled": True})
    return {"read": len(fresh), "complete": complete, **({"note": "; ".join(failed[:2])} if failed else {})}
