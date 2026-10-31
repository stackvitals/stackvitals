"""The bug backlog week by week (DevLake's weekly bug retro): bugs opened and closed each week, how many stay open, and
how old the open ones are. From GitHub issues with a bug label alone, plus Jira and Linear bugs when connected."""
from datetime import datetime, timedelta

from stackvitals.connectors.base import std_type

WEEKS = 12
OLDEST = 10


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _bugs(issues: list[dict], tracked: list[dict]) -> list[dict]:
    out = [{"src": "github", "id": i["n"], "created": i["cr"], "closed": i.get("cl")}
           for i in issues or [] if i.get("cr") and any(std_type(x) == "BUG" for x in i.get("lb") or [])]
    out += [{"src": i.get("src"), "id": i.get("key") or i.get("id"), "created": i["created"],
             "closed": i.get("resolved") if i.get("cat") == "DONE" else None, "url": i.get("url")}
            for i in tracked or [] if i.get("type") == "BUG" and i.get("created") and not i.get("canceled")]
    return out


def backlog(issues: list[dict], tracked: list[dict], now: datetime, weeks: int = WEEKS) -> dict | None:
    """{"weeks": [{"week", "opened", "closed", "open"}], "open", "median_open_days", "oldest", "sources"}, or None."""
    bugs = _bugs(issues, tracked)
    if not bugs:
        return None
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for k in range(weeks - 1, -1, -1):
        start, end = monday - timedelta(weeks=k), monday - timedelta(weeks=k - 1)
        rows.append({"week": start.strftime("%Y-%m-%d"),
                     "opened": sum(start <= _t(b["created"]) < end for b in bugs),
                     "closed": sum(bool(b["closed"]) and start <= _t(b["closed"]) < end for b in bugs),
                     "open": sum(_t(b["created"]) < min(end, now) and (not b["closed"] or _t(b["closed"]) >= min(end, now))
                                 for b in bugs)})
    still = sorted((b for b in bugs if not b["closed"]), key=lambda b: b["created"])
    ages = sorted((now - _t(b["created"])).days for b in still)
    return {"weeks": rows, "open": len(still), "median_open_days": ages[len(ages) // 2] if ages else None,
            "oldest": [{"src": b["src"], "id": b["id"], "days": (now - _t(b["created"])).days, **({"url": b["url"]} if b.get("url") else {})}
                       for b in still[:OLDEST]],
            "sources": sorted({b["src"] for b in bugs})}
