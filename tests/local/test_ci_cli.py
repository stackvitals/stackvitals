import json
import subprocess
from datetime import timedelta

import httpx
from ci_fake import T0, FakeGitHub, Run, job
from stackvitals.ci.api import ActionsAPI
from stackvitals.ci.cli import main, workflow_template


def cli_make_api(cli_runs):
    fake = FakeGitHub(cli_runs)

    def handler(request):
        if request.url.path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main", "private": False})
        return fake.handle(request)
    return lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),
                                                sleep=lambda s: None, **kw)


def cli_runs():
    out = []
    for k, day in enumerate((1, 2)):
        t = T0 + timedelta(days=day)
        out.append(Run(k + 1, t, [("failure", [job(k * 10 + 1, "e2e", "failure", t, 60, failing_step="Install dependencies")]),
                                  ("success", [job(k * 10 + 2, "e2e", "success", t + timedelta(minutes=10), 60, attempt=2)])],
                       tree=f"t{k}"))
    return out


def test_local_report_on_any_repo_prints_findings_and_writes_a_dashboard(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("STACKVITALS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    code = main(["report", "o/r", "--days", "5", "--html", str(tmp_path / "site")], now=T0 + timedelta(days=3),
                make_api=cli_make_api(cli_runs()))
    out = capsys.readouterr().out
    assert code == 0 and "e2e" in out and "flaky" in out and "Install dependencies" in out
    assert (tmp_path / "site" / "ci.html").exists()
    assert json.loads((tmp_path / "site" / "data.json").read_text(encoding="utf-8"))["jobs"][0]["state"] == "flaky"


def test_report_without_a_token_explains_how_to_get_one(tmp_path, capsys, monkeypatch):
    for name in ("STACKVITALS_TOKEN", "GITHUB_TOKEN", "MERGESCOUT_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STACKVITALS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("stackvitals.ci.cli._gh_token", lambda: None)
    assert main(["report", "o/r"], make_api=cli_make_api(cli_runs())) == 1
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_init_prints_a_workflow_with_least_privilege():
    text = workflow_template("stackvitals/stackvitals@v0", ["CI", 'Tests "nightly"'])
    assert "contents: write" in text and "actions: read" in text and "pull-requests: write" in text
    assert "stackvitals/stackvitals@v0" in text and "cancel-in-progress: false" in text
    assert 'workflows: ["CI", "Tests \\"nightly\\""]' in text and "types: [completed]" in text


def test_init_for_a_repo_lists_its_own_workflow_names(capsys):
    def handler(request):
        return httpx.Response(200, json={"workflows": [
            {"name": "CI", "path": ".github/workflows/ci.yml", "state": "active"},
            {"name": "Docs", "path": ".github/workflows/docs.yml", "state": "disabled_manually"},
            {"name": "StackVitals", "path": ".github/workflows/stackvitals.yml", "state": "active"},
            {"name": "Dependabot Updates", "path": "dynamic/dependabot/dependabot-updates", "state": "active"}]})
    api = lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert main(["init", "o/r"], make_api=api, tok="t") == 0
    assert 'workflows: ["CI"]' in capsys.readouterr().out


def test_quarantine_command_wraps_a_test_run(tmp_path, monkeypatch):
    import sys as _sys
    qlist = tmp_path / "quarantine.json"
    qlist.write_text('["t::a"]', encoding="utf-8")
    report = tmp_path / "r.xml"
    script = (f"open(r'{report}','w').write('<testsuite><testcase classname=\"t\" name=\"a\"><failure message=\"x\"/>"
              "</testcase></testsuite>'); raise SystemExit(1)")
    args = ["quarantine", "--reports", str(tmp_path / "*.xml"), "--list", str(qlist), "--", _sys.executable, "-c", script]
    assert main(args) == 0
    qlist.write_text("not json", encoding="utf-8")
    assert main(args) == 1


def test_action_switches_reach_the_action(monkeypatch, tmp_path):
    from stackvitals.ci import cli as cli_mod
    seen = {}
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    for key, value in (("GITHUB_EVENT_NAME", "schedule"), ("GITHUB_REPOSITORY", "o/r"), ("STACKVITALS_TOKEN", "tok"),
                       ("STACKVITALS_REMOTE", bare.as_uri()), ("RUNNER_TEMP", str(tmp_path / "tmp"))):
        monkeypatch.setenv(key, value)

    def fake_run(env, **kw):
        seen.update(kw)
        return {"collect": {"runs": 0, "requests": 0}, "flaky": 0, "pushed": False}
    monkeypatch.setattr(cli_mod, "run_action", fake_run)
    cli_mod.action_main(["--rerun-flaky", "true", "--quarantine", "true", "--issues", "false", "--pr-comments", "false"])
    assert seen["rerun_flaky"] and seen["quarantine"] and not seen["issues"] and not seen["pr_comments"]


def test_a_json_report_that_stopped_early_says_so(tmp_path, capsys, monkeypatch):
    # Real finding: GitHub's jobs endpoint ran out while the runs list still had requests left; --json said nothing.
    monkeypatch.setenv("STACKVITALS_HOME", str(tmp_path / "home"))
    fake = FakeGitHub(cli_runs())

    def handler(request):
        if request.url.path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main", "private": False})
        if "/jobs" in request.url.path:
            return httpx.Response(403, json={"message": "API rate limit exceeded"}, headers={"x-ratelimit-remaining": "0"})
        return fake.handle(request)
    make_api = lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),  # noqa: E731
                                                    sleep=lambda s: None, **kw)
    assert main(["report", "o/r", "--days", "5", "--json"], now=T0 + timedelta(days=3), make_api=make_api, tok="tok") == 0
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["collect"]["complete"] is False and "hourly limit" in out["collect"]["stopped"]
    assert "not all history" in captured.err.lower()
