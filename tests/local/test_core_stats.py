from datetime import datetime, timezone

import pytest

from stackvitals.core import stats, time as t


def test_median_and_percentile_match_the_old_module_helpers():
    assert stats.median([]) is None
    assert stats.median([3, 1, 2]) == 2
    assert stats.median([1, 2, 3, 4]) == 2.5
    assert stats.percentile([], 0.9) is None
    # The nearest-rank method every module used: the 90th of 1..10 is 9, the 75th of 1..4 is 3.
    assert stats.percentile(list(range(1, 11)), 0.9) == 9
    assert stats.percentile([1, 2, 3, 4], 0.75) == 3
    assert stats.percentile([5], 0.5) == 5


def test_wilson_range_never_crashes_and_never_leaves_zero_to_one():
    assert stats.wilson(0, 0) == (0.0, 1.0)
    lo, hi = stats.wilson(5, 10)
    assert round(lo, 4) == 0.2366 and round(hi, 4) == 0.7634
    # More events than trials (a counting slip) clamps instead of crashing.
    lo, hi = stats.wilson(12, 10)
    assert hi == 1.0 and 0.7 < lo < 1.0
    assert stats.wilson(0, 10)[0] == 0.0


def test_median_range_is_a_distribution_free_interval_from_the_values_themselves():
    assert stats.median_range([1, 2, 3]) is None
    values = list(range(1, 21))
    lo, hi = stats.median_range(values)
    assert lo in values and hi in values and lo <= stats.median(values) <= hi
    assert (lo, hi) == (6, 16)
    wide = stats.median_range(list(range(1, 11)))
    narrow = stats.median_range(list(range(1, 201)))
    assert (wide[1] - wide[0]) / 10 > (narrow[1] - narrow[0]) / 200


def test_time_helpers_parse_github_timestamps_and_refuse_negative_spans():
    dt = t.parse("2026-10-20T12:00:00Z")
    assert dt == datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
    assert t.parse(None) is None and t.parse("") is None
    assert t.iso(dt) == "2026-10-20T12:00:00Z"
    assert t.secs("2026-10-20T12:00:00Z", "2026-10-20T13:30:00Z") == 5400
    assert t.secs("2026-10-20T13:30:00Z", "2026-10-20T12:00:00Z") is None
    assert t.secs(None, "2026-10-20T12:00:00Z") is None
    assert t.hours("2026-10-20T12:00:00Z", "2026-10-20T13:30:00Z") == 1.5
    assert t.week_of("2026-10-21T05:00:00Z") == "2026-10-19"
