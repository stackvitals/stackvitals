import json
from datetime import datetime, timedelta, timezone

import duckdb

from mergescout.signals.community_bench import community_benchmarks, newcomer_returns, repo_metrics

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def day(d, hours=0):
    return NOW - timedelta(days=d) + timedelta(hours=hours)


def con_with(prs, repos):
    con = duckdb.connect()
    con.execute("""CREATE TABLE pr_class (repo_id BIGINT, number INT, created_at TIMESTAMPTZ, merged_at TIMESTAMPTZ,
        closed_at TIMESTAMPTZ, state VARCHAR, author_login VARCHAR, author_class VARCHAR, first_human_review_at TIMESTAMPTZ,
        first_human_review_by VARCHAR)""")
    con.executemany("INSERT INTO pr_class VALUES (?,?,?,?,?,?,?,?,?,?)", prs)
    con.execute("ALTER TABLE pr_class ADD COLUMN author_role VARCHAR; UPDATE pr_class SET author_role = CASE WHEN author_class = 'ai' THEN 'agent' ELSE author_class END")
    con.execute("CREATE TABLE repo_meta (repo_id BIGINT, name VARCHAR, language VARCHAR, stars INT)")
    con.executemany("INSERT INTO repo_meta VALUES (?,?,?,?)", repos)
    return con


def pr(repo, n, who, created, answer_h=None, merged=False, cls="outsider"):
    answered = created + timedelta(hours=answer_h) if answer_h is not None else None
    return [repo, n, created, answered if merged else None, answered if (answered and not merged) else None,
            "MERGED" if merged else ("CLOSED" if answered else "OPEN"), who, cls, None, None]


def history(repo, start=400):
    # An insider PR long ago sets how far back this repo's crawled history reaches.
    return [pr(repo, 0, "maint", day(start), 5, merged=True, cls="insider")]


def test_newcomers_come_back_less_when_their_first_pr_waits_or_gets_no_answer():
    rows = history(1)
    n = 1
    for i in range(4):  # answered (merged) within 2 hours; half come back within 90 days
        rows.append(pr(1, n, f"fast{i}", day(200), 2, merged=True)); n += 1
        if i < 2:
            rows.append(pr(1, n, f"fast{i}", day(150), 3, merged=True)); n += 1
    for i in range(4):  # closed after 20 days; one comes back
        rows.append(pr(1, n, f"slow{i}", day(200), 20 * 24)); n += 1
        if i < 1:
            rows.append(pr(1, n, f"slow{i}", day(160), 3, merged=True)); n += 1
    for i in range(4):  # never answered
        rows.append(pr(1, n, f"none{i}", day(200))); n += 1
    rows.append(pr(1, n, "recent", day(60), 2, merged=True)); n += 1  # too recent to know if they return
    rows.append(pr(1, n, "early", day(390), 2, merged=True))  # within the first 60 days of history: maybe not new
    t = newcomer_returns(con_with(rows, [(1, "a/b", "Python", 5000)]), NOW)
    by = {b["bucket"]: b for b in t["by_answer"]}
    assert t["newcomers"] == 12 and t["repos"] == 1
    assert (by["within 1 day"]["newcomers"], by["within 1 day"]["returned"]) == (4, 0.5)
    assert (by["over 14 days"]["newcomers"], by["over 14 days"]["returned"]) == (4, 0.25)
    assert (by["no answer"]["newcomers"], by["no answer"]["returned"]) == (4, 0.0)
    outcome = {b["outcome"]: b for b in t["by_outcome"]}
    assert outcome["merged"]["newcomers"] == 4 and outcome["still open"]["returned"] == 0.0


def test_repo_metrics_are_the_facts_behind_the_score():
    rows = history(1)
    for i in range(12):  # 12 outside PRs in the last 90 days: 9 answered within a day, 3 after 3 days
        rows.append(pr(1, 100 + i, f"o{i}", day(60 - i), 5 if i < 9 else 72, merged=True))
        rows.append(pr(1, 400 + i, f"o{i}", day(395), 5, merged=True))  # known before: not newcomers
    for i in range(10):  # 10 newcomers 200 days ago, 8 answered within 14 days, 3 came back
        rows.append(pr(1, 200 + i, f"new{i}", day(200), 24 if i < 8 else None, merged=i < 8))
        if i < 3:
            rows.append(pr(1, 300 + i, f"new{i}", day(170), 5, merged=True))
    m = {r["repo_id"]: r for r in repo_metrics(con_with(rows, [(1, "a/b", "Python", 5000)]), NOW)}[1]
    assert m["answered_1d_share"] == 0.75 and m["first_answer_hours"] == 5.0
    assert m["newcomer_answered_share"] == 0.8 and m["newcomer_return_rate"] == 0.3


def test_benchmarks_group_repos_and_say_how_many_back_each_number(monkeypatch):
    import mergescout.signals.community_bench as cb
    monkeypatch.setattr(cb, "MIN_GROUP", 2)
    rows, repos = [], []
    for repo in (1, 2, 3):
        rows += history(repo)
        for i in range(12):
            rows.append(pr(repo, 100 + i, f"o{i}", day(60 - i), 5 * repo, merged=True))
        repos.append((repo, f"o/r{repo}", "Python", 5000))
    b = community_benchmarks(con_with(rows, repos), NOW)
    g = b["groups"]["Python|1k-10k"]
    assert g["repos"] == 3 and g["first_answer_hours"]["p50"] == 10.0 and g["first_answer_hours"]["repos"] == 3
    assert "newcomer_return_rate" not in g  # no repo had enough newcomers
    assert b["definition"] and b["newcomers"]["newcomers"] == 0


def test_the_daily_writes_community_benchmarks_and_logs_the_newcomer_table(tmp_path):
    from mergescout.snapshot.__main__ import write_extras
    rows = history(1) + [pr(1, 5, "x", day(200), 2, merged=True)]
    said = []
    write_extras(con_with(rows, [(1, "a/b", "Python", 5000)]), tmp_path, NOW, log=said.append)
    data = json.loads((tmp_path / "community-benchmarks.json").read_text(encoding="utf-8"))
    assert data["newcomers"]["newcomers"] == 1 and any(s.startswith("community benchmarks:") for s in said)
    assert any("newcomers returning by first answer" in s for s in said)
    said.clear()
    write_extras(duckdb.connect(), tmp_path / "x", NOW, log=said.append)
    assert any("community benchmarks skipped" in s for s in said)


def test_coming_back_is_new_work_a_day_later_and_automated_accounts_are_left_out():
    rows = history(1)
    for i in range(10):  # 10 newcomers; each opens a second PR 30 seconds after the first: one piece of work
        rows.append(pr(1, 200 + i, f"n{i}", day(200), 2, merged=True))
        rows.append(pr(1, 300 + i, f"n{i}", day(200) + timedelta(seconds=30), 2, merged=True))
    rows += [pr(1, 500 + i, "burst", day(30) + timedelta(minutes=i), None) for i in range(25)]  # one account, 25 PRs in a day
    rows += [pr(1, 600 + i, f"o{i}", day(40 - i), 5, merged=True) for i in range(12)]
    con = con_with(rows, [(1, "a/b", "Python", 5000)])
    m = {r["repo_id"]: r for r in repo_metrics(con, NOW)}[1]
    assert m["newcomer_return_rate"] == 0.0 and m["answered_1d_share"] == 1.0  # the 25 unanswered PRs are left out
    assert newcomer_returns(con, NOW)["by_answer"][0]["returned"] == 0.0


def test_who_carries_the_merged_work_is_measured_per_repo_as_the_app_does():
    rows, n = history(1), 1
    for i in range(12):
        rows.append(pr(1, n, "amy", day(10 + i), 2, merged=True, cls="insider")); n += 1
    for i in range(6):
        rows.append(pr(1, n, "bob", day(20 + i), 2, merged=True)); n += 1
    for i in range(4):
        rows.append(pr(1, n, "cat", day(30 + i), 2, merged=True)); n += 1
    rows.append(pr(1, n, "dependabot[bot]", day(5), 1, merged=True, cls="bot")); n += 1
    # A repo with plenty of merged work but few outside PRs still gets the dependency facts.
    rows += [pr(2, 500 + i, f"m{i % 3}", day(15 + i), 1, merged=True, cls="insider") for i in range(24)]
    by = {r["repo_id"]: r for r in repo_metrics(con_with(rows, [(1, "a/b", "Python", 5000), (2, "c/d", "Go", 300)]), NOW)}
    assert (by[1]["bus_factor"], by[1]["top_share"]) == (1, 0.5455)
    assert (by[2]["bus_factor"], by[2]["top_share"], by[2]["first_answer_hours"]) == (2, 0.3333, None)
