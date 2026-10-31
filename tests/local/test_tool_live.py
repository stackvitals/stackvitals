from datetime import datetime, timedelta, timezone

import httpx

from mergescout.tool.live import GitHubLive

NOW = datetime.now(timezone.utc)


def iso(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def gql_issue(**over):
    issue = {"title": "T", "state": "OPEN", "stateReason": None, "updatedAt": iso(1),
             "assignees": {"totalCount": 0}, "labels": {"nodes": [{"name": "good first issue"}]},
             "closedByPullRequestsReferences": {"nodes": []}, "comments": {"nodes": []}}
    issue.update(over)
    return {"data": {"rateLimit": {"cost": 1, "remaining": 4999, "resetAt": iso(0)},
                     "repository": {"issue": issue}}}


def live_with(payload=None, token="tok", rest=None):
    def handler(req):
        if req.url.path == "/graphql":
            return httpx.Response(200, json=payload)
        return rest(req)
    return GitHubLive(token, client=httpx.Client(transport=httpx.MockTransport(handler)))


def comment(login, body, days, assoc="NONE", typ="User"):
    return {"createdAt": iso(days), "authorAssociation": assoc, "author": {"__typename": typ, "login": login},
            "bodyText": body}


def test_free_issue_is_available():
    s = live_with(gql_issue()).issue_status("o", "r", 1)
    assert s["available"] is True and s["source"] == "github graphql" and s["linked_open_prs"] == 0


def test_old_claims_bots_and_ghosts_do_not_block():
    s = live_with(gql_issue(comments={"nodes": [comment("eager", "Can I work on this?", 30),
                                                comment("github-actions", "Can I work on this?", 1, typ="Bot"),
                                                comment("ghost", "I'd like to work on this", 1)]})).issue_status("o", "r", 1)
    assert s["available"] is True and s["claims"] == []


def test_fresh_lane_searches_new_beginner_issues():
    seen = []

    def rest(req):
        seen.append(req)
        return httpx.Response(200, json={"items": [{"repository_url": "https://api.github.com/repos/octo/widgets",
                                                    "number": 12, "title": "New one", "labels": [{"name": "good first issue"}],
                                                    "created_at": iso(0), "html_url": "https://github.com/octo/widgets/issues/12"}]})
    items = live_with(token=None, rest=rest).fresh_issues("python", NOW - timedelta(days=1))
    assert items[0]["repo"] == "octo/widgets" and items[0]["number"] == 12
    q = seen[0].url.params["q"]
    assert 'label:"good first issue","help wanted"' in q and "language:python" in q and "no:assignee" in q
