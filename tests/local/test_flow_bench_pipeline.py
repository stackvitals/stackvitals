from datetime import datetime, timedelta, timezone

import duckdb

from mergescout.signals.flow_bench import flow_benchmarks

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def setup(repos=60, prs=12):
    con = duckdb.connect()
    con.execute("""CREATE TABLE pr_class (repo_id BIGINT, number INT, created_at TIMESTAMPTZ, merged_at TIMESTAMPTZ,
        closed_at TIMESTAMPTZ, state VARCHAR, author_login VARCHAR, author_class VARCHAR, additions INT, deletions INT,
        first_review_at TIMESTAMPTZ, first_review_by VARCHAR, first_human_review_at TIMESTAMPTZ, first_human_review_by VARCHAR)""")
    con.execute("CREATE TABLE people (repo_id BIGINT, login VARCHAR, kind VARCHAR)")
    con.execute("CREATE TABLE repo_meta (repo_id BIGINT, name VARCHAR, stars INT, language VARCHAR)")
    rows = []
    for r in range(repos):
        con.execute("INSERT INTO repo_meta VALUES (?, ?, ?, ?)", [r, f"o/r{r}", 500, "Python"])
        con.execute("INSERT INTO people VALUES (?, 'maint', 'insider')", [r])
        for k in range(prs):
            created = NOW - timedelta(days=20, hours=k)
            outsider = k % 2 == 0
            merged = created + timedelta(hours=10 + r) if k % 3 else None
            state = "MERGED" if merged else "CLOSED"
            rows.append([r, k, created, merged, merged or created + timedelta(days=1), state, f"u{k}" if outsider else "maint2",
                         "outsider" if outsider else "insider", 20 + r, 0, created + timedelta(hours=1 + r), "maint",
                         created + timedelta(hours=1 + r), "maint"])
    con.executemany("INSERT INTO pr_class VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    # A bot's PRs never count.
    con.execute("INSERT INTO pr_class VALUES (0, 999, ?, ?, ?, 'MERGED', 'dependabot[bot]', 'bot', 1, 0, NULL, NULL, NULL, NULL)",
                [NOW - timedelta(days=2), NOW - timedelta(days=2), NOW - timedelta(days=2)])
    return con


def test_flow_benchmarks_group_repos_with_the_same_definitions_the_suite_uses():
    out = flow_benchmarks(setup(), NOW)
    g = out["groups"]["Python|100-1k"]
    assert out["repos"] == 60 and g["repos"] == 60
    # Repo r waits 1 + r hours for a first maintainer review: the median repo sits near 30 h.
    assert g["first_review_hours"]["p50"] == 30.0 and g["first_review_hours"]["p10"] == 6.0
    assert g["outsider_merge_rate"]["p50"] == 0.6667 and g["size_lines"]["p50"] == 49
    assert "all|all" in out["groups"] and "definition" in out


def test_small_groups_and_thin_repos_are_left_out():
    out = flow_benchmarks(setup(repos=30), NOW)
    assert out["groups"] == {} and out["repos"] == 30
    assert flow_benchmarks(setup(repos=60, prs=4), NOW)["repos"] == 0
