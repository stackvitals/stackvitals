from datetime import date

from mergescout.measure.sample import build_sample_queries, collect_sample


def test_builds_twenty_queries_across_buckets():
    queries = build_sample_queries(date(2026, 9, 11))
    assert len(queries) == 20
    labels = {label for label, _ in queries}
    assert labels == {"50-199", "200-999", "1k-10k", "10k+"}
    for _, q in queries:
        assert "pushed:>=2026-09-11" in q and "fork:false" in q and "archived:false" in q


def test_collect_sample_dedupes_and_tags_bucket(fake_gql):
    def responder(query, variables):
        nodes = [{"nameWithOwner": "a/b", "stargazerCount": 60}, {"nameWithOwner": "c/d", "stargazerCount": 70}]
        return {"search": {"repositoryCount": 2, "nodes": nodes}}, 1

    gql = fake_gql(responder)
    sample = collect_sample(gql, [("50-199", "q1"), ("50-199", "q2")], per_query=2)
    assert [s["repo"] for s in sample] == ["a/b", "c/d"]
    assert sample[0] == {"repo": "a/b", "stars": 60, "bucket": "50-199"}
