from datetime import datetime, timezone
from pathlib import Path
import tempfile

import duckdb

from mergescout.crawl.writer import BatchWriter
from mergescout.signals.silver import load_silver

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def t(days_ago: float) -> datetime:
    from datetime import timedelta
    return NOW - timedelta(days=days_ago)


def make_con(tables: dict[str, list[dict]]) -> duckdb.DuckDBPyConnection:
    root = Path(tempfile.mkdtemp())
    w = BatchWriter(root, "test", now=lambda: NOW)
    for table, rows in tables.items():
        w.add(table, rows)
    w.flush()
    con = duckdb.connect()
    load_silver(con, [root])
    return con


def pr(number, author, state="MERGED", assoc="NONE", merged_by="maint", typ="User", ai=None, created=30,
       review_by=None, review_assoc=None, review_after_h=None, repo=1, lines=10, files=1):
    from datetime import timedelta
    created_at = t(created)
    return {"repo_id": repo, "number": number, "author_login": author, "author_type": typ,
            "author_association": assoc, "state": state, "merged_by": merged_by if state == "MERGED" else None,
            "created_at": created_at, "merged_at": created_at + timedelta(days=1) if state == "MERGED" else None,
            "closed_at": created_at + timedelta(days=1) if state != "OPEN" else None, "ai_tag": ai,
            "first_review_by": review_by, "first_review_association": review_assoc,
            "first_review_at": created_at + timedelta(hours=review_after_h) if review_after_h is not None else None,
            "additions": lines, "deletions": 0, "changed_files": files, "closing_issue_numbers": []}
