from datetime import datetime, timedelta, timezone

from stackvitals.flow.analyze import who_acts_next
from stackvitals.flow.collect import pr_record

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def at(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n=1, au="ann", rq=(), ev=(), cm=(), lb=None, lbe=None, asg=None, mgs="MERGEABLE", lc=300):
    p = {"t": "pr", "n": n, "ti": "x", "draft": False, "st": "OPEN", "cr": at(400), "up": at(1), "mg": None, "cl": None,
         "add": 10, "del": 1, "files": 1, "au": au, "at": "User", "as": "NONE", "rq": list(rq), "ev": list(ev),
         "cm": list(cm), "ci": "SUCCESS", "lc": at(lc), "la": at(lc), "mgs": mgs}
    if lb is not None:
        p["lb"], p["lbe"] = lb, lbe or []
    if asg is not None:
        p["asg"] = asg
    return p


def test_an_assigned_reviewer_is_named_instead_of_unnamed_maintainers():
    # rust-clippy#17720: rustbot assigns the reviewer; nobody is in GitHub's review requests.
    w = who_acts_next(pr(asg=["blyxyas"]), NOW)
    assert w["actor"] == "reviewers" and w["who"] == ["blyxyas"]
    # An author who assigned themselves names nobody.
    assert who_acts_next(pr(asg=["ann"]), NOW)["actor"] == "maintainers"


def test_a_ready_label_dates_from_the_last_status_label_change():
    # rust-clippy#17655: waiting on community reviews until 09-20, then on the maintainers' review.
    events = [[at(500), "+", "S-waiting-on-community-reviews"], [at(500), "+", "S-waiting-on-review"],
              [at(100), "-", "S-waiting-on-community-reviews"]]
    w = who_acts_next(pr(lb=["S-waiting-on-review"], lbe=events, asg=["llogiq"]), NOW)
    assert w["actor"] == "reviewers" and w["who"] == ["llogiq"] and w["since"] == at(100)
    # Waiting on community reviews is a review wait too, not the author's.
    community = pr(lb=["S-waiting-on-community-reviews"], lbe=[[at(50), "+", "S-waiting-on-community-reviews"]])
    assert who_acts_next(community, NOW)["actor"] == "maintainers"


def test_a_conflict_dates_from_the_rebase_label_not_the_last_commit():
    # ansible: needs_rebase is set when main moves under the PR, often long after its last commit.
    p = pr(mgs="CONFLICTING", lb=["needs_rebase"], lbe=[[at(20), "+", "needs_rebase"]], lc=3000)
    w = who_acts_next(p, NOW)
    assert w["actor"] == "author" and w["since"] == at(20)
    assert who_acts_next(pr(mgs="CONFLICTING", lc=3000), NOW)["since"] == at(3000)


def test_collect_works_out_assignees_from_the_events_it_already_reads():
    # A separate assignees list costs a point more per page (2 -> 3 measured); assignment events share the label list.
    def ev(kind, hours, who):
        return {"__typename": kind, "createdAt": at(hours), "assignee": {"__typename": "User", "login": who}}
    node = {"number": 7, "title": "x", "state": "OPEN", "createdAt": at(9), "updatedAt": at(1), "author": {"login": "ann"},
            "marks": {"nodes": [ev("AssignedEvent", 8, "ada4a"), ev("AssignedEvent", 6, "llogiq"), ev("UnassignedEvent", 5, "ada4a"),
                                {"__typename": "LabeledEvent", "createdAt": at(4), "label": {"name": "S-waiting-on-review"}}]}}
    rec = pr_record(node, NOW)
    assert rec["asg"] == ["llogiq"] and rec["lbe"] == [[at(4), "+", "S-waiting-on-review"]]


def test_reports_show_waits_as_approximate():
    from stackvitals.flow.build import build
    from stackvitals.flow.report import render_html, render_markdown
    result = build({"open": [pr(asg=["llogiq"])], "closed": []}, {}, NOW, owner="o")
    assert "| about " in render_markdown(result, "o/r") and "<td>about " in render_html(result, "o/r")


def test_a_conflict_keeps_the_earlier_start_when_the_author_already_owed_work():
    # ansible#85711: changes requested in Aug 2025, needs_rebase only in Mar 2026; the author's turn began in August.
    cr = ["review", at(10000), "s-hertel", "CHANGES_REQUESTED", "MEMBER", "User", True]
    p = pr(ev=[cr], mgs="CONFLICTING", lb=["needs_rebase"], lbe=[[at(5000), "+", "needs_rebase"]], lc=10100)
    w = who_acts_next(p, NOW)
    assert w["actor"] == "author" and w["since"] == at(10000)


def test_the_authors_turn_runs_from_the_first_waiting_label_still_on():
    # ansible#85711: needs_revision (Aug 2025), then needs_rebase (Mar 2026); the author has owed work since August.
    p = pr(mgs="CONFLICTING", lb=["needs_revision", "needs_rebase"], lc=10100,
           lbe=[[at(10000), "+", "needs_revision"], [at(5000), "+", "needs_rebase"]])
    assert who_acts_next(p, NOW)["since"] == at(10000)
