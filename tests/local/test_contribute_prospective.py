import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "accuracy" / "contribute"))
from prospective import attempts, compare  # noqa: E402

START, END = "2026-10-23T00:00:00Z", "2027-01-21T23:59:59Z"
ITEMS = [{"repo": "o/r", "issue": n, "rank_score": s, "p_merge": p, "available": a}
         for n, s, p, a in ((1, 0.9, 0.8, True), (2, 0.5, 0.5, True), (3, 0.1, 0.2, False))]


def pr(n, closes, created, merged=None, author="out", assoc="NONE", merged_by=None):
    return {"repo": "o/r", "number": n, "created": created, "merged": merged, "author": author, "association": assoc,
            "merged_by": merged_by, "closes": closes}


def test_only_outsiders_first_prs_in_the_window_count_and_merged_means_within_30_days():
    prs = [pr(10, [1], "2026-11-01T00:00:00Z", "2026-11-05T00:00:00Z"),          # merged in 4 days
           pr(11, [1], "2026-11-02T00:00:00Z", "2026-11-03T00:00:00Z"),          # second attempt: ignored
           pr(12, [2], "2026-10-21T00:00:00Z", "2026-10-22T00:00:00Z"),          # before the freeze: ignored
           pr(13, [2], "2026-11-10T00:00:00Z", "2027-01-30T00:00:00Z"),          # merged after 81 days: not merged
           pr(14, [3], "2026-11-10T00:00:00Z", "2026-11-11T00:00:00Z", assoc="MEMBER"),  # insider
           pr(15, [], "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", author="boss", merged_by="maint"),
           pr(16, [3], "2026-12-01T00:00:00Z", None, author="maint")]           # merged others' PRs: insider
    got = {x["issue"]: x["merged"] for x in attempts(ITEMS, prs, START, END)}
    assert got == {1: True, 2: False}
    out = compare(ITEMS, attempts(ITEMS, prs, START, END), draws=50)
    assert out["attempted"] == 2 and out["top_third_attempted"] == 1 and out["too_few"] is True
    assert out["primary"]["top_third"] == 1.0 and out["primary"]["all"] == 0.5 and out["free"]["free"] == 0.5
