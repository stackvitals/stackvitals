"""One person across tools: Jira, Linear, Slack and Discord ids (or an email) map to a GitHub login through [identity]
aliases, so teams count their tracker issues and chat replies without listing anyone twice."""
from datetime import datetime, timezone

import httpx

from stackvitals.connectors import jira, linear, slack
from stackvitals.connectors.store import ConnectorStore
from stackvitals.core import identity
from stackvitals.core.config import parse
from test_connectors import JIRA_ENV, LINEAR_ENV, FakeJira, FakeLinear, jira_cfg, jira_issue, lin_issue, linear_cfg

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
IDENT = parse('[identity]\npeople = ["ana"]\n[identity.aliases]\n"jira:acc-1" = "ana"\n"slack:U9" = "bo"\n'
              '"Bo@Acme.com" = "bo"\n[identity.teams]\nweb = ["ana", "bo"]\n')[0]["identity"]


def test_tool_ids_and_emails_resolve_to_a_login():
    assert identity.login(IDENT, "jira:acc-1") == "ana"
    assert identity.login(IDENT, "linear:x", "bo@acme.com") == "bo"
    assert identity.login(IDENT, "jira:nobody", None) is None and identity.login(IDENT, None) is None
    assert identity.team_of(IDENT, "ana") == ["web"] and identity.team_of(IDENT, "zed") == []


def test_chat_ids_of_team_members_come_from_the_aliases():
    assert identity.tool_ids(IDENT, "slack") == {"U9"} and identity.tool_ids(IDENT, "discord") == set()


def test_jira_and_linear_keep_who_an_issue_is_assigned_to_on_a_private_repo(tmp_path):
    raw = jira_issue(1, "2026-09-05T10:00:00.000+0200")
    raw["fields"]["assignee"] = {"accountId": "acc-1", "displayName": "Ana", "emailAddress": "ana@acme.com"}
    jira.pull(ConnectorStore(tmp_path / "j", "jira"), JIRA_ENV, jira_cfg(), NOW, client=FakeJira([[raw]]).client())
    got = ConnectorStore(tmp_path / "j", "jira").load()["issue"][0]
    assert got["assignee"] == "jira:acc-1" and got["assignee_email"] == "ana@acme.com"
    fake = FakeJira([[raw]])
    jira.pull(ConnectorStore(tmp_path / "j", "jira"), JIRA_ENV, jira_cfg(), NOW, client=fake.client())
    assert "assignee" in [r for r in fake.calls if r.url.path.endswith("/search/jql")][0].url.params["fields"]
    lin = lin_issue(1, "2026-09-05T10:00:00.000Z")
    lin["assignee"] = {"id": "u-7", "email": "Bo@acme.com"}
    fake = FakeLinear([[lin]])
    linear.pull(ConnectorStore(tmp_path / "l", "linear"), LINEAR_ENV, linear_cfg(), NOW, client=fake.client())
    got = ConnectorStore(tmp_path / "l", "linear").load()["issue"][0]
    assert got["assignee"] == "linear:u-7" and got["assignee_email"] == "Bo@acme.com"
    assert "assignee { id email name }" in [b for _r, b in fake.calls if "issues(" in b["query"]][0]["query"]


def test_a_public_repo_keeps_no_assignee(tmp_path):
    store = ConnectorStore(tmp_path, "jira", redact=True)
    store.add([{"t": "issue", "id": "jira:1", "assignee": "jira:acc-1", "assignee_email": "a@b.c"}], "2026-10-21")
    got = ConnectorStore(tmp_path, "jira", redact=True).load()["issue"][0]
    assert "assignee" not in got and "assignee_email" not in got


def test_issues_done_are_counted_per_team_and_unmatched_people_are_counted():
    issues = [{"src": "jira", "id": "jira:1", "cat": "DONE", "resolved": "2026-10-10T00:00:00Z", "assignee": "jira:acc-1"},
              {"src": "linear", "id": "linear:2", "cat": "DONE", "resolved": "2026-10-11T00:00:00Z", "assignee": "linear:u-7",
               "assignee_email": "bo@acme.com"},
              {"src": "jira", "id": "jira:3", "cat": "DONE", "resolved": "2026-10-12T00:00:00Z", "assignee": "jira:who"},
              {"src": "jira", "id": "jira:4", "cat": "IN_PROGRESS", "resolved": None, "assignee": "jira:acc-1"},
              {"src": "jira", "id": "jira:5", "cat": "DONE", "resolved": "2026-01-01T00:00:00Z", "assignee": "jira:acc-1"}]
    got = identity.issues_by_team(issues, IDENT, since="2026-09-21T00:00:00Z")
    assert got == {"teams": {"web": {"done": 2}}, "matched": 2, "unmatched": 1}


def test_slack_counts_a_reply_from_an_aliased_member_as_the_team(tmp_path):
    cfg = parse('[connectors.slack]\nchannels = ["C1"]\n[identity.aliases]\n"slack:U9" = "bo"\n'
                '[identity.teams]\nweb = ["bo"]\n')[0]
    calls = []

    def handler(request):
        calls.append(request)
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "conversations.history":
            return httpx.Response(200, json={"ok": True, "messages": [{"ts": "1792000000.000100", "user": "U1", "reply_count": 1,
                                                                        "thread_ts": "1792000000.000100"}]})
        return httpx.Response(200, json={"ok": True, "messages": [{"ts": "1792000000.000100", "user": "U1"},
                                                                  {"ts": "1792000100.000100", "user": "U9"}]})
    store = ConnectorStore(tmp_path, "slack")
    slack.pull(store, {"STACKVITALS_SLACK_TOKEN": "xoxb-1"}, cfg, NOW, client=httpx.Client(transport=httpx.MockTransport(handler)),
               sleep=lambda s: None)
    topic = store.load()["topic"][0]
    assert topic["first_team_reply"] is not None


def test_delivery_shows_tracker_issues_done_per_team_only_when_assignees_are_kept():
    from stackvitals.core import delivery
    issue = {"src": "jira", "id": "jira:1", "key": "WEB-1", "cat": "DONE", "type": "TASK", "created": "2026-10-01T00:00:00Z",
             "resolved": "2026-10-10T00:00:00Z", "assignee": "jira:acc-1"}
    tracker = {"sources": ["jira"], "issues": [issue], "changes": [], "sprints": []}
    got = delivery._tracker(tracker, [], NOW, 30, IDENT)
    assert got["by_team"] == {"teams": {"web": {"done": 1}}, "matched": 1, "unmatched": 0, "by_email": 0, "suggested": []}
    plain = {**tracker, "issues": [{k: v for k, v in issue.items() if k != "assignee"}]}
    assert delivery._tracker(plain, [], NOW, 30, IDENT)["by_team"] is None
