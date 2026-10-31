"""Test impact without a coverage agent: names, changed tests and past failures pick the test files; build files pick
all; and the rule is replayed on past pull requests before it is trusted."""
from stackvitals.ci import impact

TESTS = ["tests/test_cart.py", "tests/test_users.py", "tests/test_billing.py"]


def test_selection_by_name_change_and_history():
    assert impact.select(["src/shop/cart.py"], TESTS) == ["tests/test_cart.py"]
    assert impact.select(["tests/test_users.py", "README.md"], TESTS) == ["tests/test_users.py"]
    assert impact.select(["pyproject.toml"], TESTS) is None and impact.select([], TESTS) is None
    learned = impact.learn([(["src/shop/prices.py"], ["tests/test_billing.py"])])
    assert impact.select(["src/shop/tax.py"], TESTS, learned) == ["tests/test_billing.py"]
    assert impact.select(["docs/guide.md"], TESTS) == []


def test_backtest_counts_failures_caught_and_tests_skipped():
    history = [(["src/shop/prices.py"], ["tests/test_billing.py"]),   # nothing learned yet: missed
               (["src/shop/tax.py"], ["tests/test_billing.py"]),      # learned from the first: caught
               (["src/shop/cart.py"], ["tests/test_cart.py"])]        # by name: caught
    got = impact.backtest(history, TESTS)
    assert (got["failures"], got["caught"], got["recall"]) == (3, 2, 0.6667) and got["skipped_share"] > 0.5


def test_history_from_ci_and_flow_leaves_flaky_tests_out():
    data = {"runs": [{"id": 1, "pr": [7], "cr": "2026-10-01T00:00:00Z"}],
            "tests": [{"run": 1, "failed": [["tests/test_cart.py::test_add", "x"], ["tests/test_users.py::test_racy", "y"]]}]}
    got = impact.history_from(data, {7: ["src/shop/cart.py"]}, {"tests/test_users.py::test_racy"})
    assert got == [(["src/shop/cart.py"], ["tests/test_cart.py"])]
