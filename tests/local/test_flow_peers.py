from datetime import datetime, timedelta, timezone

from stackvitals.flow.peers import compare, own_metrics

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def at(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, assoc, merged_after=None, review_after=None, st=None, lines=30, au="u", kind="User", age=200):
    ev = []
    if review_after is not None:
        ev.append(["review", at(age - review_after), "maint", "APPROVED", "MEMBER", "User"])
    state = st or ("MERGED" if merged_after is not None else "OPEN")
    return {"t": "pr", "n": n, "st": state, "cr": at(age), "mg": at(age - merged_after) if merged_after is not None else None,
            "cl": at(age - (merged_after or 5)) if state != "OPEN" else None, "au": au, "at": kind, "as": assoc,
            "rq": [], "ev": ev, "cm": [], "add": lines, "del": 0}


def history():
    prs = [pr(k, "MEMBER", merged_after=10, review_after=2, au="maint2") for k in range(6)]
    prs += [pr(10 + k, "NONE", merged_after=40, review_after=8, au=f"o{k}") for k in range(4)]
    prs += [pr(20 + k, "NONE", st="CLOSED", au=f"c{k}") for k in range(4)]
    prs += [pr(30, "NONE", merged_after=1, au="dependabot[bot]", kind="Bot")]
    return prs


def test_own_numbers_use_the_same_definitions_as_the_crawl_benchmarks():
    m = own_metrics(history(), NOW)
    assert m["prs"] == 14 and m["first_review_hours"] == 2.0 and m["merge_hours"] == 10.0
    assert m["outsider_merge_rate"] == 0.5 and m["size_lines"] == 30
    assert own_metrics(history()[:5], NOW) is None


BENCH = {"repos": 900, "built_at": "2026-10-17T05:00:00Z", "groups": {
    "Python|all": {"repos": 300,
                   "first_review_hours": {"repos": 300, "p10": 1.0, "p25": 3.0, "p50": 12.0, "p75": 30.0, "p90": 80.0},
                   "merge_hours": {"repos": 300, "p10": 5.0, "p25": 20.0, "p50": 48.0, "p75": 120.0, "p90": 300.0},
                   "outsider_merge_rate": {"repos": 280, "p10": 0.2, "p25": 0.4, "p50": 0.6, "p75": 0.75, "p90": 0.9},
                   "size_lines": {"repos": 300, "p10": 10, "p25": 25, "p50": 60, "p75": 150, "p90": 400}}}}


def test_compare_places_the_repo_among_similar_repos_with_plain_words():
    c = compare(own_metrics(history(), NOW), BENCH, "Python", 300)
    assert c["group"] == "Python repos" and c["repos"] == 300
    first = next(m for m in c["metrics"] if m["key"] == "first_review_hours")
    assert first["you"] == 2.0 and first["typical"] == 12.0 and first["place"].startswith("faster than about")
    rate = next(m for m in c["metrics"] if m["key"] == "outsider_merge_rate")
    assert rate["place"].startswith("below about")
    assert compare(None, BENCH, "Python", 1) is None and compare(own_metrics(history(), NOW), {"groups": {}}, "Go", 1) is None


def test_times_out_of_order_are_skipped_not_a_crash():
    prs = history()
    prs[0]["ev"] = [["review", at(300), "maint", "APPROVED", "MEMBER", "User"]]  # "before" the PR was opened
    assert own_metrics(prs, NOW)["first_review_hours"] is not None


def test_first_review_counts_only_when_the_first_human_reviewer_is_a_maintainer_like_the_crawl():
    prs = history()
    for p in prs[:3]:
        # A passer-by reviewed first (1h), a maintainer after (2h): the crawl counts no first-review time for these.
        p["ev"] = [["review", at(199), "passerby", "COMMENTED", "NONE", "User"], ["review", at(198), "maint", "APPROVED", "MEMBER", "User"]]
    # Left: three member PRs at 2h and four outsider PRs at 8h, so the median is 8h, not 2h.
    assert own_metrics(prs, NOW)["first_review_hours"] == 8.0
