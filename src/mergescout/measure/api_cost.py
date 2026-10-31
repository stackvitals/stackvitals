from datetime import datetime, timedelta

from mergescout.github.graphql import NotFound
from mergescout.timeutil import parse_time

PR_HISTORY_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    pullRequests(first: 100, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number createdAt mergedAt closedAt state authorAssociation author { login }
        reviews(first: 1) { nodes { submittedAt authorAssociation } }
      }
    }
  }
}
"""

INCREMENTAL_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    pullRequests(first: 100, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number updatedAt createdAt mergedAt closedAt state authorAssociation author { login }
        reviews(first: 1) { nodes { submittedAt authorAssociation } }
      }
    }
  }
}
"""

OPEN_ISSUES_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    issues(first: 100, after: $cursor, states: OPEN, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number updatedAt
        assignees(first: 5) { totalCount }
        labels(first: 10) { nodes { name } }
        closedByPullRequestsReferences(first: 5, includeClosedPrs: true) { nodes { number state } }
        comments(last: 5) { nodes { createdAt authorAssociation author { login } body } }
      }
    }
  }
}
"""


def walk_connection(gql, query: str, owner: str, name: str, connection: str, time_field: str,
                    since: datetime, max_pages: int) -> dict:
    cursor = None
    pages = cost = items = 0
    capped = False
    while True:
        result = gql.query(query, {"owner": owner, "name": name, "cursor": cursor})
        pages += 1
        cost += result.cost
        repo = result.data.get("repository")
        if repo is None:
            raise NotFound(f"{owner}/{name} not found")
        conn = repo[connection]
        nodes = conn["nodes"]
        in_window = [n for n in nodes if (parse_time(n.get(time_field)) or since) >= since]
        items += len(in_window)
        if len(in_window) < len(nodes) or not conn["pageInfo"]["hasNextPage"]:
            break
        if pages >= max_pages:
            capped = True
            break
        cursor = conn["pageInfo"]["endCursor"]
    return {"pages": pages, "cost": cost, "items": items, "capped": capped}


def measure_repo(gql, full_name: str, now: datetime) -> dict:
    owner, name = full_name.split("/", 1)
    try:
        full = walk_connection(gql, PR_HISTORY_QUERY, owner, name, "pullRequests", "createdAt",
                               now - timedelta(days=365), max_pages=30)
        incremental = walk_connection(gql, INCREMENTAL_QUERY, owner, name, "pullRequests", "updatedAt",
                                      now - timedelta(days=1), max_pages=30)
        issues = walk_connection(gql, OPEN_ISSUES_QUERY, owner, name, "issues", "updatedAt",
                                 now - timedelta(days=90), max_pages=20)
    except NotFound:
        return {"repo": full_name, "status": "not_found"}
    return {"repo": full_name, "status": "ok", "full": full, "incremental": incremental, "issues": issues}
