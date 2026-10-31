import pytest

from mergescout.signals.identity import build_people, build_pr_class
from mergescout.signals.repo_stats import build_repo_stats, wilson
from signals_data import NOW, make_con, pr


def stats(prs):
    con = make_con({"prs": prs})
    build_people(con)
    build_pr_class(con)
    build_repo_stats(con, NOW)
    cols = [d[0] for d in con.execute("SELECT * FROM repo_stats").description]
    return dict(zip(cols, con.execute("SELECT * FROM repo_stats").fetchone()))


def test_wilson_matches_the_textbook_values():
    lo, hi = wilson(7, 7)
    assert lo == pytest.approx(0.646, abs=0.001) and hi == pytest.approx(1.0)
    assert wilson(0, 0) is None


def test_newcomer_counts_only_prs_up_to_the_first_merge():
    s = stats([pr(1, "a", state="CLOSED", created=50), pr(2, "a", created=40), pr(3, "a", created=10),
               pr(4, "b", state="CLOSED", created=20)])
    assert (s["newcomer_decided"], s["newcomer_merged"]) == (3, 1)


def test_review_time_ignores_self_reviews():
    s = stats([pr(1, "a", review_by="maint", review_assoc="MEMBER", review_after_h=10),
               pr(2, "b", review_by="b", review_assoc="NONE", review_after_h=1),
               pr(3, "c", review_by="maint", review_assoc="MEMBER", review_after_h=30)])
    assert s["reviewed"] == 2 and s["median_review_hours"] == pytest.approx(20) and not s["review_enough"]


def test_review_time_uses_the_first_human_review_when_known():
    from datetime import timedelta
    p = pr(1, "a", review_by="gemini-code-assist", review_assoc="NONE", review_after_h=0.05)
    p.update(first_human_review_by="maint", first_human_review_association="MEMBER",
             first_human_review_at=p["created_at"] + timedelta(hours=20))
    s = stats([p, pr(2, "b", review_by="maint", review_assoc="MEMBER", review_after_h=10)])
    assert s["reviewed"] == 2 and s["median_review_hours"] == pytest.approx(15)


def test_repo_stats_carry_the_repo_name():
    con = make_con({"prs": [pr(1, "o")], "repo_meta": [{"repo_id": 1, "name": "o/r", "stars": 120}]})
    build_people(con)
    build_pr_class(con)
    build_repo_stats(con, NOW)
    assert con.execute("SELECT name, stars FROM repo_stats").fetchone() == ("o/r", 120)
