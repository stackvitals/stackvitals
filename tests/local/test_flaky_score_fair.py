import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "accuracy" / "flaky"))

from score import score  # noqa: E402


def _pair(sample, caused, n):
    return [({"sample": sample, "repo": "o/r"}, {"cause": "network", "caused_by_change": caused, "own_failure": "yes"})] * n


def test_plain_retry_rule_gets_a_range_and_a_test_against_ours():
    rows = _pair("flagged", "no", 105) + _pair("flagged", "yes", 3) + _pair("vendor_extra", "no", 7) \
        + _pair("vendor_extra", "yes", 6)
    items, labels = [i for i, _l in rows], [l for _i, l in rows]
    plain = score(items, labels, {"o/r": {"flagged": 237, "extra": 15, "known": 0, "unflagged": 0}})["plain_retry_rule"]
    assert plain["precision_range"]["low"] < plain["precision"] < plain["precision_range"]["high"]
    assert plain["ours_minus_it"]["value"] > 0 and "significant" in plain["ours_minus_it"]
    assert plain["left_out_vs_ours"]["p"] < 0.001


def test_precision_and_misses_are_broken_down_by_language_group():
    rows = [({"sample": "flagged", "repo": "a/b", "group": "go"}, {"cause": "network", "caused_by_change": "no", "own_failure": "yes"})] * 9 \
        + [({"sample": "flagged", "repo": "a/b", "group": "go"}, {"cause": "code_change", "caused_by_change": "yes", "own_failure": "yes"})] \
        + [({"sample": "flagged", "repo": "c/d", "group": "js"}, {"cause": "test", "caused_by_change": "no", "own_failure": "yes"})] * 4 \
        + [({"sample": "unflagged_failure", "repo": "c/d", "group": "js"}, {"cause": "test", "caused_by_change": "no", "own_failure": "yes"})] * 2
    out = score([i for i, _l in rows], [l for _i, l in rows], {})["by_language"]
    assert out["go"]["event_precision"]["share"] == 0.9 and out["go"]["event_precision"]["n"] == 10
    assert out["js"]["event_precision"]["share"] == 1.0 and out["js"]["miss_rate"]["n"] == 2


def test_the_plain_retry_rule_is_scored_on_retry_events_only():
    # Same-commit flips are invisible to a retry rule, so their misses can't count for or against it.
    retry = [({"sample": "flagged", "repo": "o/r", "kind": "retry"}, {"cause": "network", "caused_by_change": "no", "own_failure": "yes"})] * 20
    flip_bad = [({"sample": "flagged", "repo": "o/r", "kind": "flip"}, {"cause": "code_change", "caused_by_change": "yes", "own_failure": "yes"})] * 5
    extra = [({"sample": "vendor_extra", "repo": "o/r"}, {"cause": "network", "caused_by_change": "no", "own_failure": "yes"})] * 4
    rows = retry + flip_bad + extra
    plain = score([i for i, _l in rows], [l for _i, l in rows], {"o/r": {"flagged": 100, "extra": 10, "known": 0, "unflagged": 0}})["plain_retry_rule"]
    assert plain["precision"] == 1.0 and plain["retry_events_right"]["share"] == 1.0
