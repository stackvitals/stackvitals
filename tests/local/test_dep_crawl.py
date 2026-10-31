from datetime import datetime, timedelta, timezone

from mergescout.crawl.queries import parse_prs

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def at(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr_node(n, login, title, head="fix", kind="User", merged=None, state="OPEN"):
    return {"number": n, "title": title, "createdAt": at(100), "updatedAt": at(5), "mergedAt": merged, "closedAt": merged,
            "state": state, "headRefName": head, "additions": 1, "deletions": 1, "changedFiles": 1,
            "author": {"__typename": kind, "login": login}, "authorAssociation": "NONE", "mergedBy": None, "bodyText": "",
            "reviews": {"nodes": []}, "closingIssuesReferences": {"nodes": []}}


def test_titles_are_kept_only_for_dependency_bots_and_reverts():
    rows = {r["number"]: r for r in parse_prs(1, [
        pr_node(1, "dependabot[bot]", "Bump lodash from 4.17.20 to 4.17.21", "dependabot/npm_and_yarn/lodash-4.17.21", "Bot"),
        pr_node(2, "ann", "Fix the parser"),
        pr_node(3, "ann", 'Revert "Bump lodash from 4.17.20 to 4.17.21"'),
        pr_node(4, "org-bot", "Update dependency react to v19", "renovate/react-19.x", "Bot")])}
    assert rows[1]["title"].startswith("Bump lodash") and rows[2]["title"] is None
    assert rows[3]["title"].startswith("Revert") and rows[4]["title"] == "Update dependency react to v19"


class Recorder:
    """A fake GraphQL client: one PR page, then answers by-number lookups with CI state and commit counts."""

    def __init__(self, nodes):
        self.nodes, self.lookups = nodes, []

    def query(self, query, variables=None, partial=False, **kw):
        from mergescout.github.graphql import GraphQLResult
        rl = {"cost": 1, "remaining": 999, "resetAt": at(0)}
        if "pullRequest(number" in query:
            numbers = [int(x.split(":")[0][2:]) for x in query.split() if x.startswith("pr") and x.endswith(":")]
            self.lookups.append(numbers)
            repo = {f"pr{n}": {"commits": {"totalCount": 1 if n % 2 else 3,
                                           "nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS" if n % 2 else "FAILURE"}}}]}}
                    for n in numbers}
            return GraphQLResult(data={"rateLimit": rl, "repository": repo}, cost=1, remaining=999, reset_at=at(0))
        if "pullRequests(" in query:
            data = {"rateLimit": rl, "repository": {"pullRequests": {"pageInfo": {"hasNextPage": False}, "nodes": self.nodes}}}
            return GraphQLResult(data=data, cost=1, remaining=999, reset_at=at(0))
        data = {"rateLimit": rl, "repository": {"issues": {"pageInfo": {"hasNextPage": False}, "nodes": []}}}
        return GraphQLResult(data=data, cost=1, remaining=999, reset_at=at(0))


def test_finished_dependency_bot_prs_get_ci_state_and_commit_count_in_batches_of_50():
    from mergescout.crawl.fetch import fetch_repo
    bots = [pr_node(k, "dependabot[bot]", f"Bump x from 1.{k} to 1.{k + 1}", f"dependabot/pip/x-1.{k + 1}", "Bot",
                    merged=at(10), state="MERGED") for k in range(1, 61)]
    others = [pr_node(100, "dependabot[bot]", "Bump y from 1 to 2", "dependabot/pip/y-2", "Bot"),  # still open: no outcome
              pr_node(101, "ann", "Fix", merged=at(10), state="MERGED")]
    gql = Recorder(bots + others)
    bundle = fetch_repo(gql, 1, "o/r", NOW, changed_since=NOW - timedelta(days=30))
    assert [len(x) for x in gql.lookups] == [50, 10]
    rows = {r["number"]: r for r in bundle.prs}
    assert rows[1]["ci_state"] == "SUCCESS" and rows[1]["commit_count"] == 1
    assert rows[2]["ci_state"] == "FAILURE" and rows[2]["commit_count"] == 3
    assert rows[100]["ci_state"] is None and rows[101]["ci_state"] is None


def test_the_crawl_files_have_the_new_columns():
    from mergescout.crawl.writer import SCHEMAS
    names = SCHEMAS["prs"].names
    assert {"title", "ci_state", "commit_count"} <= set(names)
