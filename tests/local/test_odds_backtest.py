"""Phase 9: outside merge odds checked against what happened next, and how coding-agent PRs fare, across the crawl."""
from datetime import datetime, timedelta, timezone

import duckdb
import pyarrow as pa

from mergescout.signals.flow_bench import agent_prs, odds_backtest

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def crawl(repos=60, past=20, future=10):
    con = duckdb.connect()
    con.execute("""CREATE TABLE pr_class (repo_id BIGINT, number INT, created_at TIMESTAMPTZ, merged_at TIMESTAMPTZ,
        closed_at TIMESTAMPTZ, state VARCHAR, author_login VARCHAR, author_class VARCHAR, additions INT, deletions INT)""")
    con.execute("CREATE TABLE repo_meta (repo_id BIGINT, name VARCHAR, stars INT, language VARCHAR)")
    rows = []
    for r in range(repos):
        con.execute("INSERT INTO repo_meta VALUES (?, ?, ?, ?)", [r, f"o/r{r}", 500, "Python"])
        rate = 0.2 if r % 2 else 0.8  # half the repos merge few outside PRs, half most
        for k in range(past + future):
            created = NOW - timedelta(days=200 - k) if k < past else NOW - timedelta(days=80 - (k - past))
            merged = (k % 10) < rate * 10
            done = created + timedelta(days=2)
            rows.append([r, k, created, done if merged else None, done, "MERGED" if merged else "CLOSED", f"u{k}",
                         "outsider", 10, 0])
        # Coding agents: 3 of 10 merged in every repo.
        for k in range(10):
            created = NOW - timedelta(days=30)
            merged = k < 3
            rows.append([r, 1000 + k, created, created if merged else None, created + timedelta(days=1),
                         "MERGED" if merged else "CLOSED", "Copilot", "ai", 10, 0])
    # One batch insert: row-by-row inserts take most of a minute.
    cols = ["repo_id", "number", "created_at", "merged_at", "closed_at", "state", "author_login", "author_class",
            "additions", "deletions"]
    batch = pa.table({c: [r[i] for r in rows] for i, c in enumerate(cols)})
    con.register("batch", batch)
    con.execute("INSERT INTO pr_class SELECT * FROM batch")
    con.execute("ALTER TABLE pr_class ADD COLUMN author_role VARCHAR; UPDATE pr_class SET author_role = CASE WHEN author_class = 'ai' THEN 'agent' ELSE author_class END")
    return con


def test_past_outside_rates_are_checked_against_the_next_outside_prs():
    out = odds_backtest(crawl(), NOW)
    assert out["repos"] == 60 and out["prs"] == 600
    mae = out["mae"]
    # Each repo's own history beats one typical rate for everyone; shrinking costs a little when samples are big.
    assert mae["raw"] < mae["shrunk"] < mae["typical_only"]
    assert sum(b["prs"] for b in out["calibration"]) == 600
    assert all(abs(b["predicted"] - b["observed"]) < 0.15 for b in out["calibration"])


def test_repos_without_enough_outside_prs_are_left_out_of_the_backtest():
    assert odds_backtest(crawl(past=3), NOW)["repos"] == 0


def test_coding_agent_prs_are_pooled_per_group_next_to_peoples_outside_prs():
    groups = agent_prs(crawl(), NOW)
    g = groups["all|all"]
    assert g["agent"] == {"decided": 600, "merged": 0.3} and g["outsider"]["decided"] >= 600
    assert agent_prs(crawl(repos=5), NOW) == {}  # too few agent PRs to say anything


def test_raw_rates_get_a_correction_table_checked_on_repos_it_was_not_built_from():
    # Real data (13,011 repos, 2026-10-20): every prediction ran 10-15 points high and pulling toward similar repos
    # helped no group, so the brief uses the repo's own rate corrected by what happened next elsewhere.
    out = odds_backtest(crawl(), NOW)
    table = {b["bin"]: b["observed"] for b in out["calibration_raw"]}
    assert table["0.2-0.3"] == 0.2 and table["0.8-0.9"] == 0.8
    assert out["mae"]["calibrated"] < 0.05  # fitted on half the repos, measured on the other half
