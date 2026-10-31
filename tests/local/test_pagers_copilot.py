"""PagerDuty and incident.io incidents (DORA prefers them when connected, and names the source), and GitHub's Copilot
usage reports kept day by day before they expire. Shapes follow the official docs."""
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from stackvitals.connectors import copilot, incident_io, pagerduty
from stackvitals.connectors.store import ConnectorStore
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def pd_incident(n, status="resolved", created="2026-10-06T21:30:42Z", resolved="2026-10-06T23:30:42Z", urgency="high"):
    return {"id": f"P{n}", "type": "incident", "incident_number": n, "title": "The server is on fire.", "status": status,
            "urgency": urgency, "created_at": created, "updated_at": resolved or created, "resolved_at": resolved,
            "last_status_change_at": resolved or created, "html_url": f"https://acme.pagerduty.com/incidents/P{n}",
            "service": {"id": "PIJ90N7", "type": "service_reference", "summary": "Checkout"}}


def pd_client(pages, status=200, seen=None):
    def handle(request):
        (seen if seen is not None else []).append(request)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "Authentication failed", "code": 2006}})
        q = parse_qs(request.url.query.decode())
        # Like PagerDuty: only incidents that began inside since..until.
        inside = [[i for i in page if q["since"][0] <= i["created_at"] < q["until"][0]] for page in pages]
        inside = [page for page in inside if page] or [[]]
        k = int(q.get("offset", ["0"])[0]) // 100
        return httpx.Response(200, json={"incidents": inside[k], "limit": 100, "offset": k * 100, "more": k + 1 < len(inside)})
    return httpx.Client(transport=httpx.MockTransport(handle))


def test_pagerduty_incidents_are_read_with_the_documented_headers_and_filters(tmp_path):
    seen = []
    cfg = parse('[connectors.pagerduty]\nservices = ["PIJ90N7"]\n')[0]
    store = ConnectorStore(tmp_path, "pagerduty")
    out = pagerduty.pull(store, {"STACKVITALS_PAGERDUTY_TOKEN": "pd-key"}, cfg, NOW,
                         client=pd_client([[pd_incident(1)], [pd_incident(2, status="acknowledged", resolved=None)]], seen=seen))
    assert out["read"] == 2
    got = {i["key"]: i for i in store.load()["issue"]}
    assert got["PD-1"]["incident"] and got["PD-1"]["cat"] == "DONE" and got["PD-1"]["resolved"] == "2026-10-06T23:30:42Z"
    assert got["PD-2"]["cat"] == "IN_PROGRESS" and got["PD-2"]["resolved"] is None and got["PD-1"]["url"].endswith("/incidents/P1")
    r = seen[0]
    assert r.headers["authorization"] == "Token token=pd-key" and r.headers["accept"] == "application/vnd.pagerduty+json;version=2"
    q = parse_qs(r.url.query.decode())
    assert q["service_ids[]"] == ["PIJ90N7"] and q["urgencies[]"] == ["high"] and q["time_zone"] == ["UTC"]
    assert q["since"][0] < q["until"][0]


def test_a_refused_pagerduty_key_is_said_plainly(tmp_path):
    with pytest.raises(pagerduty.ConnectorError) as err:
        pagerduty.pull(ConnectorStore(tmp_path, "pagerduty"), {"STACKVITALS_PAGERDUTY_TOKEN": "pd-key"}, parse("")[0], NOW,
                       client=pd_client([], status=401))
    assert "401" in str(err.value) and "pd-key" not in str(err.value)


def io_incident(ref, category="closed", resolved="2026-10-07T03:00:00Z"):
    stamps = [{"incident_timestamp": {"id": "a", "name": "Impact started", "rank": 1}, "value": {"value": "2026-10-07T00:30:00Z"}}]
    if resolved:
        stamps.append({"incident_timestamp": {"id": "b", "name": "Resolved at", "rank": 3}, "value": {"value": resolved}})
    return {"id": f"01F{ref}", "reference": ref, "name": "Our database is sad", "permalink": f"https://app.incident.io/incidents/{ref}",
            "mode": "standard", "incident_status": {"category": category, "name": category.title()}, "severity": {"name": "Minor"},
            "created_at": "2026-10-07T01:00:00.000000Z", "updated_at": "2026-10-07T03:00:00.000000Z",
            "incident_timestamp_values": stamps}


def test_incident_io_incidents_use_the_resolved_at_timestamp_and_skip_declined_ones(tmp_path):
    seen = []

    def handle(request):
        seen.append(request)
        after = parse_qs(request.url.query.decode()).get("after")
        if not after:
            return httpx.Response(200, json={"incidents": [io_incident("INC-1"), io_incident("INC-2", "declined")],
                                             "pagination_meta": {"after": "cursor1", "page_size": 250}})
        return httpx.Response(200, json={"incidents": [io_incident("INC-3", "live", None)], "pagination_meta": {"page_size": 250}})
    store = ConnectorStore(tmp_path, "incident_io")
    out = incident_io.pull(store, {"STACKVITALS_INCIDENT_IO_TOKEN": "io-key"}, parse("")[0], NOW,
                           client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert out["read"] == 3
    got = {i["key"]: i for i in store.load()["issue"]}
    assert {k for k, i in got.items() if i["incident"]} == {"INC-1", "INC-3"} and got["INC-2"]["canceled"]
    assert got["INC-1"]["resolved"] == "2026-10-07T03:00:00Z"
    assert got["INC-3"]["cat"] == "IN_PROGRESS" and got["INC-1"]["url"] == "https://app.incident.io/incidents/INC-1"
    q = parse_qs(seen[0].url.query.decode())
    assert seen[0].headers["authorization"] == "Bearer io-key" and q["page_size"] == ["250"] and "updated_at[gte]" in q
    assert parse_qs(seen[1].url.query.decode())["after"] == ["cursor1"]


def test_a_connected_pager_tool_is_the_incident_source_for_dora():
    from stackvitals.core.delivery import incidents_for
    pager = {"t": "issue", "src": "pagerduty", "id": "pagerduty:P1", "key": "PD-1", "title": "fire", "type": "INCIDENT", "status": "resolved",
             "cat": "DONE", "created": "2026-10-06T21:30:42Z", "updated": "x", "resolved": "2026-10-06T23:30:42Z", "points": None,
             "labels": [], "sprints": [], "incident": True, "canceled": False, "url": "https://acme.pagerduty.com/incidents/P1"}
    revert = {"n": 9, "ti": 'Revert "x"', "mg": "2026-10-05T00:00:00Z", "cr": "2026-10-04T00:00:00Z", "lb": []}
    found, source = incidents_for([revert], [], [], parse("")[0], {"sources": ["pagerduty"], "issues": [pager], "changes": [], "sprints": []})
    assert [i["number"] for i in found] == ["PD-1"] and source == "PagerDuty"
    found, source = incidents_for([revert], [], [], parse("")[0], None)
    assert [i["number"] for i in found] == [9] and source == "GitHub issues, reverts and hotfixes"


ORG_DAY = {"day": "2026-10-19", "organization_id": "1", "daily_active_users": 40, "weekly_active_users": 55, "monthly_active_users": 61,
           "monthly_active_agent_users": 12, "code_generation_activity_count": 900, "code_acceptance_activity_count": 270,
           "loc_added_sum": 5000, "pull_requests": {"total_created": 80, "total_merged": 70, "total_created_by_copilot": 9,
                                                     "total_merged_created_by_copilot": 6, "median_minutes_to_merge_copilot_authored": 180}}
REPO_DAY = {"day": "2026-10-19", "repo_name": "r", "repo_owner_name": "o", "pull_requests": {"total_created_by_copilot": 2,
            "total_merged_created_by_copilot": 1, "median_minutes_to_merge_copilot_authored": 95}}


def test_copilot_reports_are_kept_day_by_day_for_the_org_and_this_repo(tmp_path):
    seen = []

    def handle(request):
        seen.append(request)
        path = request.url.path
        if path.endswith("/organization-1-day"):
            day = parse_qs(request.url.query.decode())["day"][0]
            if day != "2026-10-19":
                return httpx.Response(204)
            return httpx.Response(200, json={"download_links": ["https://files.example.com/org.ndjson?sig=1"], "report_day": day})
        if path.endswith("/repos-1-day"):
            return httpx.Response(200, json={"download_links": ["https://files.example.com/repos.ndjson?sig=2"], "report_day": "2026-10-19"})
        if path == "/org.ndjson":
            assert "authorization" not in request.headers  # a signed link: the key never goes to the file host
            return httpx.Response(200, text=json.dumps(ORG_DAY) + "\n")
        if path == "/repos.ndjson":
            return httpx.Response(200, text=json.dumps(REPO_DAY) + "\n" + json.dumps({**REPO_DAY, "repo_name": "other"}) + "\n")
        return httpx.Response(404)
    store = ConnectorStore(tmp_path, "copilot")
    env = {"STACKVITALS_COPILOT_TOKEN": "gh-key", "GITHUB_REPOSITORY": "o/r"}
    out = copilot.pull(store, env, parse("")[0], NOW, client=httpx.Client(transport=httpx.MockTransport(handle)), days=3)
    assert out["read"] == 1
    got = store.load()
    org = got["org_day"][0]
    assert org["day"] == "2026-10-19" and org["monthly_active_users"] == 61 and org["acceptance"] == 0.3
    assert got["repo_day"][0]["pull_requests"]["total_created_by_copilot"] == 2 and len(got["repo_day"]) == 1
    api = [r for r in seen if r.url.host == "api.github.com"][0]
    assert api.headers["authorization"] == "Bearer gh-key" and api.headers["x-github-api-version"] == "2026-03-10"
    assert api.url.path == "/orgs/o/copilot/metrics/reports/organization-1-day"
    # Two days after the newest report is the most GitHub has; the next run starts after the last day kept.
    assert store.state()["through"] == "2026-10-19"


def test_the_copilot_summary_adds_up_the_last_28_days_and_says_how_much_history_is_kept(tmp_path):
    from stackvitals.connectors import copilot_summary
    store = ConnectorStore(tmp_path, "copilot")
    day = lambda d, gen, acc, made: {"t": "org_day", "id": f"copilot:org:{d}", "day": d, "org": "o", "monthly_active_users": 60,  # noqa: E731
                                     "monthly_active_agent_users": 9, "code_generation_activity_count": gen,
                                     "code_acceptance_activity_count": acc, "pull_requests": {"total_created_by_copilot": made,
                                                                                              "total_merged_created_by_copilot": made - 1}}
    store.add([day("2026-08-01", 100, 90, 5), day("2026-10-10", 100, 20, 3), day("2026-10-19", 300, 100, 4),
               {"t": "repo_day", "id": "copilot:repo:2026-10-19", "day": "2026-10-19",
                "pull_requests": {"total_created_by_copilot": 2, "total_merged_created_by_copilot": 1}}], "2026-10-21")
    s = copilot_summary(tmp_path, NOW)
    assert s["days_kept"] == 3 and s["first_day"] == "2026-08-01" and s["acceptance"] == 0.3
    assert (s["org_prs_by_copilot"], s["org_prs_merged_by_copilot"], s["repo_prs_by_copilot"]) == (7, 5, 2)
    assert copilot_summary(tmp_path / "none", NOW) is None
