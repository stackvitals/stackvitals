"""Community benchmarks from the crawl: first answers and whether newcomers come back. One guard per real-data finding;
task tests live in tests/local."""
from datetime import datetime, timedelta, timezone

import duckdb

from mergescout.signals.community_bench import newcomer_returns

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def test_newcomers_are_judged_only_with_history_before_and_time_after():
    # Real data (2,824 newcomers in 321 repos): 29.9% returned after an answer within a day, 15.3% after no answer.
    day = lambda d: NOW - timedelta(days=d)  # noqa: E731
    con = duckdb.connect()
    con.execute("""CREATE TABLE pr_class (repo_id BIGINT, number INT, created_at TIMESTAMPTZ, merged_at TIMESTAMPTZ,
        closed_at TIMESTAMPTZ, state VARCHAR, author_login VARCHAR, author_class VARCHAR, first_human_review_at TIMESTAMPTZ,
        first_human_review_by VARCHAR)""")
    con.executemany("INSERT INTO pr_class VALUES (?,?,?,?,?,?,?,?,?,?)", [
        [1, 1, day(400), day(400), None, "MERGED", "maint", "insider", None, None],
        [1, 2, day(390), day(390), None, "MERGED", "early", "outsider", None, None],  # inside the first 60 days: not judged
        [1, 3, day(200), None, None, "OPEN", "quiet", "outsider", None, None],  # never answered
        [1, 4, day(200), None, day(199), "CLOSED", "told-no", "outsider", None, None],  # a quick no
        [1, 5, day(150), day(150), None, "MERGED", "told-no", "outsider", None, None],  # ...and came back
        [1, 6, day(200), None, None, "OPEN", "self", "outsider", day(199), "self"],  # a self-review is no answer
        [1, 7, day(60), day(60), None, "MERGED", "recent", "outsider", None, None]])  # too recent to judge
    t = newcomer_returns(con, NOW)
    by = {b["bucket"]: b for b in t["by_answer"]}
    assert t["newcomers"] == 3 and by["no answer"]["newcomers"] == 2 and by["within 1 day"]["returned"] == 1.0


def test_the_module_answers_from_others_names_items_not_people_and_never_scores_missing_facts_as_zero():
    from stackvitals.community.analyze import answered_at, newcomers_waiting, score
    from stackvitals.community.report import badges
    t = lambda d: (NOW - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    mine = {"t": "pr", "n": 4, "st": "OPEN", "cr": t(9), "au": "newbie", "at": "User", "as": "NONE",
            "ev": [["review", t(8), "newbie", "COMMENTED", "NONE", "User", False]],
            "cm": [[t(8), "ci-bot[bot]", "NONE", "Bot", False]]}
    assert answered_at(mine) is None  # a self-review and a bot's comment are not answers
    waiting = newcomers_waiting([mine], [], NOW)
    assert waiting == [{"kind": "pr", "n": 4, "created": t(9), "days": 9}] and "newbie" not in str(waiting)
    q = {"repos": 300, "p10": 1, "p25": 6, "p50": 24, "p75": 70, "p90": 200}
    bench = {"groups": {"all|all": {"repos": 900, "first_answer_hours": q, "newcomer_answered_share": {**q, "p10": 0.2, "p25": 0.4,
                                    "p50": 0.6, "p75": 0.8, "p90": 0.9}}}}
    s = score({"first_answer_hours": 6.0, "newcomer_answered_share": 0.6, "newcomer_return_rate": None}, bench, None, 50)
    assert s["left_out"] == ["newcomer_return_rate"] and len(s["facts"]) == 2
    assert badges({"facts": {}, "score": None})["community-score.json"]["message"] == "not enough data yet"


def test_hand_check_findings_maintainers_answers_new_work_and_automated_accounts():
    # 10 real repos checked by hand: pipx's merger showed as CONTRIBUTOR, self-closes and "+1"s counted as answers,
    # an issue and its PR 30 s apart counted as coming back, one account opened 73 of bat's PRs in a day.
    from stackvitals.community.analyze import answered_at, first_answer, funnel, insiders
    t = lambda d, h=0: (NOW - timedelta(days=d) + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    pr = lambda n, au, cr, as_="NONE", **kw: {"t": "pr", "n": n, "st": "OPEN", "cr": cr, "au": au, "at": "User", "as": as_,  # noqa: E731
                                              "ev": [], "cm": [], **kw}
    merger = pr(1, "gabor", t(30), "CONTRIBUTOR", st="MERGED", mg=t(30, 1), ev=[["merged", t(30, 1), "gabor"]])
    assert "gabor" in insiders([merger], [])
    self_closed = pr(2, "amy", t(10), st="CLOSED", cl=t(10, 1), ev=[["closed", t(10, 1), "amy"]],
                     cm=[[t(10, 2), "passerby", "NONE", "User", False]])
    assert answered_at(self_closed, {"gabor"}) is None
    start = pr(3, "maint", t(400), "OWNER", st="MERGED", mg=t(400))
    pair = [pr(4, "ann", t(200)), {"t": "issue", "n": 5, "st": "OPEN", "cr": t(200, 1), "au": "ann", "at": "User", "as": "NONE", "cm": []}]
    assert funnel([start, pair[0]], [pair[1]], NOW)["returned"] == 0
    burst = [pr(100 + i, "bot-like", t(30, i / 10)) for i in range(25)]
    assert first_answer(burst + [start], [], NOW)["left_out"] == {"accounts": 1, "items": 25}


def test_who_carries_the_work_names_nobody_and_matches_the_crawl_definition():
    # The app and the crawl count the same thing: people's merged PRs over 180 days, the fewest people behind half.
    from mergescout.signals.community_bench import repo_metrics
    from stackvitals.community.analyze import dependency
    when = lambda d: (NOW - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    prs = [{"n": i, "au": f"p{i % 3}", "at": "User", "mg": when(10 + i)} for i in range(24)]
    prs.append({"n": 99, "au": "dependabot[bot]", "at": "Bot", "mg": when(5)})
    d = dependency(prs, NOW)
    assert (d["bus_factor"], d["top_share"], d["people"]) == (2, 0.3333, 3) and "p0" not in str(d)
    con = duckdb.connect()
    con.execute("""CREATE TABLE pr_class (repo_id BIGINT, number INT, created_at TIMESTAMPTZ, merged_at TIMESTAMPTZ,
        closed_at TIMESTAMPTZ, state VARCHAR, author_login VARCHAR, author_class VARCHAR, first_human_review_at TIMESTAMPTZ,
        first_human_review_by VARCHAR)""")
    con.executemany("INSERT INTO pr_class VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [[1, i, NOW - timedelta(days=11 + i), NOW - timedelta(days=10 + i), None, "MERGED", f"p{i % 3}", "insider",
                      None, None] for i in range(24)])
    con.execute("ALTER TABLE pr_class ADD COLUMN author_role VARCHAR; UPDATE pr_class SET author_role = CASE WHEN author_class = 'ai' THEN 'agent' ELSE author_class END")
    con.execute("CREATE TABLE repo_meta (repo_id BIGINT, name VARCHAR, language VARCHAR, stars INT)")
    con.execute("INSERT INTO repo_meta VALUES (1, 'a/b', 'Go', 300)")
    # A repo with merged work but few outside PRs still gets the facts (an early version dropped it).
    row = repo_metrics(con, NOW)[0]
    assert (row["bus_factor"], row["top_share"]) == (2, 0.3333)


def test_a_regular_responder_answers_issues_and_an_issue_still_waiting_keeps_the_median_honest():
    # Labelled crawl comments (bench/accuracy/community): 22% of non-maintainer first comments are the project answering;
    # regular responders caught 45% of them on held-out repos, with 11% drive-bys among what they add.
    from stackvitals.community.analyze import first_answer, regular_responders
    t = lambda d, h=0: (NOW - timedelta(days=d) + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    old = [{"t": "issue", "n": n, "cr": t(200 + n), "au": f"u{n}", "as": "NONE", "st": "OPEN",
            "cm": [[t(200 + n, 1), "triager", "CONTRIBUTOR", "User"]]} for n in range(10)]
    new = [{"t": "issue", "n": 100 + n, "cr": t(20), "au": f"x{n}", "as": "NONE", "st": "OPEN",
            "cm": [[t(20, 3), "triager", "CONTRIBUTOR", "User"]] if n < 2 else []} for n in range(5)]
    pr = {"t": "pr", "n": 1, "cr": t(20), "au": "y", "as": "NONE", "at": "User", "st": "OPEN", "cm": [],
          "ev": [["review", t(20, 3), "triager", "COMMENTED", "CONTRIBUTOR", "User", False]]}
    assert regular_responders([pr], old + new, {"maint"}, NOW) == {"triager"}
    out = first_answer([pr], old + new, NOW, ins={"maint"})
    assert out["issues"]["answered"] == 0.4 and out["issues"]["km"]["median"] is None and out["issues"]["km"]["waiting"] == 3
    assert out["prs"]["answered"] == 0.0  # a PR still needs a maintainer, as the crawl benchmarks count it


def test_the_chaoss_page_names_only_functions_that_exist_and_matches_the_list():
    # CM1: each CHAOSS metric we answer points at the code that computes it; a renamed function fails here.
    import importlib
    from pathlib import Path
    from stackvitals.community import chaoss
    for _name, _slug, where, _d in chaoss.MAPPING:
        module, fn = where.rsplit(".", 1)
        assert callable(getattr(importlib.import_module(module), fn)), where
    root = Path(__file__).resolve().parents[1]
    assert (root / "docs" / "chaoss.md").read_text(encoding="utf-8") == chaoss.markdown()
