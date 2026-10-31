"""Test connection: one cheap call per connector proves the key and its scope work, failures read as plain sentences with
a next step, the app asks for checks through a request and reads them back from connectors.json, and no key is ever
written or printed."""
import json
import subprocess
from datetime import datetime, timezone

import httpx
import pytest

from stackvitals.connectors import check
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 24, 9, tzinfo=timezone.utc)
SECRETS = {"STACKVITALS_JIRA_TOKEN": "sek-jira-111", "STACKVITALS_JIRA_EMAIL": "me@acme.com",
           "STACKVITALS_LINEAR_TOKEN": "sek-linear-222", "STACKVITALS_PAGERDUTY_TOKEN": "sek-pd-333",
           "STACKVITALS_INCIDENT_IO_TOKEN": "sek-iio-444", "STACKVITALS_SLACK_TOKEN": "sek-slack-555",
           "STACKVITALS_DISCORD_TOKEN": "sek-discord-666", "STACKVITALS_COPILOT_TOKEN": "sek-copilot-777",
           "STACKVITALS_WEBHOOK": "https://hooks.slack.com/services/T0/B0/sek-hook-888",
           "STACKVITALS_TEAM_WEBHOOKS": "@o/web = https://discord.com/api/webhooks/1/sek-teamhook-999",
           "GITLAB_TOKEN": "sek-gitlab-aaa", "CI_PROJECT_PATH": "grp/proj", "STACKVITALS_TRIAGE_KEY": "sek-triage-bbb",
           "STACKVITALS_STORAGE": "s3://bucket/sv", "STACKVITALS_S3_ENDPOINT": "https://s3.example.com",
           "STACKVITALS_S3_KEY_ID": "AKIDsekccc", "STACKVITALS_S3_SECRET": "sek-s3-ddd", "GITHUB_REPOSITORY": "o/r"}
FAKE = [v for k, v in SECRETS.items() if "sek" in v]
TOML = """[connectors.jira]
url = "https://acme.atlassian.net"
scope_jql = "project = WEB"
[connectors.linear]
teams = ["ENG"]
[connectors.pagerduty]
services = ["PSVC1"]
[connectors.slack]
channels = ["C123"]
[connectors.discord]
channels = ["999"]
[connectors.discourse]
url = "https://discuss.example.org"
[ci.triage]
provider = "gemini"
"""
CFG = parse(TOML)[0]


class Service:
    """Every outside service in one fake transport; `fail` maps a host (or host+path start) to a status or an error."""

    def __init__(self, fail=None):
        self.fail, self.calls = fail or {}, []

    def handle(self, req: httpx.Request) -> httpx.Response:
        host, path = req.url.host, req.url.path
        self.calls.append((req.method, host, path))
        for key, what in self.fail.items():
            if key == host or (host + path).startswith(key):
                if what == "down":
                    raise httpx.ConnectError("refused", request=req)
                if isinstance(what, int):
                    return httpx.Response(what, json={"errorMessages": ["no"], "message": "no"})
                return what(req)
        if host == "acme.atlassian.net":
            if path == "/rest/api/3/myself":
                return httpx.Response(200, json={"displayName": "Ana Bot", "emailAddress": "me@acme.com"})
            return httpx.Response(200, json={"issues": [{"id": "1", "key": "WEB-7"}], "isLast": True})
        if host == "api.linear.app":
            keys = ["ENG", "OPS"]
            asked = [k.upper() for k in (json.loads(req.content).get("variables") or {}).get("keys") or []]
            return httpx.Response(200, json={"data": {"viewer": {"name": "Lin"}, "organization": {"name": "Acme"},
                                                      "teams": {"nodes": [{"key": k} for k in keys],
                                                                "pageInfo": {"hasNextPage": False}},
                                                      "wanted": {"nodes": [{"key": k} for k in keys if k in asked]}}})
        if host == "api.pagerduty.com":
            if path.startswith("/services/"):
                return httpx.Response(200, json={"service": {"id": "PSVC1", "name": "web"}})
            return httpx.Response(200, json={"incidents": [{"id": "Q1"}], "more": False})
        if host == "api.incident.io":
            return httpx.Response(200, json={"incidents": [{"id": "01"}], "pagination_meta": {}})
        if host == "slack.com":
            if path.endswith("auth.test"):
                return httpx.Response(200, json={"ok": True, "user": "svbot", "team": "Acme"})
            return httpx.Response(200, json={"ok": True, "messages": []})
        if host == "discord.com":
            if path.endswith("/users/@me"):
                return httpx.Response(200, json={"id": "1", "username": "svbot"})
            if "/webhooks/" in path:
                return httpx.Response(204)
            return httpx.Response(200, json=[])
        if host == "hooks.slack.com":
            return httpx.Response(200, text="ok")
        if host == "discuss.example.org":
            return httpx.Response(200, json={"topic_list": {"topics": [{"id": 1}, {"id": 2}]}})
        if host == "gitlab.com":
            if path.endswith("/personal_access_tokens/self"):
                return httpx.Response(200, json={"name": "sv", "active": True, "scopes": ["api", "write_repository"]})
            return httpx.Response(200, json={"path_with_namespace": "grp/proj", "default_branch": "main"})
        if host == "generativelanguage.googleapis.com":
            return httpx.Response(200, json={"data": [{"id": "models/gemini-3.5-flash-lite"}, {"id": "models/x"}]})
        if host == "s3.example.com":
            if req.method == "GET":
                return httpx.Response(200, text="<ListBucketResult></ListBucketResult>")
            return httpx.Response(204 if req.method == "DELETE" else 200)
        if host == "api.github.com":
            return httpx.Response(200, json={"download_links": ["https://files.example/x"]})
        return httpx.Response(599)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handle))


def run(name, fail=None, env=None, cfg=CFG):
    svc = Service(fail)
    return check.check(name, cfg, {**SECRETS, **(env or {})}, client=svc.client(), now=NOW), svc


ALL = ("jira", "linear", "pagerduty", "incident_io", "slack", "discord", "discourse", "webhook", "gitlab", "s3", "triage",
       "copilot")


@pytest.mark.parametrize("name", ALL)
def test_every_connector_passes_with_a_working_key_and_never_echoes_it(name):
    got, svc = run(name)
    assert got["ok"] is True, got
    assert set(got) >= {"ok", "as", "detail", "checked_at", "fix"} and got["fix"] is None
    assert got["checked_at"] == "2026-10-24T09:00:00Z" and got["detail"].endswith(".")
    assert not any(s in json.dumps(got) for s in FAKE)
    assert svc.calls  # it really asked the service


def test_what_each_check_says_and_calls():
    got, svc = run("jira")
    assert got["as"] == "Ana Bot" and "WEB" in got["detail"]
    assert ("GET", "acme.atlassian.net", "/rest/api/3/search/jql") in svc.calls
    got, _ = run("slack")
    assert got["as"] == "svbot in Acme" and "1 channel" in got["detail"]
    got, _ = run("linear")
    assert got["as"] == "Lin (Acme)" and "ENG" in got["detail"]
    got, _ = run("discourse")
    assert got["as"] is None and "no key" in got["detail"].lower()
    got, svc = run("webhook")
    assert "test message" in got["detail"] and got["as"] == "Slack webhook, 1 team webhook"
    assert [c for c in svc.calls if c[0] == "POST"] and len([c for c in svc.calls if c[0] == "POST"]) == 2
    got, svc = run("s3")
    # A list first, then one tiny object written and removed again under the prefix.
    assert [c[0] for c in svc.calls] == ["GET", "PUT", "DELETE"] and svc.calls[1][2] == "/bucket/sv/.stackvitals-check"
    got, _ = run("triage")
    assert "gemini-3.5-flash-lite" in got["detail"]


def test_the_webhook_message_is_clearly_a_test():
    seen = []

    def hook(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, text="ok")
    run("webhook", fail={"hooks.slack.com": hook})
    assert "StackVitals connection test" in json.dumps(seen[0])


@pytest.mark.parametrize("name,env_key,secret", [
    ("jira", "STACKVITALS_JIRA_TOKEN", "JIRA_API_TOKEN"), ("linear", "STACKVITALS_LINEAR_TOKEN", "LINEAR_API_KEY"),
    ("pagerduty", "STACKVITALS_PAGERDUTY_TOKEN", "PAGERDUTY_API_KEY"),
    ("incident_io", "STACKVITALS_INCIDENT_IO_TOKEN", "INCIDENT_IO_API_KEY"),
    ("slack", "STACKVITALS_SLACK_TOKEN", "SLACK_BOT_TOKEN"), ("discord", "STACKVITALS_DISCORD_TOKEN", "DISCORD_BOT_TOKEN"),
    ("webhook", "STACKVITALS_WEBHOOK", "STACKVITALS_WEBHOOK"), ("gitlab", "GITLAB_TOKEN", "GITLAB_TOKEN"),
    ("s3", "STACKVITALS_S3_SECRET", "s3-secret"), ("triage", "STACKVITALS_TRIAGE_KEY", "triage-key"),
    ("copilot", "STACKVITALS_COPILOT_TOKEN", "copilot-token")])
def test_a_missing_secret_names_the_secret_to_add(name, env_key, secret):
    env = {env_key: ""}
    if name == "webhook":
        env["STACKVITALS_TEAM_WEBHOOKS"] = ""
    got, svc = run(name, env=env)
    assert got["ok"] is False and secret in got["fix"] and not svc.calls


@pytest.mark.parametrize("name,host", [
    ("jira", "acme.atlassian.net"), ("linear", "api.linear.app"), ("pagerduty", "api.pagerduty.com"),
    ("incident_io", "api.incident.io"), ("discord", "discord.com"), ("gitlab", "gitlab.com"), ("s3", "s3.example.com"),
    ("triage", "generativelanguage.googleapis.com"), ("copilot", "api.github.com")])
def test_a_refused_key_says_wrong_or_expired_and_a_403_says_permission(name, host):
    got, _ = run(name, fail={host: 401})
    assert got["ok"] is False and ("wrong or expired" in got["detail"] or "refused" in got["detail"]) and got["fix"]
    got, _ = run(name, fail={host: 403})
    assert got["ok"] is False and ("permission" in got["detail"] or "scope" in got["detail"]) and got["fix"]


@pytest.mark.parametrize("name,host", [
    ("jira", "acme.atlassian.net"), ("pagerduty", "api.pagerduty.com"), ("discord", "discord.com"), ("gitlab", "gitlab.com"),
    ("s3", "s3.example.com"), ("copilot", "api.github.com"), ("discourse", "discuss.example.org"),
    ("webhook", "hooks.slack.com")])
def test_a_404_points_at_the_wrong_site_team_service_or_channel(name, host):
    got, _ = run(name, fail={host: 404})
    assert got["ok"] is False and "404" in got["detail"] and got["fix"]


@pytest.mark.parametrize("name,host", [(n, h) for n, h in [
    ("jira", "acme.atlassian.net"), ("linear", "api.linear.app"), ("slack", "slack.com"), ("discourse", "discuss.example.org"),
    ("incident_io", "api.incident.io"), ("webhook", "hooks.slack.com")]])
def test_a_service_that_is_down_or_unreachable_says_try_again(name, host):
    for what in ("down", 503):
        got, svc = run(name, fail={host: what})
        assert got["ok"] is False and "try again" in (got["fix"] or "").lower(), got
    # One retry at most on a network error or a 5xx.
    assert len([c for c in svc.calls if c[1] == host]) <= 2


def test_slack_and_discord_name_the_channel_the_bot_cannot_read():
    got, _ = run("slack", fail={"slack.com/api/conversations.history": lambda r: httpx.Response(
        200, json={"ok": False, "error": "not_in_channel"})})
    assert got["ok"] is False and "C123" in got["detail"] and "/invite" in got["fix"]
    got, _ = run("slack", fail={"slack.com/api/auth.test": lambda r: httpx.Response(
        200, json={"ok": False, "error": "invalid_auth"})})
    assert got["ok"] is False and "wrong or expired" in got["detail"]
    got, _ = run("slack", fail={"slack.com/api/conversations.history": lambda r: httpx.Response(
        200, json={"ok": False, "error": "missing_scope", "needed": "channels:history"})})
    assert "channels:history" in got["detail"] + got["fix"]
    got, _ = run("discord", fail={"discord.com/api/v10/channels/999": 403})
    assert got["ok"] is False and "999" in got["detail"] and "Read Message History" in got["fix"]


def test_linear_names_a_team_the_key_cannot_see_and_jira_a_bad_query():
    got, _ = run("linear", cfg=parse('[connectors.linear]\nteams = ["NOPE"]\n')[0])
    assert got["ok"] is False and "NOPE" in got["detail"] and "teams" in got["fix"]
    got, _ = run("linear", fail={"api.linear.app": lambda r: httpx.Response(
        200, json={"errors": [{"message": "auth", "extensions": {"code": "AUTHENTICATION_ERROR"}}]})})
    assert got["ok"] is False and "wrong or expired" in got["detail"]
    got, _ = run("jira", fail={"acme.atlassian.net/rest/api/3/search": lambda r: httpx.Response(
        400, json={"errorMessages": ["Field 'projekt' does not exist"]})})
    assert got["ok"] is False and "scope_jql" in got["fix"] and "projekt" in got["detail"]


def test_jira_without_a_site_says_where_to_set_it():
    got, svc = run("jira", cfg=parse("")[0])
    assert got["ok"] is False and "[connectors.jira]" in got["fix"] and not svc.calls


def test_a_bug_in_a_check_is_a_failed_check_not_a_crash(monkeypatch):
    monkeypatch.setitem(check.CHECKS, "jira", lambda *a, **k: 1 / 0)
    got, _ = run("jira")
    assert got["ok"] is False and "ZeroDivisionError" in got["detail"]


def test_resolve_takes_all_names_and_aliases_and_refuses_unknown_ones():
    assert check.resolve("all", CFG, SECRETS) == list(ALL[:7]) + ["webhook", "gitlab", "s3", "triage", "copilot"] or \
        set(check.resolve("all", CFG, SECRETS)) == set(ALL)
    assert check.resolve(["chat", "incident.io"], CFG, SECRETS) == ["webhook", "incident_io"]
    assert check.resolve("all", parse("")[0], {}) == []
    with pytest.raises(ValueError, match="nosuch"):
        check.resolve(["nosuch"], CFG, SECRETS)


def test_results_land_under_each_entry_keep_other_fields_and_drop_names_in_a_public_repo(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "connectors.json").write_text(json.dumps({"schema": 1, "connectors": {"jira": {
        "name": "Jira", "rows": {"issue": 4}, "error": None}}}), encoding="utf-8")
    results = {"jira": run("jira")[0], "s3": run("s3")[0]}
    check.save(tmp_path, results, public=True)
    doc = json.loads((docs / "connectors.json").read_text(encoding="utf-8"))
    assert doc["connectors"]["jira"]["rows"] == {"issue": 4} and doc["connectors"]["jira"]["check"]["ok"] is True
    assert doc["connectors"]["jira"]["check"]["as"] is None  # a person's name never goes on a public branch
    assert doc["connectors"]["s3"] == {"name": "Bucket storage", "check": {**results["s3"], "as": None}}
    check.save(tmp_path, results, public=False)
    doc = json.loads((docs / "connectors.json").read_text(encoding="utf-8"))
    assert doc["connectors"]["jira"]["check"]["as"] == "Ana Bot"


def test_a_pull_keeps_the_last_check_results(tmp_path):
    from stackvitals.connectors import connectors_step
    ws = Ws(tmp_path, CFG)
    check.save(tmp_path, {"jira": run("jira")[0], "webhook": run("webhook")[0]}, public=True)
    connectors_step(ws, {"STACKVITALS_JIRA_TOKEN": "t", "STACKVITALS_JIRA_EMAIL": "a@b.c"}, NOW, clients={"jira": _jira(200)})
    conn = json.loads((tmp_path / "docs" / "connectors.json").read_text(encoding="utf-8"))["connectors"]
    assert conn["jira"]["check"]["ok"] is True and conn["jira"]["rows"]["issue"] == 1
    assert conn["webhook"]["check"]["ok"] is True


class Ws:
    def __init__(self, path, settings):
        self.path, self.cache, self.notes, self.hooks = path, {"settings": settings}, [], []

    def after_commit(self, fn, label="", first=False):
        self.hooks.append(fn)


def _jira(status):
    def handle(request):
        if request.url.path == "/rest/api/3/field":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"isLast": True, "issues": [
            {"id": "1", "key": "WEB-1", "fields": {"summary": "x", "issuetype": {"name": "Bug"},
             "status": {"name": "Done", "statusCategory": {"key": "done"}}, "created": "2026-10-01T10:00:00.000+0000",
             "updated": "2026-10-02T10:00:00.000+0000", "resolutiondate": "2026-10-02T10:00:00.000+0000"}}]})
    return httpx.Client(transport=httpx.MockTransport(handle), base_url="https://acme.atlassian.net")


# The request path, end to end.

def _git_run(tmp_path, event, payload, gh, monkeypatch, svc, before=(), later=()):
    from stackvitals.core.requests import requests_step
    from stackvitals.core.settings import prepare
    from stackvitals.core.workspace import run_job
    monkeypatch.setattr(check, "TRANSPORT", httpx.MockTransport(svc.handle))
    bare = tmp_path / "remote.git"
    if not bare.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(payload), encoding="utf-8")
    summary = tmp_path / "summary.md"
    # The job keeps its history in git here, so the bucket isn't one of the services tested.
    env = {**{k: v for k, v in SECRETS.items() if k != "STACKVITALS_STORAGE"}, "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(), "RUNNER_TEMP": str(tmp_path / "tmp"),
           "GITHUB_EVENT_NAME": event, "GITHUB_EVENT_PATH": str(event_file), "GITHUB_STEP_SUMMARY": str(summary)}
    seen = {}

    def after(ws):
        seen["conn"] = (ws.path / "docs" / "connectors.json").read_text(encoding="utf-8")
    out = run_job(env, [*before, ("Requests", lambda ws: requests_step(ws, env, NOW, make_api=gh.api())), ("Look", after), *later], NOW,
                  prepare=prepare(env, make_api=gh.api()))
    return out, seen, summary


def test_a_dispatched_check_request_writes_results_and_one_summary_line_each_without_secrets(tmp_path, monkeypatch):
    from test_core_requests import GitHub
    gh = GitHub(toml=TOML)
    svc = Service(fail={"api.pagerduty.com": 401})
    payload = {"inputs": {"request": json.dumps({"version": 1, "check": ["jira", "pagerduty", "webhook"]})},
               "sender": {"login": "alice"}}
    out, seen, summary = _git_run(tmp_path, "workflow_dispatch", payload, gh, monkeypatch, svc)
    assert out["errors"] == {} and out["results"]["Requests"]["checks"] == 3
    conn = json.loads(seen["conn"])["connectors"]
    assert conn["jira"]["check"]["ok"] is True and conn["pagerduty"]["check"]["ok"] is False
    assert set(conn) == {"jira", "pagerduty", "webhook"}
    text = seen["conn"] + summary.read_text(encoding="utf-8")
    assert not any(s in text for s in FAKE)
    lines = [x for x in summary.read_text(encoding="utf-8").splitlines() if x.startswith("- ")]
    assert len(lines) == 3 and any(x.startswith("- PagerDuty: not working") for x in lines)
    # Only the asked services were called.
    assert {c[1] for c in svc.calls} == {"acme.atlassian.net", "api.pagerduty.com", "hooks.slack.com", "discord.com"}


def test_a_check_request_from_an_issue_or_comment_answers_there(tmp_path, monkeypatch):
    from test_core_requests import GitHub
    gh = GitHub(toml=TOML)
    block = json.dumps({"version": 1, "check": "all"})
    issue = {"action": "opened", "issue": {"number": 12, "title": "StackVitals: test connections", "user": {"login": "alice"},
                                           "author_association": "OWNER", "body": f"```stackvitals\n{block}\n```", "labels": []}}
    _out, seen, _s = _git_run(tmp_path, "issues", issue, gh, monkeypatch, Service())
    assert set(json.loads(seen["conn"])["connectors"]) == set(ALL) - {"s3"}
    said = [b["body"] for m, p, b in gh.calls if m == "POST" and p == "/repos/o/r/issues/12/comments"]
    assert said and "Jira: working" in said[0] and not any(s in said[0] for s in FAKE)
    assert ("PATCH", "/repos/o/r/issues/12", {"state": "closed", "state_reason": "completed"}) in gh.calls
    comment = {"action": "created", "issue": {"number": 3, "title": "x", "labels": []},
               "comment": {"id": 5, "body": "/stackvitals check slack", "user": {"login": "alice"}, "author_association": "OWNER"}}
    gh2 = GitHub(toml=TOML)
    _out, seen, _s = _git_run(tmp_path / "c", "issue_comment", comment, gh2, monkeypatch, Service())
    said = [b["body"] for m, p, b in gh2.calls if m == "POST" and p == "/repos/o/r/issues/3/comments"]
    assert said and "Slack: working" in said[0]


def test_someone_without_write_access_cannot_run_checks(tmp_path, monkeypatch):
    from test_core_requests import GitHub
    gh = GitHub(permission="triage", toml=TOML)
    svc = Service()
    payload = {"inputs": {"request": json.dumps({"version": 1, "check": ["webhook"]})}, "sender": {"login": "alice"}}
    _out, seen, summary = _git_run(tmp_path, "workflow_dispatch", payload, gh, monkeypatch, svc)
    assert not svc.calls and "write access" in summary.read_text(encoding="utf-8")


def test_a_check_only_request_is_recognised_for_the_light_path(tmp_path):
    def env_for(event, payload):
        f = tmp_path / f"{event}.json"
        f.write_text(json.dumps(payload), encoding="utf-8")
        return {"GITHUB_EVENT_NAME": event, "GITHUB_EVENT_PATH": str(f)}
    from stackvitals.core.requests import check_only
    assert check_only(env_for("workflow_dispatch", {"inputs": {"request": '{"version": 1, "check": "all"}'}}))
    assert not check_only(env_for("workflow_dispatch", {"inputs": {"request": '{"version": 1, "check": "all", '
                                                                              '"settings": {"a.b": 1}}'}}))
    assert not check_only(env_for("workflow_dispatch", {"inputs": {}}))
    assert check_only(env_for("issue_comment", {"action": "created", "comment": {"body": "/stackvitals check jira"}}))
    assert not check_only(env_for("issue_comment", {"action": "created", "comment": {"body": "/stackvitals mute"}}))
    assert not check_only(env_for("schedule", {}))


def test_the_action_runs_only_the_request_step_for_a_check(monkeypatch, tmp_path):
    import stackvitals.ci.cli as cli
    import stackvitals.core.requests as requests_mod
    order = []
    monkeypatch.setattr(requests_mod, "requests_step", lambda ws, env, now, **kw: order.append("Requests") or {
        "decisions": 0, "settings": False, "checks": 1, "working": 1})
    monkeypatch.setattr(cli, "run_action", lambda env, **kw: order.append("CI Health") or {})
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    event = tmp_path / "e.json"
    event.write_text(json.dumps({"inputs": {"request": '{"version": 1, "check": ["jira"]}'}}), encoding="utf-8")
    for key, value in (("GITHUB_EVENT_NAME", "workflow_dispatch"), ("GITHUB_REPOSITORY", "o/r"), ("STACKVITALS_TOKEN", "tok"),
                       ("STACKVITALS_REMOTE", bare.as_uri()), ("RUNNER_TEMP", str(tmp_path / "tmp")),
                       ("GITHUB_EVENT_PATH", str(event))):
        monkeypatch.setenv(key, value)
    assert cli.action_main(["--modules", "ci,flow,community"]) == 0
    assert order == ["Requests"]


def test_a_bad_check_request_is_refused_plainly():
    from stackvitals.core import decisions as dec
    with pytest.raises(dec.CommandError, match="check"):
        dec.parse_request('```stackvitals\n{"version": 1, "check": 5}\n```', NOW.date())
    req = dec.parse_request('```stackvitals\n{"version": 1, "check": ["jira"]}\n```', NOW.date())
    assert req.check == ["jira"]


# The command line.

def test_the_cli_checks_from_the_environment_and_prints_plain_lines_or_json(tmp_path, monkeypatch, capsys):
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "stackvitals.toml").write_text(TOML, encoding="utf-8")
    (tmp_path / ".env").write_text("STACKVITALS_LINEAR_TOKEN=sek-linear-222\n# a comment\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    for k in SECRETS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("STACKVITALS_JIRA_TOKEN", "sek-jira-111")
    monkeypatch.setenv("STACKVITALS_JIRA_EMAIL", "me@acme.com")
    monkeypatch.setattr(check, "TRANSPORT", httpx.MockTransport(Service(fail={"api.linear.app": 401}).handle))
    from stackvitals.cli import main
    assert main(["connectors", "check", "jira", "linear"]) == 1
    out = capsys.readouterr().out
    assert "Jira: working" in out and "Linear: not working" in out and not any(s in out for s in FAKE)
    assert main(["connectors", "check", "--all", "--json"]) == 1
    got = json.loads(capsys.readouterr().out)
    assert got["jira"]["ok"] is True and "discourse" in got and "slack" not in got
    assert main(["connectors", "check", "jira"]) == 0


# Review fixes (2026-10-24).

def test_discord_and_pagerduty_fail_on_a_400_for_one_channel_or_service():
    got, _ = run("discord", fail={"discord.com/api/v10/channels/999": 400})
    assert got["ok"] is False and "not a text channel, or a bad channel id" in got["detail"]
    got, _ = run("pagerduty", fail={"api.pagerduty.com/services/": 400})
    assert got["ok"] is False and "400" in got["detail"]


def test_a_chat_webhook_post_is_never_retried():
    got, svc = run("webhook", fail={"hooks.slack.com": 503})
    assert got["ok"] is False and len([c for c in svc.calls if c[1] == "hooks.slack.com"]) == 1
    got, svc = run("webhook", fail={"hooks.slack.com": "down"})
    assert got["ok"] is False and len([c for c in svc.calls if c[1] == "hooks.slack.com"]) == 1


def _scopes(scopes, status=200):
    return {"gitlab.com/api/v4/personal_access_tokens/self": lambda r: httpx.Response(
        status, json={"name": "sv", "active": True, "scopes": scopes})}


def test_gitlab_checks_the_token_can_write_not_only_read():
    got, svc = run("gitlab")
    assert got["ok"] is True and ("GET", "gitlab.com", "/api/v4/personal_access_tokens/self") in svc.calls
    got, _ = run("gitlab", fail=_scopes(["read_api"]))
    assert got["ok"] is False and "api" in got["detail"] and "write_repository" in got["detail"]
    got, _ = run("gitlab", fail=_scopes(["api"]))
    assert got["ok"] is False and "write_repository" in got["detail"] and "write_repository" in got["fix"]
    # A token whose scopes can't be read still passes, saying what to confirm.
    got, _ = run("gitlab", fail=_scopes([], status=404))
    assert got["ok"] is True and "write_repository" in got["detail"]


def test_jira_refuses_a_plain_http_site_before_sending_the_key():
    # The settings file already ignores such a url; the check refuses it too, whatever handed it the settings.
    import copy
    cfg = copy.deepcopy(CFG)
    cfg["connectors"]["jira"]["url"] = "http://acme.atlassian.net"
    got, svc = run("jira", cfg=cfg)
    assert got["ok"] is False and "https" in got["detail"] and "https://" in got["fix"] and not svc.calls


def test_s3_says_where_the_test_object_was_left_when_delete_fails():
    got, _ = run("s3", fail={"s3.example.com": lambda r: httpx.Response(403 if r.method == "DELETE" else
                                                                          200 if r.method == "PUT" else 200, text="")})
    assert got["ok"] is False and ".stackvitals-check" in got["detail"] and "s3://bucket/sv" in got["detail"]
    assert "delete" in got["fix"].lower()


def test_linear_finds_a_configured_team_beyond_the_first_hundred():
    def many(req):
        asked = (json.loads(req.content).get("variables") or {}).get("keys") or []
        return httpx.Response(200, json={"data": {"viewer": {"name": "Lin"}, "organization": {"name": "Acme"},
                                                  "teams": {"nodes": [{"key": f"T{i}"} for i in range(100)],
                                                            "pageInfo": {"hasNextPage": True}},
                                                  "wanted": {"nodes": [{"key": k} for k in asked if k == "ENG"]}}})
    got, _ = run("linear", fail={"api.linear.app": many})
    assert got["ok"] is True and "100+" in got["detail"], got
    got, _ = run("linear", fail={"api.linear.app": many}, cfg=parse('[connectors.linear]\nteams = ["NOPE"]\n')[0])
    assert got["ok"] is False and "NOPE" in got["detail"]


def test_public_repos_hide_who_and_the_configured_names():
    results = {n: run(n)[0] for n in ALL}
    shown = check.shown(results, public=True)
    assert all(shown[n]["as"] is None for n in ALL if n not in ("discourse", "triage"))
    assert shown["triage"]["as"] == "gemini"
    # Failure details on a public repo say "one configured channel", not its id.
    for name, fail, secret in (("slack", {"slack.com/api/conversations.history": lambda r: httpx.Response(
            200, json={"ok": False, "error": "not_in_channel"})}, "C123"),
            ("discord", {"discord.com/api/v10/channels/999": 403}, "999"),
            ("pagerduty", {"api.pagerduty.com/services/": 404}, "PSVC1"),
            ("s3", {"s3.example.com": 403}, "s3://bucket")):
        svc = Service(fail)
        got = check.check(name, CFG, SECRETS, client=svc.client(), now=NOW, public=True)
        assert got["ok"] is False and secret not in got["detail"] + got["fix"], got
    got = check.check("linear", parse('[connectors.linear]\nteams = ["NOPE"]\n')[0], SECRETS, client=Service().client(),
                      now=NOW, public=True)
    assert got["ok"] is False and "NOPE" not in got["detail"] and "ENG" not in got["detail"]
    # Private repos keep the names, which say exactly what to fix.
    got, _ = run("discord", fail={"discord.com/api/v10/channels/999": 403})
    assert "999" in got["detail"]


def test_check_dispatches_get_their_own_concurrency_group():
    from stackvitals.ci.cli import workflow_template
    text = workflow_template("o/a@v0", ["CI"])
    assert ("group: stackvitals-${{ github.event.pull_request.number || (contains(github.event.inputs.request, '\"check\"')"
            " && format('check-{0}', github.run_id)) || 'data' }}") in text
    assert "group:" in workflow_template("o/a@v0", ["CI"], compact=True)


def test_the_cli_reads_keys_under_their_repository_secret_names(tmp_path):
    # The setup guide names keys like the repository secrets; a .env written that way must still be read.
    (tmp_path / ".env").write_text("JIRA_API_TOKEN=a1\nLINEAR_API_KEY=b2\nPAGERDUTY_API_KEY=c3\nSLACK_BOT_TOKEN=d4\n"
                                   "DISCORD_BOT_TOKEN=e5\nINCIDENT_IO_API_KEY=f6\nJIRA_EMAIL=me@x.io\nSTACKVITALS_LINEAR_TOKEN=keep\n", encoding="utf-8")
    env = check.load_env(tmp_path / ".env", {})
    assert env["STACKVITALS_JIRA_TOKEN"] == "a1" and env["STACKVITALS_PAGERDUTY_TOKEN"] == "c3"
    assert env["STACKVITALS_SLACK_TOKEN"] == "d4" and env["STACKVITALS_DISCORD_TOKEN"] == "e5"
    assert env["STACKVITALS_INCIDENT_IO_TOKEN"] == "f6" and env["STACKVITALS_JIRA_EMAIL"] == "me@x.io"
    assert env["STACKVITALS_LINEAR_TOKEN"] == "keep"


def test_an_inline_comment_after_a_value_is_not_part_of_it(tmp_path):
    (tmp_path / ".env").write_text("DISCORD_CHANNEL=123 # support channel\nQUOTED=\"a # b\"\nURL=https://x.y/#frag\n",
                                   encoding="utf-8")
    env = check._env_file(tmp_path / ".env")
    assert env["DISCORD_CHANNEL"] == "123" and env["QUOTED"] == "a # b" and env["URL"] == "https://x.y/#frag"


def test_admin_keys_saved_under_their_secret_names_are_read(tmp_path):
    env = check.load_env(tmp_path / "none.env", {"ANTHROPIC_ADMIN_KEY": "a", "OPENAI_ADMIN_KEY": "o", "CURSOR_ADMIN_KEY": "c"})
    assert [env[k] for k in ("STACKVITALS_ANTHROPIC_ADMIN_KEY", "STACKVITALS_OPENAI_ADMIN_KEY", "STACKVITALS_CURSOR_ADMIN_KEY")] == ["a", "o", "c"]
