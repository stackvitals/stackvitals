"""Delivery benchmarks from the crawl: per repo, the P75 of pickup (opened to first maintainer review), review (first
review to merge) and cycle to merge, by the suite's nearest-rank rule; per group, P25-P90, a bootstrap range on the
median, and the share of repos inside LinearB's bands; the population and the gaps stated with the numbers."""
from functools import lru_cache

from mergescout.signals.delivery_bench import delivery_benchmarks
from test_flow_bench_pipeline import NOW
from test_flow_bench_pipeline import setup as build


@lru_cache(maxsize=None)
def setup(repos=60, prs=12):
    return build(repos, prs)  # the fixture inserts row by row (about 18 s): built once per shape


def test_groups_give_percentiles_a_range_on_the_median_and_linearb_band_shares():
    out = delivery_benchmarks(setup(), NOW)
    g = out["groups"]["Python|100-1k"]
    assert out["repos"] == 60 and g["repos"] == 60
    pickup = g["pickup_p75_hours"]
    # Repo r's maintainer answers after 1 + r hours: the median repo waits 30 h, P25 15 h.
    assert pickup["p50"] == 30.0 and pickup["p25"] == 15.0 and pickup["repos"] == 60
    assert pickup["p50_low"] <= 30.0 <= pickup["p50_high"] and pickup["p50_low"] < pickup["p50_high"]
    assert pickup["linearb"] == {"elite": 0.0, "good": round(4 / 60, 4), "fair": round(16 / 60, 4)}
    review = g["review_p75_hours"]
    assert review["p50"] == 9.0 and review["linearb"]["good"] == 1.0
    assert g["cycle_to_merge_p75_hours"]["p50"] == 39.0
    assert "LinearB" in out["bands_note"] and out["population"] and out["gaps"]
    assert out["definition"].startswith("per repo") and out["method"]["bootstrap_resamples"] >= 200


def test_the_range_is_the_same_on_every_build_and_small_groups_stay_out():
    a, b = delivery_benchmarks(setup(), NOW), delivery_benchmarks(setup(), NOW)
    assert a["groups"]["all|all"]["pickup_p75_hours"] == b["groups"]["all|all"]["pickup_p75_hours"]
    assert delivery_benchmarks(setup(repos=30), NOW)["groups"] == {}
