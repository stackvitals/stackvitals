import json

import httpx

from stackvitals.connectors.base import ConnectorError
from stackvitals.connectors.writeback import due, jira_comment, jira_move, linear_comment, linear_move, send
from stackvitals.core.config import parse

PRS = [{"n": 5, "mg": "2026-10-20T10:00:00Z", "ti": "WEB-1: fix login", "head": "x", "au": "ann", "at": "User"},
       {"n": 6, "mg": None, "ti": "WEB-2: draft", "head": "y", "au": "ann", "at": "User"},
       {"n": 7, "mg": "2026-10-21T10:00:00Z", "ti": "no key", "head": "feature/eng-4-billing", "au": "bo", "at": "User"},
       {"n": 8, "mg": "2026-10-22T10:00:00Z", "ti": 'Revert "WEB-1: fix login"', "head": "revert-5-x", "au": "bo", "at": "User"}]
ISSUES = [{"key": "WEB-1", "id": "jira:100"}, {"key": "WEB-2", "id": "jira:101"}, {"key": "ENG-4", "id": "linear:abc"}]


def test_write_back_is_off_by_default_and_settings_are_checked():
    cfg, notes = parse("")
    assert cfg["connectors"]["jira"]["write_back"] is False and cfg["connectors"]["linear"]["write_back"] is False
    cfg, notes = parse('[connectors.jira]\nwrite_back = true\ndone_transition = "Done"\n[connectors.linear]\nwrite_back = "yes"\n')
    assert cfg["connectors"]["jira"]["write_back"] is True and cfg["connectors"]["jira"]["done_transition"] == "Done"
    assert cfg["connectors"]["linear"]["write_back"] is False and len(notes) == 1


def test_only_merged_prs_naming_an_issue_are_due_each_once_and_reverts_never():
    got = due(PRS, ISSUES, set())
    assert [(p["n"], i["key"]) for p, i in got] == [(5, "WEB-1"), (7, "ENG-4")]
    assert due(PRS, ISSUES, {"5|WEB-1"}) == [(PRS[2], ISSUES[2])]


def test_a_refused_move_is_said_and_neither_repeats_the_comment_nor_blocks_the_next():
    # Review finding: a key that may comment but not transition re-posted the comment every run and held the queue.
    said = []

    def move(issue):
        if issue["key"] == "WEB-1":
            raise ConnectorError("Moving WEB-1 to Done was refused (403)")
        return True
    got = send([(PRS[0], ISSUES[0]), (PRS[2], ISSUES[2])], "o/r", lambda i, text: said.append(i["key"]), move)
    assert said == ["WEB-1", "ENG-4"] and got["wrote"] == 2 and got["moved"] == 1 and "WEB-1" in got["unmoved"][0]

    def refuse(issue, text):
        raise ConnectorError("A comment on WEB-1 was refused (403)")
    got = send([(PRS[0], ISSUES[0]), (PRS[2], ISSUES[2])], "o/r", refuse, move)
    assert got["wrote"] == 0 and "refused" in got["refused"]


def test_jira_gets_a_comment_and_the_named_transition():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        if request.url.path.endswith("/transitions") and request.method == "GET":
            return httpx.Response(200, json={"transitions": [{"id": "31", "name": "Done"}, {"id": "21", "name": "In Progress"}]})
        return httpx.Response(204 if "transitions" in request.url.path else 201, json={})
    client = httpx.Client(base_url="https://x.atlassian.net", transport=httpx.MockTransport(handler))
    jira_comment(client, "Basic k", "WEB-1", "Merged: o/r#5")
    assert jira_move(client, "Basic k", "WEB-1", "done") is True
    assert seen[0][:2] == ("POST", "/rest/api/3/issue/WEB-1/comment") and "o/r#5" in json.dumps(seen[0][2])
    assert seen[-1] == ("POST", "/rest/api/3/issue/WEB-1/transitions", {"transition": {"id": "31"}})
    assert jira_move(client, "Basic k", "WEB-1", "") is False


def test_linear_gets_a_comment_and_the_team_state_by_name():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if "workflowStates" in body["query"]:
            return httpx.Response(200, json={"data": {"workflowStates": {"nodes": [{"id": "st-done"}]}}})
        return httpx.Response(200, json={"data": {"ok": {"success": True}}})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    linear_comment(client, "lin_key", "linear:abc", "Merged: o/r#7")
    assert linear_move(client, "lin_key", "linear:abc", "ENG-4", "Done") is True
    assert seen[0]["variables"]["input"] == {"issueId": "abc", "body": "Merged: o/r#7"}
    assert seen[1]["variables"] == {"name": "Done", "team": "ENG"}
    assert seen[2]["variables"] == {"id": "abc", "state": "st-done"}
