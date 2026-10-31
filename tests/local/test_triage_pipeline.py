from datetime import datetime, timedelta, timezone

import duckdb

from mergescout.signals.triage import build_triage_model, training_rows

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def table(rows):
    con = duckdb.connect()
    con.execute("""CREATE TABLE pr_class (repo_id BIGINT, number INT, created_at TIMESTAMPTZ, merged_at TIMESTAMPTZ,
        closed_at TIMESTAMPTZ, state VARCHAR, author_login VARCHAR, author_class VARCHAR, author_association VARCHAR,
        additions INT, deletions INT, closing_issue_numbers INT[])""")
    con.executemany("INSERT INTO pr_class VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return con


def row(repo, n, author, days_ago, merged_after=None, assoc="CONTRIBUTOR", lines=10, issues=(), cls="outsider"):
    created = NOW - timedelta(days=days_ago)
    merged = created + timedelta(days=merged_after) if merged_after is not None else None
    return [repo, n, created, merged, merged or created + timedelta(days=40), "MERGED" if merged else "CLOSED", author, cls,
            assoc, lines, 0, list(issues)]


def test_training_rows_count_only_what_was_known_before_each_pr():
    rows = [row(1, 1, "ann", 200, merged_after=1), row(1, 2, "ann", 100, merged_after=2, issues=[5]),
            row(2, 1, "ann", 150, merged_after=1), row(1, 3, "bob", 90, merged_after=None, assoc="FIRST_TIME_CONTRIBUTOR"),
            row(1, 4, "cat", 80, merged_after=45), row(1, 5, "dan", 10, merged_after=1),
            row(1, 6, "maint", 100, merged_after=1, cls="insider")]
    out = {(r["repo"], r["number"]): r for r in training_rows(table(rows), NOW)}
    later = out[(1, 2)]
    assert later["here_merged"] == 1 and later["linked_issue"] and later["merged"]
    assert out[(1, 1)]["here_merged"] == 0
    assert out[(1, 3)]["first_timer"] and not out[(1, 3)]["merged"]
    assert out[(1, 4)]["merged"] is False  # merged, but only after 45 days
    assert (1, 5) not in out and (1, 6) not in out  # too recent to know; insiders are not triaged


def test_the_model_file_says_how_well_it_did_on_repos_it_never_saw():
    import random
    rng = random.Random(3)
    rows, n = [], 0
    for repo in range(300):
        welcoming = repo % 2 == 0
        for k in range(20):
            n += 1
            merged = rng.random() < (0.8 if welcoming else 0.2)
            rows.append(row(repo, k, f"a{rng.randrange(500)}", 40 + k * 18, merged_after=1 if merged else None))
    model = build_triage_model(table(rows), NOW)
    ev = model["evaluation"]
    assert ev["test_prs"] > 500 and ev["train_prs"] > 3000 and ev["brier"] <= ev["baseline_brier"] + 0.01
    assert model["coef"]["repo_rate=80%+"] > model["coef"]["repo_rate=<30%"]
