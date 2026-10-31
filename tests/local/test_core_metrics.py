"""Every number the suite shows comes from the registry: an id, a version, a definition, n, a range and an as-of time."""
from datetime import datetime, timedelta, timezone

import pytest

from stackvitals.core import metrics, stats

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def test_the_registry_names_every_metric_with_a_definition_and_a_version():
    m = metrics.get("flow.pickup_time")
    assert m.unit == "s" and m.kind == "median" and m.version == 1 and m.better == -1 and "first" in m.definition
    for mid in ("flow.coding_time", "flow.pickup_time", "flow.review_time", "flow.approve_time", "flow.merge_time",
                "flow.deploy_time", "flow.cycle_time", "flow.outsider_merge_rate", "community.first_answer_time",
                "ci.flake_rate", "ci.first_try_green", "ci.push_wait"):
        assert metrics.get(mid).id == mid
    with pytest.raises(KeyError):
        metrics.get("flow.nothing")
    assert all(m.min_n >= 1 for m in metrics.all())


def test_a_median_measure_carries_n_and_a_range_from_the_values_or_says_not_enough_data():
    values = [float(h * 3600) for h in range(1, 21)]
    m = metrics.measure("flow.pickup_time", values=values, as_of=NOW, window_days=90)
    assert m.value == 10.5 * 3600 and m.n == 20 and m.low == 6 * 3600 and m.high == 16 * 3600
    assert m.as_of == "2026-10-20T12:00:00Z" and m.window_days == 90 and m.note is None and m.unit == "s"
    thin = metrics.measure("flow.pickup_time", values=values[:5], as_of=NOW)
    assert thin.value is None and thin.n == 5 and thin.note == "not enough data (n=5, needs 10)"
    d = m.to_dict()
    assert set(d) == {"metric", "version", "value", "n", "low", "high", "unit", "as_of", "window_days", "note"}
    assert d["metric"] == "flow.pickup_time" and d["version"] == 1


def test_a_share_measure_uses_the_wilson_range_and_a_count_has_none():
    m = metrics.measure("flow.outsider_merge_rate", hits=5, n=10, as_of=NOW)
    assert m.value == 0.5 and (round(m.low, 4), round(m.high, 4)) == (0.2366, 0.7634) and m.unit == "share"
    assert metrics.measure("flow.outsider_merge_rate", hits=0, n=0, as_of=NOW).value is None
    c = metrics.measure("flow.open_prs", n=7, as_of=NOW)
    assert c.value == 7 and c.low is None and c.high is None and c.unit == "count"


def test_quantile_ranges_cover_the_estimate_and_narrow_with_n():
    values = list(range(1, 101))
    lo, hi = stats.quantile_range(values, 0.75)
    assert lo <= stats.percentile(values, 0.75) <= hi and lo in values and hi in values
    assert stats.quantile_range(values, 0.5) == stats.median_range(values)
    assert stats.quantile_range(values[:5], 0.75) is None


def test_team_flow_publishes_its_measures_beside_the_old_fields():
    from stackvitals.flow.analyze import analyze

    def at(hours):
        return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def pr(n, cr, mg, au="newbie", assoc="NONE"):
        return {"t": "pr", "n": n, "ti": "x", "draft": False, "st": "MERGED", "cr": at(cr), "up": at(1), "mg": at(mg), "cl": at(mg),
                "add": 10, "del": 1, "files": 1, "au": au, "at": "User", "as": assoc, "rq": [], "cm": [], "ci": "SUCCESS", "lc": at(cr),
                "ev": [["review", at(cr - 2), "bob", "APPROVED", "MEMBER", "User", False], ["merged", at(mg), "bob"]]}
    closed = [pr(k, 100 + k, 90 + k) for k in range(1, 13)]
    out = analyze({"open": [], "closed": closed}, NOW)
    m = out["measures"]
    assert m["flow.pickup_time"]["value"] == out["stages"]["pickup"]["median_s"] == 2 * 3600
    assert m["flow.pickup_time"]["n"] == 12 and m["flow.pickup_time"]["as_of"] == "2026-10-20T12:00:00Z"
    assert m["flow.outsider_merge_rate"]["value"] == 1.0 and m["flow.outsider_merge_rate"]["n"] == 12
    assert m["flow.cycle_time"]["low"] is not None
