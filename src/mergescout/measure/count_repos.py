import math
from datetime import date

COUNT_RANGES = [("50-99", "50..99"), ("100-199", "100..199"), ("200-499", "200..499"),
                ("500-999", "500..999"), ("1k-5k", "1000..4999"), ("5k+", ">=5000")]

COUNT_QUERY = """
query($q: String!) {
  rateLimit { cost remaining resetAt }
  search(query: $q, type: REPOSITORY, first: 1) { repositoryCount }
}
"""


def count_repos(gql, pushed_since: date) -> dict:
    rows = []
    cost = 0
    for label, stars in COUNT_RANGES:
        base = f"stars:{stars} fork:false archived:false"
        total = gql.query(COUNT_QUERY, {"q": base})
        active = gql.query(COUNT_QUERY, {"q": f"{base} pushed:>={pushed_since.isoformat()}"})
        cost += total.cost + active.cost
        rows.append({"range": label, "total": total.data["search"]["repositoryCount"],
                     "active": active.data["search"]["repositoryCount"]})
    return {"rows": rows, "cost": cost}


def listing_requests(rows: list[dict]) -> int:
    # Search pages hold 100 repos, so listing every active repo takes at least this many calls.
    return sum(math.ceil(row["active"] / 100) for row in rows)
