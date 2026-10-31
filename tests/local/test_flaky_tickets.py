"""A Jira or Linear ticket per flaky test (Trunk's auto-tickets): opened once, commented and moved to done when fixed."""
import json

import httpx

from stackvitals.ci import tickets
from stackvitals.core.config import parse

FLAKY = {"tests": [{"id": "t::racy", "state": "flaky", "flake_events": 4, "message": "timeout", "evidence": [{"run": 9}]}]}
FIXED = {"tests": [{"id": "t::racy", "state": "fixed"}]}


def test_jira_ticket_opened_once_then_closed_when_fixed(tmp_path):
    calls = []

    def handle(req):
        calls.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        if req.url.path == "/rest/api/3/issue":
            return httpx.Response(201, json={"id": "100", "key": "WEB-7"})
        if req.url.path.endswith("/issuetypes"):
            return httpx.Response(200, json={"issueTypes": [{"name": "Task"}, {"name": "Story"}]})
        if req.url.path.endswith("/transitions") and req.method == "GET":
            return httpx.Response(200, json={"transitions": [{"id": "31", "name": "Done"}]})
        return httpx.Response(204)
    cfg = parse('[connectors.jira]\nurl = "https://acme.atlassian.net"\nemail = "a@acme.dev"\nflaky_tickets = true\n'
                'ticket_project = "WEB"\n')[0]
    env = {"STACKVITALS_JIRA_TOKEN": "t"}
    client = lambda: httpx.Client(base_url="https://acme.atlassian.net", transport=httpx.MockTransport(handle))  # noqa: E731
    assert tickets.sync(tmp_path, FLAKY, cfg, env, client())["opened"] == ["WEB-7"]
    assert tickets.sync(tmp_path, FLAKY, cfg, env, client())["opened"] == []
    made = next(c[2] for c in calls if c[1] == "/rest/api/3/issue")
    assert made["fields"]["project"] == {"key": "WEB"} and made["fields"]["summary"] == "Flaky test: t::racy"
    assert made["fields"]["issuetype"] == {"name": "Task"}
    got = tickets.sync(tmp_path, FIXED, cfg, env, client())
    assert got["closed"] == ["WEB-7"] and ("POST", "/rest/api/3/issue/WEB-7/transitions", {"transition": {"id": "31"}}) in calls
    assert tickets.sync(tmp_path, FIXED, cfg, env, client())["closed"] == []


def test_linear_ticket_goes_to_the_named_team(tmp_path):
    seen = []

    def handle(req):
        body = json.loads(req.content)
        seen.append(body)
        if "teams(" in body["query"]:
            return httpx.Response(200, json={"data": {"teams": {"nodes": [{"id": "team-1"}]}}})
        return httpx.Response(200, json={"data": {"issueCreate": {"issue": {"id": "abc", "identifier": "ENG-3"}}}})
    cfg = parse('[connectors.linear]\nflaky_tickets = true\nticket_team = "ENG"\n')[0]
    got = tickets.sync(tmp_path, FLAKY, cfg, {"STACKVITALS_LINEAR_TOKEN": "k"},
                       httpx.Client(base_url="https://api.linear.app", transport=httpx.MockTransport(handle)))
    assert got["opened"] == ["ENG-3"] and seen[1]["variables"]["input"]["teamId"] == "team-1"


def test_off_by_default_and_says_what_is_missing(tmp_path):
    assert tickets.sync(tmp_path, FLAKY, parse("")[0], {}) == {"tickets": None}
    got = tickets.sync(tmp_path, FLAKY, parse('[connectors.linear]\nflaky_tickets = true\n')[0], {"STACKVITALS_LINEAR_TOKEN": "k"})
    assert "ticket_team" in got["problem"]
    assert parse('[connectors.jira]\nticket_project = "not a key"\n')[0]["connectors"]["jira"]["ticket_project"] == ""
