from datetime import datetime, timedelta

import duckdb

from mergescout.bench.ci import _pct, quantiles, tier
from mergescout.bench.matched import mh_risk_difference

MIN_PRS = 10
MIN_GROUP = 50
METRICS = ("first_review_hours", "merge_hours", "outsider_merge_rate", "size_lines")
DEFINITION = ("per repo, PRs opened in the last 90 days by people (bots and AI agents left out): median hours from opening "
              "to the first review by a maintainer other than the author; median hours from opening to merge; outside "
              "contributors' merged share of their decided PRs; median lines added plus removed. Repos with 10+ PRs.")


def flow_benchmarks(con: duckdb.DuckDBPyConnection, now: datetime, window_days: int = 90, top_languages: int = 25) -> dict:
    """Review-flow percentiles of public repos by language and size, from the crawl; groups need 50+ repos."""
    rows = con.execute("""
        WITH w AS (
            SELECT p.*, coalesce(p.first_human_review_at, p.first_review_at) AS review_at,
                   coalesce(p.first_human_review_by, p.first_review_by) AS review_by
            FROM pr_class p WHERE p.created_at >= $since AND p.author_class IN ('insider', 'outsider'))
        SELECT w.repo_id, any_value(rm.language) AS language, any_value(rm.stars) AS stars, count(*) AS prs,
            median(epoch(w.review_at - w.created_at) / 3600) FILTER (
                WHERE w.review_at IS NOT NULL AND w.review_by IS DISTINCT FROM w.author_login AND rv.kind = 'insider')
                AS first_review_hours,
            median(epoch(w.merged_at - w.created_at) / 3600) FILTER (WHERE w.merged_at IS NOT NULL) AS merge_hours,
            (count(*) FILTER (WHERE w.author_class = 'outsider' AND w.state = 'MERGED'))::DOUBLE
                / nullif(count(*) FILTER (WHERE w.author_class = 'outsider' AND w.state IN ('MERGED', 'CLOSED')), 0)
                AS outsider_merge_rate,
            median(coalesce(w.additions, 0) + coalesce(w.deletions, 0)) AS size_lines
        FROM w LEFT JOIN people rv ON rv.repo_id = w.repo_id AND rv.login = w.review_by
        LEFT JOIN repo_meta rm ON rm.repo_id = w.repo_id
        GROUP BY w.repo_id HAVING count(*) >= $min_prs""",
        {"since": now - timedelta(days=window_days), "min_prs": MIN_PRS}).fetchall()
    cols = ("repo_id", "language", "stars", "prs", *METRICS)
    repos = [dict(zip(cols, r)) for r in rows]
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
        for m in METRICS:
            values = [round(float(r[m]), 4) for r in items if r[m] is not None]
            if len(values) >= MIN_GROUP:
                entry[m] = {"repos": len(values), **quantiles(values)}
        out[key] = entry
    return {"version": 1, "built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "window_days": window_days,
            "repos": len(repos), "definition": DEFINITION, "population": 'public GitHub repos in the daily crawl with 10+ pull requests by people in the last 90 days', "gaps": 'no private or enterprise teams; GitHub only; review counted from opening, not from leaving draft', "groups": out}


def _median(values: list[float]) -> float | None:
    s, n = sorted(values), len(values)
    return None if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)


BUCKETS = (("5-15", 5, 15), ("15-50", 15, 50), ("50+", 50, None))


def odds_backtest(con: duckdb.DuckDBPyConnection, now: datetime, horizon_days: int = 30, settle_days: int = 60,
                  history_days: int = 365, k: int = 10, min_past: int = 5, min_future: int = 3) -> dict:
    """How well a repo's past outside-PR merge rate predicts its next outside PRs: the raw rate, the rate pulled toward
    the typical repo of its group by k PRs (what the suite shows), and that typical rate alone. The target is every
    outside PR opened in the next horizon_days, merged within the settle window or not; errors weighted by PRs and
    also given by how many past PRs a repo had."""
    cut = now - timedelta(days=horizon_days + settle_days)
    rows = con.execute("""
        SELECT p.repo_id, any_value(rm.language), any_value(rm.stars),
            count(*) FILTER (WHERE p.closed_at >= $lo AND p.closed_at < $cut AND p.state IN ('MERGED', 'CLOSED')),
            count(*) FILTER (WHERE p.closed_at >= $lo AND p.closed_at < $cut AND p.state = 'MERGED'),
            count(*) FILTER (WHERE p.created_at >= $cut AND p.created_at < $hi),
            count(*) FILTER (WHERE p.created_at >= $cut AND p.created_at < $hi AND p.merged_at IS NOT NULL AND p.merged_at < $settled)
        FROM pr_class p LEFT JOIN repo_meta rm USING (repo_id) WHERE p.author_class = 'outsider' GROUP BY p.repo_id""",
        {"lo": cut - timedelta(days=history_days), "cut": cut, "hi": cut + timedelta(days=horizon_days),
         "settled": cut + timedelta(days=horizon_days + settle_days)}).fetchall()
    repos = [(lang or "Other", tier(stars), pc, pm, fn, fm) for _, lang, stars, pc, pm, fn, fm in rows
             if pc >= min_past and fn >= min_future]
    out = {"version": 2, "repos": len(repos), "prs": sum(r[4] for r in repos), "k": k,
           "definition": f"outside PRs decided in the {history_days} days before a cut-off predict the share of outside PRs "
                         f"opened in the next {horizon_days} days that were merged within {horizon_days + settle_days} days "
                         f"of the cut-off; repos with {min_past}+ past and {min_future}+ next PRs; the typical rate is the "
                         f"median of its language and size group (50+ repos) or of all repos"}
    if not repos:
        return out
    by_group = {}
    for lang, size, pc, pm, _, _ in repos:
        for key in (f"{lang}|{size}", "all|all"):
            by_group.setdefault(key, []).append(pm / pc)
    typical = {key: _median(v) for key, v in by_group.items() if len(v) >= 50 or key == "all|all"}
    err, bins, buckets = {"raw": 0.0, "shrunk": 0.0, "typical_only": 0.0}, {}, {}
    for lang, size, pc, pm, fn, fm in repos:
        typ = typical.get(f"{lang}|{size}", typical["all|all"])
        observed, shrunk = fm / fn, (pm + k * typ) / (pc + k)
        name = next(label for label, lo, hi in BUCKETS if pc >= lo and (hi is None or pc < hi))
        b = buckets.setdefault(name, {"repos": 0, "prs": 0, "err": {"raw": 0.0, "shrunk": 0.0, "typical_only": 0.0}})
        b["repos"] += 1
        b["prs"] += fn
        for key, pred in (("raw", pm / pc), ("shrunk", shrunk), ("typical_only", typ)):
            err[key] += abs(pred - observed) * fn
            b["err"][key] += abs(pred - observed) * fn
        cal = bins.setdefault(min(int(shrunk * 10), 9), [0, 0.0, 0])
        cal[0] += fn
        cal[1] += shrunk * fn
        cal[2] += fm
    total = out["prs"]

    def table(items):
        # The share of next PRs merged, by the repo's raw past rate in tenths.
        cells = {}
        for _, _, pc, pm, fn, fm in items:
            c = cells.setdefault(min(int(pm / pc * 10), 9), [0, 0.0, 0])
            c[0] += fn
            c[1] += pm / pc * fn
            c[2] += fm
        return cells
    # The correction is measured on repos it was not built from: fit on one half, check on the other, and swap.
    halves = (repos[0::2], repos[1::2])
    err["calibrated"] = 0.0
    for fit, check in ((halves[0], halves[1]), (halves[1], halves[0])):
        cells = table(fit)
        for _, _, pc, pm, fn, fm in check:
            c = cells.get(min(int(pm / pc * 10), 9))
            err["calibrated"] += abs((c[2] / c[0] if c else pm / pc) - fm / fn) * fn
    out["calibration_raw"] = [{"bin": f"{i / 10:.1f}-{(i + 1) / 10:.1f}", "prs": n, "predicted": round(s / n, 4),
                               "observed": round(m / n, 4)} for i, (n, s, m) in sorted(table(repos).items())]
    out.update(typical=round(typical["all|all"], 4), mae={name: round(e / total, 4) for name, e in err.items()},
               by_past_prs={label: ({"repos": buckets[label]["repos"], "prs": buckets[label]["prs"],
                                     "mae": {key: round(e / buckets[label]["prs"], 4) for key, e in buckets[label]["err"].items()}}
                                    if label in buckets else {"repos": 0, "prs": 0}) for label, _, _ in BUCKETS},
               calibration=[{"bin": f"{i / 10:.1f}-{(i + 1) / 10:.1f}", "prs": n, "predicted": round(s / n, 4),
                             "observed": round(m / n, 4)} for i, (n, s, m) in sorted(bins.items())])
    return out


MIN_AGENT_REPOS = 20


def agent_prs(con: duckdb.DuckDBPyConnection, now: datetime, window_days: int = 180, min_each: int = 5) -> dict:
    """PRs opened by coding agents next to people's outside PRs in the same repos (each with min_each+ decided PRs of
    both kinds): the median repo's merge share of each, per group of similar repos with 20+ such repos. Agents are known
    by their account, as the suite's app knows them (an AI-assisted PR by a person stays that person's), and a PR counts
    in the window it was decided in."""
    rows = con.execute("""
        SELECT p.repo_id, any_value(rm.language), any_value(rm.stars),
            count(*) FILTER (WHERE p.author_role = 'agent'), count(*) FILTER (WHERE p.author_role = 'agent' AND p.state = 'MERGED'),
            count(*) FILTER (WHERE p.author_role = 'outsider'),
            count(*) FILTER (WHERE p.author_role = 'outsider' AND p.state = 'MERGED')
        FROM pr_class p LEFT JOIN repo_meta rm USING (repo_id)
        WHERE coalesce(p.merged_at, p.closed_at) >= $since AND p.state IN ('MERGED', 'CLOSED')
            AND p.author_role IN ('agent', 'outsider')
        GROUP BY p.repo_id""", {"since": now - timedelta(days=window_days)}).fetchall()
    groups = {}
    for _, lang, stars, an, am, on, om in rows:
        if an < min_each or on < min_each:
            continue
        lang = lang or "Other"
        for key in (f"{lang}|{tier(stars)}", f"{lang}|all", f"all|{tier(stars)}", "all|all"):
            groups.setdefault(key, []).append((an, am / an, on, om / on))
    return {key: {"repos_with_agent_prs": len(g),
                  "agent": {"decided": sum(x[0] for x in g), "merged": round(_median([x[1] for x in g]), 4)},
                  "outsider": {"decided": sum(x[2] for x in g), "merged": round(_median([x[3] for x in g]), 4)}}
            for key, g in groups.items() if len(g) >= MIN_AGENT_REPOS}


MIN_LEADER_REPOS = 10  # an agent seen in fewer repos is left off the leaderboard
# Which agent, from its account's name or the branch prefix it pushes from a person's account.
AGENT_NAME = """CASE
    WHEN p.author_role = 'agent' THEN coalesce(
        nullif(regexp_extract(lower(p.author_login), '(copilot|devin|claude|codex|cursor|openhands|sweep|jules|codegen)', 1), ''),
        'other agent')
    ELSE lower(regexp_extract(coalesce(p.head_ref, ''), '^(copilot|codex|cursor|devin|claude)[/-]', 1)) END"""


def agent_leaderboard(con: duckdb.DuckDBPyConnection, now: datetime, window_days: int = 180) -> dict:
    """Each coding agent across the crawl's public repos: repos and decided PRs, the share merged, the share merged by
    someone other than its author, and its gap against people's PRs of the same repo, month and size (Mantel-Haenszel,
    95% range); agents seen in fewer than 10 repos are left out."""
    rows = con.execute(f"""
        SELECT p.repo_id, strftime(coalesce(p.merged_at, p.closed_at), '%Y-%m') AS month,
            CAST(floor(log2(coalesce(p.additions, 0) + coalesce(p.deletions, 0) + 1)) AS INTEGER) AS band,
            CASE WHEN p.author_role = 'agent' OR regexp_matches(coalesce(p.head_ref, ''), '^(copilot|codex|cursor|devin|claude)[/-]', 'i')
                 THEN {AGENT_NAME} END AS agent,
            count(*), count(*) FILTER (WHERE p.state = 'MERGED'),
            count(*) FILTER (WHERE p.state = 'MERGED' AND lower(coalesce(p.merged_by, '')) <> lower(coalesce(p.author_login, '')))
        FROM pr_class p
        WHERE coalesce(p.merged_at, p.closed_at) >= $since AND p.state IN ('MERGED', 'CLOSED')
            AND p.author_role IN ('agent', 'insider', 'outsider')
        GROUP BY p.repo_id, month, band, agent""", {"since": now - timedelta(days=window_days)}).fetchall()
    people, mine = {}, {}
    for repo, month, band, agent, n, merged, others in rows:
        if agent:
            mine.setdefault(agent, {})[(repo, month, band)] = (n, merged, others)
        else:
            people[(repo, month, band)] = (n, merged)
    agents = {}
    for name, cells in mine.items():
        repos = {k[0] for k in cells}
        if len(repos) < MIN_LEADER_REPOS:
            continue
        n, merged, others = (sum(c[i] for c in cells.values()) for i in range(3))
        pairs = [(c[1], c[0], people[k][1], people[k][0]) for k, c in cells.items() if k in people and people[k][0]]
        entry = {"repos": len(repos), "prs": n, "merged": round(merged / n, 4), "merged_by_others": round(others / n, 4)}
        if pairs:
            rd, se = mh_risk_difference(pairs)
            entry["vs_people"] = {"gap": round(rd, 4), "low": round(rd - 1.96 * se, 4), "high": round(rd + 1.96 * se, 4),
                                  "prs_compared": sum(p[1] for p in pairs)}
        agents[name] = entry
    return {"window_days": window_days, "agents": dict(sorted(agents.items(), key=lambda kv: -kv[1]["prs"]))}


def agent_matched(con: duckdb.DuckDBPyConnection, now: datetime, window_days: int = 180) -> dict:
    """Coding agents' PRs (their account, or an agent's branch such as codex/ opened from a person's account) against
    people's PRs of the same repo, month and size, per group of similar repos with 20+ such repos: the gap in merged and
    in merged by someone other than the author (Mantel-Haenszel risk difference, 95% range). Most agents' PRs are merged
    by whoever ran the agent, so the second gap is the one that says whether anyone else accepted them."""
    rows = con.execute("""
        SELECT p.repo_id, any_value(rm.language), any_value(rm.stars),
            strftime(coalesce(p.merged_at, p.closed_at), '%Y-%m') AS month,
            CAST(floor(log2(coalesce(p.additions, 0) + coalesce(p.deletions, 0) + 1)) AS INTEGER) AS band,
            (p.author_role = 'agent' OR regexp_matches(coalesce(p.head_ref, ''), '^(copilot|codex|cursor|devin|claude)[/-]', 'i')) AS agent,
            count(*), count(*) FILTER (WHERE p.state = 'MERGED'),
            count(*) FILTER (WHERE p.state = 'MERGED' AND lower(coalesce(p.merged_by, '')) <> lower(coalesce(p.author_login, '')))
        FROM pr_class p LEFT JOIN repo_meta rm USING (repo_id)
        WHERE coalesce(p.merged_at, p.closed_at) >= $since AND p.state IN ('MERGED', 'CLOSED')
            AND p.author_role IN ('agent', 'insider', 'outsider')
        GROUP BY p.repo_id, month, band, agent""", {"since": now - timedelta(days=window_days)}).fetchall()
    strata, meta = {}, {}
    for repo, lang, stars, month, band, agent, n, merged, others in rows:
        cell = strata.setdefault((repo, month, band), [0, 0, 0, 0, 0, 0])
        at = 0 if agent else 3
        cell[at], cell[at + 1], cell[at + 2] = n, merged, others
        meta[repo] = (lang or "Other", stars)
    groups = {}
    for (repo, _month, _band), c in strata.items():
        if c[0] and c[3]:
            lang, stars = meta[repo]
            for key in (f"{lang}|{tier(stars)}", f"{lang}|all", f"all|{tier(stars)}", "all|all"):
                groups.setdefault(key, []).append((repo, c))
    out = {}
    for key, cells in groups.items():
        repos = {repo for repo, _c in cells}
        if len(repos) < MIN_AGENT_REPOS:
            continue
        found = {"repos": len(repos), "agent_prs": sum(c[0] for _r, c in cells)}
        for name, hit in (("merged", 1), ("merged_by_others", 2)):
            rd, se = mh_risk_difference([(c[hit], c[0], c[3 + hit], c[3]) for _r, c in cells])
            found[name] = {"gap": round(rd, 4), "low": round(rd - 1.96 * se, 4), "high": round(rd + 1.96 * se, 4)}
        out[key] = found
    return out
