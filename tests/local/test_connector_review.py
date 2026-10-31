"""Fixes from the Phase 12 connector review: each test is one verified finding."""
import gzip
import json

import pytest

from stackvitals.connectors.store import ConnectorStore


def test_a_unicode_line_separator_in_a_title_never_breaks_the_store(tmp_path):
    # Review finding: records keep U+2028 raw, and splitlines() cut them in two, so every later load raised.
    store = ConnectorStore(tmp_path, "pagerduty")
    store.add([{"t": "issue", "id": "1", "title": "db down again\x85now"}], "2026-10-20")
    store.add([{"t": "issue", "id": "2", "title": "fine"}], "2026-10-21")
    store.compress("2026-10-21")
    assert sorted(i["title"] for i in store.load()["issue"]) == ["db down again\x85now", "fine"]


def test_a_damaged_line_is_skipped_instead_of_stopping_every_later_run(tmp_path):
    store = ConnectorStore(tmp_path, "jira")
    store.days.mkdir(parents=True)
    (store.days / "2026-10-20.ndjson").write_text('{"t":"issue","id":"1"}\n{"t":"issue","id":\n{"t":"issue","id":"3"}\n',
                                                 encoding="utf-8")
    (store.days / "2026-10-19.ndjson.gz").write_bytes(gzip.compress(json.dumps({"t": "sprint", "id": 9}).encode() + b"\n"))
    out = store.load()
    assert [i["id"] for i in out["issue"]] == ["1", "3"] and out["sprint"][0]["id"] == 9


def test_a_public_repo_never_stores_or_reads_tracker_titles_links_or_sprint_names(tmp_path):
    # Review finding: "Fix auth bypass in /admin", a private Jira link and "Project Falcon S4" reached public files.
    store = ConnectorStore(tmp_path, "jira", redact=True)
    store.add([{"t": "issue", "id": "1", "key": "WEB-1", "title": "Fix auth bypass in /admin", "url": "https://acme.atlassian.net/browse/WEB-1",
                "type": "BUG"}, {"t": "sprint", "id": "s1", "name": "Project Falcon S4", "end": "2026-10-10T00:00:00Z"}], "2026-10-21")
    raw = (store.days / "2026-10-21.ndjson").read_text(encoding="utf-8")
    assert "auth bypass" not in raw and "atlassian" not in raw and "Falcon" not in raw
    old = ConnectorStore(tmp_path, "linear")
    old.add([{"t": "issue", "id": "2", "key": "ENG-2", "title": "Customer DB breach", "url": "https://linear.app/x/ENG-2"}], "2026-10-20")
    seen = ConnectorStore(tmp_path, "linear", redact=True).load()["issue"][0]
    assert "title" not in seen and "url" not in seen and seen["key"] == "ENG-2"


def test_the_connector_step_hides_titles_unless_the_repo_is_known_to_be_private(tmp_path):
    from datetime import datetime, timezone

    from stackvitals import connectors
    from stackvitals.core.config import parse

    class Fake:
        @staticmethod
        def configured(env, cfg):
            return True

        @staticmethod
        def pull(store, env, cfg, now, client=None):
            store.add([{"t": "issue", "id": "1", "key": "WEB-1", "title": "Secret plan", "url": "https://x"}], "2026-10-21")
            return {"read": 1, "complete": True}

    class Ws:
        def __init__(self, path, info):
            self.path, self.notes, self.cache = path, [], {"settings": parse("")[0], "repo_info": info}
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    saved = connectors.CONNECTORS
    connectors.CONNECTORS = {"jira": Fake}
    try:
        public, private = Ws(tmp_path / "pub", {"private": False}), Ws(tmp_path / "priv", {"private": True})
        connectors.connectors_step(public, {}, now)
        connectors.connectors_step(private, {}, now)
        unknown = Ws(tmp_path / "unknown", None)
        connectors.connectors_step(unknown, {}, now)
    finally:
        connectors.CONNECTORS = saved
    assert "title" not in public.cache["tracker"]["issues"][0] and "title" not in unknown.cache["tracker"]["issues"][0]
    assert private.cache["tracker"]["issues"][0]["title"] == "Secret plan"


def test_a_sprint_without_its_name_is_named_by_its_dates():
    from datetime import datetime, timezone

    from stackvitals.connectors import tracker
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    sprints = [{"t": "sprint", "id": "s1", "state": "CLOSED", "start": "2026-09-28T00:00:00Z", "end": "2026-10-10T00:00:00Z"}]
    rows = tracker.planning([], [], sprints, now, since=datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert rows[0]["name"] == "Sprint ending 2026-10-10"


def _pd_fake(incidents, seen):
    import httpx
    from urllib.parse import parse_qs

    def handle(request):
        q = parse_qs(request.url.query.decode())
        seen.append(q)
        inside = [i for i in incidents if q["since"][0] <= i["created_at"] < q["until"][0]]
        if q.get("sort_by") == ["created_at:asc"]:
            inside.sort(key=lambda i: i["created_at"])
        off, lim = int(q["offset"][0]), int(q["limit"][0])
        return httpx.Response(200, json={"incidents": inside[off:off + lim], "more": off + lim < len(inside)})
    return httpx.Client(transport=httpx.MockTransport(handle))


def test_a_capped_pagerduty_pull_carries_on_where_it_stopped(tmp_path):
    # Review finding: a capped pass saved the chunk start, and the next run stepped back two weeks, so it read the same pages.
    from datetime import datetime, timedelta, timezone

    from stackvitals.connectors import pagerduty
    from stackvitals.core.config import parse
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    t0 = datetime(2026, 10, 10, tzinfo=timezone.utc)
    stamp = lambda k: (t0 + timedelta(minutes=17 * k)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    # Shuffled, as PagerDuty's own order is not documented.
    incidents = [{"id": f"P{k}", "incident_number": k, "status": "resolved", "created_at": stamp(k), "updated_at": stamp(k),
                  "resolved_at": stamp(k)} for k in (list(range(0, 500, 2)) + list(range(1, 500, 2)))]
    store, env, cfg = ConnectorStore(tmp_path, "pagerduty"), {"STACKVITALS_PAGERDUTY_TOKEN": "k"}, parse("")[0]
    store.save_state({"since": "2026-10-09T00:00:00Z"})
    seen = []
    runs = [pagerduty.pull(store, env, cfg, now, client=_pd_fake(incidents, seen), pages=2) for _ in range(3)]
    assert [r["complete"] for r in runs] == [False, False, True] and len(store.load()["issue"]) == 500
    assert all(q["sort_by"] == ["created_at:asc"] for q in seen) and store.state() == {"since": "2026-10-21T12:00:00Z"}


def test_a_capped_incident_io_pull_keeps_its_place_in_the_pass(tmp_path):
    # Review finding: the pass is sorted by creation, and a capped one started over, so past 5,000 incidents it never ended.
    from datetime import datetime, timedelta, timezone
    from urllib.parse import parse_qs

    import httpx

    from stackvitals.connectors import incident_io
    from stackvitals.core.config import parse
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    stamp = lambda k: (t0 + timedelta(hours=k)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")  # noqa: E731
    incidents = [{"id": f"01F{k:04d}", "reference": f"INC-{k}", "incident_status": {"category": "closed", "name": "Closed"},
                  "created_at": stamp(k), "updated_at": stamp(600 - k)} for k in range(600)]

    def handle(request):
        q = parse_qs(request.url.query.decode())
        rows = [i for i in incidents if i["updated_at"] >= q["updated_at[gte]"][0]]
        ids = [i["id"] for i in rows]
        after = q.get("after", [None])[0]
        if after and after not in ids:
            return httpx.Response(422, json={"type": "validation_error"})
        start = ids.index(after) + 1 if after else 0
        size = int(q["page_size"][0])
        page = rows[start:start + size]
        more = start + size < len(rows)
        return httpx.Response(200, json={"incidents": page, "pagination_meta": {"page_size": size, **({"after": page[-1]["id"]} if more else {})}})
    store, env, cfg = ConnectorStore(tmp_path, "incident_io"), {"STACKVITALS_INCIDENT_IO_TOKEN": "k"}, parse("")[0]
    client = httpx.Client(transport=httpx.MockTransport(handle))
    store.save_state({"since": "2026-08-01T00:00:00Z"})
    runs = [incident_io.pull(store, env, cfg, now, client=client, pages=1) for _ in range(3)]
    assert [r["complete"] for r in runs] == [False, False, True] and len(store.load()["issue"]) == 600
    assert store.state() == {"since": "2026-09-26T00:00:00Z"}
    # A cursor the API no longer knows starts that pass over instead of failing every run.
    store.save_state({"since": "2026-08-01T00:00:00Z", "after": "gone", "newest": "2026-08-01T00:00:00Z"})
    out = incident_io.pull(store, env, cfg, now, client=client, pages=5)
    assert out["complete"] and len(store.load()["issue"]) == 600 and "after" not in store.state()


class _Jira:
    """Jira's enhanced search over issues whose times carry the account's +0200 offset; JQL dates are read in that zone."""

    def __init__(self, issues):
        self.issues, self.jql = issues, []

    def handle(self, request):
        import re
        from datetime import datetime
        from urllib.parse import parse_qs

        import httpx
        if request.url.path == "/rest/api/3/field":
            return httpx.Response(200, json=[])
        q = parse_qs(request.url.query.decode())
        self.jql.append(q["jql"][0])
        floor = datetime.strptime(re.search(r'updated >= "([^"]+)"', q["jql"][0]).group(1) + " +0200", "%Y/%m/%d %H:%M %z")
        rows = sorted((i for i in self.issues if datetime.fromisoformat(i["fields"]["updated"]) >= floor),
                      key=lambda i: i["fields"]["updated"])
        start = int(q.get("nextPageToken", ["0"])[0])
        page = rows[start:start + 100]
        last = start + 100 >= len(rows)
        return httpx.Response(200, json={"issues": page, "isLast": last, **({} if last else {"nextPageToken": str(start + 100)})})

    def client(self):
        import httpx
        return httpx.Client(transport=httpx.MockTransport(self.handle), base_url="https://acme.atlassian.net")


def _jira_issue(n, updated):
    return {"id": str(n), "key": f"WEB-{n}", "fields": {"summary": "x", "status": {"name": "Done", "statusCategory": {"key": "done"}},
                                                        "created": updated, "updated": updated}}


def _jira_cfg():
    from stackvitals.core.config import parse
    return parse('[connectors.jira]\nurl = "https://acme.atlassian.net"\n')[0]


JIRA_ENV = {"STACKVITALS_JIRA_TOKEN": "t", "STACKVITALS_JIRA_EMAIL": "a@b.c"}


def test_a_capped_jira_pull_carries_on_without_stepping_back_a_day(tmp_path):
    # Review finding: a capped pass stepped back a whole day next run, so more than 2,000 updates in a day never got through.
    from datetime import datetime, timedelta, timezone

    from stackvitals.connectors import jira
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    t0 = datetime(2026, 10, 20, 8, tzinfo=timezone(timedelta(hours=2)))
    issues = [_jira_issue(k, (t0 + timedelta(seconds=20 * k)).isoformat(timespec="milliseconds").replace("+02:00", "+0200"))
              for k in range(450)]
    store, fake = ConnectorStore(tmp_path, "jira"), _Jira(issues)
    store.save_state({"since": "2026-10-20T05:00:00Z"})
    runs = [jira.pull(store, JIRA_ENV, _jira_cfg(), now, client=fake.client(), pages=2) for _ in range(3)]
    assert [r["complete"] for r in runs] == [False, False, True] and len(store.load()["issue"]) == 450
    # The cursor is written in the account's own zone, so nothing is skipped or read a day early while catching up;
    # after a full pass, a day of overlap again.
    jira.pull(store, JIRA_ENV, _jira_cfg(), now, client=fake.client(), pages=2)
    starts = list(dict.fromkeys(j.split('"')[1] for j in fake.jql))
    assert starts == ["2026/10/19 05:00", "2026/10/20 09:06", "2026/10/20 10:12", "2026/10/19 08:29"]


def test_more_jira_updates_in_one_minute_than_a_run_reads_are_passed_with_a_note(tmp_path):
    from datetime import datetime, timezone

    from stackvitals.connectors import jira
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    issues = [_jira_issue(k, f"2026-10-20T08:00:{k % 60:02d}.{k:03d}+0200") for k in range(300)]
    issues.append(_jira_issue(999, "2026-10-20T08:05:00.000+0200"))
    store, fake = ConnectorStore(tmp_path, "jira"), _Jira(issues)
    store.save_state({"since": "2026-10-20T05:00:00Z"})
    runs = [jira.pull(store, JIRA_ENV, _jira_cfg(), now, client=fake.client(), pages=2) for _ in range(3)]
    assert "note" not in runs[0] and "one minute" in runs[1]["note"] and runs[2]["complete"]
    assert 'updated >= "2026/10/20 08:01"' in fake.jql[-1] and "WEB-999" in {i["key"] for i in store.load()["issue"]}


def test_a_connector_note_reaches_the_job_summary(tmp_path):
    from datetime import datetime, timezone

    from stackvitals import connectors
    from stackvitals.core.config import parse

    class Fake:
        configured = staticmethod(lambda env, cfg: True)
        pull = staticmethod(lambda store, env, cfg, now, client=None: {"read": 0, "complete": False, "note": "a minute was skipped."})

    class Ws:
        path, notes, cache = tmp_path, [], {"settings": parse("")[0]}
    saved, connectors.CONNECTORS = connectors.CONNECTORS, {"jira": Fake}
    try:
        connectors.connectors_step(Ws, {}, datetime(2026, 10, 21, tzinfo=timezone.utc))
    finally:
        connectors.CONNECTORS = saved
    assert Ws.notes == ["Jira: a minute was skipped."]


@pytest.mark.parametrize("name", ["pagerduty", "incident_io", "jira", "copilot"])
def test_a_page_that_is_not_json_is_said_plainly_instead_of_failing_the_job(tmp_path, name):
    # Review finding: a 200 maintenance page (HTML) raised ValueError, which only ConnectorError was caught for.
    from datetime import datetime, timezone

    import httpx

    from stackvitals.connectors import CONNECTORS
    from stackvitals.core.config import parse
    cfg = parse('[connectors.jira]\nurl = "https://acme.atlassian.net"\n[connectors.copilot]\norg = "acme"\n')[0]
    env = {"STACKVITALS_JIRA_TOKEN": "t", "STACKVITALS_JIRA_EMAIL": "a@b.c", "STACKVITALS_PAGERDUTY_TOKEN": "t",
           "STACKVITALS_INCIDENT_IO_TOKEN": "t", "STACKVITALS_COPILOT_TOKEN": "t"}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>Down for maintenance</html>")),
                          base_url="https://acme.atlassian.net")
    with pytest.raises(CONNECTORS[name].ConnectorError) as err:
        CONNECTORS[name].pull(ConnectorStore(tmp_path, name), env, cfg, datetime(2026, 10, 21, tzinfo=timezone.utc), client=client)
    assert "not JSON" in str(err.value)


def test_an_unexpected_error_in_one_connector_never_fails_the_job(tmp_path):
    from datetime import datetime, timezone

    from stackvitals import connectors
    from stackvitals.core.config import parse

    def boom(store, env, cfg, now, client=None):
        raise KeyError("id")

    class Broken:
        configured, pull = staticmethod(lambda env, cfg: True), staticmethod(boom)

    class Fine:
        configured = staticmethod(lambda env, cfg: True)
        pull = staticmethod(lambda store, env, cfg, now, client=None: {"read": 0, "complete": True})

    class Ws:
        path, notes, cache = tmp_path, [], {"settings": parse("")[0]}
    saved, connectors.CONNECTORS = connectors.CONNECTORS, {"jira": Broken, "linear": Fine}
    try:
        out = connectors.connectors_step(Ws, {}, datetime(2026, 10, 21, tzinfo=timezone.utc))
    finally:
        connectors.CONNECTORS = saved
    assert out["linear"]["error"] is None and "KeyError" in out["jira"]["error"] and Ws.notes[0].startswith("Jira: ")


def test_a_key_expiry_written_as_a_toml_date_time_is_kept_as_a_date(tmp_path):
    from datetime import datetime, timezone

    from stackvitals import connectors
    from stackvitals.core.config import parse
    cfg, notes = parse("[connectors.pagerduty]\nkey_expires = 2026-10-30T10:00:00Z\n[connectors.linear]\nkey_expires = \"20261101\"\n")
    assert notes == [] and cfg["connectors"]["pagerduty"]["key_expires"] == "2026-10-30"
    assert cfg["connectors"]["linear"]["key_expires"] == "2026-11-01"

    class Fake:
        configured = staticmethod(lambda env, cfg: True)
        pull = staticmethod(lambda store, env, cfg, now, client=None: {"read": 0, "complete": True})

    class Ws:
        path, notes, cache = tmp_path, [], {"settings": cfg}
    saved, connectors.CONNECTORS = connectors.CONNECTORS, {"pagerduty": Fake}
    try:
        connectors.connectors_step(Ws, {}, datetime(2026, 10, 21, tzinfo=timezone.utc))
    finally:
        connectors.CONNECTORS = saved
    assert Ws.notes == ["PagerDuty: the key expires on 2026-10-30; create a new one and update the secret."]


def test_a_webhook_secret_with_spaces_or_a_bad_address_never_fails_the_job():
    import httpx

    from stackvitals.core import chat
    sent = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: sent.append(str(r.url)) or httpx.Response(200)))
    msg = {"title": "t", "lines": [], "links": [], "data": {}}
    assert chat.post(" https://hooks.slack.com/services/T/B/x\n", msg, client) is None
    assert sent == ["https://hooks.slack.com/services/T/B/x"]
    assert chat.post("https://hooks.slack.com/services/T\n/B/x", msg, client) == "Could not send the webhook (InvalidURL)."


def test_an_incident_declined_or_merged_later_stops_counting(tmp_path):
    # Review finding: declined ones were skipped on read, so the copy stored while it was live stayed open for ever.
    from datetime import datetime, timezone

    import httpx

    from stackvitals.connectors import incident_io, tracker
    from stackvitals.core.config import parse
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)

    def inc(ref, category):
        return {"id": f"01F{ref}", "reference": ref, "incident_status": {"category": category, "name": category.title()},
                "created_at": "2026-10-20T01:00:00Z", "updated_at": "2026-10-20T02:00:00Z"}

    def client(*found):
        return httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"incidents": list(found), "pagination_meta": {"page_size": 250}})))
    store, env = ConnectorStore(tmp_path, "incident_io"), {"STACKVITALS_INCIDENT_IO_TOKEN": "k"}
    incident_io.pull(store, env, parse("")[0], now, client=client(inc("INC-1", "live"), inc("INC-2", "live"), inc("INC-3", "declined")))
    assert [i["number"] for i in tracker.incidents(store.load()["issue"])] == ["INC-1", "INC-2"]
    incident_io.pull(store, env, parse("")[0], now, client=client(inc("INC-1", "declined"), inc("INC-2", "merged")))
    assert tracker.incidents(store.load()["issue"]) == []


def test_pager_incidents_stay_out_of_the_issues_and_sprints_numbers():
    # Found in review: the filter read "source" while records say "src", so PagerDuty pages counted as Jira issues.
    from datetime import datetime, timezone

    from stackvitals.core import delivery
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    issues = [{"src": "jira", "id": "jira:1", "key": "WEB-1", "type": "BUG", "cat": "DONE", "created": "2026-10-01T00:00:00Z",
               "resolved": "2026-10-02T00:00:00Z"},
              {"src": "pagerduty", "id": "pagerduty:P1", "key": "PD-1", "type": "INCIDENT", "cat": "DONE", "incident": True,
               "created": "2026-10-03T00:00:00Z", "resolved": "2026-10-03T02:00:00Z"}]
    out = delivery._tracker({"sources": ["jira", "pagerduty"], "issues": issues, "changes": [], "sprints": []}, [], now, 90)
    assert out["issues"] == 1 and out["incidents"] == 0 and "INCIDENT" not in out["lead_time"]


def test_a_connector_whose_key_is_gone_no_longer_feeds_delivery(tmp_path):
    # Review finding: after the PagerDuty key was removed, its old pages stayed DORA's only incident source for ever.
    from stackvitals import connectors
    from stackvitals.core.config import parse
    ConnectorStore(tmp_path, "pagerduty").add([{"t": "issue", "src": "pagerduty", "id": "pagerduty:P1", "key": "PD-1",
                                               "incident": True, "created": "2026-10-01T00:00:00Z"}], "2026-10-01")
    ConnectorStore(tmp_path, "jira").add([{"t": "issue", "src": "jira", "id": "jira:1", "key": "WEB-1"}], "2026-10-01")
    cfg = parse("")[0]
    assert connectors.active({"STACKVITALS_JIRA_TOKEN": "t"}, cfg) == ["jira"]
    got = connectors.load(tmp_path, names=connectors.active({"STACKVITALS_JIRA_TOKEN": "t"}, cfg))
    assert got["sources"] == ["jira"] and [i["key"] for i in got["issues"]] == ["WEB-1"]
    assert connectors.load(tmp_path, names=[]) is None and connectors.load(tmp_path)["sources"] == ["jira", "pagerduty"]


def test_incident_io_can_be_scoped_by_type_and_never_counts_test_incidents(tmp_path):
    from datetime import datetime, timezone

    import httpx

    from stackvitals import connectors
    from stackvitals.connectors import incident_io, tracker
    from stackvitals.core.config import parse
    cfg, notes = parse('[connectors.incident_io]\nincident_types = ["Platform"]\n')
    assert notes == [] and connectors.CONNECTORS["incident_io"].scope(cfg) is None
    assert "every incident" in incident_io.scope(parse("")[0]) and "every service" in connectors.CONNECTORS["pagerduty"].scope(parse("")[0])

    def inc(ref, kind, mode="standard"):
        return {"id": f"01F{ref}", "reference": ref, "mode": mode, "incident_type": {"id": "01G", "name": kind},
                "incident_status": {"category": "live", "name": "Live"}, "created_at": "2026-10-20T01:00:00Z",
                "updated_at": "2026-10-20T02:00:00Z"}
    found = [inc("INC-1", "Platform"), inc("INC-2", "Billing"), inc("INC-3", "Platform", "test"), inc("INC-4", "Platform", "tutorial")]
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"incidents": found, "pagination_meta": {"page_size": 250}})))
    store = ConnectorStore(tmp_path, "incident_io")
    incident_io.pull(store, {"STACKVITALS_INCIDENT_IO_TOKEN": "k"}, cfg, datetime(2026, 10, 21, tzinfo=timezone.utc), client=client)
    assert [i["number"] for i in tracker.incidents(store.load()["issue"])] == ["INC-1"]


def test_changed_connector_settings_read_everything_again(tmp_path):
    # Review finding: narrowing scope_jql kept every other project's issues, and widening it never read the older ones.
    from datetime import datetime, timezone

    from stackvitals import connectors
    from stackvitals.core.config import parse
    pulls = []

    class Fake:
        configured = staticmethod(lambda env, cfg: True)

        @staticmethod
        def pull(store, env, cfg, now, client=None):
            pulls.append(dict(store.state()))
            store.add([{"t": "issue", "id": f"jira:{len(pulls)}", "key": f"WEB-{len(pulls)}"}], "2026-10-21")
            store.save_state({"since": "2026-10-21T00:00:00Z"})
            return {"read": 1, "complete": True}

    class Ws:
        path, notes, cache = tmp_path, [], {"settings": parse("[connectors.jira]\nscope_jql = \"project = WEB\"\n")[0],
                                            "repo_info": {"private": True}}
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    saved, connectors.CONNECTORS = connectors.CONNECTORS, {"jira": Fake}
    try:
        connectors.connectors_step(Ws, {}, now)
        connectors.connectors_step(Ws, {}, now)
        assert Ws.notes == [] and pulls[1]["since"] and len(Ws.cache["tracker"]["issues"]) == 2
        Ws.cache["settings"] = parse("[connectors.jira]\nscope_jql = \"project in (WEB, API)\"\n")[0]
        connectors.connectors_step(Ws, {}, now)
    finally:
        connectors.CONNECTORS = saved
    assert pulls[2] == {} and [i["key"] for i in Ws.cache["tracker"]["issues"]] == ["WEB-3"]
    assert "the repo's visibility or what StackVitals keeps changed" in Ws.notes[0]


def test_a_repo_turning_public_rewrites_its_connector_store_without_titles(tmp_path):
    from datetime import datetime, timezone

    from stackvitals import connectors
    from stackvitals.core.config import parse

    class Fake:
        configured = staticmethod(lambda env, cfg: True)

        @staticmethod
        def pull(store, env, cfg, now, client=None):
            store.add([{"t": "issue", "id": "jira:1", "key": "WEB-1", "title": "Secret plan"}], "2026-10-21")
            return {"read": 1, "complete": True}

    class Ws:
        path, notes, cache = tmp_path, [], {"settings": parse("")[0], "repo_info": {"private": True}}
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    saved, connectors.CONNECTORS = connectors.CONNECTORS, {"jira": Fake}
    try:
        connectors.connectors_step(Ws, {}, now)
        Ws.cache["repo_info"] = {"private": False}
        connectors.connectors_step(Ws, {}, now)
    finally:
        connectors.CONNECTORS = saved
    raw = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "connectors" / "jira" / "days").glob("*.ndjson"))
    assert "Secret plan" not in raw and "WEB-1" in raw


def test_a_jira_incident_stays_one_when_only_the_scope_query_read_it_again(tmp_path):
    # The scope query writes issues as not incidents; a mark from the incident query decides, newest update first.
    from stackvitals import connectors
    store = ConnectorStore(tmp_path, "jira")
    base = {"t": "issue", "src": "jira", "id": "jira:1", "key": "WEB-1", "type": "BUG", "created": "2026-10-01T00:00:00Z"}
    store.add([{**base, "updated": "2026-10-02T00:00:00Z", "incident": True, "type": "INCIDENT"},
               {"t": "mark", "id": "jira:1:incident", "issue": "jira:1", "updated": "2026-10-02T00:00:00Z"}], "2026-10-02")
    store.add([{**base, "updated": "2026-10-02T00:00:00Z", "incident": False}], "2026-10-03")
    got = connectors.load(tmp_path)["issues"][0]
    assert got["incident"] and got["type"] == "INCIDENT"
    # Changed later and no longer found by the incident query: no longer an incident.
    store.add([{**base, "updated": "2026-10-05T00:00:00Z", "incident": False}], "2026-10-05")
    assert connectors.load(tmp_path)["issues"][0]["incident"] is False


def test_connector_history_is_under_retention_and_the_size_cap(tmp_path):
    # Review finding: connectors/ was outside every retention rule and the size cap, so it grew for ever.
    from stackvitals.core.store import HistoryStore
    days = tmp_path / "connectors" / "jira" / "days"
    days.mkdir(parents=True)
    for name in ("2025-01-01.ndjson.gz", "2026-10-01.ndjson.gz"):
        (days / name).write_bytes(b"x" * 10)
    (tmp_path / "connectors" / "copilot" / "days").mkdir(parents=True)
    (tmp_path / "connectors" / "copilot" / "days" / "2025-01-01.ndjson.gz").write_bytes(b"x")
    store = HistoryStore(tmp_path)
    assert store.retention("2026-10-21") == {"connectors/jira/days": 1}
    assert sorted(p.name for p in days.iterdir()) == ["2026-10-01.ndjson.gz"] and store.size() == 11


def test_a_record_read_again_unchanged_is_not_written_again(tmp_path):
    # Review finding: every pull appended every record it read (two weeks again for PagerDuty, every cycle for Linear).
    store = ConnectorStore(tmp_path, "pagerduty")
    rec = {"t": "issue", "id": "pagerduty:P1", "status": "triggered"}
    store.add([rec, rec], "2026-10-20")
    store.compress("2026-10-21")
    again = ConnectorStore(tmp_path, "pagerduty")
    again.add([rec], "2026-10-21")
    assert not (again.days / "2026-10-21.ndjson").exists()
    again.add([{**rec, "status": "resolved"}, rec], "2026-10-21")
    lines = (again.days / "2026-10-21.ndjson").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["status"] for x in lines] == ["resolved", "triggered"]


def test_jira_writes_an_issue_found_by_both_queries_once_per_change(tmp_path):
    from datetime import datetime, timezone

    from stackvitals import connectors
    from stackvitals.connectors import jira
    from stackvitals.core.config import parse
    issue = _jira_issue(1, "2026-10-20T08:00:00.000+0200")
    issue["fields"]["issuetype"] = {"name": "Incident"}
    # The fake answers both queries with the issue, as Jira would when it is in scope and an incident.
    fake = _Jira([issue])
    cfg = parse('[connectors.jira]\nurl = "https://acme.atlassian.net"\nincident_jql = "issuetype = Incident"\n')[0]
    store = ConnectorStore(tmp_path, "jira")
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    for _ in range(2):
        jira.pull(store, JIRA_ENV, cfg, now, client=fake.client())
    lines = [json.loads(x) for x in (store.days / "2026-10-21.ndjson").read_text(encoding="utf-8").splitlines()]
    assert sorted(x["t"] for x in lines) == ["issue", "mark"]
    got = connectors.load(tmp_path)["issues"][0]
    assert got["incident"] and got["type"] == "INCIDENT"


def test_a_jira_issue_done_without_a_resolution_date_is_resolved_when_it_moved_to_done():
    # Review finding: workflows that never set a resolution left Done issues out of lead time and sprint "done" counts.
    from stackvitals.connectors import jira
    raw = {"id": "1", "key": "WEB-1", "fields": {"summary": "x", "status": {"name": "Shipped", "statusCategory": {"key": "done"}},
                                                  "created": "2026-10-01T10:00:00.000+0200", "updated": "2026-10-09T10:00:00.000+0200",
                                                  "resolutiondate": None},
           "changelog": {"histories": [
               {"id": "1", "created": "2026-10-03T10:00:00.000+0200", "items": [{"field": "status", "fromString": "To Do", "toString": "Shipped"}]},
               {"id": "2", "created": "2026-10-04T10:00:00.000+0200", "items": [{"field": "status", "fromString": "Shipped", "toString": "In Progress"}]},
               {"id": "3", "created": "2026-10-08T10:00:00.000+0200", "items": [{"field": "status", "fromString": "In Progress", "toString": "Shipped"}]},
               {"id": "4", "created": "2026-10-09T10:00:00.000+0200", "items": [{"field": "labels", "fromString": "", "toString": "x"}]}]}}
    issue = jira._records(raw, "https://acme.atlassian.net", None, None, False)[0]
    assert issue["resolved"] == "2026-10-08T08:00:00Z"
    raw["fields"]["status"] = {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}
    assert jira._records(raw, "https://acme.atlassian.net", None, None, False)[0]["resolved"] is None


def test_a_copilot_day_that_is_not_ready_yet_is_asked_for_again(tmp_path):
    # Review finding: a 204 for a day GitHub had not finished moved the cursor past it, so that day was never kept.
    from datetime import datetime, timezone
    from urllib.parse import parse_qs

    import httpx

    from stackvitals.connectors import copilot
    from stackvitals.core.config import parse
    ready = {"2026-10-18"}

    def handle(request):
        if request.url.host == "files.example.com":
            return httpx.Response(200, text=json.dumps({"day": request.url.path.strip("/")}) + "\n")
        day = parse_qs(request.url.query.decode())["day"][0]
        if day not in ready:
            return httpx.Response(204)
        return httpx.Response(200, json={"download_links": [f"https://files.example.com/{day}"]})
    store, env = ConnectorStore(tmp_path, "copilot"), {"STACKVITALS_COPILOT_TOKEN": "k", "GITHUB_REPOSITORY": "o/r"}
    client = httpx.Client(transport=httpx.MockTransport(handle))
    store.save_state({"through": "2026-10-17"})
    copilot.pull(store, env, parse("")[0], datetime(2026, 10, 21, 12, tzinfo=timezone.utc), client=client)
    assert store.state()["through"] == "2026-10-18"
    ready.add("2026-10-19")
    copilot.pull(store, env, parse("")[0], datetime(2026, 10, 22, 12, tzinfo=timezone.utc), client=client)
    assert sorted(d["day"] for d in store.load()["org_day"]) == ["2026-10-18", "2026-10-19"]
    # A day still empty well after it ended had no usage: later runs move past it.
    store.save_state({"through": "2026-10-01"})
    copilot.pull(store, env, parse("")[0], datetime(2026, 10, 12, 12, tzinfo=timezone.utc), client=client)
    assert store.state()["through"] == "2026-10-07"


def test_a_flaky_test_name_can_not_become_a_link_or_a_ping_in_any_chat():
    # Review finding: a test named "x[Open the fix](https://evil.example)" became a real link in Slack and Teams.
    from stackvitals.ci.automation import alert_message
    from stackvitals.core import chat
    msg = alert_message(["test_login[Open the fix](https://evil.example) <!channel>"], "o/r")
    hooks = {"slack": "https://hooks.slack.com/services/T/B/x", "teams": "https://x.webhook.office.com/a",
             "discord": "https://discord.com/api/webhooks/1/a"}
    for shape, url in hooks.items():
        sent = chat.payload(url, msg)
        flat = str(sent)
        assert "](https://evil" not in flat and "<https://evil" not in flat and (shape != "slack" or "<!channel>" not in flat), shape
    assert chat.payload(hooks["discord"], msg)["allowed_mentions"] == {"parse": []}
    assert "&lt;!channel&gt;" in chat.payload(hooks["slack"], chat.message("<!channel> hi", []))["text"]


def test_every_page_of_recent_linear_cycles_is_read(tmp_path):
    # Review finding: only the first 50 cycles were read, so teams with more lost their sprints.
    import json as _json
    from datetime import datetime, timezone

    import httpx

    from stackvitals.connectors import linear
    from stackvitals.core.config import parse
    asked = []

    def handle(request):
        body = _json.loads(request.content)
        if "cycles(" in body["query"]:
            asked.append(body["variables"])
            k = int(body["variables"].get("after") or 0)
            nodes = [{"id": f"c{k * 50 + j}", "number": k * 50 + j, "startsAt": "2026-10-01T00:00:00Z", "endsAt": "2026-10-14T00:00:00Z",
                      "team": {"key": "ENG"}} for j in range(50 if k < 2 else 7)]
            more = k < 2
            return httpx.Response(200, json={"data": {"cycles": {"nodes": nodes, "pageInfo": {"hasNextPage": more, "endCursor": str(k + 1) if more else None}}}})
        return httpx.Response(200, json={"data": {"issues": {"nodes": [], "pageInfo": {"hasNextPage": False}}}})
    store = ConnectorStore(tmp_path, "linear")
    cfg = parse('[connectors.linear]\nteams = ["ENG"]\n')[0]
    linear.pull(store, {"STACKVITALS_LINEAR_TOKEN": "k"}, cfg, datetime(2026, 10, 21, tzinfo=timezone.utc),
                client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert len(store.load()["sprint"]) == 107 and [a.get("after") for a in asked] == [None, "1", "2"]
    assert asked[0]["filter"] == {"team": {"key": {"in": ["ENG"]}}, "endsAt": {"gte": "2026-04-24T00:00:00Z"}}
