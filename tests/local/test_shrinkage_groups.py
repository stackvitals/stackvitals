import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "accuracy" / "uncertainty"))

from shrinkage import keys  # noqa: E402


def test_finer_groups_fall_back_to_language_and_size_then_all():
    r = {"language": "Go", "stars": 500, "median_s": 700, "workflows": 5}
    plain = keys(r)
    assert plain[-1] == "all|all" and len(plain) == 2
    both = keys(r, "lang_size_both")
    assert both[1:] == plain and both[0].startswith(plain[0] + "|") and both[0].endswith("d2w2")
    assert keys(r, "lang_size_duration")[0].endswith("|d2") and keys(r, "lang_size_workflows")[0].endswith("|w2")
