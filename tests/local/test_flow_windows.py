from datetime import datetime, timedelta, timezone

from stackvitals.flow.analyze import analyze, who_acts_next
from stackvitals.flow.collect import pr_record

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def at(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def opr(n, pushed, failing=(), ran=("test (3.12)",), au=None, rq=(), ev=(), cm=()):
    return {"t": "pr", "n": n, "ti": f"PR {n}", "draft": False, "st": "OPEN", "cr": at(pushed + 5), "up": at(pushed),
            "mg": None, "cl": None, "add": 10, "del": 1, "files": 1, "au": au or f"a{n}", "at": "User", "as": "NONE",
            "rq": list(rq), "ev": list(ev), "cm": list(cm), "ci": "FAILURE" if failing else "SUCCESS", "lc": at(pushed),
            "chk": {"failing": [[f, True] for f in failing], "awaiting": False, "required_any": True, "ran": list(ran)}}


def actors(prs):
    return {q["n"]: q["actor"] for q in analyze({"open": prs, "closed": []}, NOW)["queue"]}


def test_breakage_is_judged_against_prs_pushed_around_the_same_time_not_todays():
    # fastapi#16387: a job failed on every PR around 09-22 and was fixed on main by 10-01; today's PRs pass it.
    then = [opr(k, pushed=25 * 24 + k, failing=["test (3.12)"]) for k in range(1, 5)]
    today = [opr(10 + k, pushed=48 + k) for k in range(3)]
    lone = opr(20, pushed=30, failing=["test (3.12)"])
    got = actors(then + today + [lone])
    assert all(got[k] == "maintainers" for k in range(1, 5))
    # Failing now, while PRs pushed around it pass the same job: still the author's.
    assert got[20] == "author"


def test_breakage_in_a_quiet_repo_uses_the_nearest_prs_when_a_week_holds_too_few():
    # httpie: a PR every few days, the job broken on all of them; the last week alone has only two.
    prs = [opr(k, pushed=24 * 4 * k, failing=["test (3.12)"]) for k in range(6)]
    assert set(actors(prs).values()) == {"maintainers"}
    # Breakage that ended: the nearest PRs pass it, so this PR's failure is its own.
    old = [opr(k, pushed=24 * (40 + 4 * k), failing=["test (3.12)"]) for k in range(5)]
    got = actors(old + [opr(10 + k, pushed=24 * 4 * k) for k in range(1, 6)] + [opr(30, pushed=10, failing=["test (3.12)"])])
    assert got[30] == "author"


def rv(hours, who, state="APPROVED", raised=None):
    e = ["review", at(hours), who, state, "MEMBER", "User"]
    return e + [raised] if raised is not None else e


def test_a_later_review_that_raises_points_reopens_an_approval():
    # mypy#22180: approved, then a second maintainer raised issues in a comment-only review; the author agreed to fix.
    p = opr(1, pushed=100, ev=[rv(90, "hauntsaninja"), rv(20, "JukkaL", "COMMENTED", True)])
    w = who_acts_next(p, NOW)
    assert w["actor"] == "author" and w["since"] == at(20) and "JukkaL" in w["why"]
    # A plain "looks good" comment-review keeps the approval.
    assert who_acts_next(opr(2, pushed=100, ev=[rv(90, "a"), rv(20, "b", "COMMENTED", False)]), NOW)["step"] == "merge"
    # Records saved before the flag existed behave as before.
    assert who_acts_next(opr(3, pushed=100, ev=[rv(90, "a"), rv(20, "b", "COMMENTED")]), NOW)["step"] == "merge"
    # New work after the points were raised: back to that reviewer.
    w = who_acts_next(opr(4, pushed=5, ev=[rv(90, "a"), rv(20, "b", "COMMENTED", True)]), NOW)
    assert w["actor"] == "reviewers" and w["who"] == ["b"] and w["since"] == at(5)


def review_node(body, inline):
    return {"__typename": "PullRequestReview", "submittedAt": at(3), "state": "COMMENTED", "author": {"__typename": "User", "login": "m"},
            "authorAssociation": "MEMBER", "body": body, "comments": {"totalCount": inline}}


def test_collect_marks_reviews_that_raise_something_and_never_keeps_their_text():
    node = {"number": 7, "title": "x", "state": "OPEN", "createdAt": at(9), "updatedAt": at(1), "author": {"login": "zed"},
            "events": {"nodes": [review_node("Could this use a set?", 0), review_node("", 2), review_node("LGTM", 0),
                                 review_node("@zed see above", 0)]}}
    rec = pr_record(node, NOW)
    assert [e[6] for e in rec["ev"]] == [True, True, False, True]
    assert "set?" not in str(rec) and "LGTM" not in str(rec)


def test_one_authors_repeated_mistake_is_not_breakage_for_everyone():
    # psf/black#5555: one person opened five PRs, all missing the changelog line the "check" job wants.
    same = [opr(k, pushed=2 + k, failing=["check"], ran=("check",), au="ump45nose") for k in range(1, 6)]
    other = [opr(10, pushed=4, ran=("check",))]
    assert set(actors(same + other)[k] for k in range(1, 6)) == {"author"}
