"""Decisions made on GitHub and the weekly rhythm: a request issue changes settings only for someone with write access,
a `/stackvitals` command is logged and reaches CI Health's quarantine list, and the digest goes out once a week."""
import base64
import json
import subprocess
from datetime import datetime, timezone

import httpx

from stackvitals.ci.api import ActionsAPI
from stackvitals.ci.automation import apply_decisions, quarantine_list
from stackvitals.core import decisions as dec
from stackvitals.core.config import parse
from stackvitals.core.workspace import run_job

NOW = datetime(2026, 10, 26, 9, tzinfo=timezone.utc)


class GitHub:
    def __init__(self, role="write"):
        self.role, self.toml, self.calls = role, "[alerts]\npickup_p75_hours = 4\n", []

    def handle(self, request):
        path, body = request.url.path, json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        if path.endswith("/permission"):
            return httpx.Response(200, json={"permission": "read", "role_name": self.role if "/alice/" in path else "read"})
        if path.endswith("/contents/.github/stackvitals.toml"):
            if request.method == "PUT":
                self.toml = base64.b64decode(body["content"]).decode()
                return httpx.Response(200, json={})
            if request.headers.get("accept") == "application/vnd.github.raw":
                return httpx.Response(200, content=self.toml.encode())
            return httpx.Response(200, json={"sha": "s", "content": base64.b64encode(self.toml.encode()).decode()})
        if path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main", "private": False, "has_pages": True})
        if path == "/repos/o/r/issues" and request.method == "POST":
            return httpx.Response(201, json={"number": 40, "node_id": "I"})
        return httpx.Response(200, json=[] if request.method == "GET" else {})

    def api(self):
        return lambda tok, repo, **kw: ActionsAPI(tok, repo, client=httpx.Client(transport=httpx.MockTransport(self.handle)),
                                                  sleep=lambda s: None, **kw)


def job(tmp_path, gh, event, payload, steps):
    from stackvitals.core.settings import prepare
    bare = tmp_path / "remote.git"
    if not bare.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    (tmp_path / "event.json").write_text(json.dumps(payload), encoding="utf-8")
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_EVENT_NAME": event, "GITHUB_EVENT_PATH": str(tmp_path / "event.json")}
    return run_job(env, [(label, (lambda fn: lambda ws: fn(ws, env))(fn)) for label, fn in steps], NOW,
                   prepare=prepare(env, make_api=gh.api()))


def request(author):
    block = json.dumps({"version": 1, "settings": {"alerts.pickup_p75_hours": 6}})
    return {"action": "opened", "issue": {"number": 12, "title": "StackVitals: settings", "user": {"login": author},
                                          "author_association": "OWNER", "body": f"```stackvitals\n{block}\n```"}}


def test_a_request_changes_settings_only_for_someone_with_write_access(tmp_path):
    from stackvitals.core.requests import requests_step
    stranger = GitHub()
    job(tmp_path / "a", stranger, "issues", request("mallory"), [("Requests", lambda ws, env: requests_step(ws, env, NOW, make_api=stranger.api()))])
    assert "= 4" in stranger.toml and any("write access" in (b or {}).get("body", "") for m, p, b in stranger.calls)
    seen, owner = {}, GitHub()
    job(tmp_path / "b", owner, "issues", request("alice"), [
        ("Requests", lambda ws, env: requests_step(ws, env, NOW, make_api=owner.api())),
        ("Check", lambda ws, env: seen.update(cfg=ws.cache["settings"], log=dec.Store(ws.path).log()))])
    assert "pickup_p75_hours = 6" in owner.toml and seen["cfg"]["alerts"]["pickup_p75_hours"] == 6.0
    assert seen["log"][0]["verb"] == "set" and seen["log"][0]["by"] == "alice"


def test_a_comment_command_is_logged_and_reaches_the_quarantine_list(tmp_path):
    from stackvitals.core.requests import requests_step
    gh, seen = GitHub(role="triage"), {}
    payload = {"action": "created", "issue": {"number": 5, "title": "Flaky test: t::slow", "labels": []},
               "comment": {"id": 1, "body": "/stackvitals quarantine for 14d because upstream bug",
                           "user": {"login": "alice"}, "author_association": "MEMBER"}}
    job(tmp_path, gh, "issue_comment", payload, [
        ("Requests", lambda ws, env: requests_step(ws, env, NOW, make_api=gh.api())),
        ("Check", lambda ws, env: seen.update(state=dec.Store(ws.path).state(NOW.date())))])
    result = {"tests": [{"id": "t::slow", "state": "ok"}], "jobs": []}
    apply_decisions(result, seen["state"])
    assert quarantine_list(result, parse("")[0], seen["state"]) == ["t::slow"]
    assert seen["state"]["test:t::slow"]["until"] == "2026-11-09" and seen["state"]["test:t::slow"]["reason"] == "upstream bug"


def test_the_digest_goes_out_once_a_week(tmp_path):
    from stackvitals.core.digest import digest_step
    gh = GitHub()

    def pages(ws, env):
        (ws.path / "docs").mkdir(exist_ok=True)
        (ws.path / "docs" / "flow.json").write_text(json.dumps({"schema": 1, "open": 2, "stale": 0}), encoding="utf-8")
    steps = [("Team Flow", pages), ("Digest", lambda ws, env: digest_step(ws, env, NOW, make_api=gh.api()))]
    first = job(tmp_path, gh, "schedule", {}, steps)
    second = job(tmp_path, gh, "schedule", {}, steps)
    assert first["results"]["Digest"]["week"] == "2026-W44" and second["results"]["Digest"] is None
    # The digest and its three pulse questions (on by default), once for the week.
    posted = [b["body"] for m, p, b in gh.calls if m == "POST" and p.endswith("/comments")]
    assert len(posted) == 4 and sum("stackvitals:pulse 2026-W44" in x for x in posted) == 3
