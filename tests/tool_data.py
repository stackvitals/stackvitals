import sqlite3
from pathlib import Path

from mergescout.snapshot.schema import DDL, SCHEMA_VERSION

REPO = {"repo_id": 1, "name": "octo/widgets", "stars": 1200, "language": "Python", "pushed_at": "2026-10-10T00:00:00Z",
        "archived": 0, "license": "MIT", "has_discussions": 1, "open_issues": 40, "open_prs": 5, "insiders": 2,
        "outsider_prs": 60, "merged": 45, "closed": 10, "merge_rate": 0.818, "merge_low": 0.69, "merge_high": 0.9,
        "merge_enough": 1, "newcomer_merged": 12, "newcomer_decided": 20, "newcomer_rate": 0.6, "newcomer_low": 0.39,
        "newcomer_high": 0.78, "newcomer_enough": 1, "reviewed": 40, "median_review_hours": 6.5, "review_enough": 1,
        "window_days": 365, "window_complete": 1, "ai_prs": 3, "bot_prs": 20, "insider_prs": 80, "blocking_walls": 0,
        "walls_json": "[]", "labels_json": "[]", "notes": "[]", "contributing": 1,
        "fetched_at": "2026-10-14T00:00:00Z"}
ISSUE = {"repo_id": 1, "number": 7, "title": "Add database retry to the ETL loader",
         "body": "Steps to reproduce: run the loader with a flaky database.", "labels": '["good first issue"]',
         "language": "Python", "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-12T00:00:00Z",
         "available": 1, "opportunity": 1, "blocked_by": "", "assignees": 0, "linked_open_prs": 0, "dead_ends": 0,
         "claimers": 0, "last_claim_at": None, "interest_30d": 0, "score": 0.7, "rank_score": 0.6,
         "p_avail": 1.0, "p_merge": 0.69, "p_reply": 0.88, "p_fixed": 0.3, "p_quality": 0.75, "mult": 1.0,
         "fetched_at": "2026-10-14T00:00:00Z", "beginner": 1, "kind": "task"}


def make_snapshot(path: Path, repos=(REPO,), issues=(ISSUE,), examples=(), built_at="2026-10-14T05:00:00Z") -> Path:
    db = sqlite3.connect(path)
    db.executescript(DDL)
    for table, rows in (("repos", repos), ("issues", issues), ("outsider_prs", examples)):
        for r in rows:
            db.execute(f"INSERT INTO {table} ({', '.join(r)}) VALUES ({', '.join('?' * len(r))})", list(r.values()))
    db.execute("INSERT INTO issues_fts (rowid, title, labels, body) SELECT rowid, title, labels, body FROM issues")
    db.executemany("INSERT INTO meta VALUES (?, ?)", [("schema_version", SCHEMA_VERSION), ("built_at", built_at),
                                                    ("issues", str(len(issues))), ("repos", str(len(repos)))])
    db.commit()
    db.close()
    return path
