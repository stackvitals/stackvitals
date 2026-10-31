"""The org view: every repo that runs the suite, rolled up from the facts each publishes on its own data branch (counts
summed, rates and times as medians across repos, and the repos that lead each), so a platform team sees the org's
CI, review and delivery health on one page without reading any repo's raw history."""
from statistics import median

SUMS = ("ci_flaky", "ci_broken", "open_prs", "stale_prs", "deployments", "findings", "newcomers_waiting", "vulns_open",
        "vulns_serious")
MEDIANS = ("ci_first_try", "pickup_p75_h", "review_p75_h", "cycle_p75_h", "change_failure_rate", "community_score")
# Which way is worse for each number the leaders are ranked by.
WORSE_HIGH = {"ci_flaky", "ci_broken", "stale_prs", "findings", "newcomers_waiting", "pickup_p75_h", "review_p75_h",
              "cycle_p75_h", "change_failure_rate", "vulns_serious"}
LEADERS = 5


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def org_rollup(repos: list[dict]) -> dict:
    live = [r for r in repos if not r.get("archived") and not r.get("fork")]
    facts = {r["name"]: ((r.get("modules") or {}).get("facts") or {}) for r in live if (r.get("modules") or {}).get("facts")}
    out = {"repos": len(live), "running": len(facts), "totals": {}, "medians": {}, "counts": {}, "leaders": {}}
    for key in SUMS:
        vals = [f[key] for f in facts.values() if _num(f.get(key))]
        out["totals"][key] = sum(vals) if vals else None
    for key in MEDIANS:
        vals = [f[key] for f in facts.values() if _num(f.get(key))]
        out["medians"][key], out["counts"][key] = (round(median(vals), 4) if vals else None), len(vals)
    for key in WORSE_HIGH:
        ranked = sorted(((n, f[key]) for n, f in facts.items() if _num(f.get(key)) and f[key] > 0), key=lambda x: -x[1])
        out["leaders"][key] = [{"repo": n, "value": v} for n, v in ranked[:LEADERS]]
    return out
