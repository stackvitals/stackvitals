import json
from datetime import datetime, timedelta, timezone

from stackvitals.community.build import build
from stackvitals.community.report import badges, render_html, render_markdown, render_text

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def t(days, hours=0):
    return (NOW - timedelta(days=days) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, au, cr, as_="NONE", mg=None, ev=(), cm=(), title="Fix things"):
    return {"t": "pr", "n": n, "st": "MERGED" if mg else "OPEN", "cr": cr, "mg": mg, "cl": mg, "au": au, "at": "User",
            "as": as_, "ev": list(ev), "cm": list(cm), "ti": title}


BENCH = {"built_at": "2026-10-19", "groups": {"all|all": {
    "repos": 900, "first_answer_hours": {"repos": 800, "p10": 1, "p25": 6, "p50": 24, "p75": 70, "p90": 200},
    "newcomer_answered_share": {"repos": 500, "p10": 0.2, "p25": 0.4, "p50": 0.64, "p75": 0.8, "p90": 0.95},
    "newcomer_return_rate": {"repos": 300, "p10": 0.05, "p25": 0.14, "p50": 0.21, "p75": 0.3, "p90": 0.4}}},
    "newcomers": {"newcomers": 2824, "repos": 321, "return_days": 90, "by_answer": [
        {"bucket": "within 1 day", "newcomers": 999, "returned": 0.299, "merged": 0.54},
        {"bucket": "over 14 days", "newcomers": 553, "returned": 0.217, "merged": 0.43},
        {"bucket": "no answer", "newcomers": 587, "returned": 0.153, "merged": 0.0}], "by_outcome": []}}


def data():
    prs = [pr(1, "maint", t(400), "OWNER", mg=t(400))]
    prs += [pr(10 + i, f"o{i}", t(60 - i), mg=t(60 - i, 5)) for i in range(12)] + [pr(100 + i, f"o{i}", t(395), mg=t(395)) for i in range(12)]
    prs += [pr(200 + i, f"n{i}", t(200), mg=t(199) if i < 8 else None) for i in range(10)]
    prs += [pr(300, "fresh", t(9), title="<script>alert(1)</script> @everyone")]
    return {"open": [p for p in prs if p["st"] == "OPEN"], "closed": [p for p in prs if p["st"] != "OPEN"]}


def result():
    return build(data(), {"open": [], "closed": []}, {"weeks": {}}, {}, {"language": "Python", "stars": 5000}, NOW, bench=BENCH)


def test_build_gathers_the_score_the_waiting_list_and_the_crawl_lever():
    r = result()
    assert r["score"]["score"] > 0 and r["score"]["repos"] == 900
    assert [w["n"] for w in r["waiting"]] == [208, 209, 300]  # unmerged first PRs nobody answered, oldest first
    assert r["lever"]["newcomers"] == 2824 and r["traffic"] is None


def test_pages_name_items_not_people_and_escape_what_people_wrote():
    r = result()
    md, page, text = render_markdown(r, "o/r"), render_html(r, "o/r"), render_text(r, "o/r")
    for out in (md, page, text):
        assert "fresh" not in out and "n0" not in out  # the waiting list names items, never people
        assert "<script>alert" not in out  # the page has its own script; what people wrote is escaped
    assert "https://github.com/o/r/pull/300" in page and "29.9%" in md and "/100" in md


def test_badges_follow_the_shields_endpoint_format():
    files = badges(result())
    facts, score = files["community-badge.json"], files["community-score.json"]
    assert facts["schemaVersion"] == 1 and "first answer" in facts["message"] and "newcomers back" in facts["message"]
    assert score["label"] == "community score" and score["message"].endswith("/100")
    empty = badges(build({"open": [], "closed": []}, {"open": [], "closed": []}, {}, {}, {}, NOW))
    assert empty["community-badge.json"]["message"] == "not enough data yet" and empty["community-score.json"]["color"] == "lightgrey"
    json.dumps(files)


def test_the_report_says_when_automated_accounts_were_left_out_and_when_outside_prs_stopped():
    r = result()
    r["answers"]["left_out"] = {"accounts": 1, "items": 82}
    r["answers"]["issues"] = {"items": 0, "answered": None, "median_hours": None, "within_1d": None, "earlier": 16}
    text = render_text(r, "o/r")
    assert "82 items from 1 account that opened 20 or more in one day" in text
    assert "No outside issues in the last 90 days (16 in the 9 months before)" in text
