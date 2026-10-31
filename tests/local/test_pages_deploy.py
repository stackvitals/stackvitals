"""Pages from the Action (opt-in for busy repos): after its commit the job hands the published folder to the deploy
steps, and says whether there is anything new to deploy."""
import subprocess
from datetime import datetime, timezone

from stackvitals.core.workspace import run_job

NOW = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)


def env(tmp_path, **extra):
    bare = tmp_path / "remote.git"
    if not bare.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
            "RUNNER_TEMP": str(tmp_path / "t"), **extra}


def page(ws):
    (ws.path / "docs").mkdir(exist_ok=True)
    (ws.path / "docs" / "ci.html").write_text("ci page", encoding="utf-8")


def test_the_published_folder_is_handed_to_the_deploy_steps(tmp_path):
    out = tmp_path / "pages"
    job = run_job(env(tmp_path, STACKVITALS_PAGES_DIR=str(out)), [("CI Health", page)], NOW)
    assert job["pages"] is True and (out / "ci.html").read_text(encoding="utf-8") == "ci page" and (out / "index.html").exists()
    again = run_job(env(tmp_path, STACKVITALS_PAGES_DIR=str(tmp_path / "pages2")), [("CI Health", page)], NOW)
    assert again["outcome"] == "unchanged" and again["pages"] is False  # nothing new to deploy


def test_the_action_step_says_when_there_is_something_to_deploy(tmp_path, monkeypatch):
    import stackvitals.ci.cli as cli
    import stackvitals.core.requests as requests_mod
    monkeypatch.setattr(requests_mod, "requests_step", lambda ws, env, now, **kw: None)

    def ci(env, **kw):
        page(kw["workspace"])
        return {"collect": {"runs": 0, "requests": 0}, "flaky": 0}
    monkeypatch.setattr(cli, "run_action", ci)
    outputs = tmp_path / "outputs.txt"
    for key, value in {**env(tmp_path, STACKVITALS_PAGES_DIR=str(tmp_path / "pages")), "GITHUB_EVENT_NAME": "workflow_run",
                       "GITHUB_OUTPUT": str(outputs)}.items():
        monkeypatch.setenv(key, value)
    assert cli.action_main(["--modules", "ci"]) == 0
    assert "pages=true" in outputs.read_text(encoding="utf-8")


def test_without_the_setting_nothing_is_copied(tmp_path):
    job = run_job(env(tmp_path), [("CI Health", page)], NOW)
    assert job.get("pages") is False and not (tmp_path / "pages").exists()
