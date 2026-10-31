"""A flaky test keeps one issue for its whole life: closed as "not planned" means the team decided to live with it (it
stays closed, nothing new is opened), closed as done while still flaky means it is reopened with fresh evidence, and the
first code owner who is a person can be assigned."""
from stackvitals.ci.api import APIError
from stackvitals.ci.automation import sync_issues


class Api:
    repo = "o/r"

    def __init__(self, issues, refuse_assignees=False):
        self.issues, self.refuse_assignees, self.sent = issues, refuse_assignees, []

    def _get(self, path, params=None):
        assert params["state"] == "all" and params["labels"] == "flaky-test"
        return self.issues if params.get("page", 1) == 1 else []

    def send(self, method, path, body=None):
        if self.refuse_assignees and body and body.get("assignees"):
            raise APIError("POST /repos/o/r/issues: HTTP 422 invalid assignee")
        self.sent.append((method, path, body))
        return {}


def flaky(test_id, owners=None):
    return {"id": test_id, "state": "flaky", "flake_events": 3, "runs": 40, "last_flake": "2026-10-20T10:00:00Z",
            "owners": owners or []}


def result(*tests):
    return {"tests": list(tests), "jobs": []}


def test_closed_as_not_planned_stays_closed_and_no_duplicate_is_opened():
    api = Api([{"number": 7, "title": "Flaky test: t::a", "state": "closed", "state_reason": "not_planned"}])
    counts = sync_issues(api, result(flaky("t::a")))
    assert api.sent == [] and counts["created"] == 0 and counts["kept_closed"] == 1


def test_closed_as_done_while_still_flaky_is_reopened_with_evidence():
    api = Api([{"number": 8, "title": "Flaky test: t::b", "state": "closed", "state_reason": "completed"}])
    counts = sync_issues(api, result(flaky("t::b")))
    assert counts["reopened"] == 1 and counts["created"] == 0
    (m1, p1, b1), (m2, p2, b2) = api.sent
    assert (m1, p1, b1["state"]) == ("PATCH", "/repos/o/r/issues/8", "open")
    assert m2 == "POST" and p2 == "/repos/o/r/issues/8/comments" and "3 times" in b2["body"]


def test_the_newest_issue_with_a_title_decides():
    api = Api([{"number": 3, "title": "Flaky test: t::c", "state": "closed", "state_reason": "completed"},
               {"number": 9, "title": "Flaky test: t::c", "state": "open", "state_reason": None}])
    counts = sync_issues(api, result(flaky("t::c")))
    assert counts["updated"] == 1 and api.sent[0][1] == "/repos/o/r/issues/9"


def test_the_first_person_among_the_owners_is_assigned_when_asked():
    api = Api([])
    sync_issues(api, result(flaky("t::d", owners=["@org/core", "@alice", "@bob"])), assign_owners=True)
    assert api.sent[0][2]["assignees"] == ["alice"]
    quiet = Api([])
    sync_issues(quiet, result(flaky("t::d", owners=["@alice"])))
    assert "assignees" not in quiet.sent[0][2]


def test_an_owner_who_cannot_be_assigned_still_gets_the_issue_opened():
    api = Api([], refuse_assignees=True)
    counts = sync_issues(api, result(flaky("t::e", owners=["@outside"])), assign_owners=True)
    assert counts["created"] == 1 and "assignees" not in api.sent[0][2]
