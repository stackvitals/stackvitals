"""What delivery metrics need from collection: the first commit (coding time), the merge commit (matching deployments),
the first comments (pickup counts comments, as LinearB and DevLake do), labels on closed PRs (hotfixes), AI co-author
trailers, and deployments and releases with the commit they shipped."""
from datetime import datetime, timedelta, timezone

from stackvitals.flow.collect import OPEN_ONLY, _repo_fields, ai_tools, pr_record

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def iso(h):
    return (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def node():
    return {"number": 7, "title": "Fix pool", "isDraft": False, "state": "MERGED", "createdAt": iso(50), "updatedAt": iso(1),
            "mergedAt": iso(10), "closedAt": iso(10), "additions": 10, "deletions": 2, "changedFiles": 1,
            "author": {"__typename": "User", "login": "amy"}, "authorAssociation": "NONE", "baseRefName": "main",
            "headRefName": "fix", "headRepositoryOwner": {"login": "amy"}, "mergeable": "UNKNOWN",
            "mergeCommit": {"oid": "m3rg3"},
            "first": {"totalCount": 4, "nodes": [{"commit": {"authoredDate": iso(70)}}]},
            "commits": {"nodes": [{"commit": {"committedDate": iso(20), "authoredDate": iso(21)}}]},
            "recent": {"nodes": [{"commit": {"authoredDate": iso(21), "committedDate": iso(20), "parents": {"totalCount": 1},
                                              "author": {"user": {"login": "amy"}},
                                              "message": "Fix pool\n\nCo-authored-by: Claude <noreply@anthropic.com>"}}]},
            "reviewRequests": {"nodes": []}, "labels": {"nodes": [{"name": "hotfix"}]}, "marks": {"nodes": []},
            "events": {"filteredCount": 0, "nodes": []},
            "early": {"nodes": [{"createdAt": iso(49), "author": {"__typename": "User", "login": "bob"}, "authorAssociation": "MEMBER"}]},
            "talk": {"filteredCount": 12, "nodes": [{"createdAt": iso(30), "body": "looks good", "author": {"__typename": "User", "login": "bob"},
                                                     "authorAssociation": "MEMBER"}]}}


def test_a_pr_record_keeps_what_delivery_needs():
    r = pr_record(node(), NOW)
    assert r["fa"] == iso(70) and r["nc"] == 4 and r["mc"] == "m3rg3" and r["ai"] == ["claude"]
    assert [c[0] for c in r["cm"]] == [iso(49), iso(30)]  # the first comments join the latest ones, oldest first
    assert r["cmn"] == 12 and r["lb"] == ["hotfix"]
    assert "lb" not in OPEN_ONLY  # labels stay on closed PRs: a merged hotfix is an incident


def test_ai_tools_are_read_from_co_author_trailers_and_tool_footers():
    assert ai_tools(["x\n\nCo-authored-by: Claude <noreply@anthropic.com>"]) == ["claude"]
    assert ai_tools(["Generated with [Claude Code](https://claude.com/claude-code)"]) == ["claude"]
    assert ai_tools(["Co-authored-by: Copilot <175728472+Copilot@users.noreply.github.com>",
                     "Co-authored-by: Cursor Agent <cursoragent@cursor.com>"]) == ["copilot", "cursor"]
    assert ai_tools(["Co-authored-by: Ann <ann@example.com>", "plain"]) == []


def test_deployments_and_releases_carry_their_commit_and_finish_time():
    repo = {"defaultBranchRef": {"name": "main"}, "primaryLanguage": None, "stargazerCount": 5,
            "releases": {"nodes": [{"tagName": "v1", "createdAt": iso(30), "publishedAt": iso(29), "isPrerelease": False,
                                    "isDraft": False, "tagCommit": {"oid": "t4g"}}]},
            "deployments": {"nodes": [{"environment": "production", "createdAt": iso(9), "commitOid": "d3p",
                                       "latestStatus": {"state": "SUCCESS", "createdAt": iso(8)}}]}}
    info = _repo_fields(repo)
    assert info["releases"][0]["sha"] == "t4g" and info["deployments"][0] == {"env": "production", "at": iso(9), "state": "SUCCESS",
                                                                              "sha": "d3p", "done": iso(8)}


def test_issues_keep_their_labels_so_incidents_can_be_found():
    from stackvitals.community.collect import SCHEMA, issue_record
    node = {"number": 9, "state": "CLOSED", "createdAt": iso(30), "updatedAt": iso(1), "closedAt": iso(20),
            "author": {"__typename": "User", "login": "ops"}, "authorAssociation": "MEMBER",
            "labels": {"nodes": [{"name": "incident"}, {"name": "sev2"}]},
            "comments": {"totalCount": 0, "nodes": []}, "closer": {"nodes": []}}
    assert issue_record(node, NOW)["lb"] == ["incident", "sev2"] and SCHEMA >= 2
