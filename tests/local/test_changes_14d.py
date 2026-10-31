from datetime import datetime, timedelta, timezone

from stackvitals.core import changes

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def test_windows_over_two_weeks_put_the_baseline_before_both():
    (a, b), (c, d) = changes.windows(NOW, 2)
    assert b == changes.iso(NOW) and a == changes.iso(NOW - timedelta(days=14)) and d == a
    assert c == changes.iso(NOW - timedelta(days=42))


def test_a_slowdown_flagged_weekly_and_over_14_days_is_listed_once():
    slow = lambda m: {**changes.times(m, m, [50.0] * 30, [1.0] * 30, better=-1, unit="h")}  # noqa: E731
    out = changes.flag([slow("delivery.pickup"), slow("delivery.pickup_14d"), slow("delivery.cycle_to_merge_14d")])
    assert [c.get("shown_with") for c in out] == [None, "delivery.pickup", None]
    assert all(c["changed"] for c in out)


def test_a_pairing_from_the_module_pass_is_dropped_when_the_weekly_row_is_no_longer_flagged():
    week = {**changes.times("delivery.pickup", "pickup", [2.0] * 30, [1.0] * 30, better=-1, unit="h"), "p": 0.04}
    long = {**changes.times("delivery.pickup_14d", "p14", [50.0] * 30, [1.0] * 30, better=-1, unit="h"),
            "shown_with": "delivery.pickup"}
    steady = [{**week, "metric": f"x.{i}", "p": 0.9} for i in range(8)]
    out = changes.flag([week, long, *steady])
    assert not out[0]["changed"] and out[1]["changed"] and "shown_with" not in out[1]
