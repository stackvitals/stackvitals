"""What a connector pulled, in the data branch under connectors/<name>/: one NDJSON file per pull day (compressed once the
day is over), the newest copy of each record winning, and a small state file to resume from. A private repo also keeps
each answer as the service sent it (raw/), so a better reading of it rebuilds the records without asking again."""
import gzip
import json
import os
import shutil
from pathlib import Path

# Words a public repo must never hold: its data branch is as public as its pages.
REDACT = {"issue": ("title", "url", "epic_title", "assignee", "assignee_email", "assignee_name", "team"), "sprint": ("name",)}


def _clean(r: dict) -> dict:
    hidden = REDACT.get(r.get("t"), ())
    return {k: v for k, v in r.items() if k not in hidden} if hidden else r


class ConnectorStore:
    def __init__(self, root: Path, name: str, redact: bool = False):
        self.dir = Path(root) / "connectors" / name
        self.days = self.dir / "days"
        self.rawdir = self.dir / "raw"
        self.redact = redact
        self._known = None  # the stored copy of each record, read on the first add

    def add(self, records: list[dict], day: str) -> None:
        if self._known is None:
            self._known = {(r.get("t"), r.get("id")): r for r in self._lines()}
        fresh = []
        for r in records:
            r = _clean(r) if self.redact else r
            # A record read again unchanged (an overlap, a cycle every issue names) is not written again.
            if self._known.get((r.get("t"), r.get("id"))) != r:
                self._known[(r.get("t"), r.get("id"))] = r
                fresh.append(r)
        if not fresh:
            return
        self.days.mkdir(parents=True, exist_ok=True)
        with (self.days / f"{day}.ndjson").open("a", encoding="utf-8", newline="\n") as f:
            for r in fresh:
                f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")

    def keep(self, kind: str, ctx: dict, body, day: str) -> None:
        """One answer as the service sent it; never on a public repo, whose data branch anyone can read."""
        if self.redact:
            return
        self.rawdir.mkdir(parents=True, exist_ok=True)
        with (self.rawdir / f"{day}.ndjson").open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"k": kind, "c": ctx, "b": body}, separators=(",", ":"), ensure_ascii=False) + "\n")

    def raw(self):
        """The kept answers, oldest first: {"k": kind, "c": what the reading needs, "b": the body}."""
        yield from self._lines(self.rawdir)

    def clear_records(self) -> None:
        """The records only; the kept answers and the state stay, for a rebuild from them."""
        shutil.rmtree(self.days, ignore_errors=True)
        self._known = None

    def _lines(self, folder: Path | None = None):
        folder = folder or self.days
        if not folder.is_dir():
            return
        for path in sorted(folder.iterdir()):
            if path.name.endswith(".ndjson.gz"):
                text = gzip.decompress(path.read_bytes()).decode("utf-8")
            elif path.name.endswith(".ndjson"):
                text = path.read_text(encoding="utf-8")
            else:
                continue
            # Only "\n" ends a record: splitlines() also splits on U+2028 and the like, which titles may hold.
            for line in text.split("\n"):
                if line.strip():
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue  # a damaged line (a cut-off write) never stops every later run

    def load(self) -> dict[str, list[dict]]:
        """{"issue": [...], "change": [...], "sprint": [...]}, later records winning by id."""
        found = {}
        for r in self._lines():
            found[(r.get("t"), r.get("id"))] = _clean(r) if self.redact else r
        out = {"issue": [], "change": [], "sprint": []}
        for (kind, _id), r in found.items():
            out.setdefault(kind, []).append(r)
        return out

    def state(self) -> dict:
        try:
            return json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_state(self, state: dict) -> None:
        text = json.dumps(state, indent=1, sort_keys=True)
        path = self.dir / "state.json"
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)

    def reset(self) -> None:
        """Everything pulled so far is dropped, so the next pull reads from the start."""
        shutil.rmtree(self.dir, ignore_errors=True)
        self._known = None

    def compress(self, today: str) -> None:
        for folder in (self.days, self.rawdir):
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.ndjson")):
                if path.name.split(".")[0] < today:
                    gz = path.with_name(path.name + ".gz")
                    old = gzip.decompress(gz.read_bytes()) if gz.exists() else b""
                    gz.write_bytes(gzip.compress(old + path.read_bytes(), mtime=0))
                    path.unlink()
