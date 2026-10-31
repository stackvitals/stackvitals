import json
from datetime import datetime, timedelta, timezone

import httpx

from stackvitals.ci import bench
from stackvitals.ci.report import render_html, render_markdown, render_text

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def rec(rid, att, sha, secs, c="success", ev="push", path=".github/workflows/ci.yml", hours=1):
    cr = NOW - timedelta(hours=hours)
    return {"t": "run", "id": rid, "att": att, "path": path, "ev": ev, "br": "main", "sha": sha, "c": c,
            "cr": iso(cr), "st": iso(cr), "up": iso(cr + timedelta(seconds=secs))}


def test_push_stats_from_stored_runs_match_the_sampler_definition():
    runs = []
    for k in range(6):
        runs += [rec(k * 10, 1, f"s{k}", 600, hours=k + 1), rec(k * 10 + 1, 1, f"s{k}", 60, path="lint.yml", hours=k + 1)]
    # A re-run: attempt 1 failed, attempt 2 passed; only the final attempt counts, as in GitHub's run list.
    runs += [rec(90, 1, "s9", 300, "failure", hours=20), rec(90, 2, "s9", 900, hours=20)]
    runs += [rec(91, 1, "pr", 50, ev="pull_request")]
    s = bench.push_stats({"runs": runs}, NOW, 30)
    assert s["pushes"] == 7 and s["median_s"] == 600 and s["rerun_share"] == round(1 / 7, 4)
    assert s["first_try_share"] == round(6 / 7, 4) and s["workflows"] == 2


BENCH = {"version": 1, "repos": 900, "definition": "per push", "groups": {
    "Python|all": {"repos": 412, "median_s": {"p10": 100, "p25": 200, "p50": 300, "p75": 400, "p90": 500},
                   "first_try_share": {"p10": 0.5, "p25": 0.7, "p50": 0.85, "p75": 0.95, "p90": 1.0}},
    "all|all": {"repos": 900, "median_s": {"p10": 50, "p25": 90, "p50": 150, "p75": 300, "p90": 600},
                "first_try_share": {"p10": 0.4, "p25": 0.6, "p50": 0.8, "p75": 0.9, "p90": 1.0}}}}


def test_compare_uses_the_closest_group_with_enough_repos_and_places_you():
    you = {"pushes": 20, "median_s": 450, "p90_s": 900, "first_try_share": 0.6, "fail_share": 0.3, "rerun_share": 0.1}
    c = bench.compare(you, BENCH, "Python", 3000)
    assert c["group"] == "Python repos" and c["repos"] == 412
    time, green = c["metrics"]
    assert time["you"] == 450 and time["typical"] == 300 and time["place"] == "slower than about 80%"
    assert green["you"] == 0.6 and green["typical"] == 0.85 and green["place"] == "below about 80%"
    assert bench.compare(you, BENCH, "Haskell", 50)["group"] == "public repos we track"
    assert bench.compare(None, BENCH, "Python", 3000) is None and bench.compare(you, None, "Python", 1) is None


def test_benchmarks_load_from_a_url_or_file_and_never_break_a_run(tmp_path, monkeypatch):
    path = tmp_path / "b.json"
    path.write_text(json.dumps(BENCH), encoding="utf-8")
    monkeypatch.setenv("STACKVITALS_BENCH_URL", str(path))
    assert bench.load(None, tmp_path / "cache")["repos"] == 900
    monkeypatch.setenv("STACKVITALS_BENCH_URL", "https://example.invalid/b.json")
    broken = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert bench.load(None, tmp_path / "cache2", client=broken) is None
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=BENCH)))
    assert bench.load(None, tmp_path / "cache3", client=ok)["repos"] == 900


def test_badge_shows_first_try_green_pushes():
    assert bench.badge({"first_try_share": 0.934, "pushes": 40}) == {
        "schemaVersion": 1, "label": "CI first try", "message": "93%", "color": "brightgreen"}
    assert bench.badge({"first_try_share": 0.6, "pushes": 40})["color"] == "orange"
    assert bench.badge(None) == {"schemaVersion": 1, "label": "CI first try", "message": "no data", "color": "lightgrey"}


def test_reports_show_how_the_repo_compares():
    you = {"pushes": 20, "median_s": 450, "p90_s": 900, "first_try_share": 0.6, "fail_share": 0.3, "rerun_share": 0.1}
    result = {"window_days": 30, "generated": iso(NOW), "runs": 40, "rerun_share": 0.1, "infra_events": 0,
              "queue": {"median_s": 5, "p95_s": 20}, "minutes": {"linux": 10, "windows": 0, "macos": 0, "other": 0},
              "jobs": [], "tests": [], "slow_tests": [], "test_outages": [], "has_test_reports": False,
              "pushes": you, "benchmark": bench.compare(you, BENCH, "Python", 3000)}
    for text in (render_text(result, "o/r"), render_markdown(result, "o/r"), render_html(result, "o/r")):
        assert "412 Python repos" in text and "7m 30s" in text and "slower than about 80%" in text


def test_without_a_source_or_token_nothing_is_fetched(tmp_path, monkeypatch):
    monkeypatch.delenv("STACKVITALS_BENCH_URL", raising=False)

    def no_network(request):
        raise AssertionError(f"unexpected request to {request.url}")
    # With no public home set (default_url=None) and no token, nothing is asked.
    assert bench.load(None, tmp_path, client=httpx.Client(transport=httpx.MockTransport(no_network)), default_url=None) is None
    monkeypatch.setattr(bench.httpx, "Client", lambda *a, **k: httpx.Client(transport=httpx.MockTransport(no_network)))
    assert bench.load(None, tmp_path / "x", default_url=None) is None
