import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Manifest:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS archive_hours ("
                "hour_key TEXT PRIMARY KEY, status TEXT NOT NULL, events_in INTEGER, events_kept INTEGER, "
                "bad_lines INTEGER, bytes_out INTEGER, sha256 TEXT, error TEXT, updated_at TEXT NOT NULL)"
            )

    def get(self, key: str) -> dict | None:
        row = self.db.execute("SELECT * FROM archive_hours WHERE hour_key = ?", (key,)).fetchone()
        return dict(row) if row else None

    def is_done(self, key: str) -> bool:
        row = self.get(key)
        return bool(row and row["status"] == "done")

    def mark_done(self, key, *, events_in, events_kept, bad_lines, bytes_out, sha256) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO archive_hours VALUES (?, 'done', ?, ?, ?, ?, ?, NULL, ?)",
                (key, events_in, events_kept, bad_lines, bytes_out, sha256, _now()),
            )

    def mark_failed(self, key: str, error: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO archive_hours VALUES (?, 'failed', NULL, NULL, NULL, NULL, NULL, ?, ?)",
                (key, error[:500], _now()),
            )

    def close(self) -> None:
        self.db.close()
