"""The workflow listens for requests from the app and `/stackvitals` commands, starts no runner for other issue events or
strangers, and runs the request step before every module so the job works on what was just decided."""
import subprocess

import yaml

import stackvitals.ci.cli as cli


def test_the_template_hears_requests_and_commands_and_filters_everything_else():
    doc = yaml.safe_load(cli.workflow_template("o/a@v0", ["CI"]))
    on = doc[True]  # YAML 1.1 reads the key `on` as true
    assert on["issues"]["types"] == ["opened", "closed", "reopened"] and on["issue_comment"]["types"] == ["created"]
    assert "request" in on["workflow_dispatch"]["inputs"]
    assert doc["permissions"]["issues"] == "write"
    rule = doc["jobs"]["vitals"]["if"]
    assert "```stackvitals" in rule and "/stackvitals" in rule and "author_association" in rule and "flaky-test" in rule


def test_on_an_issue_event_the_request_step_runs_before_the_modules(monkeypatch, tmp_path):
    order = []
    import stackvitals.core.requests as requests_mod
    monkeypatch.setattr(requests_mod, "requests_step", lambda ws, env, now, **kw: order.append("Requests") or {"decisions": 1, "settings": False})
    monkeypatch.setattr(cli, "run_action", lambda env, **kw: order.append("CI Health") or {
        "collect": {"runs": 0, "requests": 0}, "flaky": 0})
    monkeypatch.setattr(cli, "run_flow_action", lambda env, **kw: order.append("Team Flow") or None)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    for key, value in (("GITHUB_EVENT_NAME", "issue_comment"), ("GITHUB_REPOSITORY", "o/r"), ("STACKVITALS_TOKEN", "tok"),
                       ("STACKVITALS_REMOTE", bare.as_uri()), ("RUNNER_TEMP", str(tmp_path / "tmp"))):
        monkeypatch.setenv(key, value)
    assert cli.action_main(["--modules", "ci,flow"]) == 0
    # A comment command runs light: Requests and CI Health, not the scheduled modules.
    assert order == ["Requests", "CI Health"]
