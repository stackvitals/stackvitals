from datetime import date

STAR_BUCKETS = [("50-199", "50..199"), ("200-999", "200..999"), ("1k-10k", "1000..9999"), ("10k+", ">=10000")]
CREATED_SLICES = ["<2016-01-01", "2016-01-01..2018-12-31", "2019-01-01..2021-12-31",
                  "2022-01-01..2023-12-31", ">=2024-01-01"]

SEARCH_QUERY = """
query($q: String!, $n: Int!) {
  rateLimit { cost remaining resetAt }
  search(query: $q, type: REPOSITORY, first: $n) {
    repositoryCount
    nodes { ... on Repository { nameWithOwner stargazerCount } }
  }
}
"""


def build_sample_queries(pushed_since: date) -> list[tuple[str, str]]:
    # Mixing star ranges and creation years gives a spread of repo sizes and ages.
    return [
        (label, f"stars:{stars} created:{created} pushed:>={pushed_since.isoformat()} fork:false archived:false")
        for label, stars in STAR_BUCKETS
        for created in CREATED_SLICES
    ]


def collect_sample(gql, queries: list[tuple[str, str]], per_query: int = 15) -> list[dict]:
    seen: set[str] = set()
    sample = []
    for label, q in queries:
        result = gql.query(SEARCH_QUERY, {"q": q, "n": per_query})
        for node in result.data["search"]["nodes"]:
            name = node.get("nameWithOwner")
            if name and name not in seen:
                seen.add(name)
                sample.append({"repo": name, "stars": node["stargazerCount"], "bucket": label})
    return sample
