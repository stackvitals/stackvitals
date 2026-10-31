from datetime import datetime, timedelta, timezone

import duckdb

from mergescout.signals.deps_trends import repo_trends

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def con_with(prs, people, repos):
    con = duckdb.connect()
    con.execute("""CREATE TABLE pr_class (repo_id BIGINT, number INT, created_at TIMESTAMPTZ, merged_at TIMESTAMPTZ, state VARCHAR,
        author_class VARCHAR, merged_by VARCHAR, first_human_review_at TIMESTAMPTZ, first_human_review_by VARCHAR)""")
    if prs:
        con.executemany("INSERT INTO pr_class VALUES (?,?,?,?,?,?,?,?,?)", prs)
    con.execute("CREATE TABLE people (repo_id BIGINT, login VARCHAR, kind VARCHAR)")
    if people:
        con.executemany("INSERT INTO people VALUES (?,?,?)", people)
    con.execute("CREATE TABLE repo_meta (repo_id BIGINT, name VARCHAR, stars INT)")
    con.executemany("INSERT INTO repo_meta VALUES (?,?,?)", repos)
    return con


def quarter_prs(repo, start_day, merged_share, response_h, merger, n=10, first=0):
    rows = []
    for k in range(n):
        created = NOW - timedelta(days=start_day - k)
        merged = k < merged_share * n
        rows.append([repo, first + k, created, created + timedelta(hours=30) if merged else None, "MERGED" if merged else "CLOSED",
                     "outsider", merger if merged else None, created + timedelta(hours=response_h), "maint"])
    return rows


def test_quarterly_lines_show_a_repo_that_stopped_merging_outside_fixes():
    # Repo 1: outside PRs merged 80% and answered in 10 h a year ago; now 20% and 200 h, all merged by one person.
    rows = quarter_prs(1, 340, 0.8, 10, "a", first=0) + quarter_prs(1, 250, 0.7, 20, "b", first=100) \
        + quarter_prs(1, 160, 0.5, 60, "a", first=200) + quarter_prs(1, 70, 0.2, 200, "a", first=300)
    # Repo 2, a peer of similar size, stays healthy.
    for i, day in enumerate((340, 250, 160, 70)):
        rows += quarter_prs(2, day, 0.8, 8, "c" if i % 2 else "d", first=i * 100)
    con = con_with(rows, [(1, "maint", "insider"), (2, "maint", "insider")],
                   [(1, "acme/lib", 5000), (2, "peer/lib", 6000)])
    t = repo_trends(con, ["acme/lib", "peer/lib"], NOW)
    lib = t["acme/lib"]
    assert [q["quarter"] for q in lib["quarters"]] == ["2025Q4", "2026Q1", "2026Q2", "2026Q3"]
    assert lib["quarters"][0]["outside_merge_rate"] == 0.8 and lib["quarters"][-1]["outside_merge_rate"] == 0.2
    # Q2's 5 merges were all by one person; the last quarter's 2 merges are too few to say.
    assert lib["quarters"][-1]["first_response_hours"] == 200.0 and lib["quarters"][2]["top_merger_share"] == 1.0
    assert lib["quarters"][-1]["top_merger_share"] is None
    assert lib["direction"]["outside_merge_rate"] == "falling" and lib["direction"]["first_response_hours"] == "slower"
    assert t["peer/lib"]["direction"]["outside_merge_rate"] == "steady"
    # Against repos of its size it is now among the slowest to answer.
    assert lib["peers"]["first_response_hours"]["place"] == "slower than most similar repos"


def test_thin_quarters_say_so_instead_of_a_rate():
    con = con_with(quarter_prs(1, 70, 1.0, 5, "a", n=3), [(1, "maint", "insider")], [(1, "tiny/lib", 50)])
    q = repo_trends(con, ["tiny/lib"], NOW)["tiny/lib"]["quarters"][-1]
    assert q["outside_decided"] == 3 and q["outside_merge_rate"] is None


def test_repos_outside_the_crawl_are_simply_absent():
    con = con_with([], [], [(1, "acme/lib", 10)])
    assert repo_trends(con, ["other/repo"], NOW) == {}


def test_the_daily_snapshot_writes_trend_lines_for_watched_repos(tmp_path):
    import json

    from mergescout.snapshot.__main__ import write_trends
    rows = quarter_prs(1, 160, 0.5, 60, "a") + quarter_prs(1, 70, 0.2, 200, "a", first=100)
    con = con_with(rows, [(1, "maint", "insider")], [(1, "acme/lib", 5000)])
    (tmp_path / "watch-repos.txt").write_text("acme/lib\nnot/crawled\n", encoding="utf-8")
    said = []
    write_trends(con, tmp_path, NOW, said.append)
    data = json.loads((tmp_path / "deps-trends.json").read_text(encoding="utf-8"))
    assert list(data["repos"]) == ["acme/lib"] and data["repos"]["acme/lib"]["quarters"][-1]["outside_merge_rate"] == 0.2
    assert any("trend lines: 1 of 2" in s for s in said)


def test_bots_that_merge_are_not_counted_as_the_one_person_merging():
    # Hand-check: ueberdb2's repo showed one merger doing everything; it was an automation account.
    rows = quarter_prs(1, 70, 1.0, 5, "github-actions", n=8) + quarter_prs(1, 60, 1.0, 5, "automerge-app", n=8, first=50) \
        + quarter_prs(1, 50, 1.0, 5, "alice", n=3, first=100) + quarter_prs(1, 40, 1.0, 5, "bob", n=3, first=150)
    con = con_with(rows, [(1, "maint", "insider"), (9, "automerge-app", "bot")], [(1, "ether/ueberdb", 900)])
    q = repo_trends(con, ["ether/ueberdb"], NOW)["ether/ueberdb"]["quarters"][-1]
    assert q["merges"] == 6 and q["top_merger_share"] == 0.5
