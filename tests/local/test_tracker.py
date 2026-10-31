"""Tracker data joined to the rest: issue keys link PRs, lead time by type, sprint scope and carry-over, tracker incidents in
DORA, DevLake's issue tables, and the Connectors step's status with its key-expiry warning."""
import json
from datetime import datetime, timezone

import httpx

from stackvitals.connectors import connectors_step, load, tracker
from stackvitals.connectors.store import ConnectorStore
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
S5 = {"t": "sprint", "src": "jira", "id": "jira:sprint:5", "name": "Sprint 5", "state": "CLOSED", "start": "2026-09-01T09:00:00Z",
      "end": "2026-09-14T17:00:00Z", "complete": "2026-09-14T18:00:00Z"}
S6 = {**S5, "id": "jira:sprint:6", "name": "Sprint 6", "state": "ACTIVE", "start": "2026-09-15T09:00:00Z", "end": "2026-09-28T17:00:00Z",
      "complete": None}


def issue(key, kind="REQUIREMENT", created="2026-09-01T08:00:00Z", resolved=None, sprints=(), points=None, canceled=False,
          incident=False, status=None):
    done = resolved is not None
    return {"t": "issue", "src": "jira", "id": f"jira:{key}", "key": key, "title": f"Thing {key}", "type": kind,
            "original_type": "Story", "status": status or ("Done" if done else "To Do"),
            "cat": "DONE" if done else "IN_PROGRESS" if status == "In Progress" else "TODO",
            "created": created, "updated": resolved or created, "resolved": resolved, "points": points, "priority": "Medium",
            "labels": [], "sprints": list(sprints), "incident": incident, "canceled": canceled,
            "url": f"https://acme.atlassian.net/browse/{key}"}


ISSUES = [issue("WEB-1", resolved="2026-09-05T08:00:00Z", sprints=[S5["id"]], points=3),
          issue("WEB-2", "BUG", created="2026-09-02T08:00:00Z", resolved="2026-09-03T08:00:00Z"),
          issue("WEB-3", sprints=[S5["id"], S6["id"]], points=5, status="In Progress"),
          issue("WEB-4", resolved="2026-09-04T08:00:00Z", canceled=True),
          issue("WEB-77", "INCIDENT", created="2026-10-02T10:00:00Z", resolved="2026-10-02T14:00:00Z", incident=True)]
CHANGES = [{"t": "change", "src": "jira", "id": "c1", "issue": "jira:WEB-3", "field": "sprint", "from": [], "to": [S5["id"]],
            "at": "2026-09-05T10:00:00Z"},
           {"t": "change", "src": "jira", "id": "c2", "issue": "jira:WEB-1", "field": "status", "from": "To Do",
            "to": "In Progress", "at": "2026-09-03T08:00:00Z"}]
TRACKER = {"sources": ["jira"], "issues": ISSUES, "changes": CHANGES, "sprints": [S5, S6]}


def test_issue_keys_in_pr_titles_and_branches_link_prs_to_known_issues():
    prs = [{"n": 1, "ti": "WEB-1: add cache", "head": "x"}, {"n": 2, "ti": "Fix login", "head": "feature/web-2-login"},
           {"n": 3, "ti": "Support UTF-8 and ABC-999", "head": "y"}]
    assert tracker.pr_links(prs, ISSUES) == [(1, "WEB-1"), (2, "WEB-2")]


def test_lead_and_cycle_time_count_finished_issues_by_type_and_leave_canceled_ones_out():
    out = tracker.lead_times(ISSUES, CHANGES, datetime(2026, 8, 1, tzinfo=timezone.utc), NOW, min_n=1)
    assert out["REQUIREMENT"]["n"] == 1 and out["REQUIREMENT"]["lead_p50_h"] == 96.0
    # In progress (the first move to an in-progress status) to done.
    assert out["REQUIREMENT"]["cycle_p50_h"] == 48.0 and out["BUG"]["n"] == 1 and out["BUG"]["cycle_n"] == 0


def test_planning_shows_scope_done_carry_over_and_late_additions():
    rows = tracker.planning(ISSUES, CHANGES, [S5, S6], NOW)
    s5 = next(r for r in rows if r["name"] == "Sprint 5")
    assert (s5["scope"], s5["done"], s5["carried_over"], s5["added_after_start"]) == (2, 1, 1, 1)
    assert (s5["points_scope"], s5["points_done"]) == (8, 3)
    s6 = next(r for r in rows if r["name"] == "Sprint 6")
    assert s6["state"] == "ACTIVE" and s6["carried_over"] == 0


def test_tracker_incidents_join_dora_with_their_own_links():
    from stackvitals.core.delivery import find_incidents
    found = find_incidents([], [], [{"id": "d1", "finished": "2026-10-01T10:00:00Z"}], parse("")[0], extra=tracker.incidents(ISSUES))
    assert found == [{"source": "jira", "number": "WEB-77", "created": "2026-10-02T10:00:00Z", "resolved": "2026-10-02T14:00:00Z",
                      "url": "https://acme.atlassian.net/browse/WEB-77", "fix_chain_deployment": None, "never_shipped": False,
                      "deployment": "d1",
                      "deployment_finished": "2026-10-01T10:00:00Z", "hours_to_restore": 28.0}]


def test_delivery_and_devlakes_tables_carry_the_tracker():
    from stackvitals.core.delivery import build
    from stackvitals.core.export import devlake_tables
    flow = {"closed": [{"n": 1, "ti": "WEB-1: add cache", "head": "x", "st": "MERGED", "cr": "2026-09-02T08:00:00Z",
                        "mg": "2026-09-04T08:00:00Z", "cl": "2026-09-04T08:00:00Z", "au": "amy", "at": "User", "base": "main",
                        "ev": [], "cm": [], "lb": [], "ai": [], "add": 5, "del": 1}], "open": []}
    out = build(flow, {"default_branch": "main"}, {"runs": [], "jobs": []}, [], NOW, 90, parse("")[0], tracker=TRACKER)
    assert out["tracker"]["sources"] == ["jira"] and out["tracker"]["linked_prs"] == 1
    assert out["tracker"]["planning"][0]["name"] == "Sprint 5" and out["tracker"]["lead_time"]["BUG"]["n"] == 1
    assert any(i["number"] == "WEB-77" for i in out["incidents"])
    tables = devlake_tables("o/r", flow, {"default_branch": "main"}, {"runs": [], "jobs": []}, [], parse("")[0], tracker=TRACKER)
    keys = {r["issue_key"] for r in tables["issues"]}
    assert {"WEB-1", "WEB-77"} <= keys and {r["name"] for r in tables["sprints"]} == {"Sprint 5", "Sprint 6"}
    assert {(r["pull_request_key"], r["issue_key"]) for r in tables["pull_request_issues"]} == {(1, "WEB-1")}
    assert any(r["field_name"] == "status" and r["original_to_value"] == "In Progress" for r in tables["issue_changelogs"])
    assert any(r["incident_key"] == "WEB-77" and r["url"].endswith("/browse/WEB-77") for r in tables["incidents"])
    assert len([r for r in tables["sprint_issues"] if r["sprint_id"].endswith("sprint:5")]) == 2


class Ws:
    def __init__(self, path, settings):
        self.path, self.cache, self.notes = path, {"settings": settings}, []


def jira_fake(status=200):
    def handle(request):
        if status != 200:
            return httpx.Response(status, json={"errorMessages": ["no"]})
        if request.url.path == "/rest/api/3/field":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"isLast": True, "issues": [
            {"id": "1", "key": "WEB-1", "fields": {"summary": "x", "issuetype": {"name": "Bug"}, "status": {"name": "Done",
             "statusCategory": {"key": "done"}}, "created": "2026-10-01T10:00:00.000+0000", "updated": "2026-10-02T10:00:00.000+0000",
             "resolutiondate": "2026-10-02T10:00:00.000+0000"}}]})
    return httpx.Client(transport=httpx.MockTransport(handle), base_url="https://acme.atlassian.net")


def test_the_step_pulls_writes_a_status_and_warns_before_the_key_expires(tmp_path):
    cfg = parse('[connectors.jira]\nurl = "https://acme.atlassian.net"\nkey_expires = "2026-10-30"\n')[0]
    env = {"STACKVITALS_JIRA_TOKEN": "t", "STACKVITALS_JIRA_EMAIL": "me@acme.com"}
    ws = Ws(tmp_path, cfg)
    out = connectors_step(ws, env, NOW, clients={"jira": jira_fake()})
    assert out["jira"]["read"] == 1 and out["jira"]["error"] is None
    status = json.loads((tmp_path / "docs" / "connectors.json").read_text(encoding="utf-8"))["connectors"]["jira"]
    assert status["rows"]["issue"] == 1 and status["expiring"] and status["key_expires"] == "2026-10-30"
    assert any("expires" in n for n in ws.notes) and load(tmp_path)["issues"][0]["key"] == "WEB-1"
    # A refused key later: said on the page, the history kept.
    connectors_step(ws, env, NOW, clients={"jira": jira_fake(401)})
    status = json.loads((tmp_path / "docs" / "connectors.json").read_text(encoding="utf-8"))["connectors"]["jira"]
    assert "refused" in status["error"] and status["rows"]["issue"] == 1


def test_no_key_means_no_step_work_and_no_files(tmp_path):
    assert connectors_step(Ws(tmp_path, parse("")[0]), {}, NOW) is None
    assert not (tmp_path / "docs" / "connectors.json").exists() and load(tmp_path) is None


def test_a_scheduled_run_with_a_key_pulls_after_team_flow_and_before_delivery(monkeypatch, tmp_path):
    import subprocess

    import stackvitals.ci.cli as cli
    import stackvitals.connectors as conn
    import stackvitals.core.alerts as alerts
    import stackvitals.core.delivery_report as dr
    import stackvitals.core.digest as digest
    import stackvitals.core.insights as insights
    import stackvitals.core.requests as requests_mod
    order = []
    monkeypatch.setattr(requests_mod, "requests_step", lambda ws, env, now, **kw: order.append("Requests") or {})
    monkeypatch.setattr(cli, "run_flow_action", lambda env, **kw: order.append("Team Flow") or None)
    monkeypatch.setattr(conn, "connectors_step", lambda ws, env, now: order.append("Connectors") or {"jira": {"read": 2, "complete": True, "error": None}})
    monkeypatch.setattr(dr, "delivery_step", lambda ws, env, now, **kw: order.append("Delivery") or None)
    monkeypatch.setattr(insights, "insights_step", lambda ws, env, now: order.append("Insights") or None)
    monkeypatch.setattr(alerts, "alerts_step", lambda ws, env, now: order.append("Alerts") or None)
    monkeypatch.setattr(digest, "digest_step", lambda ws, env, now: order.append("Digest") or None)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    for key, value in (("GITHUB_EVENT_NAME", "schedule"), ("GITHUB_REPOSITORY", "o/r"), ("STACKVITALS_TOKEN", "tok"),
                       ("STACKVITALS_REMOTE", bare.as_uri()), ("RUNNER_TEMP", str(tmp_path / "tmp")),
                       ("STACKVITALS_JIRA_TOKEN", "jira-key")):
        monkeypatch.setenv(key, value)
    assert cli.action_main(["--modules", "flow"]) == 0
    assert order[:4] == ["Requests", "Team Flow", "Connectors", "Delivery"]
    monkeypatch.delenv("STACKVITALS_JIRA_TOKEN")
    order.clear()
    # Since Phase 17 the step is always there on scheduled runs (a Discourse forum needs no key) and does nothing
    # without a configured connector.
    assert cli.action_main(["--modules", "flow"]) == 0 and "Connectors" in order


def test_the_delivery_page_shows_issue_times_sprints_and_links_tracker_incidents():
    from stackvitals.core import delivery_report
    from stackvitals.core.delivery import build
    flow = {"closed": [], "open": []}
    out = build(flow, {"default_branch": "main"}, {"runs": [], "jobs": []}, [], NOW, 90, parse("")[0], tracker=TRACKER)
    page = delivery_report.render_html(out, "o/r")
    assert "Issues from Jira" in page and "Sprint 5" in page and "carried over" in page.lower()
    assert "https://acme.atlassian.net/browse/WEB-77" in page and ">WEB-77<" in page


def test_sprints_older_than_what_was_read_are_left_out_since_their_scope_would_be_partial():
    # Real-data finding (Hibernate's Jira): issues read for 180 days still name 2024 sprints, which then looked nearly empty.
    old = {**S5, "id": "jira:sprint:1", "name": "Sprint 1", "start": "2024-10-01T09:00:00Z", "complete": "2024-10-14T18:00:00Z"}
    issues = ISSUES + [issue("WEB-9", sprints=[old["id"]])]
    rows = tracker.planning(issues, CHANGES, [old, S5, S6], NOW, since=datetime(2026, 4, 24, tzinfo=timezone.utc))
    assert [r["name"] for r in rows] == ["Sprint 5", "Sprint 6"]
