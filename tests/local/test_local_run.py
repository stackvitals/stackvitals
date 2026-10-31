import httpx
import pytest

from stackvitals.ci.api import ActionsAPI, APIError
from stackvitals.core import uicli


def test_a_read_only_run_never_sends_a_write_to_github(monkeypatch):
    sent = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(201, json={})))
    api = ActionsAPI("tok", "o/r", client=client)
    monkeypatch.setenv("STACKVITALS_READ_ONLY", "1")
    with pytest.raises(APIError, match="read-only"):
        api.send("POST", "/repos/o/r/issues", {"title": "x"})
    assert sent == []
    monkeypatch.delenv("STACKVITALS_READ_ONLY")
    api.send("POST", "/repos/o/r/issues", {"title": "x"})
    assert len(sent) == 1


def test_ui_collect_runs_the_job_locally_read_only_then_serves_it(tmp_path, monkeypatch):
    seen = {}

    def fake_job(argv, env):
        seen["argv"], seen["env"] = argv, env
        return 0

    monkeypatch.setattr(uicli, "_run_job", fake_job)
    def fake_fetch(repo, tok, folder, remote=None):
        seen["remote"] = remote
        (folder / "docs").mkdir(parents=True, exist_ok=True)
        (folder / "docs" / "index.html").write_text("app", encoding="utf-8")
        return folder

    monkeypatch.setattr(uicli, "fetch", fake_fetch)
    monkeypatch.setattr(uicli, "write_webapp", lambda docs: None, raising=False)
    server = type("S", (), {"server_port": 1, "serve_forever": lambda s: None, "server_close": lambda s: None})()
    monkeypatch.setattr(uicli, "serve", lambda folder, port=0: server)
    assert uicli.main(["o/r", "--collect", "--no-open"], tok="tok", home=tmp_path) == 0
    env = seen["env"]
    assert env["STACKVITALS_READ_ONLY"] == "1" and env["GITHUB_REPOSITORY"] == "o/r" and env["STACKVITALS_TOKEN"] == "tok"
    assert env["STACKVITALS_REMOTE"].endswith("o__r.git") and env["GITHUB_EVENT_NAME"] == "schedule"
    assert seen["remote"] == env["STACKVITALS_REMOTE"]
    assert "--modules" in seen["argv"] and "ci,flow" in seen["argv"] and "false" in seen["argv"]


def test_a_read_only_run_keeps_the_digest_to_itself(monkeypatch, capsys):
    from stackvitals.ci import cli
    monkeypatch.setenv("STACKVITALS_READ_ONLY", "1")
    cli._print_digest({"Digest": {"week": "2026-W44", "channels": ["issue"]}})
    assert "not sent (read-only local run)" in capsys.readouterr().out
