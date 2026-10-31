"""Working agreements (Swarmia's team rules), set under [agreements] and off until a team sets one: the pull requests of
the last 14 days that broke one (open ones still waiting count too), counts per rule, and 13 weekly windows for the app's
"how often would this have been broken" preview. Measured with Delivery's phases, so the numbers match its page."""
from datetime import datetime, timedelta

from stackvitals.core.time import iso

WINDOW_DAYS = 14
WEEKS = 13
LABELS = {"review_within_hours": "First review within {} h", "merge_within_days": "Merged within {} days",
          "max_pr_lines": "PRs under {} lines", "linked_issue": "PRs link an issue", "review_before_merge": "Reviewed before merge"}


def _hours(a: str, b: datetime) -> float:
    return (b - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds() / 3600


def _merged_break(rule: str, limit, p: dict, ph: dict):
    """(broken, the value that broke it) for one merged pull request."""
    if rule == "review_within_hours":
        return (ph.get("pickup") or 0) > limit, round(ph.get("pickup") or 0, 1)
    if rule == "merge_within_days":
        days = (ph.get("cycle_to_merge") or 0) / 24
        return days > limit, round(days, 1)
    if rule == "max_pr_lines":
        lines = (p.get("add") or 0) + (p.get("del") or 0)
        return lines > limit, lines
    if rule == "linked_issue":
        return not p.get("iss"), False
    if rule == "review_before_merge":
        return not ph.get("reviewed"), False
    return False, None


def _open_break(rule: str, limit, p: dict, now: datetime):
    """Open pull requests already past a time limit (the rest are judged when they merge)."""
    from stackvitals.flow.analyze import ready_at
    ready = ready_at(p) or p.get("cr")
    if not ready or p.get("draft"):
        return False, None
    waited = _hours(ready, now)
    if rule == "review_within_hours":
        # Delivery's pickup: a comment or review by another person; bots and the author's own words don't count.
        from stackvitals.core.delivery import phases
        return phases(p, None).get("first_activity") is None and waited > limit, round(waited, 1)
    if rule == "merge_within_days":
        return waited / 24 > limit, round(waited / 24, 1)
    return False, None


def check(rows: list[tuple], open_prs: list[dict], cfg: dict, now: datetime) -> dict | None:
    """rows: Delivery's merged people's pull requests with their phases; None when no agreement is set."""
    rules = {k: v for k, v in (cfg or {}).items() if k in LABELS and v}
    if not rules:
        return None
    since = iso(now - timedelta(days=WINDOW_DAYS))
    recent = [(p, ph) for p, ph, _dep in rows if (p.get("mg") or "") >= since]
    exceptions = []
    for p, ph in recent:
        for rule, limit in rules.items():
            broken, value = _merged_break(rule, limit, p, ph)
            if broken:
                exceptions.append({"pr": p["n"], "rule": rule, "value": value, "limit": limit, "open": False, "at": p["mg"]})
    for p in open_prs or []:
        if (p.get("at") or "User") != "User":
            continue
        for rule, limit in rules.items():
            broken, value = _open_break(rule, limit, p, now)
            if broken:
                exceptions.append({"pr": p["n"], "rule": rule, "value": value, "limit": limit, "open": True, "at": iso(now)})
    weekly = {rule: [] for rule in rules}
    for k in range(WEEKS - 1, -1, -1):
        hi, lo = iso(now - timedelta(days=7 * k)), iso(now - timedelta(days=7 * (k + 1)))
        week = [(p, ph) for p, ph, _dep in rows if lo < (p.get("mg") or "") <= hi]
        for rule, limit in rules.items():
            weekly[rule].append([hi[:10], sum(1 for p, ph in week if _merged_break(rule, limit, p, ph)[0]), len(week)])
    return {"rules": rules, "labels": {r: LABELS[r].format(v) for r, v in rules.items()}, "window_days": WINDOW_DAYS,
            "merged": len(recent), "counts": {r: sum(1 for e in exceptions if e["rule"] == r) for r in rules},
            "exceptions": sorted(exceptions, key=lambda e: (e["rule"], -e["pr"])), "weekly": weekly}


def nudges(agreed: dict | None, sent: list[str]) -> tuple[list[dict], list[str]]:
    """Open pull requests breaking an agreement that weren't announced yet, and the ones to remember (still open)."""
    if not agreed:
        return [], []
    now_open = [e for e in agreed.get("exceptions") or [] if e.get("open")]
    keys = [f"{e['pr']}|{e['rule']}" for e in now_open]
    fresh = [e for e, k in zip(now_open, keys) if k not in set(sent)]
    return fresh, keys


def nudge_lines(fresh: list[dict], labels: dict, repo: str) -> list[str]:
    unit = {"review_within_hours": "h", "merge_within_days": "days"}
    return [f"[#{e['pr']}](https://github.com/{repo}/pull/{e['pr']}): {e['value']} {unit.get(e['rule'], '')} so far, "
            f"against \"{labels.get(e['rule'], e['rule'])}\"" for e in fresh]
