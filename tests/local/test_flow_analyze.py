from datetime import datetime, timedelta, timezone

from stackvitals.flow.analyze import analyze, stages, who_acts_next

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def at(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, ev=(), st="OPEN", cr=100, mg=None, au="alice", assoc="CONTRIBUTOR", kind="User", rq=(), cm=(), ci="SUCCESS",
       lc=90, draft=False):
    return {"t": "pr", "n": n, "ti": f"PR {n}", "draft": draft, "st": st, "cr": at(cr), "up": at(1),
            "mg": at(mg) if mg is not None else None, "cl": at(mg) if mg is not None else None, "add": 10, "del": 1,
            "files": 1, "au": au, "at": kind, "as": assoc, "rq": list(rq), "ev": list(ev), "cm": list(cm), "ci": ci,
            "lc": at(lc)}


def rv(hours, who, state="APPROVED", kind="User", assoc="MEMBER"):
    return ["review", at(hours), who, state, assoc, kind]


def test_stages_follow_githubs_boundaries_and_skip_bots_and_the_author():
    p = pr(1, st="MERGED", cr=100, mg=68, ev=[["ready", at(98)], ["req", at(97), "bob"], rv(96, "sourcery-ai", kind="Bot"),
                                               rv(95, "alice", "COMMENTED", assoc="CONTRIBUTOR"), rv(90, "bob", "COMMENTED"),
                                               rv(70, "bob"), ["merged", at(68), "bob"]])
    s = stages(p)
    assert s["pickup"] == 8 * 3600 and s["review"] == 20 * 3600 and s["merge"] == 2 * 3600 and s["cycle"] == 30 * 3600


def test_a_pr_merged_without_any_human_review_has_no_pickup():
    s = stages(pr(2, st="MERGED", mg=50, ev=[["merged", at(50), "alice"]]))
    assert s["pickup"] is None and s["reviewed"] is False and s["cycle"] == 50 * 3600


def test_who_acts_next_names_the_person_and_the_event_that_put_the_ball_there():
    assert who_acts_next(pr(1, draft=True), NOW)["actor"] == "nobody"
    w = who_acts_next(pr(2, ev=[["req", at(50), "carol"]], rq=["carol"]), NOW)
    assert w["actor"] == "reviewers" and w["who"] == ["carol"] and w["since"] == at(50)
    w = who_acts_next(pr(3, ev=[rv(30, "bob", "CHANGES_REQUESTED")], lc=40), NOW)
    assert w["actor"] == "author" and w["who"] == ["alice"] and "bob" in w["why"]
    w = who_acts_next(pr(4, ev=[rv(30, "bob", "CHANGES_REQUESTED")], lc=20), NOW)
    assert w["actor"] == "reviewers" and w["who"] == ["bob"] and w["since"] == at(20)
    w = who_acts_next(pr(5, ev=[rv(30, "bob")]), NOW)
    assert w["actor"] == "maintainers" and "approved" in w["why"] and w["since"] == at(30)
    w = who_acts_next(pr(6), NOW)
    assert w["actor"] == "maintainers" and "nobody" in w["why"] and w["since"] == at(100)
    w = who_acts_next(pr(7, ci="FAILURE", ev=[["req", at(50), "carol"]], rq=["carol"]), NOW)
    assert w["actor"] == "author" and "check" in w["why"]
    w = who_acts_next(pr(8, cm=[[at(20), "bob", "MEMBER", "User"]]), NOW)
    assert w["actor"] == "author" and w["since"] == at(20)
    w = who_acts_next(pr(9, cm=[[at(20), "bob", "MEMBER", "User"], [at(10), "alice", "CONTRIBUTOR", "User"]]), NOW)
    assert w["actor"] == "maintainers" and w["since"] == at(10)


def test_the_queue_flags_waits_longer_than_this_repos_usual_and_counts_open_requests():
    closed = [pr(100 + k, st="MERGED", cr=500 + k, mg=480 + k, ev=[["req", at(499 + k), "bob"], rv(495 + k, "bob"),
                                                                      ["merged", at(480 + k), "bob"]]) for k in range(10)]
    waiting = pr(1, ev=[["req", at(50), "carol"]], rq=["carol"])
    fresh = pr(2, cr=3, ev=[["req", at(2), "carol"]], rq=["carol"])
    bot = pr(3, au="dependabot[bot]", kind="Bot")
    out = analyze({"open": [waiting, fresh, bot], "closed": closed}, NOW)
    q = {i["n"]: i for i in out["queue"]}
    assert q[1]["slow"] and not q[2]["slow"] and 3 not in q
    assert out["load"] == [{"reviewer": "carol", "open_requests": 2, "oldest_since": at(50)}]
    assert out["stages"]["pickup"]["median_s"] == 5 * 3600 and out["stages"]["pickup"]["n"] == 10
    assert out["bots"]["open"] == 1 and "responders" not in out


def test_outsiders_and_insiders_are_measured_apart_and_people_speed_stays_private_unless_asked():
    # One login is one person: the outsider PRs come from someone else, not from the member under another label.
    closed = [pr(10, st="MERGED", cr=300, mg=200, assoc="MEMBER", ev=[rv(290, "bob"), ["merged", at(200), "bob"]]),
              pr(11, st="MERGED", cr=300, mg=100, au="newbie", assoc="NONE", ev=[rv(250, "bob"), ["merged", at(100), "bob"]]),
              pr(12, st="CLOSED", cr=300, mg=None, au="newbie", assoc="NONE")]
    closed[2]["cl"] = at(150)
    out = analyze({"open": [], "closed": closed}, NOW, people_speed=True)
    assert out["groups"]["insider"]["merged"] == 1 and out["groups"]["outsider"]["merged"] == 1
    assert out["groups"]["outsider"]["closed_unmerged"] == 1 and out["groups"]["outsider"]["merge_rate"] == 0.5
    assert out["responders"][0]["reviewer"] == "bob"


def test_slow_needs_a_day_at_least_and_old_waits_become_stale_backlog():
    closed = [pr(100 + k, st="MERGED", cr=500 + k, mg=494.9 + k, ev=[rv(495 + k, "bob"), ["merged", at(494.9 + k), "bob"]])
              for k in range(10)]
    approved = pr(1, ev=[rv(2, "bob")])
    ancient = pr(2, cr=24 * 60, ev=[["req", at(24 * 50), "carol"]], rq=["carol"])
    overdue = pr(3, ev=[["req", at(50), "carol"]], rq=["carol"])
    out = analyze({"open": [approved, ancient, overdue], "closed": closed}, NOW)
    q = {i["n"]: i for i in out["queue"]}
    assert not q[1]["slow"] and q[3]["slow"] and not q[3]["stale"] and q[2]["stale"]
    assert [i["n"] for i in out["queue"]][:2] == [3, 1] and out["queue"][-1]["n"] == 2


def test_outsider_prs_are_compared_with_how_long_outsiders_usually_wait():
    fast_insiders = [pr(100 + k, st="MERGED", cr=900 + k, mg=880 + k, assoc="MEMBER",
                        ev=[rv(899 + k, "bob"), ["merged", at(880 + k), "bob"]]) for k in range(30)]
    slow_outsiders = [pr(200 + k, st="MERGED", cr=900 + k, mg=800 + k, au="newbie", assoc="NONE",
                         ev=[rv(840 + k, "bob"), ["merged", at(800 + k), "bob"]]) for k in range(10)]
    waiting = pr(1, au="newbie", assoc="NONE", cr=40, ev=[["req", at(40), "bob"]], rq=["bob"])
    out = analyze({"open": [waiting], "closed": fast_insiders + slow_outsiders}, NOW)
    assert out["queue"][0]["slow"] is False and out["queue"][0]["usual_s"] >= 60 * 3600


def test_only_maintainers_reviews_decide_who_holds_the_ball():
    # Real finding (uv #21758): a passer-by's "request changes" put the PR on them.
    w = who_acts_next(pr(1, ev=[rv(30, "passerby", "CHANGES_REQUESTED", assoc="NONE")]), NOW)
    assert w["actor"] == "maintainers" and w["step"] == "pickup"
    w = who_acts_next(pr(2, ev=[rv(30, "passerby", "APPROVED", assoc="CONTRIBUTOR")]), NOW)
    assert w["actor"] == "maintainers" and "approved" not in w["why"]


def test_a_stacked_pr_waits_for_its_parent_not_for_reviewers():
    parent = pr(1, ev=[["req", at(50), "carol"]], rq=["carol"]) | {"head": "feat-a", "ho": "o", "base": "main"}
    child = pr(2, ev=[["req", at(40), "carol"]], rq=["carol"]) | {"head": "feat-b", "ho": "o", "base": "feat-a"}
    out = analyze({"open": [parent, child], "closed": []}, NOW, owner="o")
    assert [q["n"] for q in out["queue"]] == [1]
    w = who_acts_next(child, NOW, heads={"feat-a": 1})
    assert w["actor"] == "nobody" and "#1" in w["why"]


# Hand-check of 51 real open PRs (10 wrong, 7 debatable): each rule below fixes one of the patterns found.
def test_merge_conflicts_and_ci_waiting_for_approval_decide_first():
    w = who_acts_next(pr(1, rq=["carol"], ev=[["req", at(50), "carol"]]) | {"mgs": "CONFLICTING"}, NOW)
    assert w["actor"] == "author" and "conflict" in w["why"]
    w = who_acts_next(pr(2, ci="FAILURE") | {"chk": {"failing": [["docs", True]], "awaiting": True, "required_any": True}}, NOW)
    assert w["actor"] == "maintainers" and "approv" in w["why"]


def test_only_required_failing_checks_put_the_pr_on_the_author():
    flaky = {"failing": [["Build&Test: node-24", False]], "awaiting": False, "required_any": True}
    w = who_acts_next(pr(1, ci="FAILURE", rq=["bluwy"], ev=[["req", at(50), "bluwy"]]) | {"chk": flaky}, NOW)
    assert w["actor"] == "reviewers" and w["who"] == ["bluwy"]
    broken = {"failing": [["Lint", True]], "awaiting": False, "required_any": True}
    assert who_acts_next(pr(2, ci="FAILURE") | {"chk": broken}, NOW)["actor"] == "author"


def test_a_check_failing_on_many_open_prs_at_once_is_infrastructure_not_the_author():
    chk = {"failing": [["docs/readthedocs.org:tox", True]], "awaiting": False, "required_any": True}
    prs = [pr(k, ci="FAILURE", rq=["gab"], ev=[["req", at(20), "gab"]], au=f"a{k}") | {"chk": chk} for k in range(1, 4)]
    out = analyze({"open": prs, "closed": []}, NOW)
    assert {q["actor"] for q in out["queue"]} == {"reviewers"}


def test_a_rebase_is_not_an_answer_to_requested_changes():
    w = who_acts_next(pr(1, ev=[rv(30, "bob", "CHANGES_REQUESTED")], lc=5) | {"la": at(60)}, NOW)
    assert w["actor"] == "author"
    w = who_acts_next(pr(2, ev=[rv(30, "bob", "CHANGES_REQUESTED")], lc=5) | {"la": at(5)}, NOW)
    assert w["actor"] == "reviewers"


def test_waiting_counts_from_the_latest_re_request():
    w = who_acts_next(pr(1, rq=["carol"], ev=[["req", at(200), "carol"], ["req", at(20), "carol"]]), NOW)
    assert w["since"] == at(20)


def test_a_maintainer_comment_puts_the_pr_on_the_author_only_when_it_asks_something():
    asks = pr(1, cm=[[at(20), "bob", "MEMBER", "User", True]])
    says = pr(2, cm=[[at(20), "bob", "MEMBER", "User", False]])
    assert who_acts_next(asks, NOW)["actor"] == "author"
    assert who_acts_next(says, NOW)["actor"] == "maintainers"


def test_an_approved_pr_written_by_a_maintainer_waits_on_that_maintainer():
    w = who_acts_next(pr(1, assoc="MEMBER", au="zanieb", ev=[rv(30, "konstin")]), NOW)
    assert w["actor"] == "author" and w["who"] == ["zanieb"] and "approved" in w["why"]


def test_non_required_failures_count_unless_a_reviewer_was_asked_and_noisy_bots_never_count():
    # Re-scoring: black's changelog check and poetry's test jobs aren't required, but they are the author's to fix.
    changelog = {"failing": [["check-changelog", False]], "awaiting": False, "required_any": True}
    assert who_acts_next(pr(1, ci="FAILURE") | {"chk": changelog}, NOW)["actor"] == "author"
    perf = {"failing": [["CodSpeed Performance Analysis", False]], "awaiting": False, "required_any": True}
    assert who_acts_next(pr(2, ci="FAILURE") | {"chk": perf}, NOW)["actor"] == "maintainers"


def test_shared_breakage_means_failing_on_nearly_every_recent_pr_that_ran_the_check():
    # Re-scoring: black's changelog check fails on many PRs because many authors forget it; that is still each author's.
    chk = lambda failing: {"failing": [["check", False]] if failing else [], "ran": ["check"], "awaiting": False,  # noqa: E731
                           "required_any": False}
    prs = [pr(k, ci="FAILURE", au=f"a{k}") | {"chk": chk(True)} for k in range(1, 4)]
    prs += [pr(k, au=f"a{k}") | {"chk": chk(False)} for k in range(4, 9)]
    out = analyze({"open": prs, "closed": []}, NOW)
    assert {q["actor"] for q in out["queue"] if q["n"] < 4} == {"author"}
    broken = [pr(k, ci="FAILURE", au=f"a{k}") | {"chk": chk(True)} for k in range(1, 4)]
    assert {q["actor"] for q in analyze({"open": broken, "closed": []}, NOW)["queue"]} == {"maintainers"}


def test_a_question_is_answered_by_any_push_but_requested_changes_need_new_work():
    asked = pr(1, ev=[rv(30, "bob", "COMMENTED")], lc=10) | {"la": at(60)}
    assert who_acts_next(asked, NOW)["actor"] == "maintainers"
    blocked = pr(2, ev=[rv(30, "bob", "CHANGES_REQUESTED")], lc=10) | {"la": at(60)}
    assert who_acts_next(blocked, NOW)["actor"] == "author"
