from datetime import datetime, timezone

from stackvitals.connectors import jira, linear
from stackvitals.connectors.store import _clean

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)


def test_a_jira_issue_keeps_the_epic_it_belongs_to():
    raw = {"id": "100", "key": "WEB-1", "fields": {"summary": "Fix login", "issuetype": {"name": "Story"},
           "status": {"name": "Done", "statusCategory": {"key": "done"}}, "created": "2026-10-01T10:00:00.000+0000",
           "parent": {"key": "WEB-9", "fields": {"summary": "Accounts revamp", "issuetype": {"name": "Epic"}}}}}
    issue = jira._records(raw, "https://x.atlassian.net", None, None, False)[0]
    assert issue["epic"] == "WEB-9" and issue["epic_title"] == "Accounts revamp"
    # A sub-task's parent is a story, not an epic.
    raw["fields"]["parent"]["fields"]["issuetype"]["name"] = "Story"
    assert jira._records(raw, "https://x.atlassian.net", None, None, False)[0].get("epic") is None


def test_a_linear_issue_keeps_its_project_and_public_repos_lose_its_name():
    n = {"id": "abc", "identifier": "ENG-4", "title": "t", "url": "u", "state": {"name": "Done", "type": "completed"},
         "project": {"id": "p1", "name": "Billing v2"}, "createdAt": "2026-10-01T10:00:00.000Z"}
    issue = linear._issue_records(n, set())[0]
    assert issue["epic"] == "linear:project:p1" and issue["epic_title"] == "Billing v2"
    clean = _clean(issue)
    assert "epic_title" not in clean and clean["epic"] == "linear:project:p1"


def test_investment_by_epic_shares_merged_work_and_feature_work():
    from stackvitals.core.investment import by_epic
    prs = [{"n": n, "mg": "2026-10-10T00:00:00Z", "au": "ann", "at": "User", "ti": f"WEB-{k}: x", "head": "f"}
           for n, k in ((1, 1), (2, 1), (3, 2), (4, 3), (5, 7))]
    issues = [{"key": "WEB-1", "type": "REQUIREMENT", "epic": "WEB-9", "epic_title": "Accounts"},
              {"key": "WEB-2", "type": "BUG", "epic": "WEB-9", "epic_title": "Accounts"},
              {"key": "WEB-3", "type": "REQUIREMENT", "epic": "WEB-8", "epic_title": "Search"},
              {"key": "WEB-7", "type": "TASK"}]
    out = by_epic(prs, issues, NOW)
    assert out["linked"] == 5 and out["epics"][0] == {"epic": "WEB-9", "title": "Accounts", "prs": 3, "share": 0.6}
    assert out["no_epic"] == 1 and out["feature_share"] == 0.6
    assert by_epic(prs, [], NOW) is None


def test_backports_to_release_branches_are_not_counted_twice_by_epic():
    from datetime import datetime, timezone
    from stackvitals.core.investment import by_epic
    now = datetime(2026, 10, 23, tzinfo=timezone.utc)
    issue = {"key": "WEB-1", "id": "jira:1", "type": "Story", "epic": "jira:9", "epic_title": "Billing"}
    pr = lambda n, base: {"n": n, "mg": "2026-10-10T00:00:00Z", "ti": "WEB-1: x", "head": "x", "au": "ann", "at": "User", "base": base}  # noqa: E731
    got = by_epic([pr(1, "main"), pr(2, "release-1.x")], [issue], now, base="main")
    assert got["linked"] == 1 and got["epics"][0]["prs"] == 1
