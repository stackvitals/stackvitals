from datetime import datetime, timedelta, timezone

from mergescout.github.graphql import GraphQLResult

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(days_ago, review_after_h=None, reviewer="maint", assoc="MEMBER", author="amy", author_assoc="NONE"):
    created = NOW - timedelta(days=days_ago)
    reviews = [] if review_after_h is None else [{"submittedAt": iso(created + timedelta(hours=review_after_h)),
                                                  "author": {"login": reviewer}, "authorAssociation": assoc}]
    return {"createdAt": iso(created), "author": {"login": author, "__typename": "User"}, "authorAssociation": author_assoc,
            "reviews": {"nodes": reviews}}


class Fake:
    def __init__(self, nodes):
        self.nodes, self.calls = nodes, 0

    def query(self, query, variables=None, **kw):
        self.calls += 1
        return GraphQLResult(data={"repository": {"pullRequests": {"nodes": self.nodes}}}, cost=1, remaining=999, reset_at="x")


def test_first_reviews_are_measured_like_the_benchmark_when_team_flow_does_not_run():
    from stackvitals.portal.inventory import review_stats
    nodes = [pr(10 + i, 2 if i < 6 else 30) for i in range(10)]  # 10 PRs: 6 reviewed after 2 h, 4 after 30 h
    nodes += [pr(5, 1, reviewer="amy", assoc="NONE")]  # the author's own review never counts
    nodes += [pr(200, 1)]  # older than 90 days
    nodes += [pr(3, 1, reviewer="outsider", assoc="NONE")]  # not a maintainer: no first review yet
    s = review_stats(Fake(nodes), "acme/web", NOW)
    assert s["prs"] == 12 and s["first_review_median_s"] == 2 * 3600


def test_too_few_prs_give_no_review_figure():
    from stackvitals.portal.inventory import review_stats
    assert review_stats(Fake([pr(5, 2) for _ in range(4)]), "acme/web", NOW) is None


def test_the_review_rule_uses_portals_own_measure_with_its_source():
    from stackvitals.portal.scorecard import evaluate, load_rules
    rules, ex = load_rules('[[rule]]\nid = "fr"\ncheck = "first_review"\npeer = 50\nlevel = "bronze"\n')
    bench = {"flow": {"groups": {"all|all": {"repos": 900, "first_review_hours": {"p10": 1, "p25": 4, "p50": 20, "p75": 60, "p90": 200}}}}}
    r = evaluate({"name": "acme/web", "modules": None, "reviews": {"first_review_median_s": 7200, "prs": 12}}, rules, ex, NOW, bench)
    assert r["results"][0]["result"] == "pass" and "last 12 PRs" in r["results"][0]["evidence"]
