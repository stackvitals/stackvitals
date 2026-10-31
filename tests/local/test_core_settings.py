"""One settings reader for every step: `.github/stackvitals.toml` is read on every run with a conditional request (free
when unchanged), the last good text lives in the data branch, and a job without CI Health still gets the repo's settings."""
import json
import subprocess
from datetime import datetime, timezone

import httpx

from stackvitals.ci.api import ActionsAPI
from stackvitals.core import settings
from stackvitals.core.config import parse
from stackvitals.core.workspace import run_job

NOW = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)
FILE_PATH = "/repos/o/r/contents/.github/stackvitals.toml"


class Server:
    """The contents endpoint with ETags: 304 when the caller already has this version."""

    def __init__(self, text="[alerts]\npickup_p75_hours = 6\n", etag='"v1"'):
        self.text, self.etag, self.status, self.seen = text, etag, None, []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append((request.url.path, request.headers.get("if-none-match"), request.headers.get("accept")))
        if request.url.path != FILE_PATH:
            return httpx.Response(404, json={"message": "Not Found"})
        if self.status:
            return httpx.Response(self.status, json={"message": "Server Error"})
        if self.text is None:
            return httpx.Response(404, json={"message": "Not Found"})
        if request.headers.get("if-none-match") == self.etag:
            return httpx.Response(304, headers={"etag": self.etag})
        return httpx.Response(200, headers={"etag": self.etag}, content=self.text.encode())

    def api(self):
        return ActionsAPI("tok", "o/r", client=httpx.Client(transport=httpx.MockTransport(self.handle)))


def test_a_changed_file_is_read_and_an_unchanged_one_costs_a_free_304(tmp_path):
    server = Server()
    got = settings.load(server.api(), tmp_path, NOW)
    assert got.cfg["alerts"]["pickup_p75_hours"] == 6.0 and got.changed and got.notes == []
    kept = json.loads((tmp_path / settings.STATE).read_text(encoding="utf-8"))
    assert kept["text"] == server.text and kept["etag"] == '"v1"'
    again = settings.load(server.api(), tmp_path, NOW)
    assert again.cfg["alerts"]["pickup_p75_hours"] == 6.0 and not again.changed
    assert server.seen[-1][1] == '"v1"'  # the second read asked "only if changed"
    server.text, server.etag = "[alerts]\npickup_p75_hours = 8\n", '"v2"'
    third = settings.load(server.api(), tmp_path, NOW)
    assert third.cfg["alerts"]["pickup_p75_hours"] == 8.0 and third.changed


def test_a_failed_read_keeps_the_last_good_settings_and_says_so(tmp_path):
    server = Server()
    settings.load(server.api(), tmp_path, NOW)
    server.status = 502
    got = settings.load(ActionsAPI("tok", "o/r", client=httpx.Client(transport=httpx.MockTransport(server.handle)),
                                   sleep=lambda s: None), tmp_path, NOW)
    assert got.cfg["alerts"]["pickup_p75_hours"] == 6.0 and not got.changed
    assert any("last good settings" in n for n in got.notes)


def test_no_file_means_the_defaults_and_a_removed_file_is_noticed(tmp_path):
    server = Server()
    settings.load(server.api(), tmp_path, NOW)
    server.text = None
    got = settings.load(server.api(), tmp_path, NOW)
    assert got.cfg == parse("")[0] and got.changed and got.text is None


def test_the_old_daily_cache_in_ci_state_is_carried_over(tmp_path):
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "state.json").write_text(json.dumps(
        {"settings": {"text": "[alerts]\nreview_p75_hours = 20\n", "checked": "2026-10-20"}}), encoding="utf-8")
    server = Server()
    server.status = 502
    got = settings.load(ActionsAPI("tok", "o/r", client=httpx.Client(transport=httpx.MockTransport(server.handle)),
                                   sleep=lambda s: None), tmp_path, NOW)
    assert got.cfg["alerts"]["review_p75_hours"] == 20.0


def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare


def test_a_job_without_ci_health_still_gets_the_repos_settings(tmp_path):
    bare, server, seen = remote(tmp_path), Server(), {}
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}

    def delivery(ws):
        seen["pickup"] = ws.cache["settings"]["alerts"]["pickup_p75_hours"]
        return {}
    out = run_job(env, [("Delivery", delivery)], NOW, prepare=settings.prepare(env, make_api=lambda tok, repo, **kw: server.api()))
    assert out["errors"] == {} and seen["pickup"] == 6.0
    shown = subprocess.run(["git", "show", f"stackvitals-data:{settings.STATE}"], cwd=bare, capture_output=True, text=True).stdout
    assert json.loads(shown)["etag"] == '"v1"'


def test_a_typo_keeps_the_last_good_settings_so_switched_off_automation_stays_off(tmp_path):
    # Review finding: a syntax error fell back to the defaults, turning default-on review requests and labels back on.
    server = Server(text="[automation]\nreview_requests = false\n")
    got = settings.load(server.api(), tmp_path, NOW)
    assert got.cfg["automation"]["review_requests"] is False
    server.text, server.etag = "[automation]\nreview_requests = false\nsize_labels = \n", '"v2"'
    got = settings.load(server.api(), tmp_path, NOW)
    assert got.cfg["automation"]["review_requests"] is False and "last good settings" in got.notes[0]
