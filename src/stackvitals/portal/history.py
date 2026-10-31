"""Since when: the daily history lines say how long a repo has had its owner status and level, which no one-off look can."""
import json
from pathlib import Path


def since(folder: Path, repos: list[dict], today: str, keep: int = 400) -> dict[str, dict[str, str]]:
    """For each repo, the first day of the unbroken run of days with today's owner status and level (today if new)."""
    days = []
    for path in sorted(Path(folder).glob("*.json"))[-keep:]:
        if path.stem >= today:
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8")).get("repos") or []
        except (OSError, ValueError):
            continue
        days.append((path.stem, {r.get("name"): r for r in rows if isinstance(r, dict)}))
    out = {}
    for r in repos:
        now = {"owners": (r.get("owners") or {}).get("status"), "level": (r.get("score") or {}).get("level")}
        found = {}
        for key, value in now.items():
            start = today
            for day, rows in reversed(days):
                row = rows.get(r["name"])
                if not row or row.get(key) != value:
                    break
                start = day
            found[key] = start
        out[r["name"]] = found
    return out
