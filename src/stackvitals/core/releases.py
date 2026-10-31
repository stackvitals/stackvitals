"""Quality per release (DevLake's release quality dashboard, plus what followed): for each recent release, the pull
requests it shipped and how many were fixes, then what came after it: reverts of its own pull requests, and incidents
in the two weeks after it went out."""
from datetime import datetime, timedelta

from stackvitals.core import investment
from stackvitals.core.ai_outcomes import is_revert, revert_target

LAST = 6
AFTER_DAYS = 14


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def quality(prs: list[dict], releases: list[dict], incidents: list[dict], now: datetime, last: int = LAST) -> list[dict] | None:
    """Newest first: {"tag", "at", "prs", "fixes", "fix_share", "reverted", "incidents_after", "settled"}. A release's PRs
    are the ones merged after the release before it and up to it; "settled" once two weeks have passed."""
    rel = sorted((r for r in releases or [] if r.get("at") and not r.get("pre")), key=lambda r: r["at"])
    if len(rel) < 2:
        return None
    merged = [p for p in prs if p.get("mg")]
    by_number = {p["n"]: p for p in merged}
    reverted = {}
    for p in merged:
        if is_revert(p) and (target := revert_target(p, by_number)) is not None:
            reverted[target] = p["mg"]
    out = []
    for prev, cur in list(zip(rel, rel[1:]))[-last:]:
        mine = [p for p in merged if prev["at"] < p["mg"] <= cur["at"] and not is_revert(p)]
        fixes = sum(investment.classify(p)[0] == "fix" for p in mine)
        end = (_t(cur["at"]) + timedelta(days=AFTER_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append({"tag": cur.get("tag"), "at": cur["at"], "prs": len(mine), "fixes": fixes,
                    "fix_share": round(fixes / len(mine), 4) if mine else None,
                    "reverted": sorted(p["n"] for p in mine if p["n"] in reverted),
                    "incidents_after": sum(cur["at"] < (i.get("created") or "") <= end for i in incidents or []),
                    "settled": _t(cur["at"]) + timedelta(days=AFTER_DAYS) <= now})
    return list(reversed(out))
