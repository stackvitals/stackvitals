"""Targeted re-sync: read one connected service again from a chosen date, from the app (a request), an issue or a
`/stackvitals resync` comment, instead of resetting everything."""
import json
from datetime import datetime, timezone

import pytest

from stackvitals import connectors
from stackvitals.connectors.store import ConnectorStore
from stackvitals.core import decisions as dec

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def block(doc):
    return f"```stackvitals\n{json.dumps(doc)}\n```"


def test_a_request_names_the_services_and_the_date():
    req = dec.parse_request(block({"version": 1, "resync": [{"source": "jira", "since": "2026-09-01"}]}), NOW.date())
    assert req.resync == [{"source": "jira", "since": "2026-09-01"}]
    for bad in ([{"source": "jira"}], [{"source": "jira", "since": "soon"}], {"source": "jira"}, []):
        with pytest.raises(dec.CommandError, match="resync"):
            dec.parse_request(block({"version": 1, "resync": bad}), NOW.date())


def test_a_comment_asks_for_a_resync():
    from stackvitals.core.requests import _resync_command
    assert _resync_command("/stackvitals resync jira since 2026-09-01") == [{"source": "jira", "since": "2026-09-01"}]
    assert _resync_command("/stackvitals resync linear pagerduty") == [{"source": "linear", "since": None},
                                                                       {"source": "pagerduty", "since": None}]
    assert _resync_command("/stackvitals check jira") is None


def test_rewinding_keeps_what_the_framework_needs_and_drops_the_progress(tmp_path):
    store = ConnectorStore(tmp_path, "jira")
    store.save_state({"since": "2026-10-27T00:00:00Z", "incident_since": "2026-10-27T00:00:00Z", "resume": "2026/10/20 10:00",
                      "scope": "abc", "reads": "def", "raw_full": True})
    said = connectors.rewind(tmp_path, "jira", "2026-09-01", NOW)
    assert ConnectorStore(tmp_path, "jira").state() == {"since": "2026-09-01T00:00:00Z", "incident_since": "2026-09-01T00:00:00Z",
                                                        "scope": "abc", "reads": "def", "raw_full": True}
    assert said == "Jira reads again from 2026-09-01."


def test_no_date_or_one_too_old_reads_the_whole_window_and_a_future_one_is_refused(tmp_path):
    ConnectorStore(tmp_path, "linear").save_state({"since": "2026-10-27T00:00:00Z", "cursor": "x", "until": "y", "scope": "s"})
    assert connectors.rewind(tmp_path, "linear", None, NOW) == "Linear reads again from 180 days back."
    assert ConnectorStore(tmp_path, "linear").state() == {"scope": "s"}
    assert "180 days back" in connectors.rewind(tmp_path, "linear", "2020-01-01", NOW)
    with pytest.raises(connectors.ConnectorError, match="future"):
        connectors.rewind(tmp_path, "linear", "2026-11-30", NOW)


def test_chat_and_copilot_rewind_their_own_way(tmp_path):
    ConnectorStore(tmp_path, "slack").save_state({"backfilled": True, "scope": "s"})
    assert "180 days back" in connectors.rewind(tmp_path, "slack", "2026-10-01", NOW)
    assert ConnectorStore(tmp_path, "slack").state() == {"scope": "s"}
    ConnectorStore(tmp_path, "copilot").save_state({"through": "2026-10-26"})
    connectors.rewind(tmp_path, "copilot", "2026-10-01", NOW)
    assert ConnectorStore(tmp_path, "copilot").state() == {"through": "2026-09-30"}


def test_an_unknown_service_is_named_plainly(tmp_path):
    with pytest.raises(connectors.ConnectorError, match="nothing to read again"):
        connectors.rewind(tmp_path, "teams", None, NOW)


def test_a_dispatched_resync_rewinds_before_the_pull_and_answers(tmp_path, monkeypatch):
    from test_connector_checks import Service, _git_run
    from test_core_requests import GitHub

    import test_connector_checks as tc
    gh = GitHub(toml=tc.TOML)
    payload = {"inputs": {"request": json.dumps({"version": 1, "resync": [{"source": "jira", "since": "2026-09-01"}]})},
               "sender": {"login": "alice"}}
    seen = {}

    def seed(ws):
        ConnectorStore(ws.path, "jira").save_state({"since": "2026-10-27T00:00:00Z", "scope": "abc"})

    def look(ws):
        seen["state"] = ConnectorStore(ws.path, "jira").state()
    out, _seen, summary = _git_run(tmp_path, "workflow_dispatch", payload, gh, monkeypatch, Service(),
                                   before=[("Seed", seed)], later=[("Look state", look)])
    assert not {"Seed", "Requests", "Look state"} & set(out["errors"]) and out["results"]["Requests"]["resynced"] == 1
    assert seen["state"] == {"since": "2026-09-01T00:00:00Z", "incident_since": "2026-09-01T00:00:00Z", "scope": "abc"}
    assert "Jira reads again from 2026-09-01." in summary.read_text(encoding="utf-8")


def test_ci_rereads_its_days_from_the_date_and_fetches_only_missing_runs(tmp_path):
    from stackvitals.ci.store import DataStore
    from stackvitals.core import resync
    store = DataStore(tmp_path)
    store.save_state({"scanned": {"2026-08-30": "done", "2026-09-02": "done", "2026-10-27": "done"},
                      "scanned_tests": {"2026-09-02": "done"}, "last_collect": "x"})
    assert resync.rewind(tmp_path, "ci", "2026-09-01", NOW) == "CI Health reads its runs again from 2026-09-01."
    state = DataStore(tmp_path).state()
    assert state["scanned"] == {"2026-08-30": "done"} and state["scanned_tests"] == {} and state["last_collect"] == "x"


def test_team_flow_reads_pull_requests_updated_since_the_date(tmp_path):
    from stackvitals.core import resync
    from stackvitals.flow.store import FlowStore
    FlowStore(tmp_path).save_state({"synced_up_to": "2026-10-27T00:00:00Z", "schema": 9})
    assert "Team Flow reads pull requests updated since 2026-09-01" in resync.rewind(tmp_path, "flow", "2026-09-01", NOW)
    assert FlowStore(tmp_path).state()["synced_up_to"] == "2026-09-01T00:00:00Z"
    resync.rewind(tmp_path, "flow", None, NOW)
    assert "synced_up_to" not in FlowStore(tmp_path).state()


def test_a_connector_name_still_rewinds_the_connector(tmp_path):
    from stackvitals.core import resync
    assert resync.rewind(tmp_path, "Jira", "2026-09-01", NOW) == "Jira reads again from 2026-09-01."
