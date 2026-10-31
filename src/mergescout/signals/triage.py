import hashlib
from datetime import datetime, timedelta

import duckdb

from mergescout.signals.triage_math import buckets, calibration, fit

DEFINITION = ("outside contributors' PRs opened 30 to 395 days ago; outcome = merged within 30 days of opening; "
              "every feature is as of the PR's opening: the author's earlier PRs and merges here, and the repo's rate over "
              "outside PRs opened 30 to 395 days before it. "
              "Checked on one repo in five, never seen in training.")
MIN_REPO_PRS = 10


def training_rows(con: duckdb.DuckDBPyConnection, now: datetime) -> list[dict]:
    """One row per outside PR whose 30-day outcome is known, with only what was known when it was opened."""
    rows = con.execute("""
        WITH outs AS (
            SELECT repo_id, number, created_at, author_login, additions, deletions, closing_issue_numbers,
                   (merged_at IS NOT NULL AND merged_at <= created_at + INTERVAL 30 DAY) AS merged30
            FROM pr_class WHERE author_class = 'outsider' AND author_login IS NOT NULL),
        -- The repo's rate as of each PR: outside PRs opened 30-395 days earlier, whose 30-day outcome was known by then.
        rated AS (
            SELECT o.*, count(*) OVER w AS past_n, sum(merged30::INT) OVER w AS past_k FROM outs o
            WINDOW w AS (PARTITION BY repo_id ORDER BY created_at
                         RANGE BETWEEN INTERVAL 395 DAY PRECEDING AND INTERVAL 30 DAY PRECEDING)),
        base AS (SELECT * FROM rated WHERE created_at >= $lo AND created_at <= $hi),
        merges AS (SELECT repo_id, author_login, merged_at FROM pr_class WHERE merged_at IS NOT NULL AND author_login IS NOT NULL),
        -- Running totals read "as of" each PR's opening: cheap even for prolific authors.
        here AS (SELECT repo_id, author_login, merged_at,
                        row_number() OVER (PARTITION BY repo_id, author_login ORDER BY merged_at) AS done FROM merges),
        opened AS (SELECT repo_id, author_login, created_at,
                          row_number() OVER (PARTITION BY repo_id, author_login ORDER BY created_at) AS done
                   FROM pr_class WHERE author_login IS NOT NULL),
        counted AS (
            SELECT b.*, coalesce(h.done, 0) AS here_merged, coalesce(o.done, 0) AS here_opened
            FROM base b
            ASOF LEFT JOIN here h ON h.repo_id = b.repo_id AND h.author_login = b.author_login AND b.created_at > h.merged_at
            ASOF LEFT JOIN opened o ON o.repo_id = b.repo_id AND o.author_login = b.author_login AND b.created_at > o.created_at)
        SELECT repo_id, number, here_merged,
               coalesce(additions, 0) + coalesce(deletions, 0) AS lines,
               coalesce(len(closing_issue_numbers), 0) > 0 AS linked_issue,
               -- GitHub reports the author's association as of the query, which leaks the outcome; history does not.
               here_opened = 0 AS first_timer,
               CASE WHEN past_n >= $min_repo THEN past_k::DOUBLE / past_n END AS repo_rate,
               merged30 AS merged
        FROM counted""",
        {"lo": now - timedelta(days=395), "hi": now - timedelta(days=30), "min_repo": MIN_REPO_PRS}).fetchall()
    cols = ("repo", "number", "here_merged", "lines", "linked_issue", "first_timer", "repo_rate", "merged")
    return [dict(zip(cols, r)) for r in rows]


def _held_out(repo_id: int) -> bool:
    # One repo in five, picked by a real hash so neighbouring ids don't land together.
    return int(hashlib.sha1(str(repo_id).encode()).hexdigest(), 16) % 5 == 0


def build_triage_model(con: duckdb.DuckDBPyConnection, now: datetime) -> dict:
    """Fit on four repos in five, check calibration on the fifth, then publish a model fitted on all of them."""
    rows = []
    for r in training_rows(con, now):
        feats = buckets(r["here_merged"], r["lines"], r["linked_issue"], r["first_timer"], r["repo_rate"])
        rows.append({**feats, "merged": bool(r["merged"]), "repo": r["repo"]})
    train = [r for r in rows if not _held_out(r["repo"])]
    test = [r for r in rows if _held_out(r["repo"])]
    evaluation = {"train_prs": len(train), "test_prs": len(test)}
    if train and test:
        evaluation |= calibration(fit(train), test)
    model = fit(rows) if rows else fit([])
    return {**model, "built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "definition": DEFINITION, "prs": len(rows),
            "evaluation": evaluation}
