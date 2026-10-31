import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "accuracy" / "flaky"))

from outside_fresh import score  # noqa: E402


def test_matches_are_judged_by_what_the_rerun_did_and_flakes_caught_are_counted():
    rows = ([{"read": True, "evidence": "passed", "signature": "serverbusy"}] * 6
            + [{"read": True, "evidence": "failed again", "signature": "http 503"}] * 2
            + [{"read": True, "evidence": "passed", "signature": None}] * 14
            + [{"read": True, "evidence": "failed again", "signature": None}] * 18
            + [{"read": True, "evidence": "not run", "signature": "too many requests"}]
            + [{"read": False, "evidence": "passed", "signature": None}])
    out = score(rows)
    assert out["jobs_read"] == 41 and out["matched"] == 9
    assert out["matched_with_rerun"] == {"passed": 6, "failed_again": 2}
    assert out["passed_among_matched_with_rerun"]["share"] == 0.75
    assert out["flakes_caught"]["k"] == 6 and out["flakes_caught"]["n"] == 20
    assert out["repeats_caught"]["share"] == 0.1 and out["match_rate_not_rerun"]["k"] == 1
