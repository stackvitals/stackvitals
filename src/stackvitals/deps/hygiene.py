"""Dependency-update hygiene from the pull requests Team Flow already keeps, the view Dependabot doesn't give: open update
PRs by age, security updates waiting more than 48 hours (the UK MoJ's rule) unless the team accepted the risk until a
date, how fast updates merge, and whether the bot went quiet (Dependabot pauses itself after 90 days without
interaction)."""
from datetime import datetime, timedelta
from statistics import median

from mergescout.signals.bumps import parse_bump
from stackvitals.core.time import iso

SECURITY_HOURS = 48


def _age(stamp: str, now: datetime) -> float:
    return (now - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds() / 3600


def hygiene(flow: dict, decisions: dict, now: datetime) -> dict | None:
    """None when no update bot has opened a pull request here."""
    def updates(rows):
        for p in rows or []:
            b = parse_bump(p.get("ti"), p.get("head"), p.get("au"))
            if b:
                yield p, b
    opened = list(updates(flow.get("open")))
    closed = list(updates(flow.get("closed")))
    if not opened and not closed:
        return None
    rows = []
    for p, b in opened:
        security = b["security"] or any("security" in (label or "").lower() for label in p.get("lb") or [])
        decided = decisions.get(f"package:{b['package']}") if b.get("package") else None
        row = {"pr": p["n"], "package": b["package"], "ecosystem": b["ecosystem"], "from": b["from_version"],
               "to": b["to_version"], "bump": b["bump"], "bot": b["bot"], "security": security,
               "age_hours": round(_age(p["cr"], now), 1)}
        if decided and decided.get("verb") == "accept":
            row["decision"] = {k: decided.get(k) for k in ("verb", "by", "until", "reason")}
        rows.append(row)
    rows.sort(key=lambda r: -r["age_hours"])
    since = iso(now - timedelta(days=90))
    merged = [_age(p["cr"], now) - _age(p["mg"], now) for p, _b in closed if p.get("mg") and p["mg"] >= since]
    last = max(p["cr"] for p, _b in opened + closed)
    return {"open": rows,
            "security_overdue": [r for r in rows if r["security"] and r["age_hours"] > SECURITY_HOURS and not r.get("decision")],
            "merged_90d": len(merged), "merge_median_hours": round(median(merged), 1) if merged else None,
            "bots": sorted({b["bot"] for _p, b in opened + closed}), "last_opened": last,
            "quiet_days": int(_age(last, now) // 24)}
