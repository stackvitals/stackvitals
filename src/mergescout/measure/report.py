def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * p)]


def summarize(results: list[dict], daily_points: int = 120_000,
              tier_sizes: tuple[int, ...] = (10_000, 25_000, 50_000, 100_000)) -> dict:
    ok = [r for r in results if r.get("status") == "ok"]
    full = [r["full"]["cost"] for r in ok]
    incr = [r["incremental"]["cost"] for r in ok]
    issues = [r["issues"]["cost"] for r in ok]
    # Totals use the mean, not the median, because a few huge repos eat most of the budget.
    fill_per_repo = _mean(full) + _mean(issues)
    refresh_per_repo = _mean(incr) + _mean(issues)
    tiers = [{"tier": n,
              "first_fill_days": n * fill_per_repo / daily_points,
              "refresh_cycle_days": n * refresh_per_repo / daily_points} for n in tier_sizes]
    buckets = {}
    for bucket in sorted({r.get("bucket") or "?" for r in ok}):
        rows = [r for r in ok if (r.get("bucket") or "?") == bucket]
        costs = [r["full"]["cost"] for r in rows]
        buckets[bucket] = {"repos": len(rows), "full_median": _percentile(costs, 0.5),
                           "full_p90": _percentile(costs, 0.9),
                           "issues_median": _percentile([r["issues"]["cost"] for r in rows], 0.5)}
    return {
        "daily_points": daily_points,
        "repos_measured": len(ok),
        "not_found": sum(1 for r in results if r.get("status") == "not_found"),
        "capped": sum(1 for r in ok if any(r[k]["capped"] for k in ("full", "incremental", "issues"))),
        "mean_full": _mean(full), "mean_incremental": _mean(incr), "mean_issues": _mean(issues),
        "tiers": tiers, "by_bucket": buckets,
    }


def render_markdown(s: dict) -> str:
    lines = [
        f"Repos measured: {s['repos_measured']} (not found: {s['not_found']}, hit page cap: {s['capped']})",
        f"Mean points per repo: full history {s['mean_full']:.1f}, incremental {s['mean_incremental']:.1f}, "
        f"open issues {s['mean_issues']:.1f}",
        f"Daily budget assumed: {s['daily_points']} points",
        "",
        "| Tier size | First fill (days) | Refresh cycle (days) |",
        "|---|---|---|",
    ]
    lines += [f"| {t['tier']} | {t['first_fill_days']:.1f} | {t['refresh_cycle_days']:.1f} |" for t in s["tiers"]]
    lines += ["", "| Star bucket | Repos | Full history median | Full history p90 | Issues median |",
              "|---|---|---|---|---|"]
    lines += [f"| {b} | {v['repos']} | {v['full_median']} | {v['full_p90']} | {v['issues_median']} |"
              for b, v in s["by_bucket"].items()]
    return "\n".join(lines)
