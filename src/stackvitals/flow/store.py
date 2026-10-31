import gzip
import json
import os
from pathlib import Path

SCHEMA = "1"


class FlowStore:
    # Closed PRs never change, so they are appended once by close day; open PRs live in one small snapshot.
    def __init__(self, root: Path, folder: str = "flow"):
        # Community keeps its issues the same way, in its own folder.
        self.dir = Path(root) / folder
        self.root = Path(root)
        self.closed = self.dir / "closed"
        self.closed.mkdir(parents=True, exist_ok=True)
        version = self.dir / "VERSION"
        if not version.exists():
            version.write_text(SCHEMA + "\n", encoding="utf-8")

    def put(self, records: list[dict], day: str) -> None:
        if not records:
            return
        with (self.closed / f"{day}.ndjson").open("a", encoding="utf-8", newline="\n") as f:
            for r in records:
                f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")

    def open(self) -> dict[int, dict]:
        try:
            return {r["n"]: r for r in json.loads((self.dir / "open.json").read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            return {}

    def save_open(self, prs: dict[int, dict]) -> None:
        self._atomic(self.dir / "open.json", json.dumps(sorted(prs.values(), key=lambda r: r["n"]),
                                                        separators=(",", ":"), ensure_ascii=False))

    def _lines(self):
        for path in sorted(self.closed.iterdir()):
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
        # The newest copy of a closed PR wins; a PR that was reopened counts as open only.
        opened = self.open()
        closed = {}
        for r in self._lines():
            if r["n"] not in closed or r.get("f", "") >= closed[r["n"]].get("f", ""):
                closed[r["n"]] = r
        return {"open": list(opened.values()), "closed": [r for n, r in closed.items() if n not in opened]}

    def asks(self) -> dict[int, list]:
        # What maintainers asked for per closed PR, as categories only (never the review text).
        from stackvitals.flow.preflight import load_asks
        return load_asks(self.dir / "asks.ndjson")

    def put_asks(self, asks: dict[int, list]) -> None:
        with (self.dir / "asks.ndjson").open("a", encoding="utf-8", newline="\n") as f:
            for n, a in asks.items():
                f.write(json.dumps({"n": n, "a": a}, separators=(",", ":")) + "\n")

    def repo(self) -> dict:
        """What the repo query saved, plus deployments and incidents recorded from other tools (repository_dispatch)."""
        from stackvitals.core import recorded
        try:
            info = json.loads((self.dir / "repo.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        got = recorded.load(self.root)
        return {**info, "recorded": got} if got["deployments"] or got["incidents"] else info

    def save_repo(self, info: dict) -> None:
        self._atomic(self.dir / "repo.json", json.dumps(info, indent=1, sort_keys=True))

    def state(self) -> dict:
        try:
            return json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_state(self, state: dict) -> None:
        self._atomic(self.dir / "state.json", json.dumps(state, indent=1, sort_keys=True))

    def compress(self, today: str) -> None:
        # Past days are gzipped right away, merged with any earlier gz of the same day.
        for path in sorted(self.closed.glob("*.ndjson")):
            day = path.name[:10]
            if day >= today:
                continue
            packed = self.closed / f"{day}.ndjson.gz"
            old = gzip.decompress(packed.read_bytes()) if packed.exists() else b""
            tmp = packed.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(old + path.read_bytes(), mtime=0))
            os.replace(tmp, packed)
            path.unlink()

    @staticmethod
    def _atomic(path: Path, text: str) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
