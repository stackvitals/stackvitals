"""Retention for every stream, a size cap that drops the oldest days first, versioned published files, and a history
squash that keeps every data file byte-identical."""
import gzip
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from stackvitals.core import store as core_store
from stackvitals.core.store import SCHEMA, HistoryStore, accept, published

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
TODAY = "2026-10-20"


def day_file(root: Path, stream: str, day: str, size: int = 100, gz: bool = False) -> Path:
    folder = root / stream
    folder.mkdir(parents=True, exist_ok=True)
    body = (json.dumps({"day": day, "pad": "x" * size}) + "\n").encode()
    if gz:
        path = folder / f"{day}.ndjson.gz"
        path.write_bytes(gzip.compress(body))
    else:
        path = folder / (f"{day}.json" if stream == "portal/history" else f"{day}.ndjson")
        path.write_bytes(body)
    return path


def test_retention_keeps_each_stream_for_its_own_number_of_days(tmp_path):
    for stream in ("ci/days", "flow/closed", "community/issues/closed", "portal/history"):
        for day in ("2024-01-01", "2025-10-01", "2026-10-19"):
            day_file(tmp_path, stream, day, gz=stream == "ci/days")
    removed = HistoryStore(tmp_path).retention(TODAY)
    kept = {stream: sorted(p.name[:10] for p in (tmp_path / stream).iterdir()) for stream in core_store.STREAMS
            if (tmp_path / stream).is_dir()}
    assert kept["ci/days"] == ["2026-10-19"]  # CI runs: 180 days
    assert kept["flow/closed"] == ["2025-10-01", "2026-10-19"]  # PRs: 400 days
    assert kept["community/issues/closed"] == ["2025-10-01", "2026-10-19"] and kept["portal/history"] == ["2025-10-01", "2026-10-19"]
    assert removed == {"ci/days": 2, "flow/closed": 1, "community/issues/closed": 1, "portal/history": 1}
    assert HistoryStore(tmp_path).retention(TODAY, {"flow/closed": 30}) == {"flow/closed": 1}


def test_the_size_cap_drops_the_oldest_days_across_streams_but_never_today_or_the_pages(tmp_path):
    day_file(tmp_path, "ci/days", "2026-10-01", size=5000)
    day_file(tmp_path, "flow/closed", "2026-10-02", size=5000)
    day_file(tmp_path, "ci/days", "2026-10-10", size=5000)
    day_file(tmp_path, "ci/days", TODAY, size=5000)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.html").write_text("x" * 50000, encoding="utf-8")
    store = HistoryStore(tmp_path)
    assert store.size() > 15000 and store.size() < 25000  # the pages do not count
    dropped = store.cap(TODAY, max_bytes=12000)
    assert dropped == ["ci/days/2026-10-01.ndjson", "flow/closed/2026-10-02.ndjson"]
    assert (tmp_path / "ci/days" / f"{TODAY}.ndjson").exists() and (tmp_path / "ci/days/2026-10-10.ndjson").exists()
    assert store.cap(TODAY, max_bytes=1) == ["ci/days/2026-10-10.ndjson"]  # today's file stays whatever the cap


def test_published_files_carry_a_schema_and_readers_refuse_newer_ones():
    out = published({"runs": 3})
    assert out["schema"] == SCHEMA and out["runs"] == 3
    assert accept({"runs": 3}) == {"runs": 3}  # files from before the schema field still read
    assert accept(out)["runs"] == 3 and accept({"schema": SCHEMA + 1, "runs": 3}) is None
    assert accept("nope") is None


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_squash_rewrites_history_to_one_commit_and_keeps_the_tree_identical(tmp_path):
    from stackvitals.ci.action import BRANCH, DataBranch
    bare = tmp_path / "remote.git"
    git("init", "-q", "--bare", str(bare), cwd=tmp_path)
    branch = DataBranch(bare.as_uri(), BRANCH, tmp_path / "w0")
    branch.open()
    for k in range(3):
        (branch.path / f"f{k}.txt").write_text(f"{k}\n", encoding="utf-8")
        assert branch.commit_push(f"c{k}") == "pushed"
    tree = git("rev-parse", "HEAD^{tree}", cwd=branch.path)
    assert git("rev-list", "--count", BRANCH, cwd=bare) == "3"
    assert branch.squash("one") == "pushed"
    fresh = DataBranch(bare.as_uri(), BRANCH, tmp_path / "w1")
    fresh.open()
    assert git("rev-list", "--count", BRANCH, cwd=bare) == "1" and git("rev-parse", "HEAD^{tree}", cwd=fresh.path) == tree
    assert sorted(p.name for p in fresh.path.iterdir() if p.name != ".git") == ["f0.txt", "f1.txt", "f2.txt"]


def test_squash_refuses_when_someone_pushed_in_between(tmp_path):
    from stackvitals.ci.action import BRANCH, DataBranch
    bare = tmp_path / "remote.git"
    git("init", "-q", "--bare", str(bare), cwd=tmp_path)
    mine = DataBranch(bare.as_uri(), BRANCH, tmp_path / "w0")
    mine.open()
    (mine.path / "a.txt").write_text("a\n", encoding="utf-8")
    mine.commit_push("a")
    other = DataBranch(bare.as_uri(), BRANCH, tmp_path / "w1")
    other.open()
    (other.path / "b.txt").write_text("b\n", encoding="utf-8")
    other.commit_push("b")
    assert mine.squash("one") == "rejected"
    fresh = DataBranch(bare.as_uri(), BRANCH, tmp_path / "w2")
    fresh.open()
    assert (fresh.path / "b.txt").exists() and git("rev-list", "--count", BRANCH, cwd=bare) == "2"
