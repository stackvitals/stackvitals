"""The agent work ledger: each coding agent's PRs on their own (merge rate, review rounds, reverts, CI failures) against
people's PRs of the same month and size; the review load agents add (inflow against merges, the waiting queue,
reviewers' open requests); and the review an open PR can expect, from similar PRs merged here."""
from datetime import datetime, timedelta, timezone

from stackvitals.core import agent_ledger

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, au, at="User", days=10, size=40, head="feature", reviews=1, merged=True, rq=(), draft=False, mg_days=None):
    created = NOW - timedelta(days=days)
    p = {"n": n, "au": au, "at": at, "head": head, "add": size, "del": 0, "cr": iso(created), "draft": draft, "rq": list(rq),
         "ev": [["review", iso(created + timedelta(hours=2 + i)), "rev", "COMMENTED", "", "User"] for i in range(reviews)]}
    if merged:
        p["mg"] = iso(NOW - timedelta(days=mg_days if mg_days is not None else days - 1))
    return p


def row(p, review_h=3.0):
    return (p, {"pickup": 1.0, "review": review_h, "cycle_to_merge": 20.0, "devlake_cycle_min": 1200}, None)


def test_each_agent_gets_its_own_line_with_review_rounds_and_merge_rate():
    rows = [row(pr(i, "Copilot", at="Bot", head=f"copilot/x{i}", reviews=3)) for i in range(12)]
    rows += [row(pr(100 + i, "devin-ai-integration[bot]", at="Bot", reviews=1)) for i in range(11)]
    rows += [row(pr(200 + i, f"dev{i % 4}", reviews=1)) for i in range(30)]
    decided = [r[0] for r in rows] + [pr(300, "Copilot", at="Bot", head="copilot/y", merged=False)]
    got = agent_ledger.by_agent(rows, {"runs": []}, [], NOW, decided)
    assert set(got) == {"copilot agent", "devin agent"}
    cop = got["copilot agent"]
    assert cop["prs"] == 12 and cop["review_rounds_p50"] == 3 and cop["merge_rate"] == round(12 / 13, 4)
    assert got["devin agent"]["review_rounds_p50"] == 1 and got["devin agent"]["merge_rate"] == 1.0
    assert "matched" in cop and cop["window"]["n"] == 12


def test_an_agent_with_few_prs_keeps_its_count_but_no_rates():
    rows = [row(pr(1, "Copilot", at="Bot", head="copilot/x"))] + [row(pr(200 + i, "dev")) for i in range(20)]
    got = agent_ledger.by_agent(rows, {"runs": []}, [], NOW, [r[0] for r in rows])
    assert got["copilot agent"]["prs"] == 1 and got["copilot agent"]["merge_rate"] is None


def test_review_load_compares_what_arrives_with_what_merges_and_who_holds_requests():
    flow = {"closed": [pr(i, "Copilot", at="Bot", head="copilot/x", days=3) for i in range(6)]
                      + [pr(50 + i, "dev", days=3) for i in range(2)],
            "open": [pr(80 + i, "Copilot", at="Bot", head="copilot/z", days=2, merged=False, reviews=0, rq=["amy"]) for i in range(5)]
                    + [pr(90, "dev", days=1, merged=False, reviews=0, rq=["amy", "bob"]),
                       pr(91, "dev", days=1, merged=False, reviews=0, draft=True)]}
    got = agent_ledger.review_load(flow, NOW, weeks=2)
    this = got["weeks"][-1]
    assert this["opened"] == {"agent": 11, "person": 4} and this["merged"] == {"agent": 6, "person": 2}
    assert got["waiting"] == {"agent": 5, "person": 1}  # drafts don't wait for review
    assert got["reviewers"] == {"n": 2, "max_open": 6, "agent_share": round(5 / 7, 4)}


def test_an_open_pr_expects_the_review_of_similar_prs_merged_here():
    history = [row(pr(i, "dev", size=40), review_h=2.0 + i % 3) for i in range(12)]
    history += [row(pr(100 + i, "Copilot", at="Bot", head="copilot/x", size=40), review_h=9.0) for i in range(6)]
    open_prs = [pr(500, "dev", size=45, merged=False), pr(501, "Copilot", at="Bot", head="copilot/q", size=40, merged=False),
                pr(502, "dev", size=5000, merged=False)]
    got = {e["pr"]: e for e in agent_ledger.expected_review(open_prs, history)}
    assert got[500]["p50_h"] == 3.0 and got[500]["similar"] == 12 and got[500]["kind"] == "person"
    assert got[501]["p50_h"] == 9.0 and got[501]["kind"] == "agent"
    assert got[502]["p50_h"] is None  # nothing that size here yet: no guess


def test_the_crawl_leaderboard_reaches_a_page_only_as_numbers_and_short_names():
    good = {"window_days": 180, "agents": {"copilot": {"repos": 40, "prs": 900, "merged": 0.71, "merged_by_others": 0.2,
                                                       "vs_people": {"gap": -0.05, "low": -0.09, "high": -0.01, "prs_compared": 800}}}}
    assert agent_ledger.leaderboard(good) == good
    bad = {"window_days": 180, "agents": {"<script>": {"repos": 40, "prs": 9, "merged": 0.5, "merged_by_others": 0.1},
                                          "codex": {"repos": "x", "prs": 9, "merged": 0.5, "merged_by_others": 0.1},
                                          "devin": {"repos": 12, "prs": 50, "merged": 2.0, "merged_by_others": 0.1}}}
    assert agent_ledger.leaderboard(bad) is None and agent_ledger.leaderboard(None) is None
