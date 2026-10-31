import hashlib
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from mergescout.archive.events import SCHEMA, slim_event
from mergescout.archive.manifest import Manifest
from mergescout.archive.stream import fetch_chunks, hour_url, iter_events, normalize_hour_key, parse_hour_key


@dataclass
class HourResult:
    hour_key: str
    status: str
    events_in: int = 0
    events_kept: int = 0
    bad_lines: int = 0
    bytes_out: int = 0
    path: Path | None = None


def hour_path(data_dir: Path, key: str) -> Path:
    day, hour = parse_hour_key(key)
    return data_dir / "bronze" / f"date={day}" / f"hour={hour}.parquet"


def write_parquet(rows: Iterable[dict], out_path: Path, batch_size: int = 50_000) -> int:
    # Write to a .part file first so a crash never leaves a half file that looks finished.
    part = out_path.with_name(out_path.name + ".part")
    written = 0
    try:
        with pq.ParquetWriter(part, SCHEMA, compression="zstd") as writer:
            batch = []
            for row in rows:
                batch.append(row)
                if len(batch) >= batch_size:
                    writer.write_table(pa.Table.from_pylist(batch, schema=SCHEMA))
                    written += len(batch)
                    batch = []
            if batch:
                writer.write_table(pa.Table.from_pylist(batch, schema=SCHEMA))
                written += len(batch)
        os.replace(part, out_path)
    finally:
        if part.exists():
            part.unlink()
    return written


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def convert_hour(
    key: str,
    data_dir: Path,
    manifest: Manifest,
    chunks_factory: Callable[[str], Iterable[bytes]] = fetch_chunks,
) -> HourResult:
    key = normalize_hour_key(key)
    if manifest.is_done(key):
        return HourResult(key, "skipped")
    out = hour_path(data_dir, key)
    out.parent.mkdir(parents=True, exist_ok=True)
    stats = {"events_in": 0, "bad_lines": 0}
    try:
        events = iter_events(chunks_factory(hour_url(key)), stats)
        kept = write_parquet((row for row in map(slim_event, events) if row is not None), out)
    except Exception as exc:
        manifest.mark_failed(key, f"{type(exc).__name__}: {exc}")
        raise
    size = out.stat().st_size
    manifest.mark_done(key, events_in=stats["events_in"], events_kept=kept,
                       bad_lines=stats["bad_lines"], bytes_out=size, sha256=_sha256(out))
    return HourResult(key, "done", stats["events_in"], kept, stats["bad_lines"], size, out)
