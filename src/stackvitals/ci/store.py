import gzip
import json
import os
from datetime import date, timedelta
from pathlib import Path

SCHEMA = "1"
KNOWN = "tests-seen.json.gz"


class DataStore:
    # History lives under <root>/ci: one NDJSON file per collection day, compressed once the day is over.
    def __init__(self, root: Path):
        self.dir = Path(root) / "ci"
        self.days = self.dir / "days"
        self.days.mkdir(parents=True, exist_ok=True)
        version = self.dir / "VERSION"
        if not version.exists():
            version.write_text(SCHEMA + "\n", encoding="utf-8")

    def add(self, records: list[dict], day: str) -> None:
        if not records:
            return
        with (self.days / f"{day}.ndjson").open("a", encoding="utf-8", newline="\n") as f:
            for r in records:
                f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")

    def _lines(self):
        for path in sorted(self.days.iterdir()):
            if path.name.endswith(".ndjson.gz"):
                text = gzip.decompress(path.read_bytes()).decode("utf-8")
            elif path.name.endswith(".ndjson"):
                text = path.read_text(encoding="utf-8")
            else:
                continue
            for line in text.splitlines():
                if line.strip():
                    yield json.loads(line)

    def load(self) -> dict[str, list[dict]]:
        # Later records win, so a run seen again keeps its newest state.
        runs, jobs, tests = {}, {}, {}
        for r in self._lines():
            if r.get("t") == "run":
                runs[(r["id"], r["att"])] = r
            elif r.get("t") == "job":
                jobs[r["id"]] = r
            elif r.get("t") == "tests":
                tests[r["art"]] = r
        return {"runs": list(runs.values()), "jobs": list(jobs.values()), "tests": list(tests.values())}

    def state(self) -> dict:
        path = self.dir / "state.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_state(self, state: dict) -> None:
        path = self.dir / "state.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def known_tests(self) -> set | None:
        """Every test id seen so far, or None before the first collect that read test reports."""
        try:
            return set(json.loads(gzip.decompress((self.dir / KNOWN).read_bytes())))
        except (OSError, ValueError, EOFError):
            return None

    def save_known_tests(self, ids: set) -> None:
        data = gzip.compress(json.dumps(sorted(ids), separators=(",", ":")).encode("utf-8"), mtime=0)
        path = self.dir / KNOWN
        # Written only when a test was added, so most runs leave the data branch alone.
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)

    def compress(self, today: str) -> None:
        for path in sorted(self.days.glob("*.ndjson")):
            if path.name.split(".")[0] < today:
                # A past day is kept compressed; late re-runs are merged in and it is compressed again.
                gz = path.with_name(path.name + ".gz")
                old = gzip.decompress(gz.read_bytes()) if gz.exists() else b""
                gz.write_bytes(gzip.compress(old + path.read_bytes(), mtime=0))
                path.unlink()

    def compact(self, today: str, retention_days: int = 180) -> None:
        oldest = (date.fromisoformat(today) - timedelta(days=retention_days)).isoformat()
        for path in sorted(self.days.iterdir()):
            if path.name.split(".")[0] < oldest:
                path.unlink()
        self.compress(today)
