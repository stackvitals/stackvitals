from datetime import datetime, timedelta

import duckdb

from mergescout.labels import BEGINNER, HOT
from mergescout.signals.identity import _quoted
from mergescout.signals.rules import (CLAIM_PATTERN, DISCUSSION_LABEL, DISCUSSION_TITLE, RULES, TRIAGE_LABEL_PATTERN,
                                      UNKNOWN_LOGINS, WAIT_LABEL_PATTERN, WAIT_PATTERN, Rules)


def norm_label_macro(con: duckdb.DuckDBPyConnection) -> None:
    # Same rule as labels.norm_label: lower case, drop :emoji:, keep letters and digits, single spaces.
    con.execute(r"""CREATE OR REPLACE MACRO norm_label(x) AS trim(regexp_replace(
        regexp_replace(regexp_replace(lower(x), ':[a-z0-9_+-]+:', ' ', 'g'), '[^a-z0-9]+', ' ', 'g'), ' +', ' ', 'g'))""")


def build_issue_signals(con: duckdb.DuckDBPyConnection, now: datetime, rules: Rules = RULES) -> None:
    norm_label_macro(con)
    claim_since = now - timedelta(days=rules.claim_days)
    interest_since = now - timedelta(days=rules.interest_days)
    con.execute(f"""
        CREATE OR REPLACE TABLE issue_signals AS
        WITH c AS (
            SELECT c.*, coalesce(pe.kind, 'outsider') AS kind FROM comments c
            LEFT JOIN people pe ON pe.repo_id = c.repo_id AND pe.login = c.author_login
            WHERE c.author_login IS NOT NULL AND lower(c.author_login) NOT IN ({_quoted(UNKNOWN_LOGINS)})),
        claims AS (
            SELECT repo_id, number, max(created_at) AS last_claim_at, count(DISTINCT author_login) AS claimers
            FROM c WHERE kind = 'outsider' AND regexp_matches(lower(body_excerpt), $claim) GROUP BY ALL),
        waits AS (
            SELECT repo_id, number, max(created_at) AS wait_at
            FROM c WHERE kind = 'insider' AND regexp_matches(lower(body_excerpt), $wait) GROUP BY ALL),
        interest AS (
            SELECT repo_id, number, count(DISTINCT author_login) AS interest_30d
            FROM c WHERE kind = 'outsider' AND created_at >= $interest_since GROUP BY ALL),
        il AS (
            SELECT *, list_transform(coalesce(labels, []), lambda x: norm_label(x)) AS nl FROM issues),
        i AS (
            SELECT *, len(list_filter(nl, lambda x: regexp_matches(x, $wait_label))) > 0 AS wait_label,
                len(list_filter(nl, lambda x: regexp_matches(x, $triage_label))) > 0 AS triage_label,
                list_has_any(nl, $hot) AS opportunity
            FROM il)
        SELECT i.repo_id, i.number, i.title, i.labels,
            i.opportunity, list_has_any(i.nl, $beginner) AS beginner, i.triage_label,
            CASE WHEN regexp_matches(lower(coalesce(i.title, '')), $disc_title)
                      OR len(list_filter(i.nl, lambda x: regexp_matches(x, $disc_label))) > 0
                 THEN 'discussion' ELSE 'task' END AS kind,
            coalesce(i.assignees, 0) AS assignees, coalesce(i.linked_open_prs, 0) AS linked_open_prs,
            coalesce(i.linked_closed_prs, 0) AS dead_ends,
            cl.last_claim_at, coalesce(cl.claimers, 0) AS claimers, w.wait_at,
            coalesce(it.interest_30d, 0) AS interest_30d,
            (coalesce(i.assignees, 0) = 0 AND coalesce(i.linked_open_prs, 0) = 0
             AND (cl.last_claim_at IS NULL OR cl.last_claim_at < $claim_since) AND w.wait_at IS NULL
             AND NOT i.wait_label AND NOT (i.triage_label AND NOT i.opportunity)) AS available,
            concat_ws(', ', CASE WHEN i.assignees > 0 THEN 'assigned' END,
                      CASE WHEN i.linked_open_prs > 0 THEN 'open PR' END,
                      CASE WHEN cl.last_claim_at >= $claim_since THEN 'claimed recently' END,
                      CASE WHEN w.wait_at IS NOT NULL THEN 'maintainer asked to wait' END,
                      CASE WHEN i.wait_label THEN 'label says not ready' END,
                      CASE WHEN i.triage_label AND NOT i.opportunity THEN 'label says not settled yet' END)
                AS blocked_by,
            i.created_at, i.updated_at, i.fetched_at, i.run_id
        FROM i
        LEFT JOIN claims cl USING (repo_id, number) LEFT JOIN waits w USING (repo_id, number)
        LEFT JOIN interest it USING (repo_id, number)
        -- Bot-made issues (CI failures, CVE alerts) are not tasks unless a beginner or help label invites outsiders:
        -- real bots also mirror maintainer tasks (stdlib-bot lint fixes, MelvinBot "Help Wanted").
        LEFT JOIN people au ON au.repo_id = i.repo_id AND au.login = i.author_login
        WHERE i.state = 'OPEN' AND NOT (coalesce(au.kind, '') = 'bot' AND NOT list_has_any(i.nl, $hot))
          AND NOT regexp_matches(lower(coalesce(i.title, '')), $dashboard) AND NOT EXISTS (
            SELECT 1 FROM issue_events e WHERE e.repo_id = i.repo_id AND e.number = i.number AND e.event = 'gone'
              AND e.observed_at::DATE >= coalesce(i.fetched_at::DATE, DATE '1970-01-01'))""",
        {"claim": CLAIM_PATTERN, "wait": WAIT_PATTERN, "interest_since": interest_since,
         "claim_since": claim_since, "hot": sorted(HOT), "beginner": sorted(BEGINNER),
         "wait_label": WAIT_LABEL_PATTERN, "triage_label": TRIAGE_LABEL_PATTERN, "disc_title": DISCUSSION_TITLE,
         "disc_label": DISCUSSION_LABEL, "dashboard": r"^\s*dependency dashboard\s*$"})
