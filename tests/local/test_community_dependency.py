"""Community health beyond newcomers: who carries the merged work (people, the top person's share, the CHAOSS bus factor,
no names), how fast newcomers are answered compared with regulars, and both against similar public repos."""
from datetime import datetime, timedelta, timezone

from stackvitals.community.analyze import answers_by_tenure, dependency, peer_range

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def t(days, hours=0):
    return (NOW - timedelta(days=days) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, au, cr, as_="NONE", at="User", mg=None, cl=None, ev=(), cm=()):
    st = "MERGED" if mg else "CLOSED" if cl else "OPEN"
    return {"t": "pr", "n": n, "st": st, "cr": cr, "mg": mg, "cl": cl or mg, "au": au, "at": at, "as": as_,
            "ev": list(ev), "cm": list(cm)}


def merged(n, au, days, at="User"):
    return pr(n, au, t(days + 1), "MEMBER", at=at, mg=t(days))


def test_who_carries_the_merged_work_without_naming_anyone():
    prs = [merged(i, "amy", 10 + i) for i in range(12)] + [merged(100 + i, "bob", 20 + i) for i in range(6)] + \
          [merged(200 + i, "cat", 30 + i) for i in range(4)] + [merged(300, "dependabot[bot]", 5, at="Bot")] + \
          [merged(400 + i, "old", 200 + i) for i in range(30)]  # over 180 days ago
    d = dependency(prs, NOW)
    # 22 merged PRs by people: amy 12 already covers half, so one person carries half of the work.
    assert d == {"days": 180, "merged": 22, "people": 3, "top_share": 0.5455, "bus_factor": 1}
    assert "amy" not in str(d)
    even = [merged(i, f"p{i % 4}", 10 + i) for i in range(24)]
    assert dependency(even, NOW)["bus_factor"] == 2 and dependency(even[:19], NOW) is None  # under 20 merged PRs


def review(at, who, assoc="MEMBER"):
    return ["review", at, who, "COMMENTED", assoc, "User", False]


def test_newcomers_and_regulars_get_their_first_answers_measured_apart():
    prs = [pr(1, "maint", t(400), "OWNER", mg=t(400))]
    n = 2
    for i in range(10):  # ten newcomers answered after 30 hours
        prs.append(pr(n, f"new{i}", t(40), ev=[review(t(40, 30), "maint")])); n += 1
    for i in range(10):  # ten regulars (earlier work 200 days ago) answered after 2 hours
        prs.append(pr(n, f"reg{i}", t(200), mg=t(199))); n += 1
        prs.append(pr(n, f"reg{i}", t(30), ev=[review(t(30, 2), "maint")])); n += 1
    out = answers_by_tenure(prs, [], NOW)
    assert out["days"] == 90
    assert out["newcomers"] == {"n": 10, "median_h": 30.0, "answered_1d_share": 0.0}
    assert out["regulars"] == {"n": 10, "median_h": 2.0, "answered_1d_share": 1.0}
    few = answers_by_tenure(prs[:4], [], NOW)
    assert few["newcomers"]["n"] == 3 and few["newcomers"]["median_h"] is None  # under 10: not enough to say


def test_peer_ranges_show_the_typical_value_rather_than_a_rank():
    bench = {"groups": {"Python|1k-10k": {"repos": 300, "bus_factor": {"repos": 280, "p10": 1, "p25": 1, "p50": 2, "p75": 3, "p90": 5}},
                        "all|all": {"repos": 900, "bus_factor": {"repos": 900, "p10": 1, "p25": 1, "p50": 1, "p75": 2, "p90": 4}}}}
    assert peer_range(bench, "Python", 4000, "bus_factor") == {"group": "Python repos with 1k-10k stars", "repos": 280,
                                                                "typical": 2, "low": 1, "high": 3}
    assert peer_range(None, "Python", 4000, "bus_factor") is None


def test_the_community_result_carries_who_carries_the_work_and_answers_by_tenure():
    from stackvitals.community.build import build
    prs = [merged(i, f"p{i % 4}", 10 + i) for i in range(24)]
    bench = {"groups": {"all|all": {"repos": 900, "bus_factor": {"repos": 900, "p10": 1, "p25": 1, "p50": 2, "p75": 3, "p90": 5},
                                    "top_share": {"repos": 900, "p10": 0.2, "p25": 0.3, "p50": 0.45, "p75": 0.6, "p90": 0.8}}}}
    out = build({"closed": prs, "open": []}, {}, {}, {}, {"language": None, "stars": 50}, NOW, bench=bench)
    d = out["dependency"]
    assert (d["bus_factor"], d["people"], d["merged"]) == (2, 4, 24)
    assert d["peers"]["bus_factor"] == {"group": "public repos we track", "repos": 900, "typical": 2, "low": 1, "high": 3}
    assert d["peers"]["top_share"]["typical"] == 0.45
    assert out["tenure"]["days"] == 90 and out["tenure"]["newcomers"]["n"] == 0
    assert build({"closed": [], "open": []}, {}, {}, {}, {}, NOW)["dependency"] is None


def test_the_report_says_who_carries_the_work_and_how_fast_newcomers_hear_back():
    from stackvitals.community.build import build
    from stackvitals.community.report import render_html, render_text
    prs = [merged(i, f"p{i % 4}", 10 + i) for i in range(24)]
    bench = {"groups": {"all|all": {"repos": 900, "bus_factor": {"repos": 900, "p10": 1, "p25": 1, "p50": 2, "p75": 3, "p90": 5},
                                    "top_share": {"repos": 900, "p10": 0.2, "p25": 0.3, "p50": 0.45, "p75": 0.6, "p90": 0.8}}}}
    out = build({"closed": prs, "open": []}, {}, {}, {}, {"language": None, "stars": 50}, NOW, bench=bench)
    out["tenure"] = {"days": 90, "newcomers": {"n": 12, "median_h": 30.0, "answered_1d_share": 0.25},
                     "regulars": {"n": 4, "median_h": None, "answered_1d_share": None}}
    text = render_text(out, "o/r")
    assert ("24 merged pull requests by 4 people in the last 180 days; the most active person made 25% of them. "
            "Bus factor 2: the fewest people behind half of the merged work.") in text
    assert "Public repos we track (900): bus factor typically 2 (middle half 1 to 3); the most active person's share typically 45%." in text
    assert "Newcomers (their first contribution here): 12, first answer after 30 h (median), within a day 25%." in text
    assert "Regulars: 4, too few to say (10 needed)." in text
    assert "Who carries the work" in render_html(out, "o/r")
    out["dependency"] = None
    assert "Fewer than 20 merged pull requests by people in the last 180 days" in render_text(out, "o/r")
