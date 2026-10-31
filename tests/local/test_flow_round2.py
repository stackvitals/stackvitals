from datetime import datetime, timedelta, timezone

from stackvitals.flow.analyze import who_acts_next
from stackvitals.flow.collect import pr_record

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def at(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n=1, au="ann", rq=(), ev=(), cm=(), cmt=None, lb=None, lbe=None, failing=None, lc=300):
    p = {"t": "pr", "n": n, "ti": "x", "draft": False, "st": "OPEN", "cr": at(400), "up": at(1), "mg": None, "cl": None,
         "add": 10, "del": 1, "files": 1, "au": au, "at": "User", "as": "NONE", "rq": list(rq), "ev": list(ev),
         "cm": list(cm), "ci": "FAILURE" if failing else "SUCCESS", "lc": at(lc), "la": at(lc)}
    if failing is not None:
        p["chk"] = {"failing": [[f, False] for f in failing], "awaiting": False, "required_any": True, "ran": list(failing)}
    if cmt is not None:
        p["cmt"] = cmt
    if lb is not None:
        p["lb"], p["lbe"] = lb, lbe or []
    return p


def cr(hours, who="edison"):
    return ["review", at(hours), who, "CHANGES_REQUESTED", "MEMBER", "User", True]


def commit(hours, who="ann", merge=False):
    return [at(hours), at(hours), who, merge]


def test_the_ball_moves_at_the_authors_first_response_not_a_later_ping():
    # vue#14965: fixed on 06-18, then "gentle follow-up" pings; the reviewers have owed a look since the fix.
    p = pr(ev=[cr(100)], cm=[[at(20), "ann", "NONE", "User", False]], cmt=[commit(80)], lc=80)
    w = who_acts_next(p, NOW)
    assert w["actor"] == "reviewers" and w["since"] == at(80)
    # tokio#8479: the author answered the maintainer, then chatted with a passer-by; the clock starts at the answer.
    talk = [[at(100), "darksonn", "MEMBER", "User", False], [at(60), "ann", "NONE", "User", False],
            [at(30), "passer", "NONE", "User", True], [at(10), "ann", "NONE", "User", False]]
    w = who_acts_next(pr(cm=talk), NOW)
    assert w["actor"] == "maintainers" and w["since"] == at(60)


def test_a_maintainers_merge_of_main_is_not_the_authors_new_work():
    # celery#10618: changes requested, then the maintainer merged main into the branch 7 seconds later.
    p = pr(ev=[cr(50, "auvipy")], cmt=[commit(300), commit(49, "auvipy", merge=True)], lc=49)
    w = who_acts_next(p, NOW)
    assert w["actor"] == "author" and w["since"] == at(50)


def test_many_failing_checks_are_the_authors_even_with_a_reviewer_asked():
    # celery#10202: linter, pre-commit and tests on every Python fail while main is green.
    broad = pr(rq=["auvipy"], ev=[["req", at(90), "auvipy"]], failing=["lint", "pre-commit", "test (3.12)", "test (3.11)"])
    assert who_acts_next(broad, NOW)["actor"] == "author"
    # One red job while a reviewer is asked stays with the reviewer (vite: a flaky Windows job).
    one = pr(rq=["auvipy"], ev=[["req", at(90), "auvipy"]], failing=["test (windows)"])
    assert who_acts_next(one, NOW)["actor"] == "reviewers"


def test_status_labels_set_by_maintainers_decide_when_nothing_newer_happened():
    # tokio#8430: a promise to implement, then S-waiting-on-author.
    p = pr(ev=[cr(200, "add-sp")], cm=[[at(100), "ann", "NONE", "User", True]], lb=["S-waiting-on-author", "A-tokio"],
           lbe=[[at(80), "+", "S-waiting-on-author"]])
    w = who_acts_next(p, NOW)
    assert w["actor"] == "author" and w["since"] == at(80) and "S-waiting-on-author" in w["why"]
    # A push after the label answers it: the label is stale, the usual rules apply.
    stale = pr(lb=["needs rebase"], lbe=[[at(80), "+", "needs rebase"]], cmt=[commit(20)], lc=20)
    assert "needs rebase" not in who_acts_next(stale, NOW)["why"]
    # vue#15891: "ready to merge" outranks an unrelated red e2e job.
    ready = pr(failing=["test / e2e-test"], lb=["ready to merge"], lbe=[[at(30), "+", "ready to merge"]])
    w = who_acts_next(ready, NOW)
    assert w["actor"] == "maintainers" and w["since"] == at(30)
    # celery#5170: "Status: Needs Test Coverage" from years ago, nothing since.
    old = pr(lb=["Status: Needs Test Coverage"], lbe=[[at(70000), "+", "Status: Needs Test Coverage"]], lc=70100)
    assert who_acts_next(old, NOW)["actor"] == "author"
    # A label with no known time (older than the last label events read) is not used.
    assert who_acts_next(pr(lb=["S-waiting-on-author"], lbe=[]), NOW)["actor"] == "maintainers"


def test_collect_keeps_labels_label_times_and_who_made_the_last_commits():
    node = {"number": 7, "title": "x", "state": "OPEN", "createdAt": at(9), "updatedAt": at(1), "author": {"login": "ann"},
            "labels": {"nodes": [{"name": "S-waiting-on-author"}]},
            "marks": {"nodes": [{"__typename": "LabeledEvent", "createdAt": at(5), "label": {"name": "S-waiting-on-author"}},
                                {"__typename": "UnlabeledEvent", "createdAt": at(4), "label": {"name": "needs review"}}]},
            "recent": {"nodes": [{"commit": {"authoredDate": at(8), "committedDate": at(7), "parents": {"totalCount": 1},
                                             "author": {"user": {"login": "ann"}}}},
                                 {"commit": {"authoredDate": at(3), "committedDate": at(3), "parents": {"totalCount": 2},
                                             "author": {"user": None}}}]}}
    rec = pr_record(node, NOW)
    assert rec["lb"] == ["S-waiting-on-author"]
    assert rec["lbe"] == [[at(5), "+", "S-waiting-on-author"], [at(4), "-", "needs review"]]
    assert rec["cmt"] == [[at(8), at(7), "ann", False], [at(3), at(3), None, True]]


def test_closed_prs_are_stored_without_fields_only_open_prs_need(tmp_path):
    # Labels, label times and commit authors only decide who acts next on open PRs; dropping them keeps history ~20% smaller.
    import sys
    sys.path.insert(0, "tests/local")
    from test_flow_collect import WithRepo, node
    from stackvitals.flow.collect import collect
    from stackvitals.flow.store import FlowStore
    extra = {"labels": {"nodes": [{"name": "S-waiting-on-author"}]},
             "marks": {"nodes": [{"__typename": "LabeledEvent", "createdAt": at(5), "label": {"name": "S-waiting-on-author"}}]},
             "recent": {"nodes": [{"commit": {"authoredDate": at(8), "committedDate": at(8), "parents": {"totalCount": 1},
                                              "author": {"user": {"login": "alice"}}}}]}}
    store = FlowStore(tmp_path)
    collect(WithRepo([node(1) | extra, node(2, state="MERGED", merged=3, closed=3) | extra]), store, "o", "r", NOW)
    data = store.load()
    assert data["open"][0]["lb"] == ["S-waiting-on-author"] and data["open"][0]["cmt"]
    # Closed PRs keep their labels (merged hotfix PRs are incidents) but not the rest.
    assert not {"lbe", "cmt"} & set(data["closed"][0]) and "lb" in data["closed"][0]


def test_who_acts_next_stays_fast_on_a_big_repo_with_many_failing_jobs():
    import random
    import time

    from stackvitals.flow.analyze import analyze
    rng, names = random.Random(1), [f"job {k}" for k in range(40)]
    opened = []
    for k in range(600):
        failing = rng.sample(names, rng.randrange(0, 25))
        opened.append(pr(k, au=f"u{k % 150}", failing=failing, lc=rng.randrange(24 * 120)) | {"chk": {
            "failing": [[f, False] for f in failing], "awaiting": False, "required_any": True, "ran": names}})
    t = time.time()
    analyze({"open": opened, "closed": []}, NOW)
    assert time.time() - t < 1.0
