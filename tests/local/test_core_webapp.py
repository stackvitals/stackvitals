"""The app is copied beside the pages at the end of every job: index.html is the app, the CI page is ci.html, files are
written only when they change (a quiet run commits nothing) and app files the package no longer has are removed."""
import subprocess
from datetime import datetime, timezone

from stackvitals.core.webapp import files, write_webapp
from stackvitals.core.workspace import run_job

NOW = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)


def test_the_package_carries_the_app_and_its_bundled_libraries():
    names = set(files())
    assert {"index.html", "app/main.js", "app/main.css", "app/boot.js", "app/LICENSES.md", "app/pages/overview.js",
            "app/help/index.json", "app/settings-workflow.json"} <= names
    assert not [n for n in names if n.startswith(("app/vendor/", "app/views/"))]


def test_written_once_rewritten_only_on_change_and_stale_files_removed(tmp_path):
    docs = tmp_path / "docs"
    (docs / "app" / "vendor").mkdir(parents=True)
    (docs / "app" / "old.js").write_text("gone", encoding="utf-8")
    (docs / "app" / "vendor" / "htm.mjs").write_text("the earlier app's library", encoding="utf-8")
    changed = write_webapp(docs)
    assert "index.html" in changed and "app/vendor/htm.mjs" in changed
    assert not (docs / "app" / "old.js").exists() and not (docs / "app" / "vendor").exists()
    assert write_webapp(docs) == []
    assert b"app/main.js" in (docs / "index.html").read_bytes()


def test_a_job_publishes_the_app_and_a_second_quiet_job_commits_nothing(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(), "RUNNER_TEMP": str(tmp_path / "t")}

    def ci(ws):
        (ws.path / "docs").mkdir(exist_ok=True)
        (ws.path / "docs" / "ci.html").write_text("ci page", encoding="utf-8")
    run_job(env, [("CI Health", ci)], NOW)
    show = lambda p: subprocess.run(["git", "show", f"stackvitals-data:{p}"], cwd=bare, capture_output=True, text=True).stdout
    assert "app/main.js" in show("docs/index.html") and show("docs/ci.html") == "ci page"
    assert run_job(env, [("CI Health", ci)], NOW)["outcome"] == "unchanged"
