import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "accuracy" / "flaky"))

from masking import summarise  # noqa: E402


def _row(caused, old, new, repo="o/r"):
    return {"repo": repo, "caused_by_change": caused, "old_safe": old, "new_safe": new}


def test_card_shows_what_the_cautious_rule_costs():
    rows = ([_row("no", True, True)] * 5 + [_row("no", True, False)] * 14 + [_row("yes", True, False)] * 15
            + [_row("unclear", True, True)] * 2)
    out = summarise(rows)
    assert out["new_rule"]["n"] == 5 and out["new_rule"]["caused_by_change"] == 0
    cost = out["harmless_called_safe"]
    assert cost["new_rule"]["n"] == 19 and cost["new_rule"]["called_safe"] == 5
    assert cost["old_rule"]["called_safe"] == 19 and cost["new_rule"]["low"] < 0.263 < cost["new_rule"]["high"]
