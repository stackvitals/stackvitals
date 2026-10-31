"""Review fixes for requests and commands: a missed command is picked up once (a cancelled waiting run loses nothing),
a dispatch answers in the job summary, a retried settings change answers right, odd ids are refused, reopening undoes."""
import json
import subprocess
from datetime import date, timedelta

import httpx
import pytest
from test_core_requests import NOW, GitHub, request_issue

from stackvitals.core import decisions as dec
from stackvitals.core.workspace import run_job


class Busy(GitHub):
    """Also lists comments and issues, as the catch-up sweep reads them."""

    def __init__(self, comments=(), issues=(), **kw):
        super().__init__(**kw)
        self.comments, self.issues = list(comments), list(issues)

    def handle(self, request):
        path = request.url.path
        if request.method == "GET" and path == "/repos/o/r/issues/comments":
            self.calls.append(("GET", path, dict(request.url.params)))
            return httpx.Response(200, json=self.comments)
        if request.method == "GET" and path == "/repos/o/r/issues":
            self.calls.append(("GET", path, dict(request.url.params)))
            return httpx.Response(200, json=self.issues)
        if request.method == "GET" and path.startswith("/repos/o/r/issues/") and path.count("/") == 5:
            n = int(path.rsplit("/", 1)[1])
            return httpx.Response(200, json={"number": n, "title": "Flaky test: t::swept", "labels": []})
        return super().handle(request)


def job(tmp_path, event, payload, gh, now=NOW, more=(), summary=None):
    from stackvitals.core.requests import requests_step
    from stackvitals.core.settings import prepare
    bare = tmp_path / "remote.git"
    if not bare.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(payload), encoding="utf-8")
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_EVENT_NAME": event, "GITHUB_EVENT_PATH": str(event_file),
           **({"GITHUB_STEP_SUMMARY": str(summary)} if summary else {})}
    seen = {}

    def after(ws):
        seen["state"] = dec.Store(ws.path).state(now.date())
        seen["log"] = dec.Store(ws.path).log()
    out = run_job(env, [("Requests", lambda ws: requests_step(ws, env, now, make_api=gh.api())), *more, ("Check", after)],
                  now, prepare=prepare(env, make_api=gh.api()))
    return out, seen, bare


def replies(gh, number=None):
    return [b["body"] for m, p, b in gh.calls if m == "POST" and p.endswith("/comments") and (number is None or f"/{number}/" in p)]


def test_a_dispatched_request_answers_in_the_job_summary(tmp_path):
    gh, summary = GitHub(permission="read"), tmp_path / "summary.md"
    request = json.dumps({"version": 1, "changes": [], "settings": {"alerts.pickup_p75_hours": 6}})
    job(tmp_path, "workflow_dispatch", {"inputs": {"request": request}, "sender": {"login": "alice"}}, gh, summary=summary)
    assert "Only people with write access" in summary.read_text(encoding="utf-8")


def test_a_settings_change_retried_after_a_rejected_push_is_answered_and_logged_once(tmp_path):
    gh, tries = GitHub(), []

    def race(ws):
        tries.append(1)
        if len(tries) == 1:
            env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "RUNNER_TEMP": str(tmp_path / "other"),
                   "STACKVITALS_REMOTE": (tmp_path / "remote.git").as_uri()}
            run_job(env, [("other", lambda w: (w.path / "other.txt").write_text("o\n", encoding="utf-8"))], NOW)
    _out, seen, _bare = job(tmp_path, "issues", request_issue(settings={"alerts.pickup_p75_hours": 6}), gh, more=[("Race", race)])
    assert len(tries) == 2  # the push was rejected once and the steps ran again
    answer = replies(gh, 12)
    assert len(answer) == 1 and "Changed in" in answer[0]
    assert [r["verb"] for r in seen["log"]] == ["set"]
    assert sum(1 for m, p, _ in gh.calls if m == "PUT") == 1


@pytest.mark.parametrize("ident", ["a\n\n@org/team", "x" * 600])
def test_ids_with_control_characters_or_no_end_are_refused(ident):
    body = "```stackvitals\n" + json.dumps({"version": 1, "changes": [{"verb": "mute", "kind": "test", "id": ident}]}) + "\n```"
    with pytest.raises(dec.CommandError):
        dec.parse_request(body, date(2026, 10, 21))


def test_reopening_an_issue_closed_as_not_planned_undoes_it(tmp_path):
    gh = GitHub()
    issue = {"number": 7, "title": "Flaky test: t::a", "labels": [{"name": "flaky-test"}], "state_reason": "not_planned"}
    _o, seen, _b = job(tmp_path, "issues", {"action": "closed", "issue": issue, "sender": {"login": "alice"}}, gh)
    assert seen["state"]["test:t::a"]["verb"] == "acknowledge"
    issue = {**issue, "state_reason": "reopened"}
    _o, seen, _b = job(tmp_path, "issues", {"action": "reopened", "issue": issue, "sender": {"login": "alice"}}, gh)
    assert seen["state"]["test:t::a"]["verb"] == "reopen"


def test_a_request_that_changed_nothing_is_closed_as_not_planned(tmp_path):
    gh = GitHub()
    job(tmp_path, "issues", request_issue(settings={"alerts.pickup_p75_hours": -1}), gh)
    assert ("PATCH", "/repos/o/r/issues/12", {"state": "closed", "state_reason": "not_planned"}) in gh.calls


def comment(cid, body, at, number=5, association="MEMBER"):
    return {"id": cid, "body": body, "user": {"login": "alice"}, "author_association": association,
            "created_at": at, "updated_at": at, "issue_url": f"https://api.github.com/repos/o/r/issues/{number}"}


def test_a_quiet_run_never_commits_the_sweep_memory(tmp_path):
    out, _seen, _bare = job(tmp_path, "schedule", {}, Busy())
    assert out["outcome"] in ("unchanged", "pushed") and not (tmp_path / "remote.git").joinpath("x").exists()
    again, _seen, _bare = job(tmp_path, "schedule", {}, Busy())
    assert again["outcome"] == "unchanged"


def test_a_command_whose_run_was_cancelled_is_picked_up_once_by_the_next_run(tmp_path):
    iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    first = Busy()
    # Tracking starts with the first command handled; nothing from before it is ever applied.
    opener = comment(40, "/stackvitals mute test:t::first for 7d because start", iso(NOW))
    job(tmp_path, "issue_comment", {"action": "created", "issue": {"number": 5, "title": "x", "labels": []}, "comment": opener}, first)
    assert not any(p == "/repos/o/r/issues/comments" for _m, p, _b in first.calls)
    missed = comment(41, "/stackvitals mute for 7d because known blip", iso(NOW + timedelta(minutes=20)))
    stranger = comment(42, "/stackvitals mute test:x", iso(NOW + timedelta(minutes=25)), association="NONE")
    later = Busy(comments=[missed, stranger])
    _o, seen, _b = job(tmp_path, "workflow_run", {}, later, now=NOW + timedelta(hours=1))
    assert seen["state"]["test:t::swept"]["verb"] == "mute" and "test:x" not in seen["state"]
    assert len(replies(later, 5)) == 1
    again = Busy(comments=[missed, stranger])
    _o, seen, _b = job(tmp_path, "schedule", {}, again, now=NOW + timedelta(hours=2))
    assert len([r for r in seen["log"] if r["id"] == "t::swept"]) == 1 and replies(again) == []


def test_the_triggering_comment_is_not_applied_again_by_the_sweep(tmp_path):
    iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    opener = comment(50, "/stackvitals mute test:t::first for 7d because start", iso(NOW))
    job(tmp_path, "issue_comment", {"action": "created", "issue": {"number": 4, "title": "x", "labels": []}, "comment": opener}, Busy())
    c = comment(51, "/stackvitals mute for 7d because blip", iso(NOW + timedelta(minutes=5)))
    payload = {"action": "created", "issue": {"number": 5, "title": "Flaky test: t::swept", "labels": []}, "comment": c}
    gh = Busy(comments=[c])
    _o, seen, _b = job(tmp_path, "issue_comment", payload, gh, now=NOW + timedelta(minutes=6))
    assert len([r for r in seen["log"] if r["id"] == "t::swept"]) == 1 and len(replies(gh, 5)) == 1
