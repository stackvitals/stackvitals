"""`stackvitals ui`: a local copy of the data branch, kept fresh, served on 127.0.0.1 with the data next to the pages."""
import subprocess
import threading

import httpx

from stackvitals.core import uicli
from stackvitals.core.summary import write_pr_summary
from stackvitals.core.workspace import run_job
from test_core_delivery import NOW
from test_core_export import fixture


def test_ui_copies_the_data_branch_serves_pages_and_data_and_refreshes(tmp_path, capsys):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}
    flow, _repo, _issues = fixture()
    run_job(env, [("seed", lambda ws: write_pr_summary(ws.path, flow, NOW, "o/r") and {})], NOW)
    folder = uicli.fetch("o/r", None, tmp_path / "ui", remote=bare.as_uri())
    assert (folder / "docs" / "explore.html").is_file() and (folder / "summary" / "manifest.json").is_file()
    server = uicli.serve(folder, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        assert httpx.get(base + "/docs/explore.html").status_code == 200
        assert httpx.get(base + "/summary/prs.jsonl").text.count("\n") == 41
    finally:
        server.shutdown()
        server.server_close()
    # A later run on the branch reaches the copy on the next `ui`.
    run_job(env, [("seed", lambda ws: (ws.path / "docs" / "note.txt").write_text("new", encoding="utf-8") and {})], NOW)
    uicli.fetch("o/r", None, tmp_path / "ui", remote=bare.as_uri())
    assert (folder / "docs" / "note.txt").read_text(encoding="utf-8") == "new"


def test_ui_says_plainly_when_the_repo_has_no_data_branch(tmp_path, capsys):
    empty = tmp_path / "empty.git"
    subprocess.run(["git", "init", "-q", "--bare", str(empty)], check=True)
    code = uicli.main(["o/r", "--remote", empty.as_uri(), "--no-open"], tok=None, home=tmp_path)
    assert code == 1 and "stackvitals-data" in capsys.readouterr().err


def test_ui_serves_this_installs_app_over_an_older_copy_on_the_branch(tmp_path, capsys, monkeypatch):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(), "RUNNER_TEMP": str(tmp_path / "tmp")}

    def old_app(ws):
        (ws.path / "docs" / "app" / "views").mkdir(parents=True, exist_ok=True)
        (ws.path / "docs" / "app" / "views" / "home.js").write_text("the earlier app", encoding="utf-8")
        return {}
    run_job(env, [("seed", old_app)], NOW)

    class Stop:
        server_port = 1
        def serve_forever(self):
            raise KeyboardInterrupt
        def server_close(self):
            pass
    monkeypatch.setattr(uicli, "serve", lambda folder, port: Stop())
    assert uicli.main(["o/r", "--remote", bare.as_uri(), "--no-open"], tok=None, home=tmp_path) == 0
    docs = tmp_path / "ui" / "o__r" / "docs"
    assert (docs / "app" / "main.js").is_file() and not (docs / "app" / "views").exists()
    assert "/docs/index.html" in capsys.readouterr().out
