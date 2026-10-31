"""Merge-queue health, which GitHub itself doesn't report: how long pull requests wait in the queue before they merge,
why they get taken out, and how many removals followed a merge-group run that failed only on jobs known to be flaky."""
import re
from collections import Counter
from datetime import datetime, timedelta

from stackvitals.core.stats import percentile
from stackvitals.core.time import iso, parse

QUEUE_BRANCH = re.compile(r"^gh-readonly-queue/.+/pr-(\d+)-")
# A pull request also leaves the queue when it merges; those removals are not trouble. GraphQL spells reasons in lowercase
# (merged, merge_conflict, failed_checks), webhooks in uppercase, so case is ignored.
MERGED = {"MERGE", "MERGED", "ALREADY_MERGED"}
CLOSE_TO_MERGE = timedelta(minutes=5)
FLAKY = {"flaky", "suspect"}
FAILED = ("failure", "timed_out")
LOOK_BACK = timedelta(hours=3)  # a removal is tied to the queue's failed runs for that PR shortly before it
MIN_N = 10  # fewer merges and the waits are left out (the count stays)


def _hours(a: str, b: str) -> float:
    return round((parse(b) - parse(a)).total_seconds() / 3600, 2)


def health(prs: list[dict], ci: dict, job_states: dict, now: datetime, window_days: int, min_n: int = MIN_N) -> dict | None:
    """{prs, merged, p50_h, p90_h, removals: {reason: n}, removed_by_flakes: [...], runs, failed_runs} over the window,
    or None when nothing used a merge queue."""
    since = iso(now - timedelta(days=window_days))
    queued = [p for p in prs if any(e[1] >= since for e in p.get("mq") or [])]
    if not queued:
        return None
    # A run's final attempt is its answer: a re-run is the same run, not another one.
    final = {}
    for r in ci.get("runs") or []:
        if r.get("ev") == "merge_group" and (r.get("cr") or "") >= since and r.get("att", 1) >= final.get(r["id"], {}).get("att", 0):
            final[r["id"]] = r
    runs = list(final.values())
    by_pr = {}
    for r in runs:
        found = QUEUE_BRANCH.match(r.get("br") or "")
        if found:
            by_pr.setdefault(int(found.group(1)), []).append(r)
    failed_jobs = {}
    for j in ci.get("jobs") or []:
        if j.get("c") in FAILED:
            failed_jobs.setdefault((j["run"], j.get("att", 1)), []).append(j.get("n"))
    waits, removals, flaky = [], Counter(), []
    for p in queued:
        events = sorted(p.get("mq") or [], key=lambda e: e[1])
        if p.get("mg"):
            entered = [e[1] for e in events if e[0] == "add" and e[1] <= p["mg"]]
            if entered:
                waits.append(_hours(entered[-1], p["mg"]))
        for e in events:
            if e[0] != "rm" or e[1] < since:
                continue
            reason = (e[2] if len(e) > 2 else None) or "UNKNOWN"
            if reason.upper() in MERGED or (p.get("mg") and abs(parse(e[1]) - parse(p["mg"])) <= CLOSE_TO_MERGE):
                continue
            removals[reason] += 1
            # Every failing run just before the removal (several workflows can fail together), and every job that failed.
            before = [r for r in by_pr.get(p["n"], []) if r.get("c") in FAILED and iso(parse(e[1]) - LOOK_BACK) <= r["cr"] <= e[1]]
            jobs = [(r.get("path"), name) for r in before for name in failed_jobs.get((r["id"], r.get("att", 1))) or []]
            if jobs and all(job_states.get(job) in FLAKY for job in jobs):
                flaky.append({"pr": p["n"], "at": e[1], "jobs": sorted({name for _path, name in jobs})})
    enough = len(waits) >= min_n
    return {"prs": len(queued), "merged": len(waits), "p50_h": percentile(waits, 0.5) if enough else None,
            "p90_h": percentile(waits, 0.9) if enough else None, "removals": dict(removals.most_common()),
            "removed_by_flakes": flaky, "runs": len(runs),
            "failed_runs": sum(1 for r in runs if r.get("c") in FAILED), "window_days": window_days}
