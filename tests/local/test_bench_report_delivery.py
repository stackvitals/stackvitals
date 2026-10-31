"""The public report's delivery section: LinearB's bands beside the crawl's own spread, a range on every median, who is
counted and who is not, and SQL that recomputes each number from the CSV next to it."""
import csv
import json

from mergescout.bench.report import build_report

Q = {"repos": 900, "p10": 0.8, "p25": 2.5, "p50": 9.5, "p75": 30.0, "p90": 90.0, "p50_low": 8.9, "p50_high": 10.2}
DELIVERY = {"version": 1, "built_at": "2026-10-21T05:00:00Z", "repos": 9000, "definition": "per repo, PRs opened ...",
            "population": "public GitHub repos in the daily crawl with 10+ PRs", "gaps": "no private or enterprise teams",
            "bands_note": "LinearB's 2026 benchmark bands on P75", "method": {"bootstrap_resamples": 400, "bootstrap_seed": 1},
            "groups": {"all|all": {"repos": 9000, "pickup_p75_hours": {**Q, "linearb": {"elite": 0.08, "good": 0.22, "fair": 0.55}},
                                   "review_p75_hours": {**Q, "p50": 6.0, "p50_low": 5.6, "p50_high": 6.4,
                                                        "linearb": {"elite": 0.3, "good": 0.6, "fair": 0.7}},
                                   "cycle_to_merge_p75_hours": {**Q, "p50": 40.0, "p50_low": 37.0, "p50_high": 43.0}},
                       "Python|all": {"repos": 1200, "pickup_p75_hours": {**Q, "repos": 1100, "p50": 7.0, "p50_low": 6.1,
                                                                          "p50_high": 7.9, "linearb": {"elite": 0.1, "good": 0.25, "fair": 0.6}}}}}


def test_the_delivery_section_has_bands_ranges_population_gaps_and_recomputes_from_the_csv(tmp_path):
    bench = tmp_path / "bench"
    bench.mkdir()
    (bench / "delivery-benchmarks.json").write_text(json.dumps(DELIVERY), encoding="utf-8")
    md = build_report(bench, tmp_path / "out").read_text(encoding="utf-8")
    assert "## Delivery" in md and "9.5 h (8.9-10.2)" in md and "22%" in md and "LinearB" in md
    assert "Who is counted: public GitHub repos in the daily crawl with 10+ PRs" in md and "Not covered: no private" in md
    assert "read_csv_auto('delivery.csv')" in md and "bootstrap" in md
    rows = list(csv.DictReader(open(tmp_path / "out" / "delivery.csv", encoding="utf-8")))
    top = next(r for r in rows if r["language"] == "all" and r["size"] == "all")
    assert float(top["pickup_p75_hours_p50"]) == 9.5 and float(top["pickup_p75_hours_p50_low"]) == 8.9
    assert float(top["pickup_p75_hours_linearb_good"]) == 0.22


def test_the_shipping_section_says_how_many_repos_ship_where_github_can_see(tmp_path):
    deploys = {"version": 1, "built_at": "2026-10-21T05:00:00Z", "repos": 3000, "definition": "per repo, the last 90 days ...",
               "population": "public GitHub repos with 100+ stars", "gaps": "deployments made outside GitHub are not seen",
               "groups": {"all|all": {"repos": 3000, "sources": {"deployments api": 0.04, "releases": 0.44, "none": 0.52},
                                      "days_per_week": {"repos": 1440, "p10": 0, "p25": 0, "p50": 0, "p75": 0, "p90": 1,
                                                        "p50_low": 0, "p50_high": 0},
                                      "tiers": {"elite": 0.01, "high": 0.15, "medium": 0.26, "low": 0.58}}}}
    bench = tmp_path / "bench"
    bench.mkdir()
    (bench / "deploys-benchmarks.json").write_text(json.dumps(deploys), encoding="utf-8")
    md = build_report(bench, tmp_path / "out").read_text(encoding="utf-8")
    assert "## Shipping" in md and "52%" in md and "58% low" in md and "Not covered: deployments made outside GitHub" in md
    rows = list(csv.DictReader(open(tmp_path / "out" / "deploys.csv", encoding="utf-8")))
    assert float(rows[0]["sources_none"]) == 0.52 and float(rows[0]["tiers_low"]) == 0.58
