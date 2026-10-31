"""Phase 13 M5: first responses that count what maintainers did, with items still waiting kept in (Kaplan-Meier)."""
from datetime import datetime, timedelta, timezone

import pytest

from stackvitals.core import stats

NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)


def test_without_waiting_items_the_kaplan_meier_median_is_the_plain_one():
    out = stats.km_median([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [True] * 10)
    assert out["median"] == 5 and out["low"] <= 5 <= out["high"] and out["answered"] == 10 and out["waiting"] == 0


def test_a_range_whose_end_the_data_cannot_reach_stays_open_and_tiny_samples_give_no_median():
    # Review finding: six answered quickly and four still waiting at 100 h printed "likely 3 h to 6 h".
    out = stats.km_median([1, 2, 3, 4, 5, 6, 100, 100, 100, 100], [True] * 6 + [False] * 4)
    assert out["median"] == 5 and out["high"] is None
    two = stats.km_median([5, 9], [True, False])
    assert two["median"] is None and two["at_least"] is None and two["too_few"] is True


def test_an_issue_closed_without_an_answer_stops_the_clock_and_is_not_waiting():
    from stackvitals.community.analyze import first_answer

    def item(n, opened_h, answer_h=None, closed_h=None):
        cr = (NOW - timedelta(hours=opened_h)).strftime("%Y-%m-%dT%H:%M:%SZ")
        at = lambda h: (NOW - timedelta(hours=opened_h - h)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        return {"t": "issue", "n": n, "cr": cr, "au": f"u{n}", "as": "NONE", "st": "CLOSED" if closed_h else "OPEN",
                "cl": at(closed_h) if closed_h else None, "ev": [["closed", at(closed_h), f"u{n}"]] if closed_h else [],
                "cm": [[at(answer_h), "maint", "MEMBER", "User"]] if answer_h else []}
    issues = [item(n, 720, closed_h=1) for n in range(6)] + [item(10 + n, 720, answer_h=2) for n in range(4)]
    km = first_answer([], issues, NOW, ins={"maint"})["issues"]["km"]
    assert km["waiting"] == 0 and km["closed_unanswered"] == 6 and km["at_least"] != 720


def test_items_still_waiting_raise_the_median_instead_of_dropping_out():
    # Four answered quickly, six still waiting after 100 hours: answered-only says 2.5 h; the honest median is over 100 h.
    out = stats.km_median([1, 2, 3, 4, 100, 100, 100, 100, 100, 100], [True] * 4 + [False] * 6)
    assert out["median"] is None and out["at_least"] == 100 and out["waiting"] == 6
    mixed = stats.km_median([1, 2, 3, 4, 5, 6, 30, 40, 50, 60], [True] * 4 + [False, False] + [True] * 4)
    assert mixed["median"] == 30 and mixed["median"] > 4.5


def test_no_items_gives_nothing():
    assert stats.km_median([], [])["median"] is None


def test_community_first_answers_report_the_median_with_waiting_items_kept_in():
    from stackvitals.community.analyze import first_answer

    def item(n, hours_open, answered_after=None):
        cr = (NOW - timedelta(hours=hours_open)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cm = [[(NOW - timedelta(hours=hours_open - answered_after)).strftime("%Y-%m-%dT%H:%M:%SZ"), "maint", "MEMBER", "User"]] \
            if answered_after is not None else []
        return {"t": "issue", "n": n, "cr": cr, "au": f"user{n}", "as": "NONE", "cm": cm, "st": "OPEN"}
    issues = [item(n, 200, 2) for n in range(5)] + [item(10 + n, 150) for n in range(6)]
    out = first_answer([], issues, NOW, ins={"maint"})["issues"]
    assert out["median_hours"] == pytest.approx(2.0) and out["km"]["median"] is None and out["km"]["at_least"] == 150
    assert out["km"]["waiting"] == 6


def _ts(days, hours=0):
    return (NOW - timedelta(days=days) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _issue(n, au, days, cm=(), as_="NONE"):
    return {"t": "issue", "n": n, "cr": _ts(days), "au": au, "as": as_, "cm": list(cm), "st": "OPEN"}


def _pr(n, au, days, ev=()):
    return {"t": "pr", "n": n, "cr": _ts(days), "au": au, "as": "NONE", "at": "User", "ev": list(ev), "cm": [], "st": "OPEN"}


def _rev(days, who, hours=1):
    return ["review", _ts(days, hours), who, "COMMENTED", "CONTRIBUTOR", "User", False]


def test_regular_responders_answer_others_issues_or_first_review_others_prs():
    from stackvitals.community.analyze import regular_responders
    issues = [_issue(n, f"u{n}", 30 + n, cm=[[_ts(30 + n, 1), "helper", "CONTRIBUTOR", "User"],
                                              [_ts(30 + n, 2), "ci-bot[bot]", "NONE", "Bot"],
                                              [_ts(30 + n, 3), "maint", "MEMBER", "User"]]) for n in range(10)]
    issues += [_issue(20 + n, f"v{n}", 30 + n, cm=[[_ts(30 + n, 1), "nine", "NONE", "User"]]) for n in range(9)]
    issues += [_issue(40 + n, f"w{n}", 400 + n, cm=[[_ts(400 + n, 1), "old", "NONE", "User"]]) for n in range(10)]
    issues += [_issue(60 + n, "self", 20 + n, cm=[[_ts(20 + n, 1), "self", "NONE", "User"]]) for n in range(10)]
    # rev gave the first review on two other people's PRs; late came second on two.
    prs = [_pr(1, "a", 10, ev=[_rev(10, "rev"), _rev(10, "late", 5)]), _pr(2, "b", 12, ev=[_rev(12, "rev"), _rev(12, "late", 5)]),
           _pr(3, "rev", 14, ev=[_rev(14, "rev")])]
    assert regular_responders(prs, issues, {"maint"}, NOW) == {"helper", "rev"}


def test_a_regular_responders_reply_answers_an_issue_but_a_pr_still_needs_a_maintainer():
    from stackvitals.community.analyze import first_answer, newcomers_waiting
    reg = [_issue(n, f"u{n}", 200 + n, cm=[[_ts(200 + n, 1), "helper", "CONTRIBUTOR", "User"]]) for n in range(10)]
    fresh = [_issue(100 + n, f"x{n}", 20, cm=[[_ts(20, 3), "helper", "CONTRIBUTOR", "User"]]) for n in range(4)]
    prs = [_pr(1, "y", 20, ev=[["review", _ts(20, 3), "helper", "COMMENTED", "CONTRIBUTOR", "User", False]])]
    out = first_answer(prs, reg + fresh, NOW, ins={"maint"})
    assert out["issues"]["items"] == 4 and out["issues"]["answered"] == 1.0 and out["issues"]["median_hours"] == 3.0
    assert out["issues"]["responders"] == 1 and out["prs"]["answered"] == 0.0
    # The roles-only rule stays available for the comparison.
    assert first_answer(prs, reg + fresh, NOW, ins={"maint"}, resp={"maint"})["issues"]["answered"] == 0.0
    assert not [w for w in newcomers_waiting(prs, reg + fresh, NOW, {"maint"}) if w["kind"] == "issue" and w["n"] >= 100]


def test_the_report_says_the_answered_only_median_and_the_one_counting_waiting_items():
    from stackvitals.community.report import _sections
    base = {"items": 20, "answered": 0.4, "median_hours": 2.0, "within_1d": 0.4, "earlier": 0}
    r = {"funnel": {"newcomers": 0, "judged": 0, "returned": 0, "return_rate": None, "regulars": 0, "maintainers": 1},
         "answers": {"days": 90, "prs": {**base, "km": {"median": None, "at_least": 300.0, "waiting": 12, "answered": 8}},
                     "issues": {**base, "km": {"median": 30.0, "low": 12.0, "high": 80.0, "waiting": 4, "answered": 16, "at_least": None}},
                     "left_out": None}}
    r["answers"]["issues"]["responders"] = 2
    lines = dict(_sections(r))["First answers by the project, last 90 days"]
    assert ("Issues count a reply from a maintainer or one of 2 regular responders (people who answered 10 or more "
            "others' issues or first-reviewed 2 or more others' PRs in the last year); PRs count a maintainer's.") in lines
    assert ("Outside PRs: 20, answered 40%, first answer after 2 h among those answered, within a day 40%; counting the 12 "
            "still waiting, over 12.5 d (more than half have no answer yet).") in " ".join(lines)
    assert "counting the 4 still waiting, 30 h (likely 12 h to 3.3 d)." in " ".join(lines)


def test_community_publishes_this_weeks_first_answers_against_the_weeks_before():
    # Review finding: the digest read Community's weekly changes, which nothing wrote (Phase 13 M1 task 3).
    from stackvitals.community.analyze import weekly_changes
    issues = [_issue(n, f"u{n}", 2 + (n % 30), cm=[[_ts(2 + (n % 30), 3), "maint", "MEMBER", "User"]]) for n in range(40)]
    found = weekly_changes([], issues, NOW, ins={"maint"})
    row = next(c for c in found if c["metric"] == "community.first_answer")
    assert row["unit"] == "h" and row["n_now"] > 0 and row["n_base"] > 0 and "changed" in row
