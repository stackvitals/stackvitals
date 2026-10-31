"""The agent work ledger: each coding agent's pull requests on their own against people's of the same month and size;
the review load agents add (what arrives against what merges, the queue waiting for a first review, reviewers' open
requests); and the review an open pull request can expect, from similar ones merged here."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from stackvitals.core.ai_outcomes import MIN_N, _band, assisted_by, mode, outcomes
from stackvitals.core.stats import median, percentile

SIMILAR_MIN = 5  # fewer similar merged PRs and an open one gets no expectation


def agent_of(p: dict) -> str | None:
    """The coding agent behind an agent's PR ("copilot agent", "devin agent", ...), else None."""
    if mode(p) != "agent":
        return None
    return next((t for t in assisted_by(p) if t.endswith(" agent")), "coding agent")


def _rounds(p: dict) -> int:
    return sum(1 for e in p.get("ev") or [] if e and e[0] == "review")


def by_agent(rows: list, ci: dict, incidents: list[dict], now: datetime, decided: list | None = None) -> dict:
    """{agent: {"prs", "merge_rate", "review_rounds_p50", "window", "matched"}}: each agent's merged PRs measured as the
    AI outcomes measure all agents together, compared with people's PRs of the same month and size."""
    names = sorted({a for r in rows if (a := agent_of(r[0]))} | {a for p in decided or [] if (a := agent_of(p))})
    out = {}
    for name in names:
        # Only this agent on the agent side; people's PRs stay the comparison.
        keep = [r for r in rows if mode(r[0]) != "agent" or agent_of(r[0]) == name]
        mine = [p for p in decided or [] if agent_of(p) == name]
        got = outcomes(keep, ci, incidents, now, decided=[p for p in decided or [] if mode(p) != "agent"] + mine
                       if decided is not None else None)
        merged = [r[0] for r in keep if agent_of(r[0]) == name]
        rounds = [_rounds(p) for p in merged]
        closed = mine  # `decided` holds merged and closed PRs only
        out[name] = {"prs": len(merged), "decided": len(closed),
                     "merge_rate": round(sum(1 for p in closed if p.get("mg")) / len(closed), 4)
                     if len(closed) >= MIN_N else None,
                     "review_rounds_p50": median(rounds) if len(rounds) >= MIN_N else None,
                     "window": got["window"]["agent"], "matched": got["matched"].get("agent")}
    return out


def _kind(p: dict) -> str:
    return "agent" if mode(p) == "agent" else "person"


def review_load(flow: dict, now: datetime, weeks: int = 8) -> dict:
    """Each of the last `weeks` weeks: PRs opened and merged, agents' and people's; the open PRs waiting for a first
    review now (drafts left out); and how the open review requests spread over reviewers."""
    prs = (flow.get("closed") or []) + (flow.get("open") or [])
    rows = []
    for k in range(weeks - 1, -1, -1):
        end = now - timedelta(days=7 * k)
        start, e = (end - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")
        opened, merged = Counter(), Counter()
        for p in prs:
            if start <= (p.get("cr") or "") < e:
                opened[_kind(p)] += 1
            if start <= (p.get("mg") or "") < e:
                merged[_kind(p)] += 1
        rows.append({"week_end": e[:10], "opened": {k: opened[k] for k in ("agent", "person")},
                     "merged": {k: merged[k] for k in ("agent", "person")}})
    live = [p for p in flow.get("open") or [] if not p.get("draft")]
    waiting = Counter(_kind(p) for p in live if not any(e and e[0] == "review" for e in p.get("ev") or []))
    load, from_agents = Counter(), 0
    for p in live:
        for who in p.get("rq") or []:
            load[who] += 1
            from_agents += _kind(p) == "agent"
    total = sum(load.values())
    # Counts only: who holds which request is on the Pull Requests page.
    return {"weeks": rows, "waiting": {k: waiting[k] for k in ("agent", "person")},
            "reviewers": {"n": len(load), "max_open": max(load.values(), default=0),
                          "agent_share": round(from_agents / total, 4) if total else None}}


def expected_review(open_prs: list[dict], history: list) -> list[dict]:
    """For each open PR: the review hours (P50, P75) of merged PRs here of the same kind and size band, or the bands
    next to it when its own has too few; None when nothing similar has merged yet."""
    pool = defaultdict(list)
    for p, ph, _d in history:
        if ph.get("review") is not None:
            pool[(_kind(p), _band(p))].append(ph["review"])
    out = []
    for p in open_prs:
        kind, band = _kind(p), _band(p)
        hours = pool[(kind, band)]
        if len(hours) < SIMILAR_MIN:
            hours = pool[(kind, band - 1)] + hours + pool[(kind, band + 1)]
        enough = len(hours) >= SIMILAR_MIN
        out.append({"pr": p.get("n"), "kind": kind, "similar": len(hours) if enough else 0,
                    "p50_h": round(median(hours), 2) if enough else None,
                    "p75_h": round(percentile(hours, 0.75), 2) if enough else None})
    return out


def leaderboard(data) -> dict | None:
    """The crawl's agent leaderboard as a page may show it: short lowercase agent names and numbers in range only
    (a damaged or tampered file shows nothing rather than something wrong)."""
    import re
    if not isinstance(data, dict) or not isinstance(data.get("agents"), dict):
        return None
    share = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 1  # noqa: E731
    count = lambda x: isinstance(x, int) and not isinstance(x, bool) and x >= 0  # noqa: E731
    gap = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and -1 <= x <= 1  # noqa: E731
    agents = {}
    for name, a in data["agents"].items():
        if not (isinstance(name, str) and re.fullmatch(r"[a-z][a-z ]{1,20}", name) and isinstance(a, dict)
                and count(a.get("repos")) and count(a.get("prs")) and share(a.get("merged")) and share(a.get("merged_by_others"))):
            continue
        entry = {k: a[k] for k in ("repos", "prs", "merged", "merged_by_others")}
        vs = a.get("vs_people")
        if isinstance(vs, dict) and all(gap(vs.get(k)) for k in ("gap", "low", "high")) and count(vs.get("prs_compared")):
            entry["vs_people"] = {k: vs[k] for k in ("gap", "low", "high", "prs_compared")}
        agents[name] = entry
    days = data.get("window_days")
    return {"window_days": days if count(days) else None, "agents": agents} if agents else None
