"""The digest goes out once a week, on the first scheduled run after the repo's day and hour: a comment on one pinned
issue (created the first time) and/or the webhook; it remembers the week's numbers for next week's comparison."""
import json
import subprocess
from datetime import datetime, timezone

import httpx

from stackvitals.ci.api import ActionsAPI
from stackvitals.core.config import parse
from stackvitals.core.workspace import run_job

MONDAY_9 = datetime(2026, 10, 26, 9, tzinfo=timezone.utc)
MONDAY_5 = datetime(2026, 10, 26, 5, tzinfo=timezone.utc)  # before the hour


class GitHub:
    def __init__(self, issues=()):
        self.issues, self.calls = list(issues), []

    def handle(self, request):
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        if request.url.path == "/repos/o/r" and request.method == "GET":
            return httpx.Response(200, json={"private": False, "has_pages": True, "default_branch": "main"})
        if request.url.path == "/repos/o/r/issues" and request.method == "GET":
            return httpx.Response(200, json=self.issues)
        if request.url.path == "/repos/o/r/issues" and request.method == "POST":
            return httpx.Response(201, json={"number": 40, "node_id": "I_40"})
        return httpx.Response(200, json={})

    def api(self):
        return lambda tok, repo, **kw: ActionsAPI(tok, repo, client=httpx.Client(transport=httpx.MockTransport(self.handle)),
                                                  sleep=lambda s: None, **kw)


def run(tmp_path, now, gh, toml="", event="schedule", hook=None):
    from stackvitals.core.digest import digest_step
    bare = tmp_path / "remote.git"
    if not bare.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_EVENT_NAME": event, **({"STACKVITALS_WEBHOOK": hook} if hook else {})}

    def publish(ws):
        (ws.path / "docs").mkdir(exist_ok=True)
        (ws.path / "docs" / "flow.json").write_text(json.dumps({"schema": 1, "open": 3, "stale": 1}), encoding="utf-8")
    sent = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: sent.append(json.loads(r.content)) or httpx.Response(200)))
    out = run_job(env, [("Team Flow", publish), ("Digest", lambda ws: digest_step(ws, env, now, make_api=gh.api(), client=client))],
                  now, prepare=lambda ws: ws.cache.update(settings=parse(toml)[0]))
    return out, sent, bare


def comments(gh):
    return [b["body"] for m, p, b in gh.calls if m == "POST" and p.endswith("/comments")]


def test_the_first_digest_opens_the_issue_and_later_ones_comment_once_a_week(tmp_path):
    gh = GitHub()
    out, _sent, bare = run(tmp_path, MONDAY_9, gh)
    assert out["results"]["Digest"]["week"] == "2026-W44"
    assert any(m == "POST" and p == "/repos/o/r/issues" and b["title"] == "StackVitals weekly digest" for m, p, b in gh.calls)
    assert "3 open pull requests" in comments(gh)[0] and "https://o.github.io/r/" in comments(gh)[0]
    last = json.loads(subprocess.run(["git", "show", "stackvitals-data:digest/last.json"], cwd=bare, capture_output=True,
                                     text=True).stdout)
    assert last["week"] == "2026-W44" and last["numbers"]["open_prs"] == 3
    again = GitHub(issues=[{"number": 40, "title": "StackVitals weekly digest", "labels": [{"name": "stackvitals"}]}])
    out2, _s, _b = run(tmp_path, MONDAY_9.replace(hour=12), again)
    assert out2["results"]["Digest"] is None and comments(again) == []  # already sent this week


def test_nothing_before_the_day_and_hour_or_when_turned_off_or_on_other_events(tmp_path):
    gh = GitHub()
    assert run(tmp_path / "a", MONDAY_5, gh)[0]["results"]["Digest"] is None
    assert run(tmp_path / "b", MONDAY_9, gh, toml="[digest]\nenabled = false\n")[0]["results"]["Digest"] is None
    assert run(tmp_path / "c", MONDAY_9, gh, event="push")[0]["results"]["Digest"] is None
    assert run(tmp_path / "d", MONDAY_9, gh, toml='[digest]\nday = "tuesday"\n')[0]["results"]["Digest"] is None
    assert comments(gh) == []


def test_the_webhook_channel_gets_the_same_text(tmp_path):
    gh = GitHub()
    _out, sent, _bare = run(tmp_path, MONDAY_9, gh, toml='[digest]\nchannels = ["webhook"]\n', hook="https://hooks.slack.com/x")
    assert sent and "StackVitals weekly digest" in sent[0]["text"] and comments(gh) == []
