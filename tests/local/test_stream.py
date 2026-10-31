import gzip

import pytest

from mergescout.archive.stream import (
    ArchiveStreamError, hour_url, iter_events, iter_lines, normalize_hour_key, parse_hour_key,
)


def chunked(data, size):
    for i in range(0, len(data), size):
        yield data[i:i + size]


def test_lines_survive_chunk_boundaries(make_gz):
    data = make_gz([{"a": i} for i in range(50)])
    lines = list(iter_lines(chunked(data, 7)))
    assert len(lines) == 50 and lines[0] == b'{"a":0}'


def test_multi_member_gzip():
    data = gzip.compress(b'{"a":1}\n') + gzip.compress(b'{"a":2}\n')
    assert list(iter_lines(chunked(data, 5))) == [b'{"a":1}', b'{"a":2}']


def test_truncated_stream_raises(make_gz):
    data = make_gz([{"a": i} for i in range(50)])
    with pytest.raises(ArchiveStreamError):
        list(iter_lines(chunked(data[:-12], 64)))


def test_corrupt_bytes_raise():
    with pytest.raises(ArchiveStreamError):
        list(iter_lines([b"this is not gzip at all"]))


def test_bad_json_lines_are_counted_and_skipped(make_gz):
    data = make_gz([{"type": "IssuesEvent"}], extra_lines=["{broken"])
    stats = {"events_in": 0, "bad_lines": 0}
    events = list(iter_events(chunked(data, 16), stats))
    assert events == [{"type": "IssuesEvent"}]
    assert stats == {"events_in": 1, "bad_lines": 1}


def test_hour_keys_and_urls():
    assert normalize_hour_key("2026-10-01-05") == "2026-10-01-5"
    assert parse_hour_key("2026-10-01-15") == ("2026-10-01", 15)
    assert hour_url("2026-10-01-05") == "https://data.gharchive.org/2026-10-01-5.json.gz"
    for bad in ("2026-10-01-24", "2026-13-01-1", "2026-10-01", "yesterday"):
        with pytest.raises(ValueError):
            normalize_hour_key(bad)
