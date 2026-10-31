"""A crawl's upload waits for the hourly reset when the account's REST limit is used up, instead of losing the hour's
work (real failure, 2026-10-20 17:27: 'API rate limit exceeded' on uploading crawl.sqlite.gz)."""
import httpx
import pytest

from mergescout.github.releases import ReleaseError, Releases

NOW = 1_800_000_000.0


def make(responses, slept, max_wait=600):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path.endswith("/tags/crawl-state"):
            return httpx.Response(200, json={"id": 1})
        if request.method == "GET" and request.url.path.endswith("/assets"):
            return httpx.Response(200, json=[])
        return responses.pop(0)
    rel = Releases("tok", "o/store", client=httpx.Client(transport=httpx.MockTransport(handler)),
                   sleep=slept.append, clock=lambda: NOW, max_wait=max_wait)
    return rel, calls


def limited(reset_in):
    return httpx.Response(403, json={"message": "API rate limit exceeded for user ID 1."},
                          headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(NOW + reset_in))})


def test_an_upload_waits_for_the_reset_and_tries_again(tmp_path):
    f = tmp_path / "crawl.sqlite.gz"
    f.write_bytes(b"data")
    slept = []
    rel, calls = make([limited(120), httpx.Response(201, json={"id": 9, "name": "crawl.sqlite.gz"})], slept)
    assert rel.upload("crawl-state", f)["id"] == 9
    assert slept == [125] and sum(1 for c in calls if c[0] == "POST") == 2


def test_a_reset_too_far_away_or_another_error_fails_at_once(tmp_path):
    f = tmp_path / "crawl.sqlite.gz"
    f.write_bytes(b"data")
    slept = []
    rel, _ = make([limited(3000)], slept)
    with pytest.raises(ReleaseError, match="rate limit"):
        rel.upload("crawl-state", f)
    assert slept == []
    rel, _ = make([httpx.Response(422, json={"message": "bad"})], slept)
    with pytest.raises(ReleaseError, match="422"):
        rel.upload("crawl-state", f)
