from datetime import datetime, timedelta

import duckdb

from mergescout.labels import HOT
from mergescout.signals.issues import norm_label_macro
from mergescout.signals.repo_stats import _wilson_macros
from mergescout.signals.rules import RULES, Rules


def build_label_trust(con: duckdb.DuckDBPyConnection, now: datetime, rules: Rules = RULES) -> None:
    norm_label_macro(con)
    _wilson_macros(con)
    con.execute("""
        CREATE OR REPLACE TABLE label_trust AS
        WITH closed AS (
            -- Refreshes bring closed issues as issue rows; only crawlers that record fixes fill linked_closed_prs.
            SELECT DISTINCT ON (repo_id, number) *
            FROM (SELECT repo_id, number, labels, state_reason, fix_pr, fix_pr_state, fix_author, fix_association,
                         closed_at, fetched_at FROM closed_issues
                  UNION ALL
                  SELECT repo_id, number, labels, state_reason, fix_pr, fix_pr_state, fix_author, fix_association,
                         closed_at, fetched_at FROM issues WHERE state = 'CLOSED' AND linked_closed_prs IS NOT NULL)
            WHERE closed_at >= $since
            ORDER BY repo_id, number, fetched_at DESC NULLS LAST),
        ci AS (
            SELECT DISTINCT ON (repo_id, number, label) *
            FROM (SELECT *, unnest(list_transform(labels, lambda x: norm_label(x))) AS label FROM closed)
            WHERE list_contains($hot, label)),
        judged AS (
            SELECT ci.repo_id, ci.label, ci.number, ci.fix_pr, CASE
                WHEN ci.state_reason = 'NOT_PLANNED' THEN 'not_planned'
                WHEN ci.state_reason = 'DUPLICATE' THEN 'duplicate'
                WHEN ci.fix_pr_state IS DISTINCT FROM 'MERGED' THEN 'other'
                WHEN pe.kind = 'bot' OR p.ai_tag = 'bot' THEN 'bot'
                WHEN p.ai_tag IS NOT NULL THEN 'ai'
                WHEN pe.kind = 'insider' OR ci.fix_association IN ('OWNER', 'MEMBER', 'COLLABORATOR') THEN 'insider'
                WHEN ci.fix_author IS NULL THEN 'other'
                ELSE 'outsider' END AS outcome
            FROM ci
            LEFT JOIN people pe ON pe.repo_id = ci.repo_id AND pe.login = ci.fix_author
            LEFT JOIN prs p ON p.repo_id = ci.repo_id AND p.number = ci.fix_pr),
        sizes AS (
            SELECT j.repo_id, j.label, median(p.additions + p.deletions) AS median_fix_lines,
                   median(p.changed_files) AS median_fix_files, count(p.number) AS sized
            FROM judged j JOIN prs p ON p.repo_id = j.repo_id AND p.number = j.fix_pr
            WHERE j.outcome IN ('outsider', 'insider') GROUP BY ALL),
        stale AS (
            SELECT repo_id, label, count(*) AS open_stale
            FROM (SELECT repo_id, created_at, unnest(list_transform(labels, lambda x: norm_label(x))) AS label
                  FROM issues WHERE state = 'OPEN')
            WHERE list_contains($hot, label) AND created_at < $stale_before GROUP BY ALL),
        counts AS (
            SELECT repo_id, label, count(*) AS closed_n,
                count(*) FILTER (WHERE outcome = 'outsider') AS outsider_fixes,
                count(*) FILTER (WHERE outcome = 'insider') AS insider_fixes,
                count(*) FILTER (WHERE outcome = 'ai') AS ai_fixes,
                count(*) FILTER (WHERE outcome = 'bot') AS bot_fixes,
                count(*) FILTER (WHERE outcome = 'not_planned') AS not_planned,
                count(*) FILTER (WHERE outcome = 'duplicate') AS duplicates,
                count(*) FILTER (WHERE outcome = 'other') AS other,
                -- The share only counts fixes whose author is known; unlinked closes say nothing about who fixed them.
                count(*) FILTER (WHERE outcome IN ('outsider', 'insider', 'ai', 'bot')) AS known_fixes
            FROM judged GROUP BY ALL)
        SELECT k.repo_id, k.label, coalesce(c.closed_n, 0) AS closed_n,
            coalesce(c.outsider_fixes, 0) AS outsider_fixes, coalesce(c.insider_fixes, 0) AS insider_fixes,
            coalesce(c.ai_fixes, 0) AS ai_fixes, coalesce(c.bot_fixes, 0) AS bot_fixes,
            coalesce(c.not_planned, 0) AS not_planned, coalesce(c.duplicates, 0) AS duplicates,
            coalesce(c.other, 0) AS other, coalesce(c.known_fixes, 0) AS known_fixes,
            c.outsider_fixes::DOUBLE / nullif(c.known_fixes, 0) AS outsider_share,
            wilson_lo(c.outsider_fixes, c.known_fixes) AS outsider_low,
            wilson_hi(c.outsider_fixes, c.known_fixes) AS outsider_high,
            coalesce(c.known_fixes, 0) >= $min_closed AS enough,
            s.median_fix_lines, s.median_fix_files, coalesce(s.sized, 0) AS sized, coalesce(st.open_stale, 0) AS open_stale
        FROM (SELECT repo_id, label FROM counts UNION SELECT repo_id, label FROM stale) k
        LEFT JOIN counts c USING (repo_id, label) LEFT JOIN sizes s USING (repo_id, label)
        LEFT JOIN stale st USING (repo_id, label)""",
        {"hot": sorted(HOT), "stale_before": now - timedelta(days=rules.stale_days), "min_closed": rules.min_closed,
         "since": now - timedelta(days=rules.window_days)})
