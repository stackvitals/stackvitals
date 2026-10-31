import json
import sqlite3
from datetime import datetime, timedelta, timezone

import anyio
import httpx
from mcp import Client

from mergescout.mcp_server import App, build_server
from mergescout.signals.evidence import build_all
from mergescout.signals.identity import build_people
from mergescout.signals.issues import build_issue_signals
from mergescout.signals.walls import find_walls
from mergescout.snapshot.build import build_snapshot
from mergescout.snapshot.publish import MANIFEST, SNAPSHOT
from mergescout.tool.live import GitHubLive, classify_comments
from mergescout.tool.queries import Snapshot, fts_query, rate_text

from signals_data import NOW, make_con, pr, t
from tool_data import ISSUE, REPO, make_snapshot

LIVE_NOW = datetime.now(timezone.utc)


def ago(days_ago):
    return (LIVE_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


# 2. Merge rates say what the window means in plain words.
def test_rate_wording_is_plain():
    busy = {**REPO, "merged": 49, "closed": 3, "merge_rate": 0.94, "merge_low": 0.84, "merge_high": 0.98,
            "window_days": 4, "window_complete": 0}
    text = rate_text(busy)
    assert text.startswith("94% of outsider PRs merged (49 of 52, likely 84-98%)")
    assert "newest 300 PRs, which cover only the last 4 days" in text
    assert "over the last 365 days" in rate_text(REPO)


# 3. Older claims and PRs mentioned in comments are shown, not hidden.
def test_snapshot_results_show_earlier_claims(tmp_path):
    snap = Snapshot(make_snapshot(tmp_path / "s.sqlite", issues=({**ISSUE, "claimers": 1,
                                                                 "last_claim_at": "2026-09-24T05:00:00Z"},)))
    row = snap.find_issues()["results"][0]
    assert "20 days ago" in row["earlier_claims"] and row["free"] is True


def issue_node(**over):
    issue = {"title": "T", "state": "OPEN", "stateReason": None, "updatedAt": ago(1), "assignees": {"totalCount": 0},
             "labels": {"nodes": [{"name": "good first issue"}]}, "closedByPullRequestsReferences": {"nodes": []},
             "timelineItems": {"nodes": []}, "comments": {"nodes": []}}
    issue.update(over)
    return issue


def live_answer(*issues):
    data = {"rateLimit": {"cost": 1, "remaining": 4999, "resetAt": ago(0)}}
    data.update({f"i{n}": {"issue": i} for n, i in enumerate(issues)})
    data["repository"] = {"issue": issues[0]} if issues else None

    def handler(req):
        return httpx.Response(200, json={"data": data})
    return GitHubLive("tok", client=httpx.Client(transport=httpx.MockTransport(handler)))


def gql_comment(login, body, days, assoc="NONE"):
    return {"createdAt": ago(days), "authorAssociation": assoc, "author": {"__typename": "User", "login": login},
            "bodyText": body}


def test_live_check_reports_older_claims_and_pr_mentions():
    s = live_answer(issue_node(comments={"nodes": [gql_comment("eager", "I'd love to work on this issue", 26),
                                                  gql_comment("lead", "Could you try the build from draft PR #1106?", 2,
                                                          assoc="MEMBER")]})).issue_status("o", "r", 1)
    assert s["available"] is True and len(s["older_claims"]) == 1 and s["mentioned_prs"] == [1106]


def test_explain_shows_the_score_used_in_lists(tmp_path):
    snap = Snapshot(make_snapshot(tmp_path / "s.sqlite"))
    assert snap.explain("octo/widgets", 7)["score"]["in_lists"] == 0.6
