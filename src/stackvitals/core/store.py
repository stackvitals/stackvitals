"""The data branch as a whole: every module's day files, with one retention rule per stream, one size cap that drops the
oldest days first, a schema number on every published file, and the counter that decides when the git history is
squashed. The branch is the source of truth; summaries and any database are derived from it."""
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

SCHEMA = 1
META = "stackvitals.json"
# Stream folder -> days kept (user decision 2026-10-20: 400 for PRs, issues and Portal history, 180 for CI runs). A
# connector day file holds the newest copy of what changed that day, so dropping it only loses records idle since.
STREAMS = {"ci/days": 180, "ci/transitions": 400, "flow/closed": 400, "community/issues/closed": 400, "portal/history": 400,
           **{f"connectors/{name}/{part}": 400 for name in ("jira", "linear", "pagerduty", "incident_io") for part in ("days", "raw")},
           "connectors/copilot/days": 730, "connectors/ai_spend/days": 730}
DEFAULT_CAP_MB = 250
SQUASH_EVERY = 1000
DAY_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(ndjson|ndjson\.gz|json)$")


class HistoryStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def meta(self) -> dict:
        try:
            return json.loads((self.root / META).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_meta(self, meta: dict) -> None:
        path = self.root / META
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"schema": SCHEMA, **meta}, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
        os.replace(tmp, path)

    def bump_commits(self) -> int:
        # Counted here because a shallow clone cannot see the branch's history.
        meta = self.meta()
        n = int(meta.get("commits") or 0) + 1
        self.save_meta({**meta, "commits": n})
        return n

    def day_files(self) -> list[tuple[str, str, Path]]:
        out = []
        for stream in STREAMS:
            folder = self.root / stream
            if not folder.is_dir():
                continue
            for path in sorted(folder.iterdir()):
                m = DAY_FILE.match(path.name)
                if m:
                    out.append((stream, m[1], path))
        return out

    def retention(self, today: str, days: dict[str, int] | None = None) -> dict[str, int]:
        """Remove day files older than each stream's retention; returns how many went, per stream."""
        keep = {**STREAMS, **(days or {})}
        removed = {}
        for stream, day, path in self.day_files():
            oldest = (date.fromisoformat(today) - timedelta(days=keep[stream])).isoformat()
            if day < oldest:
                path.unlink()
                removed[stream] = removed.get(stream, 0) + 1
        return removed

    def size(self) -> int:
        # Only the history counts, never the pages: dropping a page would not free history.
        return sum(path.stat().st_size for _, _, path in self.day_files())

    def cap(self, today: str, max_bytes: int = DEFAULT_CAP_MB * 1024 * 1024) -> list[str]:
        """Drop the oldest day files, whatever their stream, until the history fits; today's files always stay."""
        dropped = []
        files = sorted(self.day_files(), key=lambda x: (x[1], x[0]))
        total = sum(path.stat().st_size for _, _, path in files)
        for stream, day, path in files:
            if total <= max_bytes or day >= today:
                continue
            total -= path.stat().st_size
            path.unlink()
            dropped.append(f"{stream}/{path.name}")
        return dropped


def published(result: dict) -> dict:
    # Every file another tool reads says which schema it follows.
    return {"schema": SCHEMA, **result}


def accept(data) -> dict | None:
    """A published file this version understands, or None: a newer schema is never half-read."""
    if not isinstance(data, dict):
        return None
    version = data.get("schema", SCHEMA)
    return data if isinstance(version, int) and version <= SCHEMA else None


# Fields that move with the clock alone: when a page differs only in these, it is not rewritten (no commit churn).
CLOCK_FIELDS = ("generated", "as_of", "hours", "since")


def _steady(value, top: bool = True):
    if isinstance(value, dict):
        # "since" is the window's start at the top level, but a real date inside the records.
        return {k: _steady(v, False) for k, v in value.items() if k not in CLOCK_FIELDS or (k == "since" and not top)}
    if isinstance(value, list):
        return [_steady(v, False) for v in value]
    return value


def write_if_changed(path, data: dict, also=None, compact: bool = False) -> bool:
    """Write a published JSON file (and `also`'s files) unless the one there differs only in the clock fields."""
    import json
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    new = json.loads(json.dumps(data))
    if old is not None and _steady(old) == _steady(new):
        return False
    path.write_text(json.dumps(data, separators=(",", ":")) if compact else json.dumps(data, indent=1), encoding="utf-8")
    if also:
        also()
    return True
