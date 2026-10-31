"""Every module decides who is an insider, a bot or an agent with the one shared rule (the crawl's)."""
from datetime import datetime, timedelta, timezone

from mergescout.github.graphql import GraphQLResult
from stackvitals.community import analyze as community
from stackvitals.contribute.brief import _outside
from stackvitals.flow.analyze import analyze
from stackvitals.flow.knowledge import expertise
from stackvitals.flow.peers import own_metrics
from stackvitals.portal.inventory import review_stats

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def at(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, au, assoc="CONTRIBUTOR", kind="User", st="MERGED", cr=100, mg=80, merged_by=None, ev=(), paths=("src/a.py",)):
    events = list(ev)
    if merged_by:
        events.append(["merged", at(mg), merged_by])
    return {"t": "pr", "n": n, "ti": f"PR {n}", "draft": False, "st": st, "cr": at(cr), "up": at(1),
            "mg": at(mg) if st == "MERGED" else None, "cl": at(mg) if st != "OPEN" else None, "add": 10, "del": 1,
            "files": 1, "au": au, "at": kind, "as": assoc, "rq": [], "ev": sorted(events, key=lambda e: e[1]), "cm": [],
            "ci": "SUCCESS", "lc": at(cr - 1), "paths": list(paths)}


def rv(hours, who, state="APPROVED", assoc="CONTRIBUTOR", kind="User"):
    return ["review", at(hours), who, state, assoc, kind, False]


def history():
    # quietlead shows as CONTRIBUTOR (a private org member) but merges others' PRs: an insider by what they do.
    closed = [pr(k, "newcomer", cr=300 + k, mg=280 + k, merged_by="quietlead", ev=[rv(290 + k, "quietlead")]) for k in range(1, 9)]
    closed += [pr(10, "quietlead", cr=200, mg=190, merged_by="quietlead")]
    closed += [pr(11, "bors", kind="User", cr=150, mg=140, merged_by="bors")]  # a known bot typed as a user
    closed += [pr(12, "devin-ai-integration", kind="User", st="CLOSED", cr=120, mg=110)]  # a coding agent typed as a user
    closed += [pr(13, "drive-by", st="CLOSED", cr=90, mg=85)]
    return closed


def test_team_flow_lets_a_merging_contributor_hold_the_ball_and_counts_them_as_an_insider():
    waiting = pr(20, "alice", st="OPEN", cr=30, ev=[rv(20, "quietlead", "CHANGES_REQUESTED")])
    result = analyze({"open": [waiting], "closed": history()}, NOW)
    q = {x["n"]: x for x in result["queue"]}[20]
    assert q["actor"] == "author" and "quietlead" in q["why"]
    # quietlead's own PR sits with the insiders; bors and the agent are not people; drive-by and newcomer are outsiders.
    assert result["groups"]["insider"]["merged"] == 1
    assert result["groups"]["outsider"]["merged"] == 8 and result["groups"]["outsider"]["closed_unmerged"] == 1
    assert result["bots"]["closed"] == 2


def test_knowledge_and_peer_metrics_use_the_same_insiders():
    ex = expertise(history(), NOW)
    assert "quietlead" in ex.insiders and "newcomer" not in ex.insiders
    own = own_metrics(history(), NOW, window_days=365)
    # 8 reviews by quietlead count as maintainer reviews (10 h each); quietlead's own PR is not an outside PR.
    assert own["first_review_hours"] == 10 and own["prs"] == 10
    assert own["outsider_merge_rate"] == round(8 / 9, 4)


def test_community_and_the_brief_leave_out_bots_agents_and_merging_contributors():
    prs = history()
    ins = community.insiders(prs, [])
    assert ins == {"quietlead"}
    assert not community.outside(prs[-2], ins) and community.outside(prs[-1], ins)  # the agent is out, drive-by is in
    out = _outside(prs, at(400), NOW, None, None, None)
    assert out["closed"] == 9 and out["merged"] == 8


class Fake:
    def __init__(self, nodes):
        self.nodes = nodes

    def query(self, query, variables=None, **kw):
        return GraphQLResult(data={"repository": {"pullRequests": {"nodes": self.nodes}}}, cost=1, remaining=999, reset_at="x")


def test_portal_review_stats_skip_known_bots_even_with_a_maintainer_label():
    def node(days, reviewer, assoc):
        created = NOW - timedelta(days=days)
        return {"createdAt": created.strftime("%Y-%m-%dT%H:%M:%SZ"), "author": {"login": "amy", "__typename": "User"},
                "authorAssociation": "NONE",
                "reviews": {"nodes": [{"submittedAt": (created + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                       "author": {"login": reviewer}, "authorAssociation": assoc}]}}
    nodes = [node(10 + i, "maint", "MEMBER") for i in range(10)] + [node(3, "bors", "MEMBER"), node(4, "k8s-ci-robot", "COLLABORATOR")]
    s = review_stats(Fake(nodes), "acme/web", NOW)
    assert s["prs"] == 12 and s["reviewers"] == ["maint"]
