import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import zstandard

from mergescout.snapshot.publish import MANIFEST, PACKED, PREFIX, SNAPSHOT, sha256
from mergescout.snapshot.schema import SCHEMA_MAJOR

DEFAULT_REPO = "kaushik-yadav/merge-scout"


def home() -> Path:
    root = Path(os.environ.get("MERGESCOUT_HOME") or Path.home() / ".mergescout")
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_token() -> str | None:
    # The same names the rest of the suite reads, so one exported token serves every command.
    for name in ("MERGESCOUT_TOKEN", "STACKVITALS_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _major(version) -> int:
    return int(str(version).split(".")[0])


class SnapshotStore:
    def __init__(self, root: Path, releases):
        self.root, self.releases = root, releases
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = root / SNAPSHOT

    def local_manifest(self) -> dict | None:
        p = self.root / MANIFEST
        if not (p.exists() and self.path.exists()):
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            # A cut-off manifest only costs a fresh check, never a locked-out user.
            return None

    def _tmp(self, name: str) -> Path:
        # Per process and thread, so two AI tools starting together never share a half-written file.
        return self.root / f"{name}.{os.getpid()}.{threading.get_ident()}"

    def _remember(self, manifest: dict) -> None:
        tmp = self._tmp(MANIFEST)
        tmp.write_text(json.dumps({**manifest, "checked_at": _now()}), encoding="utf-8")
        os.replace(tmp, self.root / MANIFEST)

    def _latest(self) -> tuple[dict, dict] | None:
        tags = sorted((r for r in self.releases.list_releases() if r["tag_name"].startswith(PREFIX)),
                      key=lambda r: r["tag_name"], reverse=True)
        for release in tags:
            assets = {a["name"]: a for a in self.releases.assets(release)}
            if MANIFEST in assets and PACKED in assets:
                tmp = self._tmp("remote-manifest.json")
                try:
                    self.releases.download_asset(assets[MANIFEST], tmp)
                    manifest = json.loads(tmp.read_text(encoding="utf-8"))
                finally:
                    tmp.unlink(missing_ok=True)
                return {**manifest, "tag": release["tag_name"]}, assets[PACKED]
        return None

    def update(self, force: bool = False) -> str:
        found = self._latest()
        if found is None:
            return "no snapshot is published yet"
        manifest, asset = found
        local = self.local_manifest()
        if local and local.get("sha256") == manifest["sha256"] and not force:
            self._remember(local)
            return f"up to date ({local['built_at']})"

        def refuse(reason: str) -> str:
            # Remember the check, so a refused file is not downloaded again on every start.
            if local:
                self._remember(local)
                return f"kept the current file: {reason}"
            return f"no snapshot installed: {reason}"

        if _major(manifest["schema_version"]) != SCHEMA_MAJOR:
            return refuse(f"the new snapshot needs a newer mergescout (schema {manifest['schema_version']})")
        packed, fresh = self._tmp(PACKED + ".part"), self._tmp(SNAPSHOT + ".new")
        try:
            self.releases.download_asset(asset, packed)
            if sha256(packed) != manifest["sha256"]:
                return refuse("the download did not match its checksum")
            with packed.open("rb") as fi, fresh.open("wb") as fo:
                zstandard.ZstdDecompressor().copy_stream(fi, fo)
            db = sqlite3.connect(fresh)
            ok = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            version = dict(db.execute("SELECT key, value FROM meta").fetchall()).get("schema_version", "0")
            db.close()
            if not ok or _major(version) != SCHEMA_MAJOR:
                return refuse("the new snapshot failed its check")
            try:
                os.replace(fresh, self.path)
            except PermissionError:
                return refuse("it is in use; restart your AI tool to load the new one")
            self._remember(manifest)
            return f"updated to {manifest['built_at']}"
        finally:
            packed.unlink(missing_ok=True)
            fresh.unlink(missing_ok=True)

    def ensure(self, max_age_hours: float = 24, log=print) -> Path | None:
        local = self.local_manifest()
        stamp = (local or {}).get("checked_at")
        checked = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None
        if checked is None or (datetime.now(timezone.utc) - checked).total_seconds() / 3600 >= max_age_hours:
            try:
                log(self.update())
            except Exception as exc:  # noqa: BLE001 - any failure keeps the last good file
                log(f"could not check for a new snapshot: {exc}")
        return self.path if self.path.exists() else None
