"""Discord: support text channels read with a bot token the user installs (View Channel and Read Message History; message
content isn't needed): each message that isn't a reply, when anyone first replied to it and when the team did (the user
ids under `team`). The first pull reads 180 days, later ones the last 30; what was read is kept even when a later call
fails, and a channel the bot can't read (a forum channel, say) is said while the others go on. Only times and flags are
kept: no text and no user ids."""
import time
from datetime import datetime, timedelta

import httpx

from stackvitals.connectors.base import BACKFILL_DAYS, PAGES, ConnectorError, json_of, utc
from stackvitals.core import identity

NAME, TOKEN_ENV = "discord", "STACKVITALS_DISCORD_TOKEN"
API = "https://discord.com/api/v10"
RECENT_DAYS = 30
MAX_WAIT = 60

__all__ = ["ConnectorError", "configured", "pull"]


def configured(env: dict, cfg: dict) -> bool:
    return bool((env.get(TOKEN_ENV) or "").strip())


def _messages(client: httpx.Client, key: str, channel: str, before: str | None, sleep) -> list[dict]:
    for attempt in (1, 2):
        try:
            resp = client.get(f"{API}/channels/{channel}/messages", params={"limit": 100, **({"before": before} if before else {})},
                              headers={"Authorization": f"Bot {key}"})
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Discord could not be reached ({type(exc).__name__}); the next run tries again.") from None
        if resp.status_code == 429:
            wait = float(resp.headers.get("retry-after", MAX_WAIT))
            if attempt == 1 and wait <= MAX_WAIT:
                sleep(wait)
                continue
            raise ConnectorError("Discord's rate limit was reached; what was read is kept and the next run carries on.")
        if resp.status_code in (401, 403):
            raise ConnectorError(f"Discord refused the bot ({resp.status_code}): it needs View Channel and Read Message History "
                                 f"in channel {channel}.")
        if resp.status_code != 200:
            raise ConnectorError(f"Discord answered {resp.status_code} for channel {channel} (a forum channel isn't read).")
        return json_of(resp, "Discord", (list,))
    raise ConnectorError("Discord's rate limit was reached; the next run carries on.")


def _topics(msgs: list[dict], channel: str, team: set, since: str) -> list[dict]:
    replies = {}
    for m in sorted(msgs, key=lambda m: m["timestamp"]):
        ref = (m.get("message_reference") or {}).get("message_id")
        if ref:
            replies.setdefault(ref, []).append(m)
    out = []
    for m in msgs:
        created = utc(m.get("timestamp"))
        if (m.get("message_reference") or {}).get("message_id") or not created or created < since:
            continue
        author = (m.get("author") or {}).get("id")
        theirs = [r for r in replies.get(m["id"], []) if (r.get("author") or {}).get("id") != author]
        ours = next((r for r in theirs if (r.get("author") or {}).get("id") in team), None)
        out.append({"t": "topic", "src": NAME, "id": f"{NAME}:{channel}:{m['id']}", "created": created,
                    "by_team": author in team, "first_reply": utc(theirs[0]["timestamp"]) if theirs else None,
                    "first_team_reply": utc(ours["timestamp"]) if ours else None, "solved": None, "closed": False})
    return out


def pull(store, env: dict, cfg: dict, now: datetime, client: httpx.Client | None = None, pages: int = PAGES,
         sleep=time.sleep) -> dict:
    c = cfg["connectors"][NAME]
    # Team members are the ids listed here, plus those [identity] aliases map to a team member.
    key, team = env.get(TOKEN_ENV, "").strip(), set(c["team"]) | identity.tool_ids(cfg.get("identity"), NAME)
    days = RECENT_DAYS if store.state().get("backfilled") else BACKFILL_DAYS
    since = utc((now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    own = client is None
    client = client or httpx.Client(timeout=30)
    fresh, complete, failed = [], True, []
    try:
        for channel in c["channels"]:
            msgs, before = [], None
            try:
                for _ in range(pages):
                    batch = _messages(client, key, channel, before, sleep)
                    msgs += [m for m in batch if not (m.get("author") or {}).get("bot")]
                    if not batch or (utc(batch[-1].get("timestamp")) or "") < since:
                        break
                    before = batch[-1]["id"]
                else:
                    complete = False
            except ConnectorError as exc:
                failed.append(f"{channel}: {exc}")
                complete = False
            # What a channel gave before it failed still counts.
            fresh += _topics(msgs, channel, team, since)
    finally:
        if own:
            client.close()
        store.add(fresh, now.date().isoformat())
    if len(failed) == len(c["channels"]) and failed:
        raise ConnectorError(failed[0])
    if complete:
        store.save_state({**store.state(), "backfilled": True})
    return {"read": len(fresh), "complete": complete, **({"note": "; ".join(failed[:2])} if failed else {})}
