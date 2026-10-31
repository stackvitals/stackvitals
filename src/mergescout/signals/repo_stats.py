import math
from datetime import datetime, timedelta

import duckdb

from mergescout.signals.rules import RULES, Rules


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    denom = 1 + z * z / n
    return (centre - margin) / denom, min(1.0, (centre + margin) / denom)


def _wilson_macros(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE OR REPLACE MACRO wilson_lo(k, n) AS CASE WHEN n = 0 THEN NULL ELSE
            ((k::DOUBLE / n + 1.9208 / n) - 1.96 * sqrt((k::DOUBLE / n) * (1 - k::DOUBLE / n) / n + 0.9604 / (n * n)))
            / (1 + 3.8416 / n) END;
        CREATE OR REPLACE MACRO wilson_hi(k, n) AS CASE WHEN n = 0 THEN NULL ELSE least(1.0,
            ((k::DOUBLE / n + 1.9208 / n) + 1.96 * sqrt((k::DOUBLE / n) * (1 - k::DOUBLE / n) / n + 0.9604 / (n * n)))
            / (1 + 3.8416 / n)) END;""")


def build_repo_stats(con: duckdb.DuckDBPyConnection, now: datetime, rules: Rules = RULES) -> None:
    _wilson_macros(con)
    since = now - timedelta(days=rules.window_days)
    con.execute("""
        CREATE OR REPLACE TABLE repo_stats AS
        WITH ranked AS (
            SELECT repo_id, created_at, row_number() OVER (PARTITION BY repo_id ORDER BY created_at DESC) AS rn
            FROM prs WHERE created_at >= $since),
        -- Full crawls keep the newest PRs up to the cap; refreshes can add older ones, which must not widen the window.
        span AS (
            SELECT p.repo_id, coalesce(c.seen, 0) >= $cap AS truncated,
                CASE WHEN coalesce(c.seen, 0) >= $cap THEN c.cap_start ELSE $since END AS window_start
            FROM (SELECT DISTINCT repo_id FROM prs) p
            LEFT JOIN (SELECT repo_id, count(*) AS seen, min(created_at) FILTER (WHERE rn <= $cap) AS cap_start
                       FROM ranked GROUP BY repo_id) c USING (repo_id)),
        -- Prefer the first person's review; older batches only know the very first review.
        w AS (SELECT * REPLACE (coalesce(first_human_review_at, first_review_at) AS first_review_at,
                                coalesce(first_human_review_by, first_review_by) AS first_review_by)
              FROM pr_class JOIN span USING (repo_id) WHERE created_at >= window_start),
        firsts AS (
            SELECT repo_id, author_login, min(merged_at) AS first_merge FROM pr_class
            WHERE author_class = 'outsider' AND merged_at IS NOT NULL GROUP BY ALL),
        o AS (
            SELECT w.repo_id,
                count(*) AS outsider_prs,
                count(*) FILTER (WHERE state = 'MERGED') AS merged,
                count(*) FILTER (WHERE state = 'CLOSED') AS closed,
                count(*) FILTER (WHERE state = 'OPEN') AS open,
                count(*) FILTER (WHERE state IN ('MERGED', 'CLOSED')
                                 AND (f.first_merge IS NULL OR w.created_at <= f.first_merge)) AS newcomer_decided,
                count(*) FILTER (WHERE w.merged_at IS NOT NULL AND w.merged_at = f.first_merge) AS newcomer_merged,
                count(*) FILTER (WHERE first_review_at IS NOT NULL
                                 AND first_review_by IS DISTINCT FROM w.author_login AND rv.kind = 'insider') AS reviewed,
                median(epoch(first_review_at - created_at) / 3600) FILTER (
                    WHERE first_review_at IS NOT NULL AND first_review_by IS DISTINCT FROM w.author_login
                          AND rv.kind = 'insider')
                    AS median_review_hours
            FROM w LEFT JOIN firsts f USING (repo_id, author_login)
            -- Only a maintainer's review counts as a response; review bots answer within minutes.
            LEFT JOIN people rv ON rv.repo_id = w.repo_id AND rv.login = w.first_review_by
            WHERE w.author_class = 'outsider' GROUP BY w.repo_id),
        mix AS (
            SELECT repo_id, count(*) AS window_prs,
                count(*) FILTER (WHERE author_class = 'ai') AS ai_prs,
                count(*) FILTER (WHERE author_class = 'bot') AS bot_prs,
                count(*) FILTER (WHERE author_class = 'insider') AS insider_prs
            FROM w GROUP BY repo_id)
        SELECT span.repo_id, rm.name, rm.stars,
            -- When the PR cap cut history short, say how many days we really cover.
            CASE WHEN span.truncated THEN date_diff('day', span.window_start, $now) ELSE $window END AS window_days,
            NOT span.truncated AS window_complete,
            coalesce(o.outsider_prs, 0) AS outsider_prs, coalesce(o.merged, 0) AS merged,
            coalesce(o.closed, 0) AS closed, coalesce(o.open, 0) AS open,
            o.merged::DOUBLE / nullif(o.merged + o.closed, 0) AS merge_rate,
            wilson_lo(o.merged, o.merged + o.closed) AS merge_low, wilson_hi(o.merged, o.merged + o.closed) AS merge_high,
            coalesce(o.merged + o.closed, 0) >= $min_decided AS merge_enough,
            coalesce(o.newcomer_decided, 0) AS newcomer_decided, coalesce(o.newcomer_merged, 0) AS newcomer_merged,
            o.newcomer_merged::DOUBLE / nullif(o.newcomer_decided, 0) AS newcomer_rate,
            wilson_lo(o.newcomer_merged, o.newcomer_decided) AS newcomer_low,
            wilson_hi(o.newcomer_merged, o.newcomer_decided) AS newcomer_high,
            coalesce(o.newcomer_decided, 0) >= $min_decided AS newcomer_enough,
            coalesce(o.reviewed, 0) AS reviewed, o.median_review_hours,
            coalesce(o.reviewed, 0) >= $min_reviewed AS review_enough,
            coalesce(mix.window_prs, 0) AS window_prs, coalesce(mix.ai_prs, 0) AS ai_prs,
            coalesce(mix.bot_prs, 0) AS bot_prs, coalesce(mix.insider_prs, 0) AS insider_prs
        FROM span LEFT JOIN o USING (repo_id) LEFT JOIN mix USING (repo_id) LEFT JOIN repo_meta rm USING (repo_id)""",
        {"since": since, "now": now, "cap": rules.pr_cap, "window": rules.window_days,
         "min_decided": rules.min_decided, "min_reviewed": rules.min_reviewed})
