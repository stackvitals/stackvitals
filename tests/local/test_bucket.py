import json
from datetime import datetime, timezone

import httpx
import pytest

from stackvitals.core import bucket
from stackvitals.core.workspace import run_job


class FakeS3:
    """An in-memory S3 with conditional writes on PUT (If-Match / If-None-Match), as AWS S3 and R2 answer them."""

    def __init__(self):
        self.objects, self.version, self.seen = {}, 0, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=key/")
        key = request.url.path.split("/", 2)[2]
        self.seen.append((request.method, key))
        if request.method == "GET":
            if key not in self.objects:
                return httpx.Response(404)
            body, etag = self.objects[key]
            return httpx.Response(200, content=body, headers={"etag": etag})
        if request.method == "DELETE":
            self.objects.pop(key, None)
            return httpx.Response(204)
        current = self.objects.get(key)
        if "if-none-match" in request.headers and current is not None:
            return httpx.Response(412)
        if "if-match" in request.headers and (current is None or current[1] != request.headers["if-match"]):
            return httpx.Response(412)
        self.version += 1
        self.objects[key] = (request.content, f'"v{self.version}"')
        return httpx.Response(200, headers={"etag": f'"v{self.version}"'})


def store(s3, tmp_path, name="a"):
    return bucket.BucketStore("s3://data/org/repo", tmp_path / name, "https://s3.example.com", "key", "secret", "auto",
                              client=httpx.Client(transport=httpx.MockTransport(s3)))


def test_files_round_trip_and_an_unchanged_tree_writes_nothing(tmp_path):
    s3 = FakeS3()
    a = store(s3, tmp_path)
    a.open()
    (a.path / "ci" / "days").mkdir(parents=True)
    (a.path / "ci" / "days" / "2026-10-23.ndjson.gz").write_bytes(b"x" * 10)
    (a.path / "docs").mkdir()
    (a.path / "docs" / "index.html").write_text("app", encoding="utf-8")
    assert a.dirty() and a.commit_push("first") == "pushed" and a.commit_push("again") == "unchanged"
    b = store(s3, tmp_path, "b")
    b.open()
    assert (b.path / "docs" / "index.html").read_text(encoding="utf-8") == "app" and not b.dirty()
    # Content-addressed objects plus one manifest; nothing written under a path name.
    assert sorted(k.split("/")[2] for k in s3.objects) == ["manifest.json", "objects", "objects"]


def test_a_run_that_lost_the_race_is_rejected_and_replaced_contents_are_cleaned_up(tmp_path):
    s3 = FakeS3()
    a, b = store(s3, tmp_path, "a"), store(s3, tmp_path, "b")
    a.open()
    b.open()
    (a.path / "f.txt").write_text("from a", encoding="utf-8")
    (b.path / "f.txt").write_text("from b", encoding="utf-8")
    assert a.commit_push("a") == "pushed" and b.commit_push("b") == "rejected"
    b.open()
    assert (b.path / "f.txt").read_text(encoding="utf-8") == "from a"
    (b.path / "f.txt").write_text("b again", encoding="utf-8")
    assert b.commit_push("b") == "pushed"
    kept = {s3.objects[k][0] if isinstance(s3.objects[k], tuple) else s3.objects[k] for k in s3.objects if "/objects/" in k}
    assert b"from a" not in kept and b"b again" in kept  # replaced content goes; a loser's upload may stay


def test_run_job_uses_the_bucket_when_storage_names_one(tmp_path, monkeypatch):
    s3 = FakeS3()
    real = bucket.BucketStore
    monkeypatch.setattr(bucket, "BucketStore", lambda *a, **k: real(*a[:6], client=httpx.Client(transport=httpx.MockTransport(s3))))
    env = {"GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "t", "STACKVITALS_STORAGE": "s3://data/o/r",
           "STACKVITALS_S3_ENDPOINT": "https://s3.example.com", "STACKVITALS_S3_KEY_ID": "key", "STACKVITALS_S3_SECRET": "secret",
           "RUNNER_TEMP": str(tmp_path / "tmp")}

    def step(ws):
        (ws.path / "ci").mkdir(exist_ok=True)
        (ws.path / "ci" / "state.json").write_text(json.dumps({"n": 1}), encoding="utf-8")
    out = run_job(env, [("CI Health", step)], datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert out["outcome"] == "pushed" and any(k.endswith("manifest.json") for k in s3.objects)


def test_missing_keys_are_named():
    with pytest.raises(bucket.BucketError, match="STACKVITALS_S3_SECRET"):
        bucket.from_env({"STACKVITALS_STORAGE": "s3://b/p", "STACKVITALS_S3_ENDPOINT": "e", "STACKVITALS_S3_KEY_ID": "k"}, None)


def test_a_reader_that_finds_contents_cleaned_up_mid_read_starts_over(tmp_path):
    s3 = FakeS3()
    a = store(s3, tmp_path, "a")
    a.open()
    (a.path / "f.txt").write_text("one", encoding="utf-8")
    a.commit_push("1")
    reader = store(s3, tmp_path, "r")
    real = reader._send
    swapped = []

    def send(method, key, body=b"", headers=None):
        # The first time the reader asks for a file, another run has just replaced and cleaned it up.
        if method == "GET" and "/objects/" in key and not swapped:
            swapped.append(1)
            (a.path / "f.txt").write_text("two", encoding="utf-8")
            a.commit_push("2")
        return real(method, key, body, headers)
    reader._send = send
    reader.open()
    assert (reader.path / "f.txt").read_text(encoding="utf-8") == "two"
