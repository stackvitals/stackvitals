"""The connector framework: one request helper (retries, rate limits, plain errors), raw answers kept on private repos,
and records rebuilt from them without calling the service again."""
from datetime import datetime, timezone

import httpx
import pytest

from stackvitals import connectors
from stackvitals.connectors import base, jira, pagerduty
from stackvitals.connectors.store import ConnectorStore
from stackvitals.core.config import parse
from test_connectors import JIRA_ENV, FakeJira, jira_cfg, jira_issue

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
PD_ENV = {"STACKVITALS_PAGERDUTY_TOKEN": "pd-secret"}


def answers(*responses):
    calls, queue = [], list(responses)

    def handle(request):
        calls.append(request)
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    return httpx.Client(transport=httpx.MockTransport(handle)), calls


def ask(client, sleeps):
    return base.request(client, "GET", "https://svc.example/x", "Svc", refused="check the SVC secret", sleep=sleeps.append)


def test_a_rate_limit_answer_is_waited_out_then_read():
    client, calls = answers(httpx.Response(429, headers={"retry-after": "7"}), httpx.Response(200, json={"ok": 1}))
    sleeps = []
    assert ask(client, sleeps) == {"ok": 1} and sleeps == [7.0] and len(calls) == 2


def test_a_long_rate_limit_wait_stops_for_the_next_run_instead():
    client, _ = answers(httpx.Response(429, headers={"retry-after": "3600"}))
    with pytest.raises(base.ConnectorError, match="rate limit"):
        ask(client, [])


def test_a_server_error_or_dropped_connection_is_tried_again():
    client, calls = answers(httpx.ConnectError("x"), httpx.Response(502), httpx.Response(200, json=[1]))
    sleeps = []
    assert base.request(client, "GET", "https://svc.example/x", "Svc", refused="r", sleep=sleeps.append,
                        kinds=(list,)) == [1]
    assert len(calls) == 3 and len(sleeps) == 2


def test_a_refused_key_and_other_answers_say_what_to_do():
    client, _ = answers(httpx.Response(401))
    with pytest.raises(base.ConnectorError, match=r"Svc refused the key \(401\): check the SVC secret"):
        ask(client, [])
    client, _ = answers(httpx.Response(404))
    with pytest.raises(base.ConnectorError, match="Svc answered 404"):
        ask(client, [])
    client, _ = answers(*[httpx.Response(503)] * 3)
    with pytest.raises(base.ConnectorError, match="Svc answered 503"):
        ask(client, [])


def pd_incident(n, created):
    return {"id": f"P{n}", "incident_number": n, "title": f"Down {n}", "status": "resolved", "urgency": "high",
            "created_at": created, "updated_at": created, "resolved_at": created, "service": {"summary": "api"},
            "html_url": f"https://acme.pagerduty.com/incidents/P{n}"}


def pd_client(pages):
    calls = []

    def handle(request):
        calls.append(request)
        k = int(request.url.params.get("offset", "0")) // pagerduty.PAGE
        return httpx.Response(200, json={"incidents": pages[k] if k < len(pages) else [], "more": k + 1 < len(pages)})
    return httpx.Client(transport=httpx.MockTransport(handle)), calls


def test_a_private_repo_keeps_each_answer_and_a_public_one_keeps_none(tmp_path):
    cfg = parse("")[0]
    client, _ = pd_client([[pd_incident(1, "2026-10-01T10:00:00Z")]])
    pagerduty.pull(ConnectorStore(tmp_path / "priv", "pagerduty"), PD_ENV, cfg, NOW, client=client)
    kept = list(ConnectorStore(tmp_path / "priv", "pagerduty").raw())
    assert kept and kept[0]["k"] == "incidents" and kept[0]["b"]["incidents"][0]["title"] == "Down 1"
    client, _ = pd_client([[pd_incident(1, "2026-10-01T10:00:00Z")]])
    pagerduty.pull(ConnectorStore(tmp_path / "pub", "pagerduty", redact=True), PD_ENV, cfg, NOW, client=client)
    assert list(ConnectorStore(tmp_path / "pub", "pagerduty").raw()) == []
    assert not (tmp_path / "pub" / "connectors" / "pagerduty" / "raw").exists()


@pytest.mark.parametrize("name", ["jira", "pagerduty"])
def test_records_are_rebuilt_from_kept_answers_with_no_new_reads(tmp_path, name):
    store = ConnectorStore(tmp_path, name)
    if name == "jira":
        fake = FakeJira([[jira_issue(1, "2026-09-05T10:00:00.000+0200")], [jira_issue(2, "2026-09-06T10:00:00.000+0200")]],
                        incidents=[jira_issue(7, "2026-10-02T10:00:00.000+0000", kind="Incident")])
        jira.pull(store, JIRA_ENV, jira_cfg(incident_jql="issuetype = Incident"), NOW, client=fake.client())
    else:
        client, _ = pd_client([[pd_incident(1, "2026-10-01T10:00:00Z")], [pd_incident(2, "2026-10-02T10:00:00Z")]])
        pagerduty.pull(store, PD_ENV, parse("")[0], NOW, client=client)
    store.compress("2026-10-22")
    before, state = store.load(), store.state()
    assert connectors.reprocess(tmp_path, name) > 0
    after = ConnectorStore(tmp_path, name)
    assert after.load() == before and after.state() == state


def test_a_new_record_shape_is_rebuilt_from_kept_answers_not_read_again(tmp_path, monkeypatch):
    client, calls = pd_client([[pd_incident(1, "2026-10-01T10:00:00Z")]])

    class Ws:
        path, notes, cache = tmp_path, [], {"settings": parse("")[0], "repo_info": {"private": True}}
    connectors.connectors_step(Ws, PD_ENV, NOW, clients={"pagerduty": client})
    assert ConnectorStore(tmp_path, "pagerduty").state()["raw_full"]
    first = len(calls)
    monkeypatch.setattr(connectors, "RECORDS", connectors.RECORDS + 1)
    monkeypatch.setattr(pagerduty, "_record", lambda i, f=pagerduty._record: {**f(i), "title": "NEW " + i["title"]})
    gone, _ = answers()  # any read now would fail: the queue is empty
    connectors.connectors_step(Ws, PD_ENV, NOW, clients={"pagerduty": pd_client([])[0]})
    titles = [i["title"] for i in ConnectorStore(tmp_path, "pagerduty").load()["issue"]]
    assert titles == ["NEW Down 1"] and len(calls) == first
    assert any("rebuilt from the answers it kept" in n for n in Ws.notes)


def test_settings_changes_or_a_store_without_full_answers_still_read_again(tmp_path):
    store = ConnectorStore(tmp_path, "pagerduty")
    store.add([{"t": "issue", "id": "pagerduty:old", "key": "PD-0"}], "2026-10-01")
    store.save_state({"since": "2026-10-01T00:00:00Z", "scope": "older"})

    class Ws:
        path, notes, cache = tmp_path, [], {"settings": parse("")[0], "repo_info": {"private": True}}
    client, calls = pd_client([[pd_incident(1, "2026-10-01T10:00:00Z")]])
    connectors.connectors_step(Ws, PD_ENV, NOW, clients={"pagerduty": client})
    assert calls and [i["key"] for i in ConnectorStore(tmp_path, "pagerduty").load()["issue"]] == ["PD-1"]
    assert "reads everything again" in Ws.notes[0]


def test_kept_answers_follow_the_record_files_retention(tmp_path):
    # Answers and records age out together, so a rebuild never loses a record the branch still keeps.
    from stackvitals.core.store import STREAMS
    for name in ("jira", "linear", "pagerduty", "incident_io"):
        assert STREAMS[f"connectors/{name}/raw"] == STREAMS[f"connectors/{name}/days"]


def test_asking_the_service_for_more_reads_again_even_with_every_answer_kept(tmp_path, monkeypatch):
    # Kept answers lack a field asked for only now, so they can't be rebuilt from.
    client, calls = pd_client([[pd_incident(1, "2026-10-01T10:00:00Z")]])

    class Ws:
        path, notes, cache = tmp_path, [], {"settings": parse("")[0], "repo_info": {"private": True}}
    connectors.connectors_step(Ws, PD_ENV, NOW, clients={"pagerduty": client})
    monkeypatch.setattr(pagerduty, "ASKED", getattr(pagerduty, "ASKED", 1) + 1, raising=False)
    monkeypatch.setattr(connectors, "RECORDS", connectors.RECORDS + 1)
    again, calls2 = pd_client([[pd_incident(1, "2026-10-01T10:00:00Z")]])
    connectors.connectors_step(Ws, PD_ENV, NOW, clients={"pagerduty": again})
    assert calls2 and any("reads everything again" in n for n in Ws.notes)
