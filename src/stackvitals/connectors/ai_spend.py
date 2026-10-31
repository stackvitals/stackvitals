"""AI spend: what the organisation paid Anthropic and OpenAI each day (their cost reports) and Cursor this billing cycle
(plus its daily agent requests and accepted lines), each read with one optional admin key, so Delivery can set the
money beside the AI-involved pull requests merged in the same weeks."""
import base64
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import httpx

from stackvitals.connectors.base import ConnectorError, request
from stackvitals.core.time import iso, parse

NAME = "ai_spend"
KEYS = {"anthropic": "STACKVITALS_ANTHROPIC_ADMIN_KEY", "openai": "STACKVITALS_OPENAI_ADMIN_KEY",
        "cursor": "STACKVITALS_CURSOR_ADMIN_KEY"}
TOKEN_ENV = KEYS["anthropic"]  # the first one; check.py names all three
WINDOW = 90       # days read back on the first pull
REREAD = 2        # cost reports fill in late: the last two days are read again
CURSOR_DAYS = 30  # Cursor's daily usage takes at most 30 days per call
ANTHROPIC = "https://api.anthropic.com/v1/organizations/cost_report"
CLAUDE_CODE = "https://api.anthropic.com/v1/organizations/usage_report/claude_code"
OPENAI = "https://api.openai.com/v1/organization/costs"
CURSOR = "https://api.cursor.com"
PAGES = 10

__all__ = ["ConnectorError", "configured", "pull", "summary"]


def configured(env: dict, cfg: dict) -> bool:
    return any((env.get(k) or "").strip() for k in KEYS.values())


def _usd(amount) -> float:
    """Money to the cent, rounded half up as an invoice is (decimal, so $124.455 is $124.46, never $124.45)."""
    return float(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _day(ts) -> str:
    return datetime.fromtimestamp(ts / (1000 if ts > 10**11 else 1), timezone.utc).date().isoformat()


def _anthropic(client, key: str, start: datetime, now: datetime) -> list[dict]:
    out, page = [], None
    for _ in range(PAGES):
        body = request(client, "GET", ANTHROPIC, "Anthropic", refused="check the ANTHROPIC_ADMIN_KEY secret (an Admin API key)",
                       params={"starting_at": iso(start), "ending_at": iso(now), "bucket_width": "1d", "limit": 31,
                               **({"page": page} if page else {})},
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01", "user-agent": "stackvitals"})
        for b in body.get("data") or []:
            # Amounts are cents as decimal strings ("123.45" is $1.23).
            cents = sum((Decimal(str(r.get("amount") or 0)) for r in b.get("results") or []), Decimal(0))
            out.append({"t": "day", "id": f"anthropic:{b['starting_at'][:10]}", "src": "anthropic",
                        "day": b["starting_at"][:10], "usd": _usd(cents / 100)})
        page = body.get("next_page")
        if not body.get("has_more") or not page:
            break
    return out


def _openai(client, key: str, start: datetime, now: datetime) -> list[dict]:
    out, page = [], None
    for _ in range(PAGES):
        body = request(client, "GET", OPENAI, "OpenAI", refused="check the OPENAI_ADMIN_KEY secret (an admin key)",
                       params={"start_time": int(start.timestamp()), "end_time": int(now.timestamp()), "bucket_width": "1d",
                               "limit": 31, **({"page": page} if page else {})},
                       headers={"Authorization": f"Bearer {key}"})
        for b in body.get("data") or []:
            usd = sum((Decimal(str((r.get("amount") or {}).get("value") or 0)) for r in b.get("results") or []), Decimal(0))
            day = _day(b["start_time"])
            out.append({"t": "day", "id": f"openai:{day}", "src": "openai", "day": day, "usd": _usd(usd)})
        page = body.get("next_page")
        if not body.get("has_more") or not page:
            break
    return out


def _claude_code(client, key: str, start: datetime, now: datetime) -> list[dict]:
    """Claude Code's daily analytics for the organisation (one call per day): sessions, lines, commits, PRs and tool
    proposals accepted; its estimated cost is already in Anthropic's cost report, so it is kept apart, never added."""
    out, day = [], start.date()
    while day < now.date():
        totals = {"sessions": 0, "lines_added": 0, "lines_removed": 0, "commits": 0, "prs": 0, "accepted": 0, "rejected": 0,
                  "users": 0, "est_cents": Decimal(0)}
        page = None
        for _ in range(PAGES):
            body = request(client, "GET", CLAUDE_CODE, "Anthropic", refused="check the ANTHROPIC_ADMIN_KEY secret (an Admin API key)",
                           params={"starting_at": day.isoformat(), "limit": 1000, **({"page": page} if page else {})},
                           headers={"x-api-key": key, "anthropic-version": "2023-06-01", "user-agent": "stackvitals"})
            for r in body.get("data") or []:
                core = r.get("core_metrics") or {}
                totals["users"] += 1
                totals["sessions"] += core.get("num_sessions") or 0
                totals["lines_added"] += (core.get("lines_of_code") or {}).get("added") or 0
                totals["lines_removed"] += (core.get("lines_of_code") or {}).get("removed") or 0
                totals["commits"] += core.get("commits_by_claude_code") or 0
                totals["prs"] += core.get("pull_requests_by_claude_code") or 0
                for tool in (r.get("tool_actions") or {}).values():
                    totals["accepted"] += (tool or {}).get("accepted") or 0
                    totals["rejected"] += (tool or {}).get("rejected") or 0
                totals["est_cents"] += sum((Decimal(str((m.get("estimated_cost") or {}).get("amount") or 0))
                                            for m in r.get("model_breakdown") or []), Decimal(0))
            page = body.get("next_page")
            if not body.get("has_more") or not page:
                break
        if totals["users"]:
            cents = totals.pop("est_cents")
            out.append({"t": "day", "id": f"claude_code:{day.isoformat()}", "src": "claude_code", "day": day.isoformat(),
                        **totals, "est_usd": _usd(cents / 100)})
        day += timedelta(days=1)
    return out


def _cursor(client, key: str, now: datetime) -> list[dict]:
    auth = {"Authorization": "Basic " + base64.b64encode(f"{key}:".encode()).decode()}
    refused = "check the CURSOR_ADMIN_KEY secret (a Cursor admin API key)"
    spend = request(client, "POST", f"{CURSOR}/teams/spend", "Cursor", refused=refused, json={}, headers=auth)
    members = spend.get("teamMemberSpend") or []
    start = _day(spend["subscriptionCycleStart"]) if spend.get("subscriptionCycleStart") else None
    out = [{"t": "cycle", "id": f"cursor:{start}", "src": "cursor", "start": start, "members": len(members),
            # All of the cycle's usage, included and on-demand, in dollars.
            "usd": _usd(Decimal(sum(m.get("overallSpendCents") or m.get("spendCents") or 0 for m in members)) / 100)}] if start else []
    end = int(now.timestamp() * 1000)
    use = request(client, "POST", f"{CURSOR}/teams/daily-usage-data", "Cursor", refused=refused, headers=auth,
                  json={"startDate": end - CURSOR_DAYS * 86_400_000, "endDate": end})
    days = {}
    for r in use.get("data") or []:
        d = days.setdefault(_day(r["date"]), {"agent_requests": 0, "accepted_lines": 0})
        d["agent_requests"] += r.get("agentRequests") or 0
        d["accepted_lines"] += r.get("acceptedLinesAdded") or 0
    out += [{"t": "day", "id": f"cursor:{day}", "src": "cursor", "day": day, **v} for day, v in sorted(days.items())]
    return out


def pull(store, env: dict, cfg: dict, now: datetime, client: httpx.Client | None = None) -> dict:
    state = store.state()
    floor = now - timedelta(days=WINDOW)
    start = max(parse(state["since"]) - timedelta(days=REREAD), floor) if state.get("since") else floor
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    own = client is None
    client = client or httpx.Client(timeout=30)
    read, day = 0, now.date().isoformat()
    try:
        for name, fetch in (("anthropic", lambda k: _anthropic(client, k, start, now) + _claude_code(client, k, start, now)),
                            ("openai", lambda k: _openai(client, k, start, now)),
                            ("cursor", lambda k: _cursor(client, k, now))):
            key = (env.get(KEYS[name]) or "").strip()
            if key:
                rows = fetch(key)
                store.add(rows, day)
                read += len(rows)
        store.save_state({"since": iso(now)})
        return {"read": read, "complete": True}
    finally:
        if own:
            client.close()


def summary(root, now: datetime, ai_prs: int, window_days: int = 30) -> dict | None:
    """Spend per provider over the last `window_days` (Cursor: its current billing cycle), the total, and the total over
    the AI-involved pull requests merged in the same days; None before the first pull."""
    from stackvitals.connectors.store import ConnectorStore
    got = ConnectorStore(root, NAME).load()
    if not got.get("day") and not got.get("cycle"):
        return None
    since = (now - timedelta(days=window_days)).date().isoformat()
    providers = {}
    for r in got.get("day") or []:
        if r.get("usd") is not None and r["day"] >= since:
            providers[r["src"]] = _usd(Decimal(str(providers.get(r["src"], 0))) + Decimal(str(r["usd"])))
    cycles = sorted((r for r in got.get("cycle") or [] if r.get("start")), key=lambda r: r["start"])
    if cycles and cycles[-1]["start"] >= since:
        providers[cycles[-1]["src"]] = cycles[-1]["usd"]
    total = _usd(sum((Decimal(str(v)) for v in providers.values()), Decimal(0)))
    use = [r for r in got.get("day") or [] if r["src"] == "cursor" and r["day"] >= since]
    cc = [r for r in got.get("day") or [] if r["src"] == "claude_code" and r["day"] >= since]
    # The coding tools side by side over the same days: what each was used for, next to the money.
    tools = {}
    if cc:
        acted = sum(r.get("accepted", 0) + r.get("rejected", 0) for r in cc)
        tools["claude_code"] = {"sessions": sum(r.get("sessions", 0) for r in cc), "lines_added": sum(r.get("lines_added", 0) for r in cc),
                                "commits": sum(r.get("commits", 0) for r in cc), "prs": sum(r.get("prs", 0) for r in cc),
                                "acceptance": round(sum(r.get("accepted", 0) for r in cc) / acted, 4) if acted else None,
                                "est_usd": _usd(sum((Decimal(str(r.get("est_usd") or 0)) for r in cc), Decimal(0)))}
    if use:
        tools["cursor"] = {"agent_requests": sum(r.get("agent_requests") or 0 for r in use),
                           "lines_added": sum(r.get("accepted_lines") or 0 for r in use)}
    return {"window_days": window_days, "providers": providers, "total_usd": total, "ai_prs": ai_prs,
            "per_ai_pr_usd": _usd(Decimal(str(total)) / ai_prs) if ai_prs else None,
            "cursor_agent_requests": sum(r.get("agent_requests") or 0 for r in use) if use else None,
            **({"tools": tools} if tools else {})}
