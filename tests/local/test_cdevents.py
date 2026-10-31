"""Phase 26 M2: deployments and incidents arrive as CDEvents or from Flux, and findings leave as CDEvents custom events
(CloudEvents to a URL, repository_dispatch to a repo); off until set, names and counts only, never for forks."""
import json
import re

import httpx

from stackvitals.core import events, recorded

SHA = "731f7eaddfb6af01cb2173e18f0f75b0ba780ef1"


def cdevent(kind, version="0.3.0", at="2026-10-29T09:00:00.123Z", subject="svc/api", content=None, custom=None):
    ev = {"context": {"specversion": "0.5.1", "id": f"ev-{kind}-{version}", "source": "/argocd/api",
                      "type": f"dev.cdevents.{kind}.{version}", "timestamp": at},
          "subject": {"id": subject, "source": "/argocd", "content": content or {"environment": {"id": "production"},
                                                                                  "artifactId": "pkg:oci/api@sha256:ab"}}}
    if custom:
        ev["customData"] = custom
    return {"action": ev["context"]["type"], "client_payload": ev}


def test_a_cdevent_deployment_of_either_spec_version_is_recorded_with_its_commit():
    for version in ("0.3.0", "0.2.0"):
        rec, why = recorded.from_event("repository_dispatch", cdevent("service.deployed", version, custom={"sha": SHA}))
        assert why is None and rec["kind"] == "deployment" and rec["state"] == "SUCCESS"
        assert rec["sha"] == SHA and rec["env"] == "production" and rec["done"] == "2026-10-29T09:00:00Z"
    rec, _ = recorded.from_event("repository_dispatch", cdevent("service.upgraded", content={"environment": {"id": "staging"}}))
    assert rec["env"] == "staging" and rec["sha"] is None


def test_a_rollback_counts_as_a_failed_deployment():
    rec, _ = recorded.from_event("repository_dispatch", cdevent("service.rolledback"))
    assert rec["kind"] == "deployment" and rec["state"] == "FAILURE"


def test_an_incident_detected_then_resolved_becomes_one_record(tmp_path):
    for kind, at in (("incident.detected", "2026-10-29T09:00:00Z"), ("incident.resolved", "2026-10-29T10:30:00Z")):
        rec, why = recorded.from_event("repository_dispatch", cdevent(kind, at=at, subject="INC-42"))
        assert why is None
        recorded.append(tmp_path, rec)
    [inc] = recorded.incidents(recorded.load(tmp_path))
    assert (inc["number"], inc["created"], inc["resolved"]) == ("INC-42", "2026-10-29T09:00:00Z", "2026-10-29T10:30:00Z")


def test_a_resolved_incident_never_seen_detected_is_kept_but_not_counted(tmp_path):
    rec, _ = recorded.from_event("repository_dispatch", cdevent("incident.resolved", subject="INC-7"))
    recorded.append(tmp_path, rec)
    assert recorded.incidents(recorded.load(tmp_path)) == []


def test_a_bad_cdevent_is_refused_with_what_to_fix():
    bad = cdevent("service.deployed", at="yesterday")
    assert "timestamp" in recorded.from_event("repository_dispatch", bad)[1]
    wrong = cdevent("service.deployed")
    wrong["client_payload"]["context"]["type"] = "dev.cdevents.service.published.0.3.0"
    assert "context.type" in recorded.from_event("repository_dispatch", wrong)[1]
    # Events nobody listens for (a pipeline run, a spec version we don't read) are left alone.
    assert recorded.from_event("repository_dispatch", {"action": "dev.cdevents.pipelinerun.finished.0.2.0"}) == (None, None)
    assert recorded.from_event("repository_dispatch", {"action": "dev.cdevents.service.deployed.0.9.0"}) == (None, None)


def flux(reason="ReconciliationSucceeded", severity="info", revision=f"main@sha1:{SHA}", env=None):
    meta = {"kustomize.toolkit.fluxcd.io/revision": revision, **({"environment": env} if env else {})}
    return {"action": "Kustomization/webapp.apps", "client_payload": {
        "involvedObject": {"kind": "Kustomization", "name": "webapp", "namespace": "apps"}, "metadata": meta,
        "severity": severity, "reason": reason, "message": "Reconciliation finished", "reportingController": "kustomize-controller",
        "timestamp": "2022-10-28T07:26:19Z"}}


def test_a_finished_flux_reconciliation_is_a_deployment_and_its_other_events_are_ignored():
    rec, why = recorded.from_event("repository_dispatch", flux())
    assert why is None and rec["sha"] == SHA and rec["tool"] == "flux" and rec["env"] == "production"
    assert recorded.from_event("repository_dispatch", flux(revision=f"main/{SHA}", env="staging"))[0]["env"] == "staging"
    assert recorded.from_event("repository_dispatch", flux("ValidationFailed", "error")) == (None, None)
    assert recorded.from_event("repository_dispatch", flux("Progressing")) == (None, None)


def test_the_workflow_listens_for_every_cdevent_type_it_reads():
    from stackvitals.ci.cli import WORKFLOW
    listed = set(re.findall(r"dev\.cdevents\.[a-z.]+\.\d\.\d\.\d", WORKFLOW))
    wanted = {f"dev.cdevents.{k}.{v}" for k in ("service.deployed", "service.upgraded", "service.rolledback",
                                                 "incident.detected", "incident.resolved") for v in ("0.3.0", "0.2.0")}
    assert listed == wanted and all(recorded.CDEVENT.match(t) for t in wanted)


# Out: findings as events.
CUSTOM = re.compile(r"^dev\.cdeventsx\.[a-zA-Z0-9]+-[a-zA-Z]+\.[a-zA-Z]+\.[0-9]\.[0-9]\.[0-9]$")  # CDEvents custom/schema.json


def test_each_finding_is_a_valid_cdevents_custom_event_in_cloudevents_form():
    at = "2026-11-01T06:00:00Z"
    evs = (events.alerts([{"metric": "pickup_p75_hours", "level": "miss", "value": 9.5, "limit": 4.0, "n": 31}], "o/r", at)
           + events.newly_flaky(["tests/test_api.py::test_login"], "o/r", at)
           + [events.pr_verdict(12, "abc1234", [{"kind": "test", "name": "t::race", "verdict": "new"}], "o/r", at)])
    for ev in evs:
        ctx = ev["context"]
        assert CUSTOM.match(ctx["type"]) and {"specversion", "id", "source", "type", "timestamp"} <= set(ctx)
        assert {"id", "content"} <= set(ev["subject"])
        ce = events.cloudevent(ev)
        assert ce["specversion"] == "1.0" and ce["type"] == ctx["type"] and ce["time"] == at and ce["data"] == ev
        assert len(events.dispatch_body(ev)["client_payload"]) <= 10
    assert events.alerts([{"metric": "m", "level": "miss", "value": 1, "limit": 0, "n": 1}], "o/r", at)[0]["context"]["id"] == \
        events.alerts([{"metric": "m", "level": "miss", "value": 1, "limit": 0, "n": 1}], "o/r", at)[0]["context"]["id"]


def test_a_verdict_event_carries_inert_names_and_no_log_text():
    item = {"kind": "job", "name": "CI / see [here](https://evil.example) `x`", "verdict": "known flaky",
            "detail": "the log said: secret stuff"}
    ev = events.pr_verdict(3, "abc1234", [item], "o/r", "2026-11-01T06:00:00Z")
    text = json.dumps(ev)
    assert "secret stuff" not in text and "https://evil" not in text and "`" not in ev["subject"]["content"]["failures"][0]["name"]
    assert ev["subject"]["content"]["blocking"] == 0 and ev["subject"]["content"]["verdicts"] == {"known flaky": 1}


def capture(status=202):
    sent = []

    def handler(request):
        sent.append((str(request.url), request.headers.get("content-type"), request.headers.get("authorization"),
                     json.loads(request.content)))
        return httpx.Response(204 if "api.github.com" in str(request.url) else status)
    return sent, httpx.Client(transport=httpx.MockTransport(handler))


def test_nothing_is_sent_until_a_url_or_dispatch_repo_is_set():
    sent, client = capture()
    ev = events.newly_flaky(["t::x"], "o/r", "2026-11-01T06:00:00Z")
    assert events.send(ev, {"events": {"send": list(events.KINDS), "dispatch_repo": ""}}, {}, client) == []
    # A dispatch repo without its token sends nothing either.
    assert events.send(ev, {"events": {"send": list(events.KINDS), "dispatch_repo": "o/hub"}}, {}, client) == []
    assert sent == []


def test_events_go_to_the_url_as_cloudevents_and_to_the_dispatch_repo():
    sent, client = capture()
    ev = events.newly_flaky(["t::x"], "o/r", "2026-11-01T06:00:00Z")
    cfg = {"events": {"send": ["newly_flaky"], "dispatch_repo": "o/hub"}}
    env = {"STACKVITALS_EVENTS_URL": "https://collector.example/cdevents\n", "STACKVITALS_EVENTS_TOKEN": "tok"}
    assert events.send(ev, cfg, env, client) == []
    (url, ctype, auth, body), (durl, _, dauth, dbody) = sent
    assert url == "https://collector.example/cdevents" and ctype == "application/cloudevents+json" and auth is None
    assert body["specversion"] == "1.0" and body["data"]["context"]["type"] == events.TYPES["newly_flaky"]
    assert durl.endswith("/repos/o/hub/dispatches") and dauth == "Bearer tok"
    assert dbody["event_type"] == events.TYPES["newly_flaky"]
    # A kind left out of send stays home; a failing receiver is a note, never an error.
    assert events.send(events.alerts([{"metric": "m", "level": "miss", "value": 1, "limit": 0, "n": 1}], "o/r", "x"),
                       cfg, env, client) == [] and len(sent) == 2
    sent, client = capture(status=500)
    assert "events URL" in events.send(ev, {"events": {"send": ["newly_flaky"], "dispatch_repo": ""}},
                                       {"STACKVITALS_EVENTS_URL": "https://collector.example/"}, client)[0]


def test_settings_check_the_dispatch_repo_and_kinds():
    from stackvitals.core.config import parse
    cfg, notes = parse('[events]\nsend = ["pr_verdict"]\ndispatch_repo = "acme/platform-hub"\n')
    assert cfg["events"] == {"send": ["pr_verdict"], "dispatch_repo": "acme/platform-hub"} and notes == []
    cfg, notes = parse('[events]\nsend = ["everything"]\ndispatch_repo = "not a repo"\n')
    assert cfg["events"]["dispatch_repo"] == "" and len(notes) == 2


def test_a_verdict_event_goes_out_once_for_the_triggering_run_and_never_for_a_fork(monkeypatch):
    from stackvitals.ci.action import _pr_feedback

    class ChecksApi:
        repo = "o/r"

        def _get(self, path, params=None, raw=False):
            return b"##[group]Run tests\nAssertionError: 1 != 2\n" if raw else {"workflow_runs": []} if path.endswith("/runs") else []

        def send(self, method, path, body=None):
            return {}
    calls = []
    monkeypatch.setattr(events, "send", lambda evs, settings, env=None, client=None: calls.append(evs) or [])

    def run(owner):
        runs = [{"id": 5, "att": 1, "ev": "pull_request", "c": "failure", "sha": "abc1234", "pr": [7], "ho": owner,
                 "br": "fix", "wfn": "CI", "path": ".github/workflows/ci.yml", "cr": "2026-11-01T05:00:00Z"}]
        jobs = [{"run": 5, "att": 1, "id": 51, "n": "test", "c": "failure", "steps": [[3, "Run tests", "failure"]],
                 "en": "2026-11-01T05:05:00Z"}]
        payload = {"workflow_run": {"id": 5, "pull_requests": [{"number": 7}]}}
        _pr_feedback(runs, {5: runs[0]}, payload, ChecksApi(), {"runs": runs, "jobs": jobs, "tests": []},
                     {"jobs": [], "tests": []}, "o/r", comments=False, verdict=True, notes=[], settings={})
    run("o")
    assert len(calls) == 1 and calls[0][0]["subject"]["id"] == "o/r/pull/7"
    run("forker")
    assert len(calls) == 1


def test_the_docs_cdevents_recipe_for_argo_cd_sends_an_event_that_is_read():
    from pathlib import Path
    doc = (Path(__file__).resolve().parents[2] / "docs" / "connectors.md").read_text(encoding="utf-8")
    body = re.search(r'(\{"event_type":"dev\.cdevents\.service\.deployed\.0\.3\.0".*\}\}\})', doc).group(1)
    filled = (body.replace("{{.app.metadata.name}}", "web").replace("{{.app.status.operationState.syncResult.revision}}", SHA)
              .replace("{{.app.status.operationState.finishedAt}}", "2026-10-29T10:00:00Z"))
    payload = json.loads(filled)
    rec, why = recorded.from_event("repository_dispatch", {"action": payload["event_type"], "client_payload": payload["client_payload"]})
    assert why is None and rec["sha"] == SHA and rec["env"] == "production" and rec["kind"] == "deployment"


def test_the_short_setup_file_still_listens_for_our_own_events():
    import yaml
    from stackvitals.ci.cli import workflow_template
    small = yaml.safe_load(workflow_template(names=["CI"], compact=True))
    full = yaml.safe_load(workflow_template(names=["CI"]))
    on = lambda w: w.get("on") or w.get(True)  # noqa: E731 - YAML 1.1 reads a bare "on" as True
    assert on(small)["repository_dispatch"]["types"] == ["stackvitals-deployment", "stackvitals-incident"]
    assert len(on(full)["repository_dispatch"]["types"]) == 12
