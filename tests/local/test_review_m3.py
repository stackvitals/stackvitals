import random
from datetime import datetime, timedelta, timezone

import duckdb

from mergescout.signals.triage import _held_out, training_rows

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def table(rows):
    con = duckdb.connect()
    con.execute("""CREATE TABLE pr_class (repo_id BIGINT, number INT, created_at TIMESTAMPTZ, merged_at TIMESTAMPTZ,
        author_login VARCHAR, author_class VARCHAR, author_association VARCHAR, additions INT, deletions INT,
        closing_issue_numbers INT[])""")
    con.executemany("INSERT INTO pr_class VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    return con


def day(d):
    return NOW - timedelta(days=d)


def test_first_timer_comes_from_history_not_from_githubs_association_at_fetch_time():
    # Review finding: GitHub reports the association when asked, so a merged first-timer reads CONTRIBUTOR.
    rows = [[1, 1, day(100), day(99), "ann", "outsider", "CONTRIBUTOR", 5, 0, []],
            [1, 2, day(60), day(59), "ann", "outsider", "CONTRIBUTOR", 5, 0, []],
            [1, 3, day(90), None, "bob", "outsider", "FIRST_TIME_CONTRIBUTOR", 5, 0, []]]
    out = {r["number"]: r for r in training_rows(table(rows), NOW)}
    assert out[1]["first_timer"] is True and out[2]["first_timer"] is False and out[3]["first_timer"] is True


def test_the_repo_rate_uses_only_earlier_prs_whose_outcome_was_known_never_the_pr_itself():
    # Review finding: leave-one-out split labels across bucket edges and used later PRs; live scoring uses only the past.
    rows = [[1, k, day(400 - k * 10), day(399 - k * 10) if k % 2 else None, f"u{k}", "outsider", "NONE", 5, 0, []]
            for k in range(30)]
    out = {r["number"]: r for r in training_rows(table(rows), NOW)}
    # PR 25 opened 150 days ago: PRs opened 180+ days ago (k 0-22) had known outcomes, 11 of 23 merged.
    assert abs(out[25]["repo_rate"] - 11 / 23) < 1e-9 and abs(out[24]["repo_rate"] - 11 / 22) < 1e-9


def test_the_held_out_split_really_mixes_repo_ids():
    held = [r for r in range(1000) if _held_out(r)]
    assert 150 < len(held) < 250 and held[:5] != [0, 5, 10, 15, 20]


def mpr(n, paths, days=10, lines=40, au="dana", files=None):
    when = (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"t": "pr", "n": n, "st": "MERGED", "cr": when, "mg": when, "cl": when, "au": au, "at": "User", "as": "MEMBER",
            "rq": [], "ev": [], "cm": [], "paths": paths, "add": lines, "del": 0, "files": files or len(paths)}


def test_reading_review_comments_survives_github_errors_and_keeps_what_it_read(tmp_path):
    from mergescout.github.graphql import GraphQLError, GraphQLResult
    from stackvitals.flow.preflight import collect_asks
    from stackvitals.flow.store import FlowStore

    class Flaky:
        calls = 0

        def query(self, query, variables=None, **kw):
            Flaky.calls += 1
            if Flaky.calls > 1:
                raise GraphQLError("rate limited")
            data = {"rateLimit": {"cost": 1, "remaining": 1, "resetAt": "x"}, "repository": {}}
            return GraphQLResult(data=data, cost=1, remaining=1, reset_at="x")
    prs = [mpr(n, ["a.py"]) | {"ev": [["review", "2026-01-01T00:00:00Z", "bob", "COMMENTED", "MEMBER", "User"]]} for n in range(1, 5)]
    store = FlowStore(tmp_path)
    out = collect_asks(Flaky(), store, "o", "r", prs, batch=2)
    assert out["read"] == 2 and sorted(store.asks()) == [3, 4] or sorted(store.asks()) == [1, 2]


def test_the_preflight_note_cannot_mention_people_and_names_only_folders_with_history():
    from stackvitals.flow.action import _preflight_targets
    merged = [mpr(n, ["src/core/a.py", "tests/test_a.py"]) for n in range(1, 13)]
    evil = {"t": "pr", "n": 99, "ti": "x", "draft": False, "st": "OPEN", "cr": "2026-10-17T11:00:00Z", "up": "2026-10-17T11:00:00Z",
            "au": "zed", "at": "User", "as": "NONE", "rq": [], "ev": [], "cm": [], "add": 5, "del": 0,
            "paths": ["src/core/b.py", "x/@victim/y.py", "www.evil.example/z.py"]}
    notes = _preflight_targets({"open": [evil], "closed": merged}, "2026-10-17T10:00:00Z", set(), NOW)
    body = notes[0][1]
    assert "@victim" not in body and "www.evil" not in body and "src/core" in body


def test_building_the_report_stays_fast_on_a_big_repo():
    import time

    from stackvitals.flow.build import build
    rng = random.Random(1)
    merged = [mpr(n, [f"pkg{rng.randrange(40)}/m{rng.randrange(20)}/f.py", "tests/t.py"], days=rng.randrange(300)) for n in range(8000)]
    opened = [{"t": "pr", "n": 10000 + k, "ti": "x", "draft": False, "st": "OPEN", "cr": "2026-10-10T00:00:00Z",
               "up": "2026-10-10T00:00:00Z", "au": f"u{k}", "at": "User", "as": "NONE", "rq": [], "ev": [], "cm": [], "add": 5,
               "del": 0, "ci": "SUCCESS", "paths": [f"pkg{k % 40}/m1/x.py"]} for k in range(400)]
    t = time.time()
    build({"open": opened, "closed": merged}, {}, NOW, owner="o")
    assert time.time() - t < 5


def test_prs_with_more_files_than_were_read_are_not_told_they_have_none():
    from stackvitals.flow.preflight import gaps, norms
    habits = norms([mpr(n, ["src/a.py", "tests/t.py"]) for n in range(12)], ["src/b.py"], NOW)
    assert gaps({"paths": ["src/b.py"], "files": 300, "add": 5, "del": 0}, habits) == []


def test_a_bad_line_in_the_asks_file_is_skipped(tmp_path):
    from stackvitals.flow.preflight import load_asks
    f = tmp_path / "asks.ndjson"
    f.write_text('{"n": 1, "a": []}\n{"n": 2, "a": [["te\n', encoding="utf-8")
    assert load_asks(f) == {1: []}


def test_a_failing_benchmark_or_triage_step_never_stops_the_daily_snapshot(tmp_path, monkeypatch):
    import mergescout.signals.flow_bench as fb
    from mergescout.snapshot.__main__ import write_extras

    def boom(*a, **k):
        raise RuntimeError("bad crawl batch")
    monkeypatch.setattr(fb, "flow_benchmarks", boom)
    said = []
    write_extras(duckdb.connect(), tmp_path, NOW, log=said.append)
    assert any("flow benchmarks skipped" in s for s in said) and not (tmp_path / "flow-benchmarks.json").exists()
