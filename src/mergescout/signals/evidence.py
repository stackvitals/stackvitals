from datetime import datetime

import duckdb

from mergescout.signals.identity import build_people, build_pr_class
from mergescout.signals.issues import build_issue_signals
from mergescout.signals.labels import build_label_trust
from mergescout.signals.repo_stats import build_repo_stats
from mergescout.signals.rules import RULES, Rules
from mergescout.signals.walls import build_walls

EVIDENCE_VERSION = 1
TABLES = ("people", "repo_stats", "issue_signals", "label_trust", "repo_walls", "candidates")


def build_candidates(con: duckdb.DuckDBPyConnection, now: datetime, rules: Rules = RULES) -> int:
    # Built in one SQL pass: a Python loop took 285 s for 69k issues, far too slow for the full corpus.
    con.execute("CREATE OR REPLACE MACRO iso(x) AS strftime(timezone('UTC', x), '%Y-%m-%dT%H:%M:%SZ')")
    con.execute("""
        CREATE OR REPLACE TABLE candidates AS
        WITH lt AS (
            SELECT repo_id, list({label: label, closed_n: closed_n, known_fixes: known_fixes,
                                  outsider_fixes: outsider_fixes, outsider_share: outsider_share,
                                  low: outsider_low, high: outsider_high, enough: coalesce(enough, false),
                                  window_days: $window_days, median_fix_lines: median_fix_lines,
                                  median_fix_files: median_fix_files} ORDER BY label) AS labels,
                list('not enough evidence for label trust on ''' || label || ''' (' || known_fixes
                     || ' fixes with a known author; need ' || $min_closed || ')' ORDER BY label)
                    FILTER (WHERE NOT coalesce(enough, false) AND closed_n > 0) AS label_notes
            FROM label_trust GROUP BY repo_id),
        wl AS (
            SELECT repo_id, list({wall: wall, blocking: coalesce(blocking, false), evidence: evidence}
                                 ORDER BY wall) AS walls
            FROM repo_walls GROUP BY repo_id),
        base AS (
            SELECT s.*, r.name AS repo, coalesce(rs.merged, 0) AS om_merged,
                   coalesce(rs.merged, 0) + coalesce(rs.closed, 0) AS om_decided, rs.merge_rate, rs.merge_low,
                   rs.merge_high, coalesce(rs.merge_enough, false) AS om_enough,
                   coalesce(rs.newcomer_merged, 0) AS nm_merged, coalesce(rs.newcomer_decided, 0) AS nm_decided,
                   rs.newcomer_rate, rs.newcomer_low, rs.newcomer_high,
                   coalesce(rs.newcomer_enough, false) AS nm_enough, rs.window_days, rs.window_complete,
                   rs.median_review_hours, coalesce(rs.reviewed, 0) AS reviewed,
                   coalesce(rs.review_enough, false) AS review_enough, coalesce(rs.bot_prs, 0) AS bot_prs,
                   coalesce(rs.ai_prs, 0) AS ai_prs, coalesce(rs.insider_prs, 0) AS insider_prs,
                   coalesce(lt.labels, []) AS label_trust, coalesce(lt.label_notes, []) AS label_notes,
                   coalesce(wl.walls, []) AS walls
            FROM issue_signals s JOIN repo_meta r USING (repo_id) LEFT JOIN repo_stats rs USING (repo_id)
            LEFT JOIN lt USING (repo_id) LEFT JOIN wl USING (repo_id)
            WHERE s.opportunity OR s.available)
        SELECT repo_id, repo, number, title, coalesce(available, false) AS available,
            coalesce(opportunity, false) AS opportunity,
            to_json({
                version: $version, computed_at: $computed_at,
                source: {run_id: run_id, fetched_at: iso(fetched_at)},
                issue: {labels: coalesce(labels, []), assignees: assignees, linked_open_prs: linked_open_prs,
                        dead_ends: dead_ends, interest_30d: interest_30d},
                availability: {available: coalesce(available, false),
                               blocked_by: list_filter(string_split(coalesce(blocked_by, ''), ', '), lambda b: b <> ''),
                               last_claim_at: iso(last_claim_at), claimers: claimers},
                repo: {
                    outsider_merge: {merged: om_merged, decided: om_decided, rate: merge_rate, low: merge_low,
                                     high: merge_high, enough: om_enough, window_days: window_days,
                                     window_complete: coalesce(window_complete, false)},
                    newcomer_merge: {merged: nm_merged, decided: nm_decided, rate: newcomer_rate, low: newcomer_low,
                                     high: newcomer_high, enough: nm_enough, window_days: window_days,
                                     window_complete: coalesce(window_complete, false)},
                    review_hours: {median: median_review_hours, n: reviewed, enough: review_enough},
                    excluded: {bot_prs: bot_prs, ai_prs: ai_prs, insider_prs: insider_prs}},
                labels: label_trust, walls: walls,
                notes: list_concat(list_filter([
                    CASE WHEN NOT om_enough THEN 'not enough evidence for outsider merge rate (' || om_decided
                         || ' decided PRs; need ' || $min_decided || ')' END,
                    CASE WHEN NOT nm_enough THEN 'not enough evidence for newcomer merge rate (' || nm_decided
                         || ' decided PRs; need ' || $min_decided || ')' END,
                    CASE WHEN window_complete = false THEN 'PR history covers only the last ' || window_days
                         || ' days (newest ' || $pr_cap || ' PRs)' END,
                    CASE WHEN NOT review_enough THEN 'not enough evidence for review time (' || reviewed
                         || ' maintainer reviews; need ' || $min_reviewed || ')' END], lambda n: n IS NOT NULL),
                    label_notes)})::VARCHAR AS evidence_json
        FROM base""", {"version": EVIDENCE_VERSION, "computed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "min_decided": rules.min_decided, "pr_cap": rules.pr_cap,
                       "min_reviewed": rules.min_reviewed, "min_closed": rules.min_closed,
                       "window_days": rules.window_days})
    return con.execute("SELECT count(*) FROM candidates").fetchall()[0][0]


def build_all(con: duckdb.DuckDBPyConnection, now: datetime, rules: Rules = RULES) -> dict[str, int]:
    build_people(con)
    build_pr_class(con)
    build_repo_stats(con, now, rules)
    build_issue_signals(con, now, rules)
    build_label_trust(con, now, rules)
    build_walls(con)
    build_candidates(con, now, rules)
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0] for t in TABLES}
