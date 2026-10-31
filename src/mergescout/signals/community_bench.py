"""How public repos treat outside contributors, from the crawl: how fast a first answer comes, and whether newcomers come
back. Per-repo facts become percentiles by language and size; the newcomer table backs the "answer first-timers" lever."""
from datetime import datetime, timedelta

import duckdb

from mergescout.bench.ci import _pct, quantiles, tier

MIN_PRS = 10
MIN_NEWCOMERS = 10
MIN_GROUP = 50
# A repo's first 60 days of crawled history can't tell a newcomer from someone who came before it.
HISTORY_DAYS = 60
RETURN_DAYS = 90
METRICS = ("first_answer_hours", "answered_1d_share", "newcomer_answered_share", "newcomer_return_rate", "bus_factor", "top_share")
DEPENDENCY_DAYS, MIN_MERGED = 180, 20
BUCKETS = ("within 1 day", "1-3 days", "3-14 days", "over 14 days", "no answer")
DEFINITION = ("Outside contributors are people who are not owners, members, collaborators, bots or AI agents. A first "
              "answer is the first review by someone other than the author, a merge or a close. Per repo: median hours "
              "to the first answer and the share answered within a day, for outside PRs opened in the last 90 days "
              "(10+ PRs); for newcomers (an outside contributor's first PR in a repo with 60+ days of history before "
              "it), the share answered within 14 days and the share who opened another PR 1 to 90 days later (10+ newcomers). "
              "Accounts opening 20+ PRs in a repo on one day are left out as automated. Who carries the work: PRs by "
              "people (anyone but bots and AI agents) merged in the last 180 days (20+); the top person's share, and the "
              "bus factor, the fewest people behind half of them.")

ANSWER = """least(CASE WHEN p.first_human_review_by IS DISTINCT FROM p.author_login THEN p.first_human_review_at END,
                  p.merged_at, p.closed_at)"""
# One account opening 20+ PRs in a repo on one day is automated (bat: 73 in a day); it would swamp the repo's rates.
BURST = """burst AS (SELECT DISTINCT repo_id, author_login FROM pr_class WHERE author_class = 'outsider'
                     GROUP BY repo_id, author_login, CAST(created_at AS DATE) HAVING count(*) >= 20)"""
NEWCOMERS = f"""
    WITH span AS (SELECT repo_id, min(created_at) AS start FROM pr_class GROUP BY repo_id),
    {BURST},
    outside AS (SELECT p.*, {ANSWER} AS answered_at FROM pr_class p
                WHERE p.author_class = 'outsider' AND NOT EXISTS (
                    SELECT 1 FROM burst b WHERE b.repo_id = p.repo_id AND b.author_login = p.author_login)),
    ranked AS (SELECT o.*, row_number() OVER w AS k
               FROM outside o WINDOW w AS (PARTITION BY o.repo_id, o.author_login ORDER BY o.created_at, o.number)),
    firsts AS (SELECT r.* FROM ranked r JOIN span s USING (repo_id)
               WHERE r.k = 1 AND r.created_at >= s.start + INTERVAL {HISTORY_DAYS} DAY)
    -- Coming back is new work at least a day later: PRs split minutes apart are one contribution.
    SELECT f.*, (SELECT min(o.created_at) FROM outside o WHERE o.repo_id = f.repo_id AND o.author_login = f.author_login
                 AND o.created_at >= f.created_at + INTERVAL 1 DAY) AS next_at
    FROM firsts f"""


def newcomer_returns(con: duckdb.DuckDBPyConnection, now: datetime) -> dict:
    """Newcomers whose return can be judged (first PR 120+ days ago), by how long their first PR waited for an answer."""
    judged = f"WITH judged AS (SELECT * FROM ({NEWCOMERS}) WHERE created_at <= $cut)"
    cut = {"cut": now - timedelta(days=RETURN_DAYS + 30)}
    back = f"avg((next_at IS NOT NULL AND next_at <= created_at + INTERVAL {RETURN_DAYS} DAY)::INT)"
    by_answer = con.execute(f"""{judged}
        SELECT CASE WHEN answered_at IS NULL THEN 4 WHEN answered_at - created_at <= INTERVAL 1 DAY THEN 0
                    WHEN answered_at - created_at <= INTERVAL 3 DAY THEN 1 WHEN answered_at - created_at <= INTERVAL 14 DAY THEN 2
                    ELSE 3 END AS b, count(*), {back}, avg((merged_at IS NOT NULL)::INT)
        FROM judged GROUP BY 1 ORDER BY 1""", cut).fetchall()
    by_outcome = con.execute(f"""{judged}
        SELECT CASE WHEN merged_at IS NOT NULL THEN 'merged' WHEN state = 'CLOSED' THEN 'closed unmerged' ELSE 'still open' END,
               count(*), {back}
        FROM judged GROUP BY 1 ORDER BY 2 DESC""", cut).fetchall()
    n, repos = con.execute(f"{judged} SELECT count(*), count(DISTINCT repo_id) FROM judged", cut).fetchall()[0]
    return {"newcomers": n, "repos": repos, "return_days": RETURN_DAYS,
            "by_answer": [{"bucket": BUCKETS[b], "newcomers": c, "returned": round(r, 3), "merged": round(m, 3)}
                          for b, c, r, m in by_answer],
            "by_outcome": [{"outcome": o, "newcomers": c, "returned": round(r, 3)} for o, c, r in by_outcome]}


def repo_metrics(con: duckdb.DuckDBPyConnection, now: datetime) -> list[dict]:
    """The facts behind each repo's community score; a fact without enough PRs or newcomers is None."""
    params = {"lo": now - timedelta(days=90), "hi": now - timedelta(days=1), "seen": now - timedelta(days=14),
              "judged": now - timedelta(days=RETURN_DAYS + 30), "dep": now - timedelta(days=DEPENDENCY_DAYS)}
    rows = con.execute(f"""
        WITH {BURST},
        recent AS (
            SELECT p.repo_id, {ANSWER} AS answered_at, p.created_at FROM pr_class p
            WHERE p.author_class = 'outsider' AND p.created_at >= $lo AND p.created_at < $hi AND NOT EXISTS (
                SELECT 1 FROM burst b WHERE b.repo_id = p.repo_id AND b.author_login = p.author_login)),
        answers AS (
            SELECT repo_id, count(*) AS prs,
                   median(epoch(answered_at - created_at) / 3600) FILTER (WHERE answered_at IS NOT NULL) AS first_answer_hours,
                   avg((answered_at IS NOT NULL AND answered_at <= created_at + INTERVAL 1 DAY)::INT) AS answered_1d_share
            FROM recent GROUP BY repo_id),
        new AS ({NEWCOMERS}),
        newcomers AS (
            SELECT repo_id,
                   count(*) FILTER (WHERE created_at <= $seen) AS seen,
                   avg((answered_at IS NOT NULL AND answered_at <= created_at + INTERVAL 14 DAY)::INT)
                       FILTER (WHERE created_at <= $seen) AS newcomer_answered_share,
                   count(*) FILTER (WHERE created_at <= $judged) AS judged,
                   avg((next_at IS NOT NULL AND next_at <= created_at + INTERVAL {RETURN_DAYS} DAY)::INT)
                       FILTER (WHERE created_at <= $judged) AS newcomer_return_rate
            FROM new GROUP BY repo_id),
        -- Who carries the work, as the app measures it: people's merged PRs, the fewest people behind half of them.
        by_person AS (
            SELECT repo_id, author_login, count(*) AS n FROM pr_class
            WHERE merged_at >= $dep AND author_role IN ('insider', 'outsider') GROUP BY repo_id, author_login),
        running AS (
            SELECT repo_id, n, sum(n) OVER (PARTITION BY repo_id) AS total,
                   sum(n) OVER (PARTITION BY repo_id ORDER BY n DESC, author_login ROWS UNBOUNDED PRECEDING) AS upto,
                   row_number() OVER (PARTITION BY repo_id ORDER BY n DESC, author_login) AS k
            FROM by_person),
        dependency AS (
            SELECT repo_id, max(total) AS merged, max(n) / max(total) AS top_share,
                   min(k) FILTER (WHERE upto * 2 >= total) AS bus_factor
            FROM running GROUP BY repo_id)
        SELECT rm.repo_id, rm.language, rm.stars, a.prs, a.first_answer_hours, a.answered_1d_share,
               n.seen, n.newcomer_answered_share, n.judged, n.newcomer_return_rate, d.merged, d.top_share, d.bus_factor
        FROM repo_meta rm LEFT JOIN answers a USING (repo_id) LEFT JOIN newcomers n USING (repo_id)
            LEFT JOIN dependency d USING (repo_id)
        WHERE coalesce(a.prs, 0) >= {MIN_PRS} OR coalesce(n.seen, 0) >= {MIN_NEWCOMERS}
            OR coalesce(d.merged, 0) >= {MIN_MERGED}""", params).fetchall()
    out = []
    for repo_id, lang, stars, prs, hours, share_1d, seen, answered, judged, returned, merged, top, bus in rows:
        enough_prs, enough_seen, enough_judged = (prs or 0) >= MIN_PRS, (seen or 0) >= MIN_NEWCOMERS, (judged or 0) >= MIN_NEWCOMERS
        enough_merged = (merged or 0) >= MIN_MERGED
        out.append({"repo_id": repo_id, "language": lang, "stars": stars,
                    "first_answer_hours": round(hours, 2) if enough_prs and hours is not None else None,
                    "answered_1d_share": round(share_1d, 4) if enough_prs else None,
                    "newcomer_answered_share": round(answered, 4) if enough_seen else None,
                    "newcomer_return_rate": round(returned, 4) if enough_judged else None,
                    "bus_factor": int(bus) if enough_merged else None, "top_share": round(top, 4) if enough_merged else None})
    return out


def community_benchmarks(con: duckdb.DuckDBPyConnection, now: datetime, top_languages: int = 25) -> dict:
    """Percentiles of the community facts by language and size (groups need MIN_GROUP repos), plus the newcomer table."""
    repos = repo_metrics(con, now)
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
            values = [float(r[m]) for r in items if r[m] is not None]
            if len(values) >= MIN_GROUP:
                entry[m] = {"repos": len(values), **quantiles(values)}
        out[key] = entry
    return {"version": 1, "built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "repos": len(repos), "definition": DEFINITION, "population": 'public GitHub repos in the daily crawl with enough outside pull requests and issues to measure', "gaps": 'no private or enterprise teams; GitHub only; a newcomer is someone new to that repo, not to open source',
            "groups": out, "newcomers": newcomer_returns(con, now)}
