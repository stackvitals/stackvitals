from datetime import date

from mergescout.measure.count_repos import COUNT_RANGES, count_repos, listing_requests


def test_counts_total_and_active_per_range(fake_gql):
    def responder(query, variables):
        return {"search": {"repositoryCount": 250 if "pushed:" in variables["q"] else 1000}}, 1

    out = count_repos(fake_gql(responder), date(2026, 9, 11))
    assert len(out["rows"]) == len(COUNT_RANGES)
    assert out["rows"][0] == {"range": COUNT_RANGES[0][0], "total": 1000, "active": 250}
    assert out["cost"] == 2 * len(COUNT_RANGES)


def test_listing_requests_rounds_up_per_range():
    assert listing_requests([{"active": 250}, {"active": 100}, {"active": 0}]) == 4
