"""Connectors: Jira Cloud and Linear pulled into the data branch with one read-only key each, resumable, then joined to pull
requests, deployments and sprints. API shapes follow the official docs (Jira REST v3 enhanced search, Linear GraphQL)."""
import base64
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs

import httpx
import pytest

from stackvitals.connectors import jira, linear
from stackvitals.connectors.store import ConnectorStore
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
JIRA_ENV = {"STACKVITALS_JIRA_TOKEN": "tok-secret", "STACKVITALS_JIRA_EMAIL": "me@acme.com"}
LINEAR_ENV = {"STACKVITALS_LINEAR_TOKEN": "lin_api_secret"}
FIELDS = [{"id": "customfield_10020", "name": "Sprint", "schema": {"custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
          {"id": "customfield_10016", "name": "Story point estimate",
           "schema": {"type": "number", "custom": "com.pyxis.greenhopper.jira:jsw-story-points"}},
          {"id": "summary", "name": "Summary", "schema": {"type": "string"}}]
SPRINT = {"id": 5, "name": "Sprint 5", "state": "closed", "boardId": 1, "startDate": "2026-09-01T09:00:00.000Z",
          "endDate": "2026-09-14T17:00:00.000Z", "completeDate": "2026-09-14T18:00:00.000Z"}


def jira_issue(n, updated, status=("Done", "done"), kind="Story", resolved="2026-09-05T10:00:00.000+0200", sprints=(SPRINT,),
               points=3.0, history=()):
    return {"id": str(10000 + n), "key": f"WEB-{n}", "self": f"https://acme.atlassian.net/rest/api/3/issue/{10000 + n}",
            "fields": {"summary": f"Thing {n}", "issuetype": {"name": kind},
                       "status": {"name": status[0], "statusCategory": {"key": status[1]}},
                       "created": "2026-09-01T10:00:00.000+0200", "updated": updated, "resolutiondate": resolved,
                       "priority": {"name": "Medium"}, "labels": ["api"], "customfield_10020": list(sprints),
                       "customfield_10016": points},
            "changelog": {"histories": [{"id": str(500 + n), "created": "2026-09-02T09:00:00.000+0200",
                                         "items": [{"field": "status", "fromString": "To Do", "toString": "In Progress"}]},
                                        *history]}}


def jira_cfg(**over):
    text = "[connectors.jira]\nurl = \"https://acme.atlassian.net\"\nscope_jql = \"project = WEB\"\n" + "".join(
        f"{k} = {json.dumps(v)}\n" for k, v in over.items())
    cfg, notes = parse(text)
    assert notes == []
    return cfg


class FakeJira:
    def __init__(self, pages, incidents=(), status=200):
        self.pages, self.incidents, self.status, self.calls = list(pages), list(incidents), status, []

    def handle(self, request):
        self.calls.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"errorMessages": ["Client must be authenticated to access this resource."]})
        if request.url.path == "/rest/api/3/field":
            return httpx.Response(200, json=FIELDS)
        assert request.url.path == "/rest/api/3/search/jql"
        q = parse_qs(request.url.query.decode())
        if "Incident" in q["jql"][0]:
            return httpx.Response(200, json={"issues": self.incidents, "isLast": True})
        token = q.get("nextPageToken", ["0"])[0]
        page = self.pages[int(token)]
        last = int(token) + 1 >= len(self.pages)
        return httpx.Response(200, json={"issues": page, "isLast": last, **({} if last else {"nextPageToken": str(int(token) + 1)})})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handle), base_url="https://acme.atlassian.net")


def test_jira_issues_status_changes_and_sprints_land_in_the_store(tmp_path):
    fake = FakeJira([[jira_issue(1, "2026-09-05T10:00:00.000+0200")], [jira_issue(2, "2026-09-06T10:00:00.000+0200")]])
    store = ConnectorStore(tmp_path, "jira")
    out = jira.pull(store, JIRA_ENV, jira_cfg(), NOW, client=fake.client())
    assert out["read"] == 2 and out["complete"]
    got = store.load()
    issue = {i["key"]: i for i in got["issue"]}["WEB-1"]
    assert issue["cat"] == "DONE" and issue["type"] == "REQUIREMENT" and issue["original_type"] == "Story"
    assert issue["created"] == "2026-09-01T08:00:00Z" and issue["resolved"] == "2026-09-05T08:00:00Z"
    assert issue["points"] == 3.0 and issue["sprints"] == ["jira:sprint:5"] and issue["url"] == "https://acme.atlassian.net/browse/WEB-1"
    assert {(c["field"], c["from"], c["to"]) for c in got["change"]} == {("status", "To Do", "In Progress")}
    assert got["sprint"][0] == {"t": "sprint", "src": "jira", "id": "jira:sprint:5", "name": "Sprint 5", "state": "CLOSED",
                                "start": "2026-09-01T09:00:00Z", "end": "2026-09-14T17:00:00Z", "complete": "2026-09-14T18:00:00Z"}
    search = [r for r in fake.calls if r.url.path.endswith("/search/jql")][0]
    q = parse_qs(search.url.query.decode())
    assert q["jql"][0].startswith("(project = WEB) AND updated >= ") and q["jql"][0].endswith("ORDER BY updated ASC")
    assert "customfield_10020" in q["fields"][0] and "customfield_10016" in q["fields"][0] and q["expand"] == ["changelog"]
    auth = search.headers["authorization"]
    assert auth == "Basic " + base64.b64encode(b"me@acme.com:tok-secret").decode()


def test_jira_pulls_resume_from_the_last_update_and_stop_at_the_page_cap(tmp_path):
    pages = [[jira_issue(k, f"2026-09-{10 + k:02d}T10:00:00.000+0000")] for k in range(5)]
    store = ConnectorStore(tmp_path, "jira")
    out = jira.pull(store, JIRA_ENV, jira_cfg(), NOW, client=FakeJira(pages).client(), pages=2)
    assert out["read"] == 2 and not out["complete"]
    assert store.state()["since"] == "2026-09-11T10:00:00Z"
    fake = FakeJira([[jira_issue(9, "2026-10-01T10:00:00.000+0000")]])
    jira.pull(store, JIRA_ENV, jira_cfg(), NOW, client=fake.client())
    jql = parse_qs([r for r in fake.calls if r.url.path.endswith("/search/jql")][0].url.query.decode())["jql"][0]
    # A capped pass carries on from the minute it reached, written in the account's own zone (+0000 here).
    assert 'updated >= "2026/09/11 10:00"' in jql


def test_jira_issues_found_by_the_incident_query_are_incidents(tmp_path):
    inc = jira_issue(77, "2026-10-02T10:00:00.000+0000", kind="Incident", resolved="2026-10-02T14:00:00.000+0000")
    store = ConnectorStore(tmp_path, "jira")
    jira.pull(store, JIRA_ENV, jira_cfg(incident_jql="issuetype = Incident"), NOW,
              client=FakeJira([[jira_issue(1, "2026-09-05T10:00:00.000+0200")]], incidents=[inc]).client())
    from stackvitals import connectors
    by_key = {i["key"]: i for i in connectors.load(tmp_path)["issues"]}
    assert by_key["WEB-77"]["incident"] and by_key["WEB-77"]["type"] == "INCIDENT" and not by_key["WEB-1"]["incident"]


def test_a_refused_jira_key_is_said_plainly_without_the_key_and_keeps_what_was_stored(tmp_path):
    store = ConnectorStore(tmp_path, "jira")
    jira.pull(store, JIRA_ENV, jira_cfg(), NOW, client=FakeJira([[jira_issue(1, "2026-09-05T10:00:00.000+0200")]]).client())
    with pytest.raises(jira.ConnectorError) as err:
        jira.pull(store, JIRA_ENV, jira_cfg(), NOW, client=FakeJira([], status=401).client())
    assert "401" in str(err.value) and "tok-secret" not in str(err.value) and "me@acme.com" not in str(err.value)
    assert len(store.load()["issue"]) == 1


def test_jira_settings_need_an_atlassian_site_and_say_what_is_missing():
    cfg, notes = parse('[connectors.jira]\nurl = "https://evil.example.com"\n')
    assert cfg["connectors"]["jira"]["url"] == "" and any("atlassian.net" in n for n in notes)
    assert not jira.configured({}, jira_cfg()) and jira.configured(JIRA_ENV, jira_cfg())
    with pytest.raises(jira.ConnectorError, match="url"):
        jira.pull(ConnectorStore("unused", "jira"), JIRA_ENV, parse("")[0], NOW, client=FakeJira([]).client())


LIN_CYCLE = {"id": "c1", "number": 7, "name": "Cycle 7", "startsAt": "2026-09-01T00:00:00.000Z", "endsAt": "2026-09-15T00:00:00.000Z",
             "completedAt": "2026-09-15T00:00:00.000Z", "team": {"key": "ENG"}}


def lin_issue(n, updated, state=("Done", "completed"), labels=(), cycle=LIN_CYCLE, history=()):
    return {"id": f"uuid-{n}", "identifier": f"ENG-{n}", "title": f"Thing {n}", "url": f"https://linear.app/acme/issue/ENG-{n}",
            "priority": 2, "estimate": 2, "createdAt": "2026-09-01T10:00:00.000Z", "updatedAt": updated,
            "startedAt": "2026-09-02T10:00:00.000Z", "completedAt": "2026-09-04T10:00:00.000Z" if state[1] == "completed" else None,
            "canceledAt": "2026-09-04T10:00:00.000Z" if state[1] == "canceled" else None,
            "state": {"name": state[0], "type": state[1]}, "team": {"key": "ENG"},
            "labels": {"nodes": [{"name": x} for x in labels]}, "cycle": cycle,
            "history": {"nodes": [{"createdAt": "2026-09-02T10:00:00.000Z", "fromState": {"name": "Todo", "type": "unstarted"},
                                   "toState": {"name": "In Progress", "type": "started"}, "fromCycleId": None, "toCycleId": None},
                                  *history]}}


class FakeLinear:
    def __init__(self, pages, status=200):
        self.pages, self.status, self.calls = list(pages), status, []

    def handle(self, request):
        body = json.loads(request.content)
        self.calls.append((request, body))
        if self.status != 200:
            return httpx.Response(self.status, json={"errors": [{"message": "Authentication required"}]})
        if "cycles(" in body["query"]:
            return httpx.Response(200, json={"data": {"cycles": {"nodes": [LIN_CYCLE], "pageInfo": {"hasNextPage": False, "endCursor": None}}}})
        k = int(body["variables"].get("after") or 0)
        more = k + 1 < len(self.pages)
        return httpx.Response(200, json={"data": {"issues": {"nodes": self.pages[k],
                                                             "pageInfo": {"hasNextPage": more, "endCursor": str(k + 1) if more else None}}}})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handle))


def linear_cfg(**over):
    text = "[connectors.linear]\nteams = [\"ENG\"]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in over.items())
    cfg, notes = parse(text)
    assert notes == []
    return cfg


def test_linear_issues_state_changes_and_cycles_land_in_the_store(tmp_path):
    fake = FakeLinear([[lin_issue(1, "2026-09-05T10:00:00.000Z", labels=("Bug",))],
                       [lin_issue(2, "2026-09-03T10:00:00.000Z", state=("Canceled", "canceled"), labels=("incident",))]])
    store = ConnectorStore(tmp_path, "linear")
    out = linear.pull(store, LINEAR_ENV, linear_cfg(), NOW, client=fake.client())
    assert out["read"] == 2 and out["complete"]
    got = {i["key"]: i for i in store.load()["issue"]}
    assert got["ENG-1"]["cat"] == "DONE" and got["ENG-1"]["type"] == "BUG" and got["ENG-1"]["resolved"] == "2026-09-04T10:00:00Z"
    assert got["ENG-2"]["canceled"] and got["ENG-2"]["incident"] and got["ENG-1"]["sprints"] == ["linear:cycle:c1"]
    assert {(c["field"], c["from"], c["to"]) for c in store.load()["change"]} == {("status", "Todo", "In Progress")}
    assert store.load()["sprint"][0]["name"] == "Cycle 7" and store.load()["sprint"][0]["state"] == "CLOSED"
    request, body = [c for c in fake.calls if "issues(" in c[1]["query"]][0]
    assert request.headers["authorization"] == "lin_api_secret" and body["variables"]["filter"]["team"] == {"key": {"in": ["ENG"]}}
    assert request.url == "https://api.linear.app/graphql"


def test_a_capped_linear_pass_continues_where_it_stopped_on_the_next_run(tmp_path):
    pages = [[lin_issue(k, f"2026-09-{20 - k:02d}T10:00:00.000Z")] for k in range(4)]
    store = ConnectorStore(tmp_path, "linear")
    out = linear.pull(store, LINEAR_ENV, linear_cfg(), NOW, client=FakeLinear(pages).client(), pages=2)
    assert out["read"] == 2 and not out["complete"] and store.state()["cursor"] == "2"
    fake = FakeLinear(pages)
    out = linear.pull(store, LINEAR_ENV, linear_cfg(), NOW, client=fake.client(), pages=5)
    first = [b for _r, b in fake.calls if "issues(" in b["query"]][0]
    assert first["variables"]["after"] == "2" and out["complete"] and store.state().get("cursor") is None
    assert len(store.load()["issue"]) == 4


def test_a_refused_linear_key_is_said_plainly(tmp_path):
    with pytest.raises(linear.ConnectorError) as err:
        linear.pull(ConnectorStore(tmp_path, "linear"), LINEAR_ENV, linear_cfg(), NOW, client=FakeLinear([], status=401).client())
    assert "401" in str(err.value) and "lin_api_secret" not in str(err.value)


def test_the_store_keeps_the_newest_copy_of_each_record_and_compresses_past_days(tmp_path):
    store = ConnectorStore(tmp_path, "jira")
    store.add([{"t": "issue", "id": "jira:1", "title": "old"}], "2026-10-01")
    store.add([{"t": "issue", "id": "jira:1", "title": "new"}], "2026-10-02")
    store.compress("2026-10-03")
    assert [i["title"] for i in store.load()["issue"]] == ["new"]
    assert sorted(p.name for p in (tmp_path / "connectors" / "jira" / "days").iterdir()) == ["2026-10-01.ndjson.gz",
                                                                                          "2026-10-02.ndjson.gz"]


def test_the_app_can_set_a_jira_site_but_never_send_the_key_elsewhere():
    from stackvitals.core.tomledit import EditError, apply
    out = apply("", {"connectors.jira.url": "https://acme.atlassian.net", "connectors.jira.key_expires": "2027-10-21",
                     "connectors.linear.teams": ["ENG"]})
    cfg = parse(out)[0]["connectors"]
    assert cfg["jira"]["url"] == "https://acme.atlassian.net" and cfg["jira"]["key_expires"] == "2027-10-21"
    assert cfg["linear"]["teams"] == ["ENG"]
    with pytest.raises(EditError):
        apply("", {"connectors.jira.url": "https://collector.example.com"})
