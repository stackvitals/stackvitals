"""Changes asked for on GitHub, applied by the Action: a request issue from the app changes settings and records
decisions, a `/stackvitals` comment records a decision, someone without access changes nothing, and every outcome is
answered on the issue (request issues are closed once applied)."""
import base64
import json
import subprocess
from datetime import datetime, timezone

import httpx

from stackvitals.ci.api import ActionsAPI
from stackvitals.core import decisions as dec
from stackvitals.core.workspace import run_job

NOW = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)
TOML = "[alerts]\npickup_p75_hours = 4\n"


class GitHub:
    """Contents, permissions, comments and issue edits, recorded."""

    def __init__(self, permission="write", protected=False, toml=TOML):
        self.permission, self.protected, self.toml, self.calls = permission, protected, toml, []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else None
        self.calls.append((method, path, body))
        if path.endswith("/collaborators/alice/permission") or path.endswith("/collaborators/mallory/permission"):
            # GitHub's legacy field maps triage to read and maintain to write; role_name holds the real role.
            role = self.permission if path.split("/")[-2] == "alice" else "read"
            legacy = {"triage": "read", "maintain": "write"}.get(role, role)
            return httpx.Response(200, json={"permission": legacy, "role_name": role})
        if path == "/repos/o/r/contents/.github/stackvitals.toml" and method == "GET":
            if request.headers.get("accept") == "application/vnd.github.raw":
                return httpx.Response(200, headers={"etag": '"x"'}, content=self.toml.encode())
            return httpx.Response(200, json={"sha": "abc", "content": base64.b64encode(self.toml.encode()).decode()})
        if path == "/repos/o/r/contents/.github/stackvitals.toml" and method == "PUT":
            if self.protected and body.get("branch") in (None, "main"):
                return httpx.Response(409, json={"message": "Repository rule violations found"})
            self.toml = base64.b64decode(body["content"]).decode()
            return httpx.Response(200, json={"commit": {"sha": "new"}})
        if path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main", "private": False})
        if path == "/repos/o/r/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "base"}})
        if path == "/repos/o/r/git/refs" and method == "POST":
            return httpx.Response(201, json={"ref": body["ref"]})
        if path == "/repos/o/r/pulls" and method == "POST":
            return httpx.Response(201, json={"number": 77, "html_url": "https://github.com/o/r/pull/77"})
        return httpx.Response(201 if method == "POST" else 200, json={})

    def api(self):
        return lambda tok, repo, **kw: ActionsAPI(tok, repo, client=httpx.Client(transport=httpx.MockTransport(self.handle)),
                                                  sleep=lambda s: None, **kw)


def run(tmp_path, event, payload, gh):
    from stackvitals.core.requests import requests_step
    bare = tmp_path / "remote.git"
    if not bare.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(payload), encoding="utf-8")
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_EVENT_NAME": event, "GITHUB_EVENT_PATH": str(event_file)}
    seen = {}

    def after(ws):
        seen["settings"] = ws.cache.get("settings")
        seen["state"] = dec.Store(ws.path).state(NOW.date())
    from stackvitals.core.settings import prepare
    out = run_job(env, [("Requests", lambda ws: requests_step(ws, env, NOW, make_api=gh.api())), ("Check", after)], NOW,
                  prepare=prepare(env, make_api=gh.api()))
    return out, seen


def request_issue(author="alice", association="OWNER", changes=(), settings=None):
    block = json.dumps({"version": 1, "changes": list(changes), "settings": settings or {}})
    return {"action": "opened", "issue": {"number": 12, "title": "StackVitals: change settings", "user": {"login": author},
                                          "author_association": association, "body": f"From the app.\n\n```stackvitals\n{block}\n```\n",
                                          "labels": []}}


def test_a_request_issue_changes_settings_records_decisions_answers_and_closes(tmp_path):
    gh = GitHub()
    out, seen = run(tmp_path, "issues", request_issue(
        changes=[{"verb": "quarantine", "kind": "test", "id": "t::a", "until": "2026-11-30", "reason": "upstream"}],
        settings={"alerts.pickup_p75_hours": 6}), gh)
    assert out["errors"] == {} and "pickup_p75_hours = 6" in gh.toml
    assert seen["settings"]["alerts"]["pickup_p75_hours"] == 6.0  # this job already runs on the new value
    assert seen["state"]["test:t::a"]["by"] == "alice" and seen["state"]["test:t::a"]["source"] == "issue #12"
    comments = [b["body"] for m, p, b in gh.calls if m == "POST" and p == "/repos/o/r/issues/12/comments"]
    assert comments and "pickup_p75_hours" in comments[0] and "t::a" in comments[0]
    assert not any(line.startswith("/stackvitals") for line in comments[0].splitlines())  # a reply never re-triggers
    assert ("PATCH", "/repos/o/r/issues/12", {"state": "closed", "state_reason": "completed"}) in gh.calls


def test_a_comment_command_on_a_flaky_issue_targets_its_test(tmp_path):
    gh = GitHub(permission="triage")
    payload = {"action": "created", "issue": {"number": 5, "title": "Flaky test: tests/api.py::test_retry", "labels": []},
               "comment": {"id": 99, "body": "/stackvitals mute for 7d because known network blip",
                           "user": {"login": "alice"}, "author_association": "MEMBER"}}
    _out, seen = run(tmp_path, "issue_comment", payload, gh)
    item = seen["state"]["test:tests/api.py::test_retry"]
    assert item["verb"] == "mute" and item["until"] == "2026-10-28" and item["source"] == "comment on #5"


def test_someone_without_access_changes_nothing_and_gets_told(tmp_path):
    gh = GitHub()
    _out, seen = run(tmp_path, "issues", request_issue(author="mallory", association="COLLABORATOR",
                                                      settings={"alerts.pickup_p75_hours": 99}), gh)
    assert gh.toml == TOML and seen["state"] == {}
    replies = [b["body"] for m, p, b in gh.calls if m == "POST" and p.endswith("/comments")]
    assert replies and "write access" in replies[0]
    assert not any(m == "PATCH" and b.get("state") == "closed" for m, p, b in gh.calls if b)


def test_triage_access_may_decide_but_not_change_settings(tmp_path):
    gh = GitHub(permission="triage")
    _out, seen = run(tmp_path, "issues", request_issue(settings={"alerts.pickup_p75_hours": 6}), gh)
    assert gh.toml == TOML and seen["settings"]["alerts"]["pickup_p75_hours"] == 4.0


def test_a_protected_branch_gets_a_pull_request_instead(tmp_path):
    gh = GitHub(protected=True)
    _out, seen = run(tmp_path, "issues", request_issue(settings={"alerts.pickup_p75_hours": 6}), gh)
    assert ("POST", "/repos/o/r/git/refs", {"ref": "refs/heads/stackvitals/settings-12", "sha": "base"}) in gh.calls
    assert any(m == "POST" and p == "/repos/o/r/pulls" for m, p, _ in gh.calls)
    replies = [b["body"] for m, p, b in gh.calls if m == "POST" and p.endswith("/comments")]
    assert "pull/77" in replies[0] and seen["settings"]["alerts"]["pickup_p75_hours"] == 4.0  # not merged yet


def test_a_value_the_parser_refuses_changes_nothing(tmp_path):
    gh = GitHub()
    run(tmp_path, "issues", request_issue(settings={"alerts.pickup_p75_hours": -1}), gh)
    replies = [b["body"] for m, p, b in gh.calls if m == "POST" and p.endswith("/comments")]
    assert gh.toml == TOML and replies and "nothing was changed" in replies[0].lower()


def test_closing_a_flaky_issue_as_not_planned_is_logged_as_acknowledged(tmp_path):
    gh = GitHub()
    payload = {"action": "closed", "sender": {"login": "alice"},
               "issue": {"number": 8, "title": "Flaky job: ci.yml / lint", "state_reason": "not_planned",
                         "labels": [{"name": "flaky-test"}]}}
    _out, seen = run(tmp_path, "issues", payload, gh)
    assert seen["state"]["job:ci.yml / lint"]["verb"] == "acknowledge"


def test_a_manual_run_carrying_a_request_applies_it_without_an_issue(tmp_path):
    gh = GitHub()
    block = json.dumps({"version": 1, "changes": [{"verb": "snooze", "kind": "finding", "id": "red_ci", "reason": ""}]})
    _out, seen = run(tmp_path, "workflow_dispatch", {"inputs": {"request": block}, "sender": {"login": "alice"}}, gh)
    assert seen["state"]["finding:red_ci"]["source"] == "manual run" and seen["state"]["finding:red_ci"]["by"] == "alice"
    assert not any(p.endswith("/comments") for m, p, _ in gh.calls)


def test_a_command_on_a_pull_request_targets_that_pull_request(tmp_path):
    gh = GitHub(permission="write")
    payload = {"action": "created", "issue": {"number": 31, "title": "Release 2.0", "pull_request": {"url": "x"}, "labels": []},
               "comment": {"id": 5, "body": "/stackvitals exclude because a release PR waits on purpose",
                           "user": {"login": "alice"}, "author_association": "OWNER"}}
    _out, seen = run(tmp_path, "issue_comment", payload, gh)
    assert seen["state"]["pr:31"]["verb"] == "exclude" and seen["state"]["pr:31"]["reason"] == "a release PR waits on purpose"


def test_settings_changes_are_logged_for_the_activity_view(tmp_path):
    gh = GitHub()
    _out, seen = run(tmp_path, "issues", request_issue(settings={"alerts.pickup_p75_hours": 6}), gh)
    row = seen["state"]["setting:alerts.pickup_p75_hours"]
    assert row["verb"] == "set" and row["by"] == "alice" and row["reason"] == "4.0 to 6"
    gh2 = GitHub(protected=True)
    _out, seen2 = run(tmp_path / "p", "issues", request_issue(settings={"alerts.pickup_p75_hours": 6}), gh2)
    assert "pull request" in seen2["state"]["setting:alerts.pickup_p75_hours"]["reason"]
