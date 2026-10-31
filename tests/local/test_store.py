import io
import tarfile
from datetime import datetime, timezone

import pytest

from mergescout.crawl.state import CrawlState
from mergescout.store.sync import pull, push, safe_extract

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)
QUIET = {"log": lambda *a: None}


class MemReleases:
    def __init__(self, fail=False):
        self.files, self.fail = {}, fail

    def upload(self, tag, path, name=None):
        if self.fail:
            raise RuntimeError("network down")
        self.files[(tag, name or path.name)] = path.read_bytes()
        return {}

    def download(self, tag, name, dest):
        if (tag, name) not in self.files:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.files[(tag, name)])
        return True


def make_data(d):
    for table in ("prs", "issues"):
        (d / "crawl" / table).mkdir(parents=True, exist_ok=True)
        (d / "crawl" / table / "run=111-1-000.parquet").write_bytes(b"a")
        (d / "crawl" / table / "run=111-1-001.parquet").write_bytes(b"b")
        (d / "crawl" / table / "run=222-1-000.parquet").write_bytes(b"c")
    CrawlState(d / "crawl.sqlite").upsert_repos([{"repo_id": 1, "name": "o/r", "stars": 100, "pushed_at": None,
                                                   "priority": 0}])


def test_push_uploads_one_bundle_per_run_then_clears_local_batches(tmp_path):
    make_data(tmp_path)
    rel = MemReleases()
    out = push(tmp_path, rel, NOW, **QUIET)
    assert out == {"runs": 2, "state": True, "discover": False}
    assert set(rel.files) == {("crawl-2026-W42", "crawl-111-1.tar"), ("crawl-2026-W42", "crawl-222-1.tar"),
                              ("crawl-state", "crawl.sqlite.gz")}
    names = tarfile.open(fileobj=io.BytesIO(rel.files[("crawl-2026-W42", "crawl-111-1.tar")])).getnames()
    assert sorted(names) == ["crawl/issues/run=111-1-000.parquet", "crawl/issues/run=111-1-001.parquet",
                             "crawl/prs/run=111-1-000.parquet", "crawl/prs/run=111-1-001.parquet"]
    assert not list((tmp_path / "crawl").rglob("*.parquet")) and not list((tmp_path / "outbox").glob("*"))


def test_pull_restores_state_and_discover_into_an_empty_folder(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    make_data(src)
    (src / "discover" / "basics").mkdir(parents=True)
    (src / "discover" / "basics" / "a.parquet").write_bytes(b"basics")
    rel = MemReleases()
    assert push(src, rel, NOW, with_discover=True, **QUIET)["discover"] is True
    assert pull(dst, rel, **QUIET) == {"state": True, "discover": True}
    assert CrawlState(dst / "crawl.sqlite").counts() == {"queued": 1}
    assert (dst / "discover" / "basics" / "a.parquet").read_bytes() == b"basics"


class ListingReleases(MemReleases):
    def get(self, tag):
        return {"id": tag} if any(t == tag for t, _ in self.files) else None

    def list_releases(self):
        return [{"id": tag, "tag_name": tag} for tag in sorted({t for t, _ in self.files})]

    def assets(self, release):
        return [{"id": (release["id"], n), "name": n} for t, n in self.files if t == release["id"]]

    def download_asset(self, asset, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.files[asset["id"]])
