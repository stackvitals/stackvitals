"""Delivery benchmarks from the crawl: per repo the P75 of pickup, review and cycle to merge (the suite's nearest-rank
rule, so a repo's own Delivery page compares like with like), per group the spread with a bootstrap range on the median
and the share of repos inside LinearB's published bands, with the population and the gaps stated beside the numbers."""
import math
from datetime import datetime, timedelta

import duckdb

from mergescout.bench.ci import BOOTSTRAP_RESAMPLES as RESAMPLES
from mergescout.bench.ci import BOOTSTRAP_SEED as SEED
from mergescout.bench.ci import _pct, bootstrap_median, tier

MIN_PRS = 10  # PRs a repo needs in the window
MIN_VALUES = 5  # values a repo needs for one metric
MIN_GROUP = 50
METRICS = {"pickup_p75_hours": "pickup", "review_p75_hours": "review", "cycle_to_merge_p75_hours": "cycle"}
# LinearB's 2026 bands on P75 hours: elite below the first, good up to the second, fair up to the third.
LINEARB = {"pickup_p75_hours": (1, 4, 16), "review_p75_hours": (3, 14, 24)}
DEFINITION = ("per repo, PRs opened in the last 90 days by people (bots and AI agents left out), repos with 10+ such PRs: "
              "the P75 (nearest rank) of hours from opening to the first review by a maintainer other than the author "
              "(pickup), from that review to the merge (review), and from opening to the merge (cycle to merge); a repo "
              "needs 5+ values for a metric. Groups by language and stars need 50+ repos.")
POPULATION = ("public GitHub repos in the daily crawl that had 10+ pull requests by people in the last 90 days; GitHub "
              "only, any CI")
GAPS = ("no private or enterprise teams; no GitLab or Bitbucket; pickup counts from opening, not from leaving draft (the "
        "crawl does not keep draft history), so repos that open drafts look slower than LinearB's own pickup; cycle to "
        "merge has no coding or deploy time, so it is not LinearB's full cycle time")
BANDS_NOTE = ("LinearB's 2026 benchmark bands on P75 (pickup: elite under 1 h, good up to 4 h, fair up to 16 h; review: "
              "elite under 3 h, good up to 14 h, fair up to 24 h); each share is the part of the group's repos inside that "
              "band or a better one")


def _p75(values: list[float]) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, max(0, math.ceil(0.75 * len(s)) - 1))]


def per_repo(con: duckdb.DuckDBPyConnection, now: datetime, window_days: int = 90) -> list[dict]:
    rows = con.execute("""
        WITH w AS (
            SELECT p.*, coalesce(p.first_human_review_at, p.first_review_at) AS review_at,
                   coalesce(p.first_human_review_by, p.first_review_by) AS review_by
            FROM pr_class p WHERE p.created_at >= $since AND p.author_class IN ('insider', 'outsider'))
        SELECT w.repo_id, any_value(rm.language), any_value(rm.stars), count(*),
            list(epoch(w.review_at - w.created_at) / 3600) FILTER (
                WHERE w.review_at IS NOT NULL AND w.review_by IS DISTINCT FROM w.author_login AND rv.kind = 'insider'),
            list(epoch(w.merged_at - w.review_at) / 3600) FILTER (
                WHERE w.merged_at IS NOT NULL AND w.review_at IS NOT NULL AND w.review_at <= w.merged_at
                  AND w.review_by IS DISTINCT FROM w.author_login AND rv.kind = 'insider'),
            list(epoch(w.merged_at - w.created_at) / 3600) FILTER (WHERE w.merged_at IS NOT NULL)
        FROM w LEFT JOIN people rv ON rv.repo_id = w.repo_id AND rv.login = w.review_by
        LEFT JOIN repo_meta rm ON rm.repo_id = w.repo_id
        GROUP BY w.repo_id HAVING count(*) >= $min_prs""",
        {"since": now - timedelta(days=window_days), "min_prs": MIN_PRS}).fetchall()
    out = []
    for repo_id, language, stars, prs, pickup, review, cycle in rows:
        rec = {"repo_id": repo_id, "language": language, "stars": stars, "prs": prs}
        for metric, values in zip(METRICS, (pickup, review, cycle)):
            values = [v for v in values or [] if v is not None and v >= 0]
            rec[metric] = round(_p75(values), 4) if len(values) >= MIN_VALUES else None
        out.append(rec)
    return out


def _entry(metric: str, values: list[float]) -> dict:
    low, high = bootstrap_median(values)
    entry = {"repos": len(values), **{f"p{int(q * 100)}": _pct(values, q) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
             "p50_low": low, "p50_high": high}
    if metric in LINEARB:
        elite, good, fair = LINEARB[metric]
        n = len(values)
        entry["linearb"] = {"elite": round(sum(v < elite for v in values) / n, 4), "good": round(sum(v <= good for v in values) / n, 4),
                            "fair": round(sum(v <= fair for v in values) / n, 4)}
    return entry


def delivery_benchmarks(con: duckdb.DuckDBPyConnection, now: datetime, window_days: int = 90, top_languages: int = 25) -> dict:
    """Delivery percentiles of public repos by language and size; groups need 50+ repos with the metric."""
    repos = per_repo(con, now, window_days)
    counts = {}
    for r in repos:
        counts[r["language"] or "Other"] = counts.get(r["language"] or "Other", 0) + 1
    langs = {name for name, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:top_languages]}
    groups = {}
    for r in repos:
        lang = r["language"] if r["language"] in langs else "Other"
        for key in (f"{lang}|{tier(r['stars'])}", f"{lang}|all", f"all|{tier(r['stars'])}", "all|all"):
            groups.setdefault(key, []).append(r)
    out = {}
    for key, items in groups.items():
        if len(items) < MIN_GROUP:
            continue
        entry = {"repos": len(items)}
        for metric in METRICS:
            values = [r[metric] for r in items if r[metric] is not None]
            if len(values) >= MIN_GROUP:
                entry[metric] = _entry(metric, values)
        out[key] = entry
    return {"version": 1, "built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "window_days": window_days, "repos": len(repos),
            "definition": DEFINITION, "population": POPULATION, "gaps": GAPS, "bands_note": BANDS_NOTE,
            "method": {"percentile": "nearest rank", "bootstrap_resamples": RESAMPLES, "bootstrap_seed": SEED,
                       "range": "95% of the resampled medians"},
            "groups": out}
