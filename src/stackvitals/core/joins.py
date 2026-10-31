"""Join keys between modules: CI runs to the pull requests they tested, and how far back the CI history has no gaps."""
from collections import defaultdict
from datetime import date

# pull_request_target runs test the base branch's code, not the PR's, so they say nothing about the PR's commits.
PR_EVENTS = {"pull_request"}


def runs_by_pr(runs: list[dict], prs: list[dict]) -> dict[int, list[dict]]:
    """CI runs of pull_request events keyed by PR number: the number GitHub gives (same-repo PRs), else the PR with the
    same head owner and branch that was open when the run was created (forks; a reused branch maps to the right PR)."""
    numbers = {p["n"] for p in prs}
    by_head = defaultdict(list)
    for p in prs:
        if p.get("ho") and p.get("head"):
            by_head[(p["ho"].lower(), p["head"])].append(p)
    out = defaultdict(list)
    for r in runs:
        if r.get("ev") not in PR_EVENTS:
            continue
        hits = [n for n in r.get("pr") or [] if n in numbers]
        if not hits and r.get("ho") and r.get("br"):
            cr = r.get("cr") or ""
            open_then = [p for p in by_head.get((r["ho"].lower(), r["br"]), []) if p["cr"] <= cr <= (p.get("cl") or "9999")]
            if open_then:
                hits = [max(open_then, key=lambda p: p["cr"])["n"]]
        if hits:
            out[hits[0]].append(r)
    return dict(out)


def coverage_start(state: dict, runs: list[dict]) -> str | None:
    """Where the CI history is unbroken: the oldest day of the run of consecutive scanned days that ends at the newest one;
    without that record, the oldest run kept."""
    days = sorted((state or {}).get("scanned") or {}, reverse=True)
    if days:
        start = days[0]
        for day in days[1:]:
            if (date.fromisoformat(start) - date.fromisoformat(day)).days != 1:
                break
            start = day
        return f"{start}T00:00:00Z"
    return min((r["cr"] for r in runs if r.get("cr")), default=None)
