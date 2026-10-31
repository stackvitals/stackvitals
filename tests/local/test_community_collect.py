from datetime import datetime, timedelta, timezone

from stackvitals.community.collect import ISSUES_QUERY, collect_issues
from stackvitals.flow.store import FlowStore

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def issue(n, updated_days, state="OPEN", closed_days=None, author="newbie", assoc="NONE", comments=()):
    return {"number": n, "state": state, "createdAt": iso(NOW - timedelta(days=updated_days + 5)),
            "updatedAt": iso(NOW - timedelta(days=updated_days)),
            "closedAt": iso(NOW - timedelta(days=closed_days)) if closed_days is not None else None,
            "author": {"__typename": "User", "login": author}, "authorAssociation": assoc,
            "comments": {"totalCount": len(comments), "nodes": [
                {"createdAt": iso(NOW - timedelta(days=d)), "author": {"__typename": t, "login": who}, "authorAssociation": a}
                for d, who, a, t in comments]}}


def pages(*blocks):
    def responder(query, variables):
        assert query == ISSUES_QUERY
        i = int(variables["cursor"] or 0)
        nodes, more = blocks[i]
        return {"repository": {"issues": {"pageInfo": {"hasNextPage": more, "endCursor": str(i + 1)}, "nodes": nodes}}}, 1
    return responder


def test_the_store_can_live_in_another_folder_of_the_data_branch(tmp_path):
    store = FlowStore(tmp_path, "community/issues")
    assert (tmp_path / "community" / "issues" / "closed").is_dir() and FlowStore(tmp_path).dir == tmp_path / "flow"


def test_issues_are_read_newest_first_and_split_into_open_and_closed_by_day(tmp_path, fake_gql):
    store = FlowStore(tmp_path, "community/issues")
    gql = fake_gql(pages(([issue(1, 1, comments=[(2, "maint", "MEMBER", "User")]), issue(2, 3, "CLOSED", 3)], True),
                         ([issue(3, 10, "CLOSED", 10, author="bot1", comments=[(9, "x", "NONE", "Bot")])], False)))
    out = collect_issues(gql, store, "o", "r", NOW)
    data = store.load()
    assert out == {"issues": 3, "points": 2, "complete": True}
    assert [r["n"] for r in data["open"]] == [1] and sorted(r["n"] for r in data["closed"]) == [2, 3]
    first = data["open"][0]
    assert first["au"] == "newbie" and first["as"] == "NONE" and first["cm"][0][1:] == ["maint", "MEMBER", "User"]
    assert store.state()["synced_up_to"] == iso(NOW - timedelta(days=1))


def test_a_later_run_reads_only_what_changed_since_and_closes_open_issues(tmp_path, fake_gql):
    store = FlowStore(tmp_path, "community/issues")
    collect_issues(fake_gql(pages(([issue(1, 5)], False))), store, "o", "r", NOW - timedelta(days=4))
    later = fake_gql(pages(([issue(1, 0, "CLOSED", 0), issue(7, 400)], False)))  # #7 is older than the last sync
    out = collect_issues(later, store, "o", "r", NOW)
    data = store.load()
    assert out["issues"] == 1 and data["open"] == [] and [r["n"] for r in data["closed"]] == [1]
    assert later.calls[0][1]["since"] < iso(NOW - timedelta(days=4))


def test_a_first_run_reads_a_year_and_stops_at_githubs_hourly_limit(tmp_path, fake_gql):
    from mergescout.github.graphql import RateLimited
    store = FlowStore(tmp_path, "community/issues")
    calls = []

    def responder(query, variables):
        calls.append(variables)
        if variables["cursor"]:
            raise RateLimited("hourly limit")
        return {"repository": {"issues": {"pageInfo": {"hasNextPage": True, "endCursor": "1"}, "nodes": [issue(1, 2)]}}}, 1
    out = collect_issues(fake_gql(responder), store, "o", "r", NOW)
    assert out["complete"] is False and "synced_up_to" not in store.state() and store.load()["open"][0]["n"] == 1
    assert calls[0]["since"] == iso(NOW - timedelta(days=360))


def test_who_closed_a_pr_or_an_issue_is_kept_so_self_closes_are_not_answers():
    from stackvitals.community.collect import issue_record
    from stackvitals.flow.collect import _event
    assert _event({"__typename": "ClosedEvent", "createdAt": "2026-10-01T00:00:00Z", "actor": {"login": "amy"}}) == \
        ["closed", "2026-10-01T00:00:00Z", "amy"]
    node = {**issue(9, 3, "CLOSED", 2), "closer": {"nodes": [{"createdAt": iso(NOW - timedelta(days=2)), "actor": {"login": "newbie"}}]}}
    assert issue_record(node, NOW)["clb"] == "newbie" and "closer" in ISSUES_QUERY
