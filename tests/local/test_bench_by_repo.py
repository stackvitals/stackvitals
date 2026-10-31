import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "accuracy"))

from fair import by_repo  # noqa: E402


def test_one_big_repo_shows_up_in_every_figure():
    rows = [("big", False)] * 18 + [("a", False), ("b", False), ("c", False), ("d", True), ("e", False), ("f", False)]
    out = by_repo(rows)
    assert out["repos"] == 7 and out["biggest"] == {"repo": "big", "items": 18, "share": 0.75}
    assert out["without_biggest"]["k"] == 1 and out["without_biggest"]["n"] == 6
    # Each repo counted once is the widest honest range; it is wider than the items' own.
    assert out["repo_wilson_high"] > 0.4
    assert 0 <= out["boot_low"] <= out["boot_high"] <= 1


def test_no_hits_still_gives_a_range_and_the_bootstrap_is_seeded():
    rows = [(f"r{i}", False) for i in range(12)]
    out = by_repo(rows)
    assert out["boot_low"] == out["boot_high"] == 0.0 and out["repo_wilson_high"] > 0.2
    assert by_repo(rows) == out
    assert by_repo([])["repos"] == 0
