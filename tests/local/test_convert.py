import pyarrow.parquet as pq
import pytest

from mergescout.archive.convert import convert_hour, hour_path, write_parquet
from mergescout.archive.events import slim_event
from mergescout.archive.manifest import Manifest

REPO = {"id": 10, "name": "o/r"}
EVENTS = [
    {"id": "1", "type": "IssuesEvent", "created_at": "2026-10-01T15:00:01Z", "actor": {"login": "a"},
     "repo": REPO, "payload": {"action": "opened", "issue": {"number": 7, "state": "open"}}},
    {"id": "2", "type": "PullRequestEvent", "created_at": "2026-10-01T15:00:02Z", "actor": {"login": "b"},
     "repo": REPO, "payload": {"action": "opened", "number": 8, "pull_request": {"number": 8}}},
    {"id": "3", "type": "IssueCommentEvent", "created_at": "2026-10-01T15:00:03Z", "actor": {"login": "c"},
     "repo": REPO, "payload": {"action": "created", "issue": {"number": 7}, "comment": {"body": "hi"}}},
    {"id": "4", "type": "PushEvent", "created_at": "2026-10-01T15:00:04Z", "actor": {"login": "d"},
     "repo": REPO, "payload": {"ref": "refs/heads/main"}},
    {"id": "5", "type": "WatchEvent", "created_at": "2026-10-01T15:00:05Z", "actor": {"login": "e"},
     "repo": REPO, "payload": {"action": "started"}},
]
KEY = "2026-10-01-15"


def test_write_parquet_is_zstd_and_complete(tmp_path):
    out = tmp_path / "x.parquet"
    rows = [slim_event(e) for e in EVENTS[:4]]
    assert write_parquet(rows, out, batch_size=3) == 4
    assert pq.read_table(out).num_rows == 4
    assert pq.ParquetFile(out).metadata.row_group(0).column(0).compression == "ZSTD"
    assert not (tmp_path / "x.parquet.part").exists()


def test_convert_hour_writes_file_and_manifest(tmp_path, make_gz):
    data = make_gz(EVENTS, extra_lines=["{broken"])
    manifest = Manifest(tmp_path / "manifest.sqlite")
    result = convert_hour(KEY, tmp_path, manifest, chunks_factory=lambda url: [data])
    assert (result.status, result.events_in, result.events_kept, result.bad_lines) == ("done", 5, 4, 1)
    assert result.path == hour_path(tmp_path, KEY) and result.path.exists()
    row = manifest.get(KEY)
    assert row["status"] == "done" and row["events_kept"] == 4 and len(row["sha256"]) == 64


def test_second_run_is_a_no_op(tmp_path, make_gz):
    manifest = Manifest(tmp_path / "manifest.sqlite")
    convert_hour(KEY, tmp_path, manifest, chunks_factory=lambda url: [make_gz(EVENTS)])

    def must_not_download(url):
        raise AssertionError("should not download a finished hour")

    assert convert_hour(KEY, tmp_path, manifest, chunks_factory=must_not_download).status == "skipped"


def test_failed_download_leaves_nothing_and_retry_works(tmp_path, make_gz):
    data = make_gz(EVENTS)
    manifest = Manifest(tmp_path / "manifest.sqlite")

    def cut_off(url):
        yield data[: len(data) // 2]
        raise ConnectionError("network dropped")

    with pytest.raises(ConnectionError):
        convert_hour(KEY, tmp_path, manifest, chunks_factory=cut_off)
    assert list(hour_path(tmp_path, KEY).parent.glob("*")) == []
    assert manifest.get(KEY)["status"] == "failed" and not manifest.is_done(KEY)
    assert convert_hour(KEY, tmp_path, manifest, chunks_factory=lambda url: [data]).status == "done"


def test_manifest_survives_reopen(tmp_path, make_gz):
    path = tmp_path / "manifest.sqlite"
    m = Manifest(path)
    convert_hour(KEY, tmp_path, m, chunks_factory=lambda url: [make_gz(EVENTS)])
    m.close()
    assert Manifest(path).is_done(KEY)
