"""What changed before an incident: the deployments in the 72 hours before it began and the pull requests merged in
that time (each with the deployment that shipped it), config and dependency changes called out, ranked so the likeliest
cause comes first: the incident's own (or the last) deployment, a pull request a revert undid, then closeness in time."""
import re
from datetime import datetime, timedelta

from stackvitals.core.ai_outcomes import is_revert, revert_target

WINDOW_HOURS = 72
MAX_CANDIDATES = 15
DEPENDENCY = re.compile(r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lockb?|poetry\.lock|uv\.lock|Pipfile\.lock|"
                        r"requirements[^/]*\.txt|go\.(mod|sum)|Cargo\.(lock|toml)|Gemfile(\.lock)?|composer\.(json|lock)|"
                        r"packages\.lock\.json|gradle\.lockfile|pom\.xml|package\.json|pyproject\.toml)$")
CONFIG = re.compile(r"(^|/)(\.github/workflows/|Dockerfile|docker-compose[^/]*\.ya?ml$|[^/]+\.tf$|helm/|k8s/|kubernetes/|"
                    r"deploy/|config/|\.env\.example$|[^/]+\.(toml|ini|cfg|conf)$)")


def _t(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _kind(paths: list[str]) -> str:
    if any(DEPENDENCY.search(p) for p in paths):
        return "dependency"
    if any(CONFIG.search(p) for p in paths):
        return "config"
    return "pr"


def timeline(incident: dict, rows: list, deps: list[dict], hours: int = WINDOW_HOURS) -> dict:
    """{"incident", "window_hours", "candidates": [{"kind", "ref", "at", "why", "deployment"}]}, likeliest first."""
    start = _t(incident["created"])
    since = start - timedelta(hours=hours)
    within = lambda when: bool(when) and since <= _t(when) < start  # noqa: E731
    shipped = [d for d in deps if within(d.get("finished"))]
    own = incident.get("deployment")
    last = max(shipped, key=lambda d: d["finished"])["id"] if shipped else None
    by_number = {p["n"]: p for p, _ph, _d in rows}
    reverted = {n for p, _ph, _d in rows if is_revert(p) and (n := revert_target(p, by_number)) is not None}
    near = lambda when: 1 - (start - _t(when)).total_seconds() / (hours * 3600)  # noqa: E731
    out = []
    for d in shipped:
        mine = d["id"] == own or (own is None and d["id"] == last)
        out.append({"kind": "deployment", "ref": f"deployment {(d.get('sha') or '')[:7] or d['id']}", "at": d["finished"],
                    "deployment": d["id"],
                    "why": "the deployment this incident is tied to" if d["id"] == own else
                           "the last deployment before it began" if d["id"] == last else "deployed in the window",
                    "rank": 100 if mine else 40 + 20 * near(d["finished"])})
    for p, _ph, d in rows:
        if not within(p.get("mg")) or is_revert(p):
            continue
        kind = _kind(p.get("paths") or [])
        why = []
        rank = 30 * near(p["mg"])
        if p["n"] in reverted:
            why.append("later reverted")
            rank += 60
        if d and d["id"] in (own, last):
            why.append("shipped in that deployment")
            rank += 40
        if kind != "pr":
            why.append(f"changes {'dependencies' if kind == 'dependency' else 'configuration'}")
            rank += 5
        out.append({"kind": kind, "ref": f"#{p['n']}", "at": p["mg"], "deployment": d["id"] if d else None,
                    "why": "; ".join(why) or "merged in the window", "rank": rank, "title": (p.get("ti") or "")[:120]})
    out.sort(key=lambda c: -c["rank"])
    return {"incident": {k: incident.get(k) for k in ("source", "number", "created", "resolved", "deployment")},
            "window_hours": hours, "candidates": [{k: v for k, v in c.items() if k != "rank"} for c in out[:MAX_CANDIDATES]]}


def recent(incidents: list[dict], rows: list, deps: list[dict], now: datetime, days: int = 90, most: int = 10) -> list[dict]:
    """A timeline for each incident that began in the last `days`, newest first."""
    floor = now - timedelta(days=days)
    fresh = sorted((i for i in incidents if i.get("created") and _t(i["created"]) >= floor), key=lambda i: i["created"],
                   reverse=True)
    return [timeline(i, rows, deps) for i in fresh[:most]]
