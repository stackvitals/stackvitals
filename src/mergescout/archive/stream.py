import zlib
from collections.abc import Iterable, Iterator
from datetime import date

import httpx
import orjson

ARCHIVE_BASE = "https://data.gharchive.org"


class ArchiveStreamError(Exception):
    pass


def normalize_hour_key(key: str) -> str:
    parts = key.split("-")
    if len(parts) != 4:
        raise ValueError(f"Hour key must look like 2026-10-01-15, got {key!r}")
    try:
        day = date(int(parts[0]), int(parts[1]), int(parts[2]))
        hour = int(parts[3])
    except ValueError as exc:
        raise ValueError(f"Hour key must look like 2026-10-01-15, got {key!r}") from exc
    if not 0 <= hour <= 23:
        raise ValueError(f"Hour must be 0-23, got {hour}")
    return f"{day.isoformat()}-{hour}"


def parse_hour_key(key: str) -> tuple[str, int]:
    norm = normalize_hour_key(key)
    day, hour = norm.rsplit("-", 1)
    return day, int(hour)


def hour_url(key: str) -> str:
    return f"{ARCHIVE_BASE}/{normalize_hour_key(key)}.json.gz"


def fetch_chunks(url: str, client: httpx.Client | None = None, chunk_size: int = 1 << 20) -> Iterator[bytes]:
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True)
    try:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            # Raw bytes, so httpx never tries to unzip for us.
            yield from resp.iter_raw(chunk_size)
    finally:
        if own:
            client.close()


def iter_lines(chunks: Iterable[bytes]) -> Iterator[bytes]:
    decomp = zlib.decompressobj(zlib.MAX_WBITS | 16)
    buffer = b""
    try:
        for chunk in chunks:
            data = decomp.decompress(chunk)
            # A file can hold several gzip parts back to back.
            while decomp.unused_data:
                leftover = decomp.unused_data
                decomp = zlib.decompressobj(zlib.MAX_WBITS | 16)
                data += decomp.decompress(leftover)
            buffer += data
            *lines, buffer = buffer.split(b"\n")
            yield from (line for line in lines if line)
        buffer += decomp.flush()
    except zlib.error as exc:
        raise ArchiveStreamError(f"Archive file is corrupt: {exc}") from exc
    if not decomp.eof:
        raise ArchiveStreamError("Archive file ended early (download cut off).")
    if buffer.strip():
        yield buffer


def iter_events(chunks: Iterable[bytes], stats: dict) -> Iterator[dict]:
    for line in iter_lines(chunks):
        try:
            event = orjson.loads(line)
        except orjson.JSONDecodeError:
            stats["bad_lines"] += 1
            continue
        stats["events_in"] += 1
        yield event
