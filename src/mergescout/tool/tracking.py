import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from mergescout.tool.live import LiveError
from mergescout.tool.refs import parse_ref

OUTCOMES = ("started", "pr_opened", "merged", "closed_unmerged", "abandoned", "taken_by_someone_else")
WATCH = ("state", "assignees", "linked_open_prs")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Tracker:
    # Tracked issues and outcomes stay on this machine; nothing is sent anywhere.
    def __init__(self, root: Path):
        self.root = root
        self.file, self.outcomes = root / "tracked.json", root / "outcomes.jsonl"

    def tracked(self) -> dict:
        if not self.file.exists():
            return {}
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except ValueError:
            # A damaged file is kept aside for the user and tracking starts fresh.
            os.replace(self.file, self.file.with_name(self.file.name + ".bad"))
            return {}

    def _save(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_name(f"{self.file.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, self.file)

    @staticmethod
    def _view(status: dict) -> dict:
        return {**{k: status.get(k) for k in WATCH}, "claims": len(status.get("claims") or []),
                "waits": len(status.get("waits") or [])}

    def track(self, key: str, status: dict) -> dict:
        # GitHub names ignore letter case, so tracked keys do too.
        key = key.lower()
        data = self.tracked()
        data[key] = {"tracked_at": data.get(key, {}).get("tracked_at", _now()), "last": self._view(status)}
        self._save(data)
        return data[key]

    def untrack(self, key: str) -> None:
        data = self.tracked()
        data.pop(key.lower(), None)
        self._save(data)

    def updates(self, live) -> list[dict]:
        data, changes = self.tracked(), []
        for key, item in data.items():
            ref = parse_ref(key)
            try:
                now = self._view(live.issue_status(ref.owner, ref.name, ref.number))
            except (LiveError, httpx.HTTPError) as exc:
                # One deleted issue or a rate limit must not hide the others.
                changes.append({"issue": key, "error": str(exc)})
                continue
            diff = {k: [item["last"].get(k), v] for k, v in now.items() if item["last"].get(k) != v}
            if diff:
                changes.append({"issue": key, "changed": diff})
            item["last"] = now
        self._save(data)
        return changes

    def report_outcome(self, key: str, outcome: str, note: str = "") -> dict:
        if outcome not in OUTCOMES:
            raise ValueError(f"Outcome must be one of: {', '.join(OUTCOMES)}.")
        entry = {"issue": key.lower(), "outcome": outcome, "note": note[:500], "at": _now()}
        self.root.mkdir(parents=True, exist_ok=True)
        with self.outcomes.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return entry
