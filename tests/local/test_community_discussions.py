from datetime import datetime, timezone

from stackvitals.community.analyze import first_answer
from stackvitals.community.collect import collect_discussions
from stackvitals.flow.store import FlowStore

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


class Result:
    def __init__(self, data):
        self.data, self.cost = data, 1


class Gql:
    def __init__(self, nodes):
        self.nodes, self.calls = nodes, 0

    def query(self, q, v):
        self.calls += 1
        return Result({"repository": {"discussions": {"nodes": self.nodes, "pageInfo": {"hasNextPage": False}}}})


def node(n, created, comments, closed=None, chosen=None, author="newbie", assoc="NONE", category="Q&A"):
    return {"number": n, "createdAt": created, "updatedAt": created, "closed": bool(closed), "closedAt": closed,
            "author": {"__typename": "User", "login": author}, "authorAssociation": assoc,
            "category": {"name": category, "isAnswerable": category == "Q&A"}, "answerChosenAt": chosen,
            "comments": {"totalCount": len(comments), "nodes": [{"createdAt": t, "author": {"__typename": "User", "login": who},
                                                                  "authorAssociation": a} for t, who, a in comments]}}


def test_discussions_are_kept_like_issues_and_answered_by_the_project_rule(tmp_path):
    nodes = [node(1, "2026-10-01T10:00:00Z", [("2026-10-01T12:00:00Z", "peer", "NONE"), ("2026-10-02T10:00:00Z", "maint", "MEMBER")],
                  chosen="2026-10-02T11:00:00Z"),
             node(2, "2026-10-05T10:00:00Z", [("2026-10-05T11:00:00Z", "peer", "NONE")]),
             node(3, "2026-10-06T10:00:00Z", [], author="maint", assoc="MEMBER")]
    store = FlowStore(tmp_path, "community/discussions")
    got = collect_discussions(Gql(nodes), store, "o", "r", NOW)
    data = store.load()
    recs = {r["n"]: r for r in data["open"] + data["closed"]}
    assert got["discussions"] == 3 and recs[1]["t"] == "discussion" and recs[1]["ans"] == "2026-10-02T11:00:00Z"
    assert recs[1]["cat"] == "Q&A" and "body" not in str(recs)
    out = first_answer([], [], NOW, discussions=data["open"] + data["closed"], ins={"maint"})
    d = out["discussions"]
    # Only the maintainer's reply counts (24 hours after opening); the peer's doesn't; the maintainer's own post isn't outside.
    assert d["items"] == 2 and d["median_hours"] == 24.0 and d["answer_chosen"] == 0.5
