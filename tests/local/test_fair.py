import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "accuracy"))

from fair import compare_shares, mcnemar, mixture  # noqa: E402


def test_mixture_of_two_rates_gets_a_range_around_its_point():
    # The plain retry rule: our 108 flagged events (105 right) plus 13 left-out ones (7 right), weighted 237:15.
    out = mixture([(105, 108, 237), (7, 13, 15)])
    assert abs(out["share"] - (237 * 105 / 108 + 15 * 7 / 13) / 252) < 1e-4
    assert out["low"] < out["share"] < out["high"] and out["high"] - out["low"] < 0.1


def test_mixture_difference_says_when_its_range_crosses_zero():
    out = mixture([(105, 108, 237), (7, 13, 15)], against=(105, 108))
    assert out["difference"]["low"] > 0  # every extra event is a draw from a worse rate
    tie = mixture([(50, 100, 90), (5, 10, 10)], against=(50, 100))
    assert tie["difference"]["low"] < 0 < tie["difference"]["high"] and not tie["difference"]["significant"]


def test_the_same_seed_gives_the_same_range():
    assert mixture([(9, 10, 1), (1, 2, 1)]) == mixture([(9, 10, 1), (1, 2, 1)])


def test_two_independent_shares_get_fishers_test():
    out = compare_shares(105, 108, 7, 13)
    assert out["difference"] > 0.4 and out["p"] < 0.001 and out["significant"]
    same = compare_shares(5, 10, 5, 10)
    assert same["p"] == 1.0 and not same["significant"]


def test_paired_rules_on_the_same_items_get_mcnemar():
    # 20 items only rule A gets right, 3 only rule B gets right: a real difference.
    assert mcnemar(20, 3)["p"] < 0.001
    assert mcnemar(4, 4)["p"] == 1.0 and not mcnemar(4, 4)["significant"]
    assert mcnemar(0, 0)["p"] is None
