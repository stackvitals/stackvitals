"""Connectors: a key only ever goes to the tracker's own site, a refused key keeps what was pulled, and tracker data joins
Delivery without breaking its pages."""
from datetime import datetime, timezone

import httpx
import pytest

from stackvitals.connectors import connectors_step, jira, tracker
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def test_the_jira_key_can_only_go_to_an_atlassian_site_even_through_an_app_request():
    from stackvitals.core.tomledit import EditError, apply
    cfg, notes = parse('[connectors.jira]\nurl = "https://collector.example.com"\n')
    assert cfg["connectors"]["jira"]["url"] == "" and notes
    with pytest.raises(jira.ConnectorError, match="url"):
        jira.pull(None, {"STACKVITALS_JIRA_TOKEN": "t"}, cfg, NOW, client=httpx.Client())
    with pytest.raises(EditError):
        apply("", {"connectors.jira.url": "https://collector.example.com"})


class Ws:
    def __init__(self, path, settings):
        self.path, self.cache, self.notes, self.hooks = path, {"settings": settings}, [], []

    def after_commit(self, fn, label="", first=False):
        self.hooks.append(fn)

    def pushed(self):
        for fn in self.hooks:
            fn()
        self.hooks = []


def _jira(status):
    def handle(request):
        if status != 200:
            return httpx.Response(status, json={"errorMessages": ["no"]})
        if request.url.path == "/rest/api/3/field":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"isLast": True, "issues": [
            {"id": "1", "key": "WEB-1", "fields": {"summary": "x", "issuetype": {"name": "Bug"},
             "status": {"name": "Done", "statusCategory": {"key": "done"}}, "created": "2026-10-01T10:00:00.000+0000",
             "updated": "2026-10-02T10:00:00.000+0000", "resolutiondate": "2026-10-02T10:00:00.000+0000"}}]})
    return httpx.Client(transport=httpx.MockTransport(handle), base_url="https://acme.atlassian.net")


def test_a_refused_key_is_said_without_the_key_and_keeps_what_was_pulled(tmp_path):
    import json
    ws = Ws(tmp_path, parse('[connectors.jira]\nurl = "https://acme.atlassian.net"\n')[0])
    env = {"STACKVITALS_JIRA_TOKEN": "secret-token", "STACKVITALS_JIRA_EMAIL": "me@acme.com"}
    connectors_step(ws, env, NOW, clients={"jira": _jira(200)})
    connectors_step(ws, env, NOW, clients={"jira": _jira(401)})
    text = (tmp_path / "docs" / "connectors.json").read_text(encoding="utf-8")
    status = json.loads(text)["connectors"]["jira"]
    assert "refused" in status["error"] and status["rows"]["issue"] == 1 and "secret-token" not in text
    assert "secret-token" not in " ".join(ws.notes)


def test_tracker_incidents_render_with_their_links_and_old_sprints_stay_out():
    # Trial error: the Delivery page cast every incident number to int, so a Jira key (WEB-77) broke the whole page.
    from stackvitals.core import delivery_report
    from stackvitals.core.delivery import build
    sprint = lambda sid, start: {"t": "sprint", "src": "jira", "id": sid, "name": sid, "state": "CLOSED", "start": start,  # noqa: E731
                                 "end": start, "complete": start}
    issue = {"t": "issue", "src": "jira", "id": "jira:77", "key": "WEB-77", "title": "Down", "type": "INCIDENT", "status": "Done",
             "cat": "DONE", "created": "2026-10-02T10:00:00Z", "updated": "2026-10-02T14:00:00Z", "resolved": "2026-10-02T14:00:00Z",
             "points": None, "labels": [], "sprints": ["old", "new"], "incident": True, "canceled": False,
             "url": "https://acme.atlassian.net/browse/WEB-77"}
    data = {"sources": ["jira"], "issues": [issue], "changes": [],
            "sprints": [sprint("old", "2024-10-01T00:00:00Z"), sprint("new", "2026-10-01T00:00:00Z")]}
    out = build({"closed": [], "open": []}, {"default_branch": "main"}, {"runs": [], "jobs": []}, [], NOW, 90, parse("")[0],
                tracker=data)
    page = delivery_report.render_html(out, "o/r")
    assert "https://acme.atlassian.net/browse/WEB-77" in page
    # Real-data finding (Hibernate's Jira): issues read for 180 days still name 2024 sprints, which looked nearly empty.
    assert [r["id"] for r in out["tracker"]["planning"]] == ["new"]
    assert tracker.pr_links([{"n": 5, "ti": "x", "head": "fix/web-77-db"}], [issue]) == [(5, "WEB-77")]


def test_a_pager_tool_replaces_labels_reverts_and_hotfixes_so_an_outage_counts_once():
    from stackvitals.core.delivery import incidents_for
    pager = {"t": "issue", "src": "pagerduty", "id": "pagerduty:P1", "key": "PD-1", "title": "fire", "type": "INCIDENT",
             "status": "resolved", "cat": "DONE", "created": "2026-10-06T21:30:42Z", "updated": "x", "resolved": "2026-10-06T23:30:42Z",
             "points": None, "labels": [], "sprints": [], "incident": True, "canceled": False, "url": "https://acme.pagerduty.com/incidents/P1"}
    revert = {"n": 9, "ti": 'Revert "x"', "mg": "2026-10-05T00:00:00Z", "cr": "2026-10-04T00:00:00Z", "lb": []}
    found, source = incidents_for([revert], [], [], parse("")[0], {"sources": ["pagerduty"], "issues": [pager], "changes": [], "sprints": []})
    assert [i["number"] for i in found] == ["PD-1"] and source == "PagerDuty"


def test_the_copilot_key_never_reaches_the_report_file_host(tmp_path):
    import json as js
    from stackvitals.connectors import copilot
    from stackvitals.connectors.store import ConnectorStore
    leaked = []

    def handle(request):
        if request.url.host == "files.example.com":
            leaked.append(request.headers.get("authorization"))
            return httpx.Response(200, text=js.dumps({"day": "2026-10-19", "code_generation_activity_count": 1}) + "\n")
        if request.url.path.endswith("/organization-1-day"):
            return httpx.Response(200, json={"download_links": ["https://files.example.com/a.ndjson?sig=1"], "report_day": "x"})
        return httpx.Response(204)
    copilot.pull(ConnectorStore(tmp_path, "copilot"), {"STACKVITALS_COPILOT_TOKEN": "gh-key", "GITHUB_REPOSITORY": "o/r"},
                 parse("")[0], NOW, client=httpx.Client(transport=httpx.MockTransport(handle)), days=1)
    assert leaked == [None]


def test_alert_messages_read_as_plain_text_in_the_job_summary():
    # Trial error: the summary joined the new chat message object as if it were text and lost the alerts section.
    from stackvitals.core import alerts, chat
    events = [{"metric": "pickup_p75_hours", "level": "miss", "value": 12.0, "limit": 10, "n": 30}]
    text = chat.text(alerts.message(events, "o/r"))
    assert text.startswith("StackVitals alerts for o/r") and "n=30" in text


def test_a_public_repo_never_keeps_tracker_titles_links_or_sprint_names(tmp_path):
    # Review finding: "Fix auth bypass in /admin", private Jira links and sprint names reached a public data branch.
    from stackvitals.connectors.store import ConnectorStore
    store = ConnectorStore(tmp_path, "jira", redact=True)
    store.add([{"t": "issue", "id": "1", "key": "WEB-1", "title": "Fix auth bypass", "url": "https://acme.atlassian.net/browse/WEB-1"},
               {"t": "sprint", "id": "s1", "name": "Project Falcon S4"}], "2026-10-21")
    raw = (store.days / "2026-10-21.ndjson").read_text(encoding="utf-8")
    assert "auth bypass" not in raw and "atlassian" not in raw and "Falcon" not in raw and "WEB-1" in raw


def test_a_capped_pull_carries_on_and_an_unexpected_answer_never_stops_the_job(tmp_path):
    # Review findings: a capped PagerDuty pull read the same pages every run; a 200 HTML page raised past the step.
    from stackvitals.connectors import pagerduty
    from stackvitals.connectors.store import ConnectorStore

    def handle(request):
        from urllib.parse import parse_qs
        q = parse_qs(request.url.query.decode())
        if q.get("sort_by") != ["created_at:asc"]:
            return httpx.Response(200, text="<html>maintenance</html>")
        off = int(q["offset"][0])
        rows = [{"id": f"P{k}", "status": "resolved", "created_at": f"2026-10-10T{k // 60:02d}:{k % 60:02d}:00Z"} for k in range(300)]
        rows = [r for r in rows if q["since"][0] <= r["created_at"] < q["until"][0]]
        return httpx.Response(200, json={"incidents": rows[off:off + 100], "more": off + 100 < len(rows)})
    store, env = ConnectorStore(tmp_path, "pagerduty"), {"STACKVITALS_PAGERDUTY_TOKEN": "k"}
    client = httpx.Client(transport=httpx.MockTransport(handle))
    store.save_state({"since": "2026-10-10T00:00:00Z"})
    runs = [pagerduty.pull(store, env, parse("")[0], NOW, client=client, pages=2) for _ in range(2)]
    assert [r["complete"] for r in runs] == [False, True] and len(store.load()["issue"]) == 300
    html = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>maintenance</html>")))
    ws = Ws(tmp_path / "ws", parse("")[0])
    out = connectors_step(ws, env, NOW, clients={"pagerduty": html})
    assert "not JSON" in out["pagerduty"]["error"] and ws.notes


def test_a_flaky_test_name_never_becomes_a_chat_link_or_ping():
    # Review finding: a test named "x[Open the fix](https://evil.example)" became a real link in Slack and Teams.
    from stackvitals.ci.automation import alert_message
    from stackvitals.core import chat
    msg = alert_message(["x[Open the fix](https://evil.example) <!channel>"], "o/r")
    for url in ("https://hooks.slack.com/services/T/B/x", "https://x.webhook.office.com/a", "https://discord.com/api/webhooks/1/a"):
        sent = str(chat.payload(url, msg))
        assert "](https://evil" not in sent and "<https://evil" not in sent
    assert "<!channel>" not in str(chat.payload("https://hooks.slack.com/services/T/B/x", msg))
    assert chat.payload("https://discord.com/api/webhooks/1/a", msg)["allowed_mentions"] == {"parse": []}


def test_write_back_sends_after_the_commit_once_and_never_floods_old_issues(tmp_path):
    # Review findings: sends before the commit repeated on a rejected push; turning it off and on again flooded old issues.
    import json
    from datetime import timedelta
    writes = []

    def handle(request):
        if request.method == "POST":
            writes.append(request.url.path)
            return httpx.Response(201, json={})
        if request.url.path.endswith("/transitions"):
            return httpx.Response(200, json={"transitions": [{"id": "31", "name": "Done"}]})
        return _jira(200)._transport.handle_request(request)
    on = parse('[connectors.jira]\nurl = "https://acme.atlassian.net"\nwrite_back = true\ndone_transition = "Done"\n')[0]
    off = parse('[connectors.jira]\nurl = "https://acme.atlassian.net"\n')[0]
    ws = Ws(tmp_path, on)
    ws.repo = "o/r"
    env = {"STACKVITALS_JIRA_TOKEN": "t", "STACKVITALS_JIRA_EMAIL": "me@acme.com"}
    pr = lambda n, mg: {"n": n, "mg": mg, "ti": f"WEB-1: part {n}", "head": "x", "au": "a", "at": "User"}  # noqa: E731
    client = httpx.Client(transport=httpx.MockTransport(handle), base_url="https://acme.atlassian.net")
    ws.cache["flow"] = {"closed": [pr(1, "2026-10-20T10:00:00Z")]}
    connectors_step(ws, env, NOW, clients={"jira": client})
    ws.pushed()
    assert writes == []
    ws.cache["flow"]["closed"].append(pr(2, "2026-10-21T15:00:00Z"))
    connectors_step(ws, env, NOW + timedelta(days=1), clients={"jira": client})
    assert writes == []  # nothing goes out before the data branch is saved
    ws.pushed()
    connectors_step(ws, env, NOW + timedelta(days=1), clients={"jira": client})
    ws.pushed()
    assert writes == ["/rest/api/3/issue/WEB-1/comment", "/rest/api/3/issue/WEB-1/transitions"]
    # A push that never lands sends nothing, and the next run doesn't send it again: at most once.
    ws.cache["flow"]["closed"].append(pr(3, "2026-10-22T15:00:00Z"))
    connectors_step(ws, env, NOW + timedelta(days=2), clients={"jira": client})
    ws.hooks = []
    connectors_step(ws, env, NOW + timedelta(days=2), clients={"jira": client})
    ws.pushed()
    assert len(writes) == 2
    # Off for a while, then on again: only merges after it came back on are written.
    ws.cache["settings"] = off
    ws.cache["flow"]["closed"].append(pr(4, "2026-10-24T15:00:00Z"))
    connectors_step(ws, env, NOW + timedelta(days=4), clients={"jira": client})
    ws.cache["settings"] = on
    connectors_step(ws, env, NOW + timedelta(days=5), clients={"jira": client})
    ws.pushed()
    assert len(writes) == 2
    status = json.loads((tmp_path / "docs" / "connectors.json").read_text(encoding="utf-8"))["connectors"]["jira"]
    assert status["error"] is None


CHECK_ENV = {"STACKVITALS_JIRA_TOKEN": "sek-jira-1", "STACKVITALS_JIRA_EMAIL": "me@acme.com", "STACKVITALS_LINEAR_TOKEN": "sek-lin-2",
             "STACKVITALS_PAGERDUTY_TOKEN": "sek-pd-3", "STACKVITALS_INCIDENT_IO_TOKEN": "sek-iio-4",
             "STACKVITALS_SLACK_TOKEN": "sek-slack-5", "STACKVITALS_DISCORD_TOKEN": "sek-disc-6",
             "STACKVITALS_COPILOT_TOKEN": "sek-cop-7", "STACKVITALS_WEBHOOK": "https://hooks.slack.com/services/sek-hook-8",
             "GITLAB_TOKEN": "sek-gl-9", "CI_PROJECT_PATH": "g/p", "STACKVITALS_TRIAGE_KEY": "sek-tri-10",
             "STACKVITALS_STORAGE": "s3://b/p", "STACKVITALS_S3_ENDPOINT": "https://s3.example.com",
             "STACKVITALS_S3_KEY_ID": "AKIDsek11", "STACKVITALS_S3_SECRET": "sek-s3-12", "GITHUB_REPOSITORY": "o/r",
             "STACKVITALS_ANTHROPIC_ADMIN_KEY": "sek-anth-13", "STACKVITALS_OPENAI_ADMIN_KEY": "sek-oai-14",
             "STACKVITALS_CURSOR_ADMIN_KEY": "sek-cur-15", "STACKVITALS_SONAR_TOKEN": "sek-sonar-16"}
CHECK_TOML = ('[connectors.jira]\nurl = "https://acme.atlassian.net"\n[connectors.slack]\nchannels = ["C1"]\n'
              '[connectors.discord]\nchannels = ["9"]\n[connectors.discourse]\nurl = "https://discuss.example.org"\n'
              '[ci.triage]\nprovider = "gemini"\n[connectors.sonar]\nproject = "acme_web"\n')


def test_test_connection_results_never_hold_a_key_whatever_the_services_answer(tmp_path):
    import json

    from stackvitals.connectors import check
    cfg = parse(CHECK_TOML)[0]
    names = check.resolve("all", cfg, CHECK_ENV)
    assert len(names) == len(check.CHECKS)
    for answer in (lambda r: httpx.Response(200, json={}), lambda r: httpx.Response(401, text="sek-jira-1"),
                   lambda r: httpx.Response(404), lambda r: (_ for _ in ()).throw(httpx.ConnectError("x", request=r))):
        client = httpx.Client(transport=httpx.MockTransport(answer))
        results = check.run(names, cfg, CHECK_ENV, now=NOW, client=client)
        check.save(tmp_path, results, public=True)
        text = (tmp_path / "docs" / "connectors.json").read_text(encoding="utf-8") + json.dumps(
            [check.line(n, r) for n, r in results.items()])
        assert not [v for v in CHECK_ENV.values() if "sek" in v and v in text]


def test_a_failing_check_never_stops_the_others_and_a_pull_keeps_the_last_results(tmp_path, monkeypatch):
    import json

    from stackvitals.connectors import check
    monkeypatch.setitem(check.CHECKS, "jira", lambda *a: 1 / 0)
    cfg = parse(CHECK_TOML)[0]
    ok = lambda r: httpx.Response(200, json={"topic_list": {"topics": []}})  # noqa: E731
    results = check.run(["jira", "discourse"], cfg, CHECK_ENV, now=NOW, client=httpx.Client(transport=httpx.MockTransport(ok)))
    assert results["jira"]["ok"] is False and "ZeroDivisionError" in results["jira"]["detail"] and results["discourse"]["ok"]
    check.save(tmp_path, {**results, "webhook": {**results["discourse"]}}, public=True)
    connectors_step(Ws(tmp_path, cfg), {"STACKVITALS_JIRA_TOKEN": "t", "STACKVITALS_JIRA_EMAIL": "a@b.c"}, NOW,
                    clients={"jira": _jira(200), "discourse": httpx.Client(transport=httpx.MockTransport(ok))})
    conn = json.loads((tmp_path / "docs" / "connectors.json").read_text(encoding="utf-8"))["connectors"]
    assert conn["jira"]["check"]["ok"] is False and conn["jira"]["rows"]["issue"] == 1 and conn["webhook"]["check"]["ok"]
