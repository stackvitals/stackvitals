import hashlib
import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import zstandard

SNAPSHOT, PACKED, MANIFEST, PREFIX = "mergescout.sqlite", "mergescout.sqlite.zst", "manifest.json", "data-"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pack(out: Path) -> dict:
    src = out / SNAPSHOT
    db = sqlite3.connect(src)
    meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
    db.close()
    with src.open("rb") as fi, (out / PACKED).open("wb") as fo:
        # One thread and the known size keep memory small (threads ran out of memory on a 8 GB laptop; same speed).
        zstandard.ZstdCompressor(level=19).copy_stream(fi, fo, size=src.stat().st_size)
    manifest = {"schema_version": meta["schema_version"], "built_at": meta["built_at"], "issues": int(meta["issues"]),
                "repos": int(meta["repos"]), "sha256": sha256(out / PACKED), "size": (out / PACKED).stat().st_size,
                "sqlite_size": src.stat().st_size}
    (out / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def previous_manifest(releases, tag: str) -> dict | None:
    # The newest published day other than the one being written.
    older = sorted((r for r in releases.list_releases() if r["tag_name"].startswith(PREFIX) and r["tag_name"] != tag),
                   key=lambda r: r["tag_name"], reverse=True)
    for release in older:
        asset = next((a for a in releases.assets(release) if a["name"] == MANIFEST), None)
        if asset:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / MANIFEST
                releases.download_asset(asset, path)
                return json.loads(path.read_text(encoding="utf-8"))
    return None


def publish(releases, out: Path, now: datetime, keep: int = 7, force: bool = False, min_ratio: float = 0.5,
            log=print) -> str:
    manifest = pack(out)
    if not manifest["issues"] or not manifest["repos"]:
        raise ValueError("refusing to publish an empty snapshot")
    tag = f"{PREFIX}{now:%Y-%m-%d}"
    prev = previous_manifest(releases, tag)
    # A build that lost part of the crawl data must not replace a good day; --force when the drop is expected.
    if prev and not force and manifest["issues"] < min_ratio * (prev.get("issues") or 0):
        raise ValueError(f"refusing to publish: the snapshot shrank from {prev['issues']} to {manifest['issues']} "
                         "issues (a partial build?); use --force if this is expected")
    # Data first, manifest last: a reader never sees a manifest whose file is missing (the checksum guards the rest).
    releases.upload(tag, out / PACKED)
    releases.upload(tag, out / MANIFEST)
    data = sorted((r for r in releases.list_releases() if r["tag_name"].startswith(PREFIX)),
                  key=lambda r: r["tag_name"], reverse=True)
    for old in data[keep:]:
        releases.delete_release(old)
        log(f"removed {old['tag_name']}")
    log(f"published {tag}: {manifest['issues']} issues, {manifest['size'] / 1e6:.1f} MB")
    return tag
