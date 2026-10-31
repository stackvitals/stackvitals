from datetime import datetime, timedelta, timezone

import httpx

from mergescout.bench.ci import TokenPool, aggregate, fetch_all, repo_stats, todays_share

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def run(k, secs, conclusion="success", attempt=1, path=".github/workflows/ci.yml", days_ago=1, sha=None, wait=0,
        status="completed"):
    created = NOW - timedelta(days=days_ago, hours=k)
    start = created + timedelta(seconds=wait)
    return {"id": k * 100 + len(path), "head_sha": sha or f"s{k}", "path": path, "conclusion": conclusion,
            "run_attempt": attempt, "status": status, "created_at": iso(created), "run_started_at": iso(start),
            "updated_at": iso(start + timedelta(seconds=secs))}


def test_repo_stats_measure_each_push_until_all_its_checks_finish():
    lint = ".github/workflows/lint.yml"
    runs = []
    for k in range(8):
        runs += [run(k, 280 + k * 10, wait=20), run(k, 15, path=lint)]
    runs += [run(20, 900, "failure"), run(20, 30, path=lint), run(21, 400, attempt=2),
             run(22, 50, "failure", path="dynamic/dependabot/x"), run(23, 5000, "failure", days_ago=40),
             run(24, 60, status="in_progress"), run(24, 10, path=lint), run(25, 60, "cancelled")]
    s = repo_stats(runs, since=NOW - timedelta(days=30))
    # 10 pushes: 8 green, 1 failed, 1 re-run; waits are queue plus run, re-run pushes are left out of them.
    assert s["pushes"] == 10 and s["median_s"] == 340 and s["fail_share"] == 0.1
    assert s["first_try_share"] == 0.8 and s["rerun_share"] == 0.1 and s["workflows"] == 2
    assert repo_stats(runs[:8]) is None


def test_a_full_page_drops_its_oldest_push_which_may_be_cut_off():
    runs = [run(k, 300) for k in range(6)]
    assert repo_stats(runs)["pushes"] == 6 and repo_stats(runs, page_full=True)["pushes"] == 5


def test_four_weeks_of_daily_shares_cover_every_repo_once():
    names = [f"o/r{i}" for i in range(2800)]
    seen = []
    for d in range(28):
        seen += todays_share(names, NOW + timedelta(days=d))
    assert sorted(seen) == sorted(names)


def test_fetch_asks_for_a_light_page_without_slow_filters():
    pool, calls = pool_for({})
    seen = []
    pool.client = httpx.Client(transport=httpx.MockTransport(
        lambda req: seen.append(dict(req.url.params)) or httpx.Response(200, json={"workflow_runs": []})))
    fetch_all(pool, [{"name": "o/a", "language": "Go", "stars": 500}], NOW)
    assert seen == [{"event": "push", "per_page": "50", "exclude_pull_requests": "true"}]


def pool_for(answers, remaining="4000"):
    calls = []

    def handler(request):
        calls.append((request.headers["authorization"], request.url.path))
        repo = request.url.path.split("/repos/")[1].split("/actions")[0]
        status, body = answers.get(repo, (200, {"workflow_runs": [run(k, 300) for k in range(6)]}))
        return httpx.Response(status, json=body, headers={"x-ratelimit-remaining": remaining})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TokenPool(["tok-a", "tok-b"], client=client, reserve=100), calls


def test_fetch_skips_repos_without_actions_and_keeps_the_rest():
    pool, calls = pool_for({"o/gone": (404, {"message": "Not Found"}), "o/off": (403, {"message": "Actions disabled"})})
    out = fetch_all(pool, [{"name": n, "language": "Go", "stars": 500} for n in ("o/a", "o/gone", "o/off")], NOW)
    assert [r["repo"] for r in out["records"]] == ["o/a"] and out["records"][0]["language"] == "Go"
    assert out["complete"]


def test_fetch_moves_to_the_next_token_and_stops_when_all_are_low():
    pool, calls = pool_for({}, remaining="50")
    out = fetch_all(pool, [{"name": f"o/r{i}", "language": "Go", "stars": 500} for i in range(5)], NOW, workers=1)
    assert not out["complete"] and {c[0] for c in calls} == {"Bearer tok-a", "Bearer tok-b"}


def test_aggregates_group_by_language_and_size_with_enough_repos():
    recs = [{"repo": f"o/p{i}", "language": "Python", "stars": 500, "median_s": 100 + i, "p90_s": 200,
             "fail_share": 0.1, "first_try_share": 0.9, "rerun_share": 0.02, "pushes": 20} for i in range(25)]
    recs += [{"repo": f"o/g{i}", "language": "Go", "stars": 50_000, "median_s": 900, "p90_s": 990,
              "fail_share": 0.2, "first_try_share": 0.7, "rerun_share": 0.05, "pushes": 20} for i in range(5)]
    agg = aggregate(recs, NOW)
    py = agg["groups"]["Python|100-1k"]
    assert py["repos"] == 25 and py["median_s"]["p50"] == 112 and py["median_s"]["p25"] == 106
    assert "Go|10k+" not in agg["groups"] and agg["groups"]["all|all"]["repos"] == 30


def test_pool_waits_for_the_hourly_reset_when_allowed():
    slept, calls = [], []

    def handler(request):
        calls.append(1)
        left = "50" if len(calls) == 1 else "4000"
        return httpx.Response(200, json={"workflow_runs": [run(k, 300) for k in range(6)]},
                              headers={"x-ratelimit-remaining": left, "x-ratelimit-reset": "1300"})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    pool = TokenPool(["tok-a"], client=client, reserve=100, sleep=slept.append, clock=lambda: 1000, max_wait=900)
    out = fetch_all(pool, [{"name": f"o/r{i}", "language": "Go", "stars": 500} for i in range(3)], NOW, workers=1)
    assert out["complete"] and len(out["records"]) == 3 and slept == [305]
    pool = TokenPool(["tok-a"], client=client, reserve=100, sleep=slept.append, clock=lambda: 1000, max_wait=60)
    calls.clear()
    assert not fetch_all(pool, [{"name": f"o/r{i}", "language": "Go", "stars": 500} for i in range(3)], NOW,
                         workers=1)["complete"]


def write_basics(folder, rows):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from mergescout.discover.sweep import SCHEMA
    folder.mkdir(parents=True, exist_ok=True)
    full = [{f.name: None for f in SCHEMA} | r for r in rows]
    pq.write_table(pa.Table.from_pylist(full, schema=SCHEMA), folder / "part.parquet")


def test_repo_list_keeps_recently_pushed_repos_once(tmp_path):
    from mergescout.bench.__main__ import load_repos
    recent, old = NOW - timedelta(days=3), NOW - timedelta(days=60)
    write_basics(tmp_path / "a", [{"repo_id": 1, "name": "o/a", "stars": 500, "language": "Go", "pushed_at": recent},
                                  {"repo_id": 2, "name": "o/old", "stars": 900, "language": "Go", "pushed_at": old},
                                  {"repo_id": 3, "name": "o/tiny", "stars": 20, "language": "Go", "pushed_at": recent}])
    write_basics(tmp_path / "b", [{"repo_id": 1, "name": "o/a", "stars": 510, "language": "Go", "pushed_at": recent}])
    assert load_repos(tmp_path, NOW) == [{"name": "o/a", "language": "Go", "stars": 510}]


class FakeReleases:
    def __init__(self, files=None):
        self.files = dict(files or {})

    def upload(self, tag, path, name=None):
        self.files[(tag, name or path.name)] = path.read_bytes()

    def get(self, tag):
        return {"tag_name": tag} if any(t == tag for t, _ in self.files) else None

    def assets(self, release):
        return [{"name": n, "tag": t} for t, n in self.files if t == release["tag_name"]]

    def download_asset(self, asset, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.files[(asset["tag"], asset["name"])])


def daily_gz(records):
    import gzip
    import json
    return gzip.compress("".join(json.dumps(r) + "\n" for r in records).encode())


def test_daily_run_stores_todays_sample_and_rebuilds_benchmarks_from_recent_days(tmp_path):
    import gzip
    import json

    from mergescout.bench.__main__ import publish
    rec = lambda i, day, m: {"repo": f"o/p{i}", "language": "Python", "stars": 500, "median_s": m, "p90_s": m,
                             "fail_share": 0.1, "first_try_share": 0.9, "rerun_share": 0.0, "pushes": 10, "day": day}
    old = [rec(i, "2026-10-09", 100) for i in range(15)] + [rec(99, "2026-08-01", 5)]
    rel = FakeReleases({("bench-2026-W41", "ci-2026-10-09.ndjson.gz"): daily_gz(old[:15]),
                        ("bench-2026-W31", "ci-2026-08-01.ndjson.gz"): daily_gz(old[15:])})
    today = [rec(i, "2026-10-16", 200) for i in range(10, 25)]
    publish(tmp_path, rel, today, NOW, log=lambda m: None)
    stored = gzip.decompress(rel.files[("bench-2026-W42", "ci-2026-10-16.ndjson.gz")]).decode().splitlines()
    assert len(stored) == 15
    agg = json.loads(rel.files[("bench-latest", "ci-benchmarks.json")])
    # 25 repos: 10 seen only last week, 15 re-read today (their newest numbers win); August is too old.
    assert agg["groups"]["Python|100-1k"]["repos"] == 25 and agg["groups"]["Python|100-1k"]["median_s"]["p50"] == 200


def test_a_token_that_cannot_read_other_repos_drops_out_instead_of_the_repos():
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])
        if request.headers["authorization"] == "Bearer tok-app":
            return httpx.Response(403, json={"message": "Resource not accessible by integration"},
                                  headers={"x-ratelimit-remaining": "4999"})
        return httpx.Response(200, json={"workflow_runs": [run(k, 300) for k in range(6)]},
                              headers={"x-ratelimit-remaining": "3000"})
    pool = TokenPool(["tok-app", "tok-pat"], client=httpx.Client(transport=httpx.MockTransport(handler)), reserve=100)
    out = fetch_all(pool, [{"name": f"o/r{i}", "language": "Go", "stars": 500} for i in range(4)], NOW, workers=1)
    assert len(out["records"]) == 4 and seen.count("Bearer tok-app") == 1


def test_a_repo_that_hit_a_used_up_token_is_read_again_with_another():
    def handler(request):
        if request.headers["authorization"] == "Bearer tok-a":
            return httpx.Response(403, json={"message": "API rate limit exceeded"}, headers={"x-ratelimit-remaining": "0"})
        return httpx.Response(200, json={"workflow_runs": [run(k, 300) for k in range(6)]},
                              headers={"x-ratelimit-remaining": "3000"})
    pool = TokenPool(["tok-a", "tok-b"], client=httpx.Client(transport=httpx.MockTransport(handler)), reserve=100)
    out = fetch_all(pool, [{"name": f"o/r{i}", "language": "Go", "stars": 500} for i in range(3)], NOW, workers=1)
    assert len(out["records"]) == 3


def test_crawler_copy_carries_the_sampler_and_never_mentions_the_suite(tmp_path):
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("sync_crawler", root / "scripts" / "sync_crawler.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    copied = sync.build(tmp_path)
    assert "src/mergescout/bench" in copied and ".github/workflows/bench.yml" in copied
    assert "tests/test_flow_bench.py" in copied
    leaks = [p for p in tmp_path.rglob("*") if p.is_file() and ".git" not in p.parts
             and "stackvitals" in p.read_bytes().decode("utf-8", "ignore").lower()]
    assert leaks == []
