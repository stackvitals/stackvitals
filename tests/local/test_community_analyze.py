from datetime import datetime, timedelta, timezone

from stackvitals.community.analyze import (answered_at, bench_facts, first_answer, funnel, newcomers_waiting, score,
                                           star_trend)

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def t(days, hours=0):
    return (NOW - timedelta(days=days) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, au, cr, as_="NONE", at="User", mg=None, cl=None, ev=(), cm=()):
    st = "MERGED" if mg else "CLOSED" if cl else "OPEN"
    return {"t": "pr", "n": n, "st": st, "cr": cr, "mg": mg, "cl": cl or mg, "au": au, "at": at, "as": as_,
            "ev": list(ev), "cm": list(cm)}


def issue(n, au, cr, as_="NONE", cl=None, cm=()):
    return {"t": "issue", "n": n, "st": "CLOSED" if cl else "OPEN", "cr": cr, "cl": cl, "au": au, "at": "User", "as": as_,
            "cm": list(cm)}


def review(at, who, assoc="MEMBER", typ="User"):
    return ["review", at, who, "COMMENTED", assoc, typ, False]


def test_an_answer_comes_from_someone_else_and_never_from_a_bot():
    p = pr(1, "amy", t(10), ev=[review(t(10, 1), "amy"), review(t(10, 2), "ci-bot", typ="Bot"), review(t(9), "max")],
           cm=[[t(10, 3), "max", "MEMBER", "User", False]])
    assert answered_at(p) == t(10, 3) and answered_at(p, comments=False) == t(9)
    assert answered_at(pr(2, "amy", t(10), cl=t(8))) == t(8)
    assert answered_at(issue(3, "amy", t(5), cm=[[t(5, 1), "amy", "NONE", "User"], [t(4), "dependabot[bot]", "NONE", "Bot"]])) is None


def test_the_funnel_follows_newcomers_from_their_first_contribution():
    prs = [pr(1, "maint", t(400), "OWNER", mg=t(400)),
           pr(2, "old", t(380), mg=t(379)),  # inside the first 60 days of history: not judged as new
           pr(3, "ann", t(200), mg=t(199)), pr(4, "ann", t(150), mg=t(149)),  # came back within 90 days
           pr(5, "bob", t(200), cl=t(170)),  # never came back
           pr(6, "cat", t(30)),  # too recent to judge
           pr(7, "maint", t(100), "OWNER", mg=t(100))]
    issues = [issue(1, "dan", t(250), cl=t(249)), issue(2, "dan", t(100)),  # came back, but after 150 days
              issue(3, "reg", t(300)), issue(4, "reg", t(220)), issue(5, "reg", t(110)), issue(6, "reg", t(20))]
    f = funnel(prs, issues, NOW)
    assert (f["newcomers"], f["judged"], f["returned"]) == (5, 4, 2) and f["return_rate"] == 0.5
    assert f["regulars"] == 1 and f["maintainers"] == 1


def test_first_answers_are_measured_for_prs_and_issues_apart():
    prs = [pr(n, f"u{n}", t(20 + n), ev=[review(t(20 + n, 2 if n <= 3 else 50), "max")]) for n in range(1, 5)]
    issues = [issue(1, "x", t(10), cm=[[t(10, 6), "max", "MEMBER", "User"]]), issue(2, "y", t(9))]
    a = first_answer(prs, issues, NOW)
    assert a["prs"]["items"] == 4 and a["prs"]["median_hours"] == 2.0 and a["prs"]["within_1d"] == 0.75
    assert a["issues"]["items"] == 2 and a["issues"]["answered"] == 0.5 and a["issues"]["median_hours"] == 6.0


def test_newcomers_waiting_lists_first_time_items_nobody_answered_oldest_first():
    prs = [pr(1, "maint", t(400), "OWNER", mg=t(400)), pr(2, "new1", t(5)), pr(3, "known", t(300), mg=t(299)),
           pr(4, "known", t(3)),  # came before: not a newcomer
           pr(5, "new2", t(8), cm=[[t(7), "maint", "OWNER", "User", False]])]  # answered
    issues = [issue(1, "new3", t(12)), issue(2, "maint", t(2), "OWNER")]
    waiting = newcomers_waiting(prs, issues, NOW)
    assert [(w["kind"], w["n"], w["days"]) for w in waiting] == [("issue", 1, 12), ("pr", 2, 5)]


def test_bench_facts_use_the_crawl_definitions():
    prs = [pr(1, "maint", t(400), "OWNER", mg=t(400))]
    prs += [pr(10 + i, f"o{i}", t(60 - i), mg=t(60 - i, 5 if i < 9 else 72)) for i in range(12)]
    prs += [pr(100 + i, f"o{i}", t(395), mg=t(395)) for i in range(12)]  # the o-authors came before: not newcomers
    for i in range(10):
        prs.append(pr(200 + i, f"n{i}", t(200), mg=t(199) if i < 8 else None))
        if i < 3:
            prs.append(pr(300 + i, f"n{i}", t(170), mg=t(170)))
    f = bench_facts(prs, NOW)
    assert f == {"first_answer_hours": 5.0, "answered_1d_share": 0.75, "newcomer_answered_share": 0.8,
                 "newcomer_return_rate": 0.3}


def group(p50s):
    return {"repos": 400, **{k: {"repos": 300, "p10": v * 0.2, "p25": v * 0.5, "p50": v, "p75": v * 1.5, "p90": v * 2}
                             for k, v in p50s.items()}}


def test_the_score_averages_where_each_fact_stands_among_similar_repos():
    bench = {"built_at": "2026-10-19", "groups": {"Python|1k-10k": group({"first_answer_hours": 24.0, "newcomer_answered_share": 0.6,
                                                                          "newcomer_return_rate": 0.2})}}
    facts = {"first_answer_hours": 12.0, "newcomer_answered_share": 0.6, "newcomer_return_rate": None}
    s = score(facts, bench, "Python", 5000)
    # Answers faster than 75% of similar repos; newcomers answered like the middle one; return rate left out.
    # The score is exactly the average of the whole percents shown, so anyone can recompute it (75 and 50 -> 63).
    assert [f["better_than"] for f in s["facts"]] == [75, 50] and s["score"] == 63
    assert [f["key"] for f in s["facts"]] == ["first_answer_hours", "newcomer_answered_share"]
    assert s["left_out"] == ["newcomer_return_rate"] and s["repos"] == 400
    assert score({"first_answer_hours": 12.0}, bench, "Python", 5000) is None  # one fact is not a score


def test_star_trend_counts_complete_weeks_and_places_growth_among_peers():
    start = int(NOW.timestamp()) // 604800 * 604800
    weeks = {str(start - i * 604800): 10 for i in range(20)}
    bench = {"groups": {"all|1k-10k": {"repos": 50, "gained_12w": {"p10": 1, "p25": 10, "p50": 60, "p75": 200, "p90": 500},
                                       "growth_12w": {"p10": 0.001, "p25": 0.01, "p50": 0.03, "p75": 0.08, "p90": 0.2}}}}
    s = star_trend(weeks, 1200, NOW, bench, None)
    assert s["gained_12w"] == 120 and s["weeks"][-1][1] == 10 and len(s["weeks"]) == 20
    assert s["peers"]["repos"] == 50 and "above" in s["peers"]["place"]


def test_traffic_sums_views_and_clones_kept_past_githubs_14_days():
    from stackvitals.community.analyze import traffic_summary
    traffic = {"views": {"2026-06-01": [9, 9], "2026-10-01": [5, 2], "2026-10-18": [3, 1]},
               "clones": {"2026-10-01": [40, 6], "2026-10-18": [10, 3]},
               "referrers": {"2026-10-18": [["github.com", 3, 1]], "2026-10-10": [["google.com", 9, 2]]}}
    s = traffic_summary(traffic, NOW)
    # June is outside the 90-day window but shows how far back the archive reaches.
    assert (s["views_total"], s["visitors_total"], s["clones_total"]) == (8, 3, 50) and s["since"] == "2026-06-01"
    assert s["referrers"] == [["github.com", 3, 1]]


def test_people_who_merge_are_maintainers_even_when_github_calls_them_contributors():
    # Hand-check: pipx's main merger shows as CONTRIBUTOR; his own PRs counted as outside and his self-merges as answers.
    from stackvitals.community.analyze import insiders
    prs = [pr(1, "gabor", t(30), "CONTRIBUTOR", mg=t(30, 1), ev=[["merged", t(30, 1), "gabor"]]),
           pr(2, "amy", t(20), mg=t(19), ev=[["merged", t(19), "gabor"]])]
    ins = insiders(prs, [])
    assert "gabor" in ins and "amy" not in ins
    f = funnel(prs, [], NOW)
    assert f["maintainers"] == 1
    a = first_answer(prs, [], NOW)
    assert a["prs"]["items"] == 1  # only amy's PR is from outside


def test_an_answer_is_a_maintainers_reply_or_a_merge_or_close_by_someone_else():
    # Hand-check: an author's self-close after a minute and a drive-by "+1" were counted as answers.
    ins = {"maint"}
    self_closed = pr(1, "amy", t(10), cl=t(10, 1), ev=[["closed", t(10, 1), "amy"]])
    plus_one = pr(2, "amy", t(10), cm=[[t(10, 2), "passerby", "NONE", "User", False]])
    maint_reply = pr(3, "amy", t(10), cm=[[t(10, 2), "passerby", "NONE", "User", False], [t(10, 5), "maint", "NONE", "User", False]])
    closed_by_maint = pr(4, "amy", t(10), cl=t(9), ev=[["closed", t(9), "maint"]])
    assert answered_at(self_closed, ins) is None and answered_at(plus_one, ins) is None
    assert answered_at(maint_reply, ins) == t(10, 5) and answered_at(closed_by_maint, ins) == t(9)
    old_record = pr(5, "amy", t(10), cl=t(9), ev=[["closed", t(9)]])  # saved before closers were kept: still counts
    assert answered_at(old_record, ins) == t(9)


def test_the_waiting_list_skips_people_github_knows_contributed_before_and_history_starts_at_the_first_fetch():
    # Hand-check: typer#1827 was listed although its author had three earlier PRs from before our history.
    prs = [pr(1, "known", t(5), "CONTRIBUTOR"), pr(2, "new", t(4), "FIRST_TIME_CONTRIBUTOR")]
    assert [w["n"] for w in newcomers_waiting(prs, [], NOW)] == [2]
    from stackvitals.community.analyze import covered_since
    old = {**pr(3, "x", t(900), mg=t(899)), "f": t(10)}  # an old PR fetched 10 days ago because it was updated lately
    recent = {**pr(4, "y", t(100), mg=t(99)), "f": t(10)}
    assert covered_since([old, recent], []) == t(370)


def test_coming_back_means_new_work_at_least_a_day_later():
    # Hand-check: an issue and the PR fixing it 30 seconds later counted as "came back".
    start = [pr(1, "maint", t(400), "OWNER", mg=t(400))]
    same_work = start + [pr(2, "ann", t(200), mg=t(199))]
    issues = [issue(1, "ann", t(200, -1))]
    assert funnel(same_work, issues, NOW)["returned"] == 0
    later = same_work + [pr(3, "ann", t(180), mg=t(179))]
    assert funnel(later, issues, NOW)["returned"] == 1


def test_accounts_that_open_20_prs_in_a_day_are_left_out_and_counted():
    # Hand-check: one account opened 82 of bat's 182 outside PRs, 73 on one day; they dragged the answer rate to 19%.
    prs = [pr(100 + i, "burst", t(30, i / 10)) for i in range(25)]
    prs += [pr(1, "amy", t(20), ev=[review(t(20, 2), "maint")]), pr(2, "bob", t(21))]
    a = first_answer(prs, [], NOW)
    assert a["prs"]["items"] == 2 and a["left_out"] == {"accounts": 1, "items": 25}
    assert [w["n"] for w in newcomers_waiting(prs, [], NOW)] == [2]


def test_a_repo_whose_outside_prs_stopped_says_how_many_came_before():
    prs = [pr(1, "maint", t(400), "OWNER", mg=t(400))] + [pr(10 + i, f"o{i}", t(150 + i), mg=t(149 + i)) for i in range(5)]
    a = first_answer(prs, [], NOW)
    assert a["prs"]["items"] == 0 and a["prs"]["earlier"] == 5


def test_a_maintainer_opening_many_prs_in_a_day_is_not_called_automated():
    # Real data: pipx's main maintainer opened 85 PRs in bursts and was reported as an automated account.
    prs = [pr(100 + i, "gabor", t(30, i / 10), "CONTRIBUTOR", mg=t(30, i / 10 + 1), ev=[["merged", t(30, i / 10 + 1), "gabor"]])
           for i in range(25)]
    prs += [pr(1, "amy", t(20), ev=[review(t(20, 2), "gabor", assoc="CONTRIBUTOR")])]
    a = first_answer(prs, [], NOW)
    assert a["left_out"] is None and a["prs"]["items"] == 1 and a["prs"]["answered"] == 1.0


def test_the_waiting_list_skips_items_older_than_the_complete_history_and_long_threads_it_cannot_see_whole():
    # Real data: express issues from 2014, updated lately, were listed; a 28-comment PR's early maintainer reply was unseen.
    recent = {**pr(1, "new1", t(20)), "f": t(5)}
    ancient = {**pr(2, "new2", t(4000)), "f": t(5)}  # older than the complete history (360 days before the first fetch)
    long_pr = {**pr(3, "new3", t(30), cm=[[t(29 - i / 10), "fan", "NONE", "User", False] for i in range(10)]), "f": t(5)}
    long_issue = {**issue(4, "new4", t(25), cm=[[t(24), "fan", "NONE", "User"]]), "cmn": 12, "f": t(5)}
    assert [w["n"] for w in newcomers_waiting([recent, ancient, long_pr], [long_issue], NOW)] == [1]
