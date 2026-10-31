from datetime import datetime, timedelta, timezone

from mergescout.github.graphql import NotFound
from mergescout.measure.api_cost import PR_HISTORY_QUERY, measure_repo, walk_connection

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)
RECENT = (NOW - timedelta(days=10)).isoformat().replace("+00:00", "Z")
OLD = (NOW - timedelta(days=400)).isoformat().replace("+00:00", "Z")


def page(nodes, has_next, cursor=None, conn="pullRequests"):
    return {"repository": {conn: {"pageInfo": {"hasNextPage": has_next, "endCursor": cursor}, "nodes": nodes}}}


def test_walk_stops_at_first_old_item(fake_gql):
    pages = {None: (page([{"createdAt": RECENT}] * 100, True, "c1"), 2),
             "c1": (page([{"createdAt": RECENT}] * 50 + [{"createdAt": OLD}] * 50, True, "c2"), 2)}
    gql = fake_gql(lambda q, v: pages[v["cursor"]])
    out = walk_connection(gql, PR_HISTORY_QUERY, "o", "r", "pullRequests", "createdAt",
                          NOW - timedelta(days=365), max_pages=30)
    assert out == {"pages": 2, "cost": 4, "items": 150, "capped": False}


def test_walk_marks_capped(fake_gql):
    gql = fake_gql(lambda q, v: (page([{"createdAt": RECENT}] * 100, True, "next"), 1))
    out = walk_connection(gql, PR_HISTORY_QUERY, "o", "r", "pullRequests", "createdAt",
                          NOW - timedelta(days=365), max_pages=3)
    assert out == {"pages": 3, "cost": 3, "items": 300, "capped": True}


def test_measure_repo_runs_all_three(fake_gql):
    def responder(query, variables):
        conn = "issues" if "issues(" in query else "pullRequests"
        return page([], False, conn=conn), 1

    out = measure_repo(fake_gql(responder), "o/r", NOW)
    assert out["status"] == "ok"
    assert out["full"]["cost"] == out["incremental"]["cost"] == out["issues"]["cost"] == 1


def test_measure_repo_not_found(fake_gql):
    def responder(query, variables):
        raise NotFound("Could not resolve to a Repository")

    assert measure_repo(fake_gql(responder), "gone/repo", NOW) == {"repo": "gone/repo", "status": "not_found"}
