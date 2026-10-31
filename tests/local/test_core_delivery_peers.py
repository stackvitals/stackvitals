"""A repo's delivery among similar public repos: its own P75s measured with the crawl benchmarks' exact definitions,
placed in the closest group with enough repos, with the median's range, LinearB's band shares and the gaps said."""
from stackvitals.core import delivery_peers
from test_core_delivery import NOW, pr, review

BENCH = {"version": 1, "built_at": "2026-10-21T05:00:00Z", "population": "public GitHub repos ...", "gaps": "no private teams ...",
         "groups": {"Python|1k-10k": {"repos": 812,
                                      "pickup_p75_hours": {"repos": 800, "p10": 1.0, "p25": 3.0, "p50": 9.5, "p75": 30.0,
                                                           "p90": 90.0, "p50_low": 8.9, "p50_high": 10.2,
                                                           "linearb": {"elite": 0.08, "good": 0.22, "fair": 0.55}},
                                      "review_p75_hours": {"repos": 700, "p10": 0.5, "p25": 2.0, "p50": 6.0, "p75": 20.0,
                                                           "p90": 60.0, "p50_low": 5.5, "p50_high": 6.6,
                                                           "linearb": {"elite": 0.3, "good": 0.6, "fair": 0.7}}},
                    "all|all": {"repos": 9000}}}


def merged_prs(wait_h):
    # Each PR opened 100+ h ago, reviewed by a maintainer `wait_h` hours later and merged 2 h after that.
    return [pr(100 + k, cr=200 + k, mg=200 + k - wait_h - 2, fa=201 + k, ev=[review(200 + k - wait_h, who="maint")])
            for k in range(12)]


def test_own_numbers_use_the_crawl_definitions_and_land_in_the_closest_group():
    own = delivery_peers.own_metrics(merged_prs(40) + [pr(1, cr=50, mg=40, au="maint", ev=[review(45, who="bob")])], NOW)
    assert own["pickup_p75_hours"] == 40.0 and own["review_p75_hours"] == 2.0 and own["prs"] == 13
    out = delivery_peers.compare(own, BENCH, "Python", 2500)
    assert out["group"] == "Python repos with 1k-10k stars" and out["repos"] == 812
    pickup = next(m for m in out["metrics"] if m["key"] == "pickup_p75_hours")
    assert pickup["you"] == 40.0 and pickup["typical"] == 9.5 and (pickup["low"], pickup["high"]) == (8.9, 10.2)
    assert pickup["place"].startswith("slower than about") and pickup["linearb"]["good"] == 0.22
    assert out["gaps"] and out["population"]


def test_too_few_prs_or_no_file_give_nothing():
    assert delivery_peers.own_metrics(merged_prs(5)[:4], NOW) is None
    assert delivery_peers.compare({"prs": 20, "pickup_p75_hours": 3.0}, None, "Python", 10) is None
    assert delivery_peers.compare({"prs": 20, "pickup_p75_hours": 3.0}, {"groups": {"x": "bad"}}, "Python", 10) is None
