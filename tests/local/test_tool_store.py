import json
import sqlite3

import httpx

from mergescout.snapshot.publish import MANIFEST, PACKED, SNAPSHOT, pack
from mergescout.tool.store import SnapshotStore


def published(tmp_path, version="1.0", built="2026-10-15T05:00:00Z"):
    out = tmp_path / f"pub-{version}-{built[:10]}"
    out.mkdir()
    db = sqlite3.connect(out / SNAPSHOT)
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    db.executemany("INSERT INTO meta VALUES (?, ?)", [("schema_version", version), ("built_at", built),
                                                    ("issues", "1"), ("repos", "1")])
    db.commit()
    db.close()
    pack(out)
    return out


class Rel:
    def __init__(self, *dirs, fail=False):
        self.dirs, self.fail = {f"data-{d.name[-10:]}": d for d in dirs}, fail

    def list_releases(self):
        if self.fail:
            raise httpx.ConnectError("offline")
        return [{"id": t, "tag_name": t} for t in self.dirs]

    def assets(self, release):
        return [{"id": (release["id"], n), "name": n} for n in (PACKED, MANIFEST)]

    def download_asset(self, asset, dest):
        tag, name = asset["id"]
        dest.write_bytes((self.dirs[tag] / name).read_bytes())


def test_first_update_downloads_then_stays_up_to_date(tmp_path):
    store = SnapshotStore(tmp_path / "home", Rel(published(tmp_path)))
    assert store.update().startswith("updated to 2026-10-15")
    assert store.update().startswith("up to date")
    meta = dict(sqlite3.connect(store.path).execute("SELECT key, value FROM meta").fetchall())
    assert meta["built_at"] == "2026-10-15T05:00:00Z"
