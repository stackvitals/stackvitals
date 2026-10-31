"""The files the app reads, written beside the pages after every job: what ran and when, links, the key facts, every
setting with its value, the decisions and their log, and (public repos only) the summary tables, so nothing has to come
from raw.githubusercontent.com. A quiet run changes none of them."""
import json
import subprocess
from datetime import datetime, timezone

from stackvitals.core import decisions as dec
from stackvitals.core.config import parse
from stackvitals.core.workspace import run_job

NOW = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)


def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare


def show(bare, path):
    out = subprocess.run(["git", "show", f"stackvitals-data:{path}"], cwd=bare, capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else None


def modules(ws):
    docs = ws.path / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "data.json").write_text(json.dumps({"schema": 1, "generated": "2026-10-21T08:00:00Z",
                                                "pushes": {"first_try_share": 0.68}, "tests": [], "jobs": [
                                                    {"workflow": ".github/workflows/ci.yml", "job": "test", "state": "flaky"}]}),
                                    encoding="utf-8")
    (docs / "flow.json").write_text(json.dumps({"schema": 1, "generated": "2026-10-21T08:30:00Z", "open": 4, "stale": 1}),
                                    encoding="utf-8")
    (docs / "ci.html").write_text("ci", encoding="utf-8")
    (ws.path / "summary").mkdir(exist_ok=True)
    (ws.path / "summary" / "prs.jsonl").write_text('{"number":1}\n', encoding="utf-8")
    if not dec.Store(ws.path).log():
        dec.Store(ws.path).record([dec.Decision("mute", "job", "ci.yml / test", "2026-11-01", "known"),
                                   dec.Decision("set", "setting", "alerts.pickup_p75_hours", None, "4.0 to 6")], by="alice",
                                  source="issue #3", now=NOW)


def run(tmp_path, private=False):
    bare = tmp_path / "remote.git"
    if not bare.exists():
        remote(tmp_path)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_WORKFLOW_REF": "o/r/.github/workflows/stackvitals.yml@refs/heads/main"}

    def prepare(ws):
        ws.cache.update(settings=parse("[alerts]\npickup_p75_hours = 6\n")[0], settings_notes=["a note"],
                        repo_info={"default_branch": "main", "private": private, "has_pages": True})
    return run_job(env, [("CI Health", modules)], NOW, prepare=prepare), bare


def test_the_app_finds_what_ran_its_facts_settings_and_decisions(tmp_path):
    _out, bare = run(tmp_path)
    app = json.loads(show(bare, "docs/app.json"))
    assert app["repo"] == "o/r" and app["default_branch"] == "main" and app["visibility"] == "public"
    assert app["modules"]["ci"]["updated"] == "2026-10-21T08:00:00Z" and "flow" in app["modules"]
    assert app["facts"]["ci_first_try"] == 0.68 and app["facts"]["ci_flaky"] == 1 and app["facts"]["open_prs"] == 4
    assert app["facts"]["decisions"] == 1  # decisions on items; settings changes are in the log only
    assert app["links"]["workflow"] == "stackvitals.yml" and app["links"]["settings_file"].endswith("/.github/stackvitals.toml")
    settings = json.loads(show(bare, "docs/settings.json"))
    assert settings["values"]["alerts"]["pickup_p75_hours"] == 6.0 and settings["notes"] == ["a note"]
    assert any(s["key"] == "alerts.pickup_p75_hours" for s in settings["settings"])
    decided = json.loads(show(bare, "docs/decisions.json"))
    assert decided["state"]["job:ci.yml / test"]["by"] == "alice" and decided["log"][-1]["verb"] == "mute"
    assert show(bare, "docs/summary/prs.jsonl") == '{"number":1}\n'


def test_a_private_repo_keeps_its_tables_out_of_the_published_folder(tmp_path):
    _out, bare = run(tmp_path, private=True)
    assert show(bare, "docs/summary/prs.jsonl") is None and json.loads(show(bare, "docs/app.json"))["visibility"] == "private"


def test_a_quiet_run_changes_nothing(tmp_path):
    run(tmp_path)
    again, _bare = run(tmp_path)
    assert again["outcome"] == "unchanged"
