import json
import sqlite3
from datetime import datetime, timezone

import httpx
import pytest
import zstandard

from mergescout.github.releases import Releases
from mergescout.snapshot.publish import MANIFEST, PACKED, SNAPSHOT, pack, publish, sha256

PUBLISHED_AT = datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc)


def tiny(out, issues=3):
    out.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(out / SNAPSHOT)
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    db.executemany("INSERT INTO meta VALUES (?, ?)", [("schema_version", "1.0"), ("built_at", "2026-10-15T05:00:00Z"),
                                                    ("issues", str(issues)), ("repos", "1")])
    db.commit()
    db.close()


class Rel:
    def __init__(self, tags=()):
        self.releases = [{"id": i, "tag_name": t} for i, t in enumerate(tags)]
        self.files, self.deleted = {}, []

    def upload(self, tag, path, name=None):
        if not any(r["tag_name"] == tag for r in self.releases):
            self.releases.append({"id": len(self.releases) + 100, "tag_name": tag})
        self.files[(tag, name or path.name)] = path.read_bytes()

    def list_releases(self):
        return list(self.releases)

    def delete_release(self, release):
        self.deleted.append(release["tag_name"])
        self.releases.remove(release)


def test_pack_compresses_and_describes_the_file(tmp_path):
    tiny(tmp_path)
    m = pack(tmp_path)
    assert m["sha256"] == sha256(tmp_path / PACKED) and m["schema_version"] == "1.0" and m["issues"] == 3
    raw = zstandard.ZstdDecompressor().stream_reader((tmp_path / PACKED).open("rb")).read()
    assert raw == (tmp_path / SNAPSHOT).read_bytes()
    assert json.loads((tmp_path / MANIFEST).read_text()) == m


def test_releases_work_without_a_token_and_delete_tags():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(204)
    rel = Releases(None, "me/repo", client=httpx.Client(transport=httpx.MockTransport(handler)))
    rel.delete_release({"id": 5, "tag_name": "data-2026-10-01"})
    assert "authorization" not in seen[0].headers
    assert [r.url.path for r in seen] == ["/repos/me/repo/releases/5", "/repos/me/repo/git/refs/tags/data-2026-10-01"]
