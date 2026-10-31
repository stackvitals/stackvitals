import os
import sqlite3
from datetime import datetime
from pathlib import Path

import duckdb

from mergescout.signals.issues import norm_label_macro
from mergescout.snapshot.schema import DDL, SCHEMA_VERSION
from mergescout.snapshot.score import WEIGHTS, Weights

ISO = "CREATE OR REPLACE MACRO iso(x) AS strftime(timezone('UTC', x), '%Y-%m-%dT%H:%M:%SZ')"
# Issue-template checklist lines ("I affirm", "I have read the Contributing Guide") hide what the issue asks.
BOILERPLATE = (r"(?im)^.*\b(i affirm|i understand that if|i have (read|searched|checked|confirmed|verified)"
               r"|code of conduct|this is not a duplicate)\b.*$\n?")

SCORED = """
CREATE OR REPLACE TABLE snap_issues AS
WITH lt AS (SELECT repo_id, label, CASE WHEN enough THEN outsider_low END AS fixed_low FROM label_trust),
il AS (SELECT repo_id, number, unnest(list_transform(labels, lambda x: norm_label(x))) AS label FROM issue_signals),
fixed AS (SELECT il.repo_id, il.number, max(lt.fixed_low) AS fixed_low FROM il JOIN lt USING (repo_id, label)
          GROUP BY ALL),
walls AS (SELECT repo_id, count(*) FILTER (WHERE blocking) AS blocking FROM repo_walls GROUP BY repo_id),
base AS (
    SELECT s.*, i.body_excerpt, rm.language, rs.merge_low, rs.review_enough, rs.median_review_hours, rs.newcomer_low,
        coalesce(w.blocking, 0) AS blocking_walls, f.fixed_low
    FROM issue_signals s JOIN issues i USING (repo_id, number) JOIN repo_meta rm USING (repo_id)
    LEFT JOIN repo_stats rs USING (repo_id) LEFT JOIN walls w USING (repo_id) LEFT JOIN fixed f USING (repo_id, number)
    WHERE s.opportunity OR s.available),
parts AS (
    -- Every part is a DOUBLE: SQLite cannot store DuckDB decimals.
    SELECT *, (CASE WHEN available THEN 1 ELSE 0 END)::DOUBLE AS p_avail,
        coalesce(merge_low, $prior_merge)::DOUBLE AS p_merge,
        (CASE WHEN review_enough THEN 1 / (1 + median_review_hours / $reply_half) ELSE $prior_reply END)::DOUBLE
            AS p_reply,
        coalesce(fixed_low, newcomer_low, $prior_fixed)::DOUBLE AS p_fixed,
        (0.5 * least(length(coalesce(body_excerpt, '')), 600) / 600
          + 0.25 * CASE WHEN regexp_matches(lower(coalesce(body_excerpt, '')),
                                            '(steps to reproduce|expected|```|error|traceback|repro)') THEN 1 ELSE 0 END
          + 0.25 * CASE WHEN len(coalesce(labels, [])) > 0 THEN 1 ELSE 0 END)::DOUBLE AS p_quality,
        (greatest(power($dead_end, coalesce(dead_ends, 0)), $dead_end_floor)
          * CASE WHEN coalesce(interest_30d, 0) >= $crowded_interest THEN $crowded ELSE 1 END
          * CASE WHEN blocking_walls > 0 THEN $blocking ELSE 1 END
          -- Trackers and debates are rarely a task; issues open for years usually hide a reason.
          * CASE WHEN kind = 'discussion' THEN $discussion ELSE 1 END
          * CASE WHEN triage_label THEN $untriaged ELSE 1 END
          * CASE WHEN date_diff('day', created_at, $now) > $very_old_days THEN $very_old
                 WHEN date_diff('day', created_at, $now) > $old_days THEN $old ELSE 1 END)::DOUBLE AS mult
    FROM base),
scored AS (
    SELECT *, (CASE WHEN available THEN ($w_avail * p_avail + $w_merge * p_merge + $w_reply * p_reply
                                         + $w_fixed * p_fixed + $w_quality * p_quality) * mult ELSE 0 END)::DOUBLE
              AS score
    FROM parts),
ranked AS (
    -- Freshness is applied once a day at build time, so queries only sort an index.
    SELECT *, score * power(0.5, greatest(coalesce(date_diff('day', coalesce(updated_at, created_at), $now), 0), 0)
                                 / $fresh_half) AS rank_score,
        row_number() OVER (PARTITION BY repo_id, opportunity ORDER BY score DESC, updated_at DESC) AS repo_rank
    FROM scored)
SELECT * FROM ranked WHERE opportunity OR repo_rank <= $per_repo_other
ORDER BY opportunity DESC, rank_score DESC LIMIT $max_issues
"""

ISSUE_ROWS = """
SELECT repo_id, number, title,
    substr(ltrim(regexp_replace(coalesce(body_excerpt, ''), $boilerplate, '', 'g'), ' ' || chr(10) || chr(13) || chr(9)),
           1, 300),
    to_json(coalesce(labels, []))::VARCHAR,
    language, iso(created_at), iso(updated_at), available::INT, opportunity::INT, blocked_by, assignees,
    linked_open_prs, dead_ends, claimers, iso(last_claim_at), interest_30d, score, rank_score,
    p_avail, p_merge, p_reply, p_fixed, p_quality, mult, iso(fetched_at), beginner::INT, kind
FROM snap_issues WHERE repo_id IN (SELECT repo_id FROM kept_repos)
"""

REPO_ROWS = """
SELECT rm.repo_id, rm.name, rm.stars, rm.language, iso(rm.pushed_at), rm.archived::INT, rm.license,
    rm.has_discussions::INT, rm.open_issues, rm.open_prs, coalesce(ins.n, 0), rs.outsider_prs, rs.merged, rs.closed,
    rs.merge_rate, rs.merge_low, rs.merge_high, rs.merge_enough::INT, rs.newcomer_merged, rs.newcomer_decided,
    rs.newcomer_rate, rs.newcomer_low, rs.newcomer_high, rs.newcomer_enough::INT, rs.reviewed, rs.median_review_hours,
    rs.review_enough::INT, rs.window_days, rs.window_complete::INT, rs.ai_prs, rs.bot_prs, rs.insider_prs,
    coalesce(w.blocking, 0), coalesce(w.walls_json, '[]'), coalesce(l.labels_json, '[]'), coalesce(n.notes, '[]'),
    (coalesce(rm.contributing_excerpt, '') <> '')::INT, iso(rm.fetched_at)
FROM repo_meta rm LEFT JOIN repo_stats rs USING (repo_id)
LEFT JOIN (SELECT repo_id, count(*) AS n FROM people WHERE kind = 'insider' GROUP BY 1) ins USING (repo_id)
LEFT JOIN (SELECT repo_id, count(*) FILTER (WHERE blocking) AS blocking,
                  to_json(list({wall: wall, blocking: blocking, evidence: evidence} ORDER BY wall))::VARCHAR AS walls_json
           FROM repo_walls GROUP BY 1) w USING (repo_id)
LEFT JOIN (SELECT repo_id, to_json(list({label: label, closed_n: closed_n, known_fixes: known_fixes,
                  outsider_fixes: outsider_fixes, outsider_share: outsider_share, low: outsider_low,
                  high: outsider_high, enough: enough, median_fix_lines: median_fix_lines,
                  median_fix_files: median_fix_files, open_stale: open_stale} ORDER BY label))::VARCHAR AS labels_json
           FROM label_trust GROUP BY 1) l USING (repo_id)
-- Evidence notes are about the repo, so they are stored once per repo, not on every issue.
LEFT JOIN (SELECT repo_id, any_value(json_extract(evidence_json, '$.notes')::VARCHAR) AS notes
           FROM candidates GROUP BY 1) n USING (repo_id)
WHERE rm.repo_id IN (SELECT repo_id FROM kept_repos)
"""

EXAMPLE_ROWS = """
SELECT repo_id, number, iso(merged_at), additions + deletions, changed_files,
    round(epoch(merged_at - created_at) / 86400, 1)
FROM (SELECT *, row_number() OVER (PARTITION BY repo_id ORDER BY merged_at DESC) AS rn FROM pr_class
      WHERE author_class = 'outsider' AND state = 'MERGED' AND merged_at IS NOT NULL)
WHERE rn <= 3 AND repo_id IN (SELECT repo_id FROM kept_repos)
"""


def build_snapshot(con: duckdb.DuckDBPyConnection, path: Path, now: datetime, w: Weights = WEIGHTS,
                   per_repo_other: int = 30, max_issues: int = 350_000) -> dict:
    norm_label_macro(con)
    con.execute(ISO)
    con.execute(SCORED, {
        "prior_merge": w.prior_merge, "prior_reply": w.prior_reply, "prior_fixed": w.prior_fixed,
        "reply_half": w.reply_half_hours, "dead_end": w.dead_end, "dead_end_floor": w.dead_end_floor,
        "crowded_interest": w.crowded_interest, "crowded": w.crowded, "blocking": w.blocking_wall,
        "w_avail": w.availability, "w_merge": w.outsider_merge, "w_reply": w.reply, "w_fixed": w.fixed_before,
        "w_quality": w.issue_quality, "now": now, "fresh_half": w.freshness_half_days, "discussion": w.discussion, "untriaged": w.untriaged,
        "old_days": w.old_days, "old": w.old, "very_old_days": w.very_old_days, "very_old": w.very_old,
        "per_repo_other": per_repo_other, "max_issues": max_issues})
    # A rename between crawls can leave two repo ids with one name; the newest copy wins.
    con.execute("CREATE OR REPLACE TEMP TABLE kept_repos AS SELECT repo_id FROM repo_meta WHERE name IS NOT NULL "
                "QUALIFY row_number() OVER (PARTITION BY lower(name) ORDER BY fetched_at DESC NULLS LAST, "
                "repo_id DESC) = 1")
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(DDL)
    counts = {}
    for table, sql in (("repos", REPO_ROWS), ("issues", ISSUE_ROWS), ("outsider_prs", EXAMPLE_ROWS)):
        rows = con.execute(sql, {"boilerplate": BOILERPLATE} if table == "issues" else None).fetchall()
        if rows:
            db.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(rows[0]))})", rows)
        counts[table] = len(rows)
    db.execute("INSERT INTO issues_fts (rowid, title, labels, body) SELECT rowid, title, labels, body FROM issues")
    meta = {"schema_version": SCHEMA_VERSION, "built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "issues": counts["issues"], "repos": counts["repos"],
            "free_issues": db.execute("SELECT count(*) FROM issues WHERE available = 1").fetchone()[0]}
    db.executemany("INSERT INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in meta.items()])
    db.commit()
    db.execute("INSERT INTO issues_fts (issues_fts) VALUES ('optimize')")
    db.execute("ANALYZE")
    db.commit()
    db.execute("VACUUM")
    db.close()
    os.replace(tmp, path)
    return counts
