"""Pre-launch audit: with the public home set before the repo is public, a 404 or unreachable benchmark file must just
leave the comparison out (no failure, no warning), and a token still reads the private store as before."""
import json

import httpx

from stackvitals.ci import bench

Q = {"p10": 1, "p25": 2, "p50": 3, "p75": 4, "p90": 5}
GOOD = {"groups": {"all|all": {"repos": 30, "median_s": Q, "first_try_share": Q}}}


def test_the_public_home_points_at_the_launch_repo():
    assert bench.PUBLIC_HOME == "stackvitals/stackvitals" and bench.BENCH_REPO == "kaushik-yadav/merge-scout"
    assert bench.DEFAULT_URL == "https://github.com/stackvitals/stackvitals/releases/download/bench-latest/ci-benchmarks.json"
    assert bench.SHARED_URL.endswith("/bench-latest/shared-benchmarks.json")


def test_a_missing_or_unreachable_public_file_skips_quietly(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("STACKVITALS_BENCH_URL", raising=False)

    def down(request):
        raise httpx.ConnectError("no route", request=request)
    for transport in (httpx.MockTransport(lambda r: httpx.Response(404, text="Not Found")), httpx.MockTransport(down)):
        assert bench.load(None, tmp_path / "c", client=httpx.Client(transport=transport)) is None
    assert not (tmp_path / "c" / "ci-benchmarks.json").exists()
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_with_a_token_a_missing_public_file_falls_back_to_the_private_store(tmp_path, monkeypatch):
    monkeypatch.delenv("STACKVITALS_BENCH_URL", raising=False)
    asked = []

    def handle(request):
        asked.append(request.url.host + request.url.path)
        if request.url.host == "github.com":
            return httpx.Response(404)
        if request.url.path.endswith("/releases/tags/bench-latest"):
            return httpx.Response(200, json={"id": 1, "tag_name": "bench-latest"})
        if request.url.path.endswith("/releases/1/assets"):
            return httpx.Response(200, json=[{"name": "ci-benchmarks.json", "id": 9}])
        if request.url.path.endswith("/releases/assets/9"):
            return httpx.Response(200, content=json.dumps(GOOD).encode())
        return httpx.Response(404)
    got = bench.load("tok", tmp_path, client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert got and got["groups"]["all|all"]["repos"] == 30
    assert asked[0].startswith("github.com/stackvitals/stackvitals/") and any("merge-scout" in a for a in asked[1:])


def test_a_published_public_file_is_used_and_cached(tmp_path, monkeypatch):
    monkeypatch.delenv("STACKVITALS_BENCH_URL", raising=False)
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=GOOD)))
    assert bench.load(None, tmp_path, client=ok)["groups"]["all|all"]["repos"] == 30
    assert (tmp_path / "ci-benchmarks.json").exists()


def test_an_explicit_url_that_fails_does_not_fall_back(tmp_path, monkeypatch):
    monkeypatch.setenv("STACKVITALS_BENCH_URL", "https://example.invalid/b.json")
    hosts = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: hosts.append(r.url.host) or httpx.Response(500)))
    assert bench.load("tok", tmp_path, client=client) is None and hosts == ["example.invalid"]
