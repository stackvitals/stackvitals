from datetime import datetime, timedelta, timezone

from stackvitals.flow.collect import collect, pr_record
from stackvitals.flow.store import FlowStore

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def at(hours):
    return iso(NOW - timedelta(hours=hours))


def node(n, state="OPEN", created=48, updated=1, events=(), requests=(), comments=(), draft=False, merged=None,
         closed=None, author="alice", assoc="CONTRIBUTOR", kind="User", ci="SUCCESS", last_commit=40):
    return {"number": n, "isDraft": draft, "state": state, "createdAt": at(created), "updatedAt": at(updated),
            "mergedAt": at(merged) if merged is not None else None, "closedAt": at(closed) if closed is not None else None,
            "additions": 10, "deletions": 2, "changedFiles": 1, "author": {"__typename": kind, "login": author},
            "authorAssociation": assoc, "baseRefName": "main", "headRefName": "fix", "headRepositoryOwner": {"login": author},
            "commits": {"nodes": [{"commit": {"committedDate": at(last_commit), "statusCheckRollup": {"state": ci}}}]},
            "reviewRequests": {"nodes": [{"requestedReviewer": {"__typename": "User", "login": r}} for r in requests]},
            "events": {"filteredCount": len(events), "nodes": list(events)},
            "talk": {"filteredCount": len(comments), "nodes": list(comments)}}


def review(hours, who, state="APPROVED", kind="User", assoc="MEMBER"):
    return {"__typename": "PullRequestReview", "submittedAt": at(hours), "state": state,
            "author": {"__typename": kind, "login": who}, "authorAssociation": assoc}


def test_a_pr_becomes_a_compact_record_with_its_events_in_order():
    rec = pr_record(node(7, events=[review(30, "bob", "CHANGES_REQUESTED"),
                                    {"__typename": "ReviewRequestedEvent", "createdAt": at(47),
                                     "requestedReviewer": {"__typename": "Team", "slug": "core"}},
                                    {"__typename": "ReadyForReviewEvent", "createdAt": at(47.5)}],
                        requests=["carol"], comments=[{"createdAt": at(20), "author": {"__typename": "User", "login": "alice"},
                                                       "authorAssociation": "CONTRIBUTOR"}]), NOW)
    assert rec["n"] == 7 and rec["au"] == "alice" and rec["rq"] == ["carol"]
    assert [e[0] for e in rec["ev"]] == ["ready", "req", "review"]
    assert rec["ev"][1][2] == "team:core" and rec["ev"][2][2:] == ["bob", "CHANGES_REQUESTED", "MEMBER", "User", False]
    assert rec["cm"] == [[at(20), "alice", "CONTRIBUTOR", "User", False]] and rec["ci"] == "SUCCESS"


class Pages:
    """A fake GraphQL client serving PRs newest-updated first, 2 per page."""

    def __init__(self, nodes):
        self.nodes = sorted(nodes, key=lambda x: x["updatedAt"], reverse=True)
        self.calls = 0

    def query(self, query, variables=None, **kw):
        from mergescout.github.graphql import GraphQLResult
        self.calls += 1
        start = int(variables.get("cursor") or 0)
        page = self.nodes[start:start + 2]
        more = start + 2 < len(self.nodes)
        data = {"rateLimit": {"cost": 1, "remaining": 999, "resetAt": iso(NOW)},
                "repository": {"pullRequests": {"pageInfo": {"hasNextPage": more, "endCursor": str(start + 2)},
                                                "nodes": page}}}
        return GraphQLResult(data=data, cost=1, remaining=999, reset_at=iso(NOW))


def test_first_run_reads_back_to_the_window_and_later_runs_only_what_changed(tmp_path):
    store = FlowStore(tmp_path)
    old = node(1, "MERGED", created=24 * 400, updated=24 * 399, merged=24 * 399, closed=24 * 399)
    gql = Pages([node(5, updated=1), node(4, "MERGED", updated=3, merged=3, closed=3), node(3, updated=5), old])
    out = collect(gql, store, "o", "r", NOW, months=12)
    data = store.load()
    assert sorted(p["n"] for p in data["open"]) == [3, 5] and [p["n"] for p in data["closed"]] == [4]
    assert out["prs"] == 3 and out["complete"]
    # PR 5 is merged later; the next run reads only PRs updated since the last one.
    gql2 = Pages([node(5, "MERGED", updated=0.5, merged=0.5, closed=0.5), node(4, "MERGED", updated=3, merged=3, closed=3)])
    collect(gql2, store, "o", "r", NOW + timedelta(minutes=30), months=12)
    data = store.load()
    assert [p["n"] for p in data["open"]] == [3] and sorted(p["n"] for p in data["closed"]) == [4, 5]


def test_a_reopened_pr_leaves_the_closed_list(tmp_path):
    store = FlowStore(tmp_path)
    collect(Pages([node(9, "CLOSED", updated=10, closed=10)]), store, "o", "r", NOW)
    collect(Pages([node(9, "OPEN", updated=1)]), store, "o", "r", NOW + timedelta(hours=1))
    data = store.load()
    assert [p["n"] for p in data["open"]] == [9] and data["closed"] == []


def test_without_checks_permission_flow_still_runs_and_says_what_to_add(tmp_path):
    # Sandbox finding: the built-in token can't read a commit's check status unless checks/statuses: read are granted.
    from mergescout.github.graphql import GraphQLError

    class NoStatus(Pages):
        def query(self, query, variables=None, **kw):
            if "statusCheckRollup" in query:
                raise GraphQLError("Resource not accessible by integration")
            result = super().query(query, variables, **kw)
            for nd in result.data["repository"]["pullRequests"]["nodes"]:
                for c in nd["commits"]["nodes"]:
                    c["commit"].pop("statusCheckRollup", None)
            return result
    store = FlowStore(tmp_path)
    out = collect(NoStatus([node(5, updated=1)]), store, "o", "r", NOW)
    assert out["complete"] and out["no_checks"] and store.load()["open"][0]["ci"] is None


def test_the_workflow_template_grants_read_access_to_check_results():
    from stackvitals.ci.cli import workflow_template
    text = workflow_template("o/a@v0", ["CI"])
    assert "checks: read" in text and "statuses: read" in text


class WithRepo(Pages):
    def query(self, query, variables=None, **kw):
        from mergescout.github.graphql import GraphQLResult
        if "releases(" in query:
            data = {"rateLimit": {"cost": 1, "remaining": 999, "resetAt": iso(NOW)},
                    "repository": {"defaultBranchRef": {"name": "main"},
                                   "releases": {"nodes": [{"tagName": "v2", "publishedAt": at(5), "createdAt": at(5),
                                                           "isPrerelease": False, "isDraft": False},
                                                          {"tagName": "v2-rc", "publishedAt": None, "createdAt": at(9),
                                                           "isPrerelease": True, "isDraft": True}]},
                                   "deployments": {"nodes": [{"environment": "production", "createdAt": at(3),
                                                              "latestStatus": {"state": "SUCCESS"}}]},
                                   "co1": {"text": "* @erin\n"}, "co2": None, "co3": None}}
            return GraphQLResult(data=data, cost=1, remaining=999, reset_at=iso(NOW))
        return super().query(query, variables, **kw)


def test_files_releases_and_codeowners_are_kept_and_old_records_are_read_again(tmp_path):
    store = FlowStore(tmp_path)
    store.save_state({"synced_up_to": at(2)})
    n = node(5, updated=10) | {"files": {"nodes": [{"path": "src/db/a.py"}, {"path": "README.md"}]}}
    collect(WithRepo([n]), store, "o", "r", NOW)
    rec = store.load()["open"][0]
    # The old state had no schema: PR 5 (updated before its cursor) was read again, now with its files.
    assert rec["paths"] == ["src/db/a.py", "README.md"]
    repo = store.repo()
    assert repo["default_branch"] == "main" and repo["codeowners"] == "* @erin\n"
    assert repo["releases"] == [{"tag": "v2", "at": at(5), "pre": False, "sha": None}]
    assert repo["deployments"] == [{"env": "production", "at": at(3), "state": "SUCCESS", "sha": None, "done": None}]


def test_conflicts_authored_date_and_whether_a_comment_asks_the_author_are_kept_never_the_text():
    nd = node(7, comments=[{"createdAt": at(5), "author": {"__typename": "User", "login": "bob"}, "authorAssociation": "MEMBER",
                            "body": "@alice could you add a test?"},
                           {"createdAt": at(4), "author": {"__typename": "User", "login": "bob"}, "authorAssociation": "MEMBER",
                            "body": "Seems fine."}])
    nd["mergeable"] = "CONFLICTING"
    nd["commits"]["nodes"][0]["commit"]["authoredDate"] = at(60)
    rec = pr_record(nd, NOW)
    assert rec["mgs"] == "CONFLICTING" and rec["la"] == at(60)
    assert [c[4] for c in rec["cm"]] == [True, False] and "Seems" not in str(rec)


class Checks:
    def __init__(self, contexts, suites):
        self.contexts, self.suites, self.calls = contexts, suites, 0

    def query(self, query, variables=None, **kw):
        import re

        from mergescout.github.graphql import GraphQLResult
        self.calls += 1
        nums = [int(x) for x in re.findall(r"pullRequest\(number:(\d+)\)", query)]
        repo = {f"p{n}": {"commits": {"nodes": [{"commit": {"checkSuites": {"nodes": self.suites},
                                                             "statusCheckRollup": {"contexts": {"nodes": self.contexts}}}}]}}
                for n in nums}
        data = {"rateLimit": {"cost": 1, "remaining": 900, "resetAt": iso(NOW)}, "repository": repo}
        return GraphQLResult(data=data, cost=1, remaining=900, reset_at=iso(NOW))


def test_open_prs_get_their_failing_checks_with_the_required_flag_and_ci_waiting_for_approval():
    from stackvitals.flow.collect import collect_checks
    store = FlowStore(tmp := __import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    store.save_open({7: pr_record(node(7), NOW), 8: pr_record(node(8, draft=True), NOW)})
    gql = Checks([{"__typename": "CheckRun", "name": "Lint", "conclusion": "FAILURE", "isRequired": True},
                  {"__typename": "CheckRun", "name": "perf", "conclusion": "FAILURE", "isRequired": False},
                  {"__typename": "StatusContext", "context": "docs", "state": "SUCCESS", "isRequired": True}],
                 [{"conclusion": "ACTION_REQUIRED", "app": {"slug": "github-actions"}}])
    collect_checks(gql, store, "o", "r")
    opened = store.open()
    assert opened[7]["chk"] == {"failing": [["Lint", True], ["perf", False]], "ran": ["Lint", "docs", "perf"], "awaiting": True,
                                "required_any": True}
    assert "chk" not in opened[8] and gql.calls == 1


def test_cancelled_runs_and_checks_that_also_passed_are_not_failures():
    from stackvitals.flow.collect import collect_checks
    store = FlowStore(__import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    store.save_open({7: pr_record(node(7), NOW)})
    gql = Checks([{"__typename": "CheckRun", "name": "Status", "conclusion": "CANCELLED", "isRequired": True},
                  {"__typename": "CheckRun", "name": "tests", "conclusion": "FAILURE", "isRequired": True},
                  {"__typename": "CheckRun", "name": "tests", "conclusion": "SUCCESS", "isRequired": True}], [])
    collect_checks(gql, store, "o", "r")
    assert store.open()[7]["chk"]["failing"] == []


def test_without_deployments_permission_flow_still_runs_and_says_what_to_add(tmp_path):
    # Sandbox finding (every scheduled run failed from 2026-10-17 12:57 UTC): the built-in token can't read
    # deployments without `deployments: read`, and the once-per-run repo query asked for them.
    from mergescout.github.graphql import GraphQLError

    class NoDeployments(WithRepo):
        def query(self, query, variables=None, **kw):
            if "deployments(" in query:
                raise GraphQLError("Resource not accessible by integration")
            result = super().query(query, variables, **kw)
            (result.data.get("repository") or {}).pop("deployments", None)  # not asked for, so not answered
            return result
    store = FlowStore(tmp_path)
    out = collect(NoDeployments([node(5, updated=1)]), store, "o", "r", NOW)
    repo = store.repo()
    assert out["complete"] and out["no_deployments"] and repo["deployments"] == [] and repo["default_branch"] == "main"


def test_a_refused_repo_query_never_stops_the_run(tmp_path):
    from mergescout.github.graphql import GraphQLError

    class NoRepo(Pages):
        def query(self, query, variables=None, **kw):
            if "defaultBranchRef" in query:
                raise GraphQLError("Resource not accessible by integration")
            return super().query(query, variables, **kw)
    store = FlowStore(tmp_path)
    out = collect(NoRepo([node(5, updated=1)]), store, "o", "r", NOW)
    assert out["complete"] and store.load()["open"][0]["n"] == 5


def test_the_workflow_template_grants_read_access_to_deployments():
    from stackvitals.ci.cli import workflow_template
    assert "deployments: read" in workflow_template("o/a@v0", ["CI"])
