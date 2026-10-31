import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "accuracy" / "uncertainty"))

from nulls import _caught, _rules  # noqa: E402


def _c(metric, p, direction="up", changed=False):
    return {"metric": f"delivery.{metric}", "p": p, "direction": direction, "changed": changed}


def test_rules_include_the_naive_test_at_the_digest_level():
    found = [_c("pickup", 0.07)]
    out = _rules(found)
    assert out["p_below_0.1"] and not out["p_below_0.05"] and out["any_difference"]


def test_every_rule_is_scored_on_the_same_slowed_weeks():
    found = [_c("pickup", 0.03), _c("deployments", 0.001)]
    flagged = [_c("pickup", 0.03, changed=False), _c("deployments", 0.001, changed=True)]
    out = _caught(found, flagged)
    # Only a review-time metric going up counts as catching the injected slowdown.
    assert out == {"any_difference": True, "p_below_0.05": True, "p_below_0.1": True, "false_alarm_control": False}
