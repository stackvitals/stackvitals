"""Deployments and incidents pushed from any tool through repository_dispatch, kept on the data branch and counted by
Delivery like GitHub's own (DevLake's webhook plugin, with GitHub as the receiver)."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from stackvitals.core import delivery, recorded
from stackvitals.core.config import parse as parse_cfg

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def event(action, **payload):
    return {"action": action, "client_payload": payload}


def test_a_deployment_event_is_kept_and_a_later_one_with_the_same_id_updates_it(tmp_path):
    ws = SimpleNamespace(path=tmp_path)
    for status in ("failure", "success"):
        (tmp_path / "ev.json").write_text(json.dumps(event("stackvitals-deployment", id="argo-42", sha="abc1234",
                                                           finished_at="2026-10-28T10:00:00+02:00", status=status, tool="argo-cd")))
        out = recorded.record_step(ws, {"GITHUB_EVENT_NAME": "repository_dispatch", "GITHUB_EVENT_PATH": str(tmp_path / "ev.json")}, NOW)
        assert out["recorded"] == "deployment"
    got = recorded.load(tmp_path)["deployments"]
    assert len(got) == 1 and got[0]["state"] == "SUCCESS" and got[0]["done"] == "2026-10-28T08:00:00Z"


def test_bad_payloads_are_refused_with_what_to_fix():
    assert recorded.from_event("repository_dispatch", event("stackvitals-deployment", finished_at="2026-10-28T10:00:00Z"))[1].startswith("an id")
    assert "finished_at" in recorded.from_event("repository_dispatch", event("stackvitals-deployment", id="1", finished_at="yesterday"))[1]
    assert "sha" in recorded.from_event("repository_dispatch", event("stackvitals-deployment", id="1", sha="main",
                                                                      finished_at="2026-10-28T10:00:00Z"))[1]
    assert recorded.from_event("push", {"action": "x"}) == (None, None)
    assert recorded.from_event("repository_dispatch", {"action": "other"}) == (None, None)


def test_delivery_counts_recorded_production_deployments_and_incidents():
    cfg = parse_cfg("")[0]
    rec = {"deployments": [{"kind": "deployment", "id": "j1", "env": "production", "sha": "abc1234", "at": "2026-10-20T10:00:00Z",
                            "done": "2026-10-20T10:00:00Z", "state": "SUCCESS"},
                           {"kind": "deployment", "id": "j2", "env": "staging", "sha": "abc1235", "at": "2026-10-21T10:00:00Z",
                            "done": "2026-10-21T10:00:00Z", "state": "SUCCESS"}],
           "incidents": [{"kind": "incident", "id": "pd-9", "created": "2026-10-20T12:00:00Z", "resolved": "2026-10-20T14:00:00Z"}]}
    deps, source = delivery.find_deployments({"recorded": rec}, {}, cfg)
    assert [d["sha"] for d in deps] == ["abc1234"] and source == "deployments api"
    incs, said = delivery.incidents_for([], [], deps, cfg, None, recorded=rec)
    assert [i["number"] for i in incs] == ["pd-9"] and incs[0]["hours_to_restore"] == 4.0 and "recorded" in said


def test_the_record_command_sends_a_dispatch_body():
    body = recorded.dispatch_body("deployment", {"id": "1", "sha": "abc1234", "finished_at": "2026-10-28T10:00:00Z", "tool": None})
    assert body == {"event_type": "stackvitals-deployment", "client_payload": {"id": "1", "sha": "abc1234",
                                                                                "finished_at": "2026-10-28T10:00:00Z"}}


def test_record_command_checks_then_sends(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    sent = []
    assert recorded.main(["deployment", "o/r", "--id", "9", "--sha", "abc1234", "--at", "2026-10-28T10:00:00Z"],
                         post=lambda url, body: sent.append((url, body)) or 204) == 0
    assert sent[0][0].endswith("/repos/o/r/dispatches") and sent[0][1]["event_type"] == "stackvitals-deployment"
    assert recorded.main(["deployment", "o/r", "--id", "9", "--sha", "main"], post=lambda u, b: 204) == 2
    assert "sha" in capsys.readouterr().err


def test_the_argo_cd_recipe_in_the_docs_sends_a_payload_that_is_accepted():
    import re
    from pathlib import Path
    doc = (Path(__file__).resolve().parents[2] / "docs" / "connectors.md").read_text(encoding="utf-8")
    body = re.search(r'(\{"event_type":"stackvitals-deployment".*\}\})', doc.split("**Argo CD**")[1]).group(1)
    filled = (body.replace("{{.app.metadata.name}}", "web").replace("{{.app.status.operationState.syncResult.revision}}", "a" * 40)
              .replace("{{.app.status.operationState.finishedAt}}", "2026-10-29T10:00:00Z"))
    payload = json.loads(filled)
    rec, why = recorded.from_event("repository_dispatch", {"action": payload["event_type"], "client_payload": payload["client_payload"]})
    assert why is None and rec["sha"] == "a" * 40 and rec["env"] == "production"
