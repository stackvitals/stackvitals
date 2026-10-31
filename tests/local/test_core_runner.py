"""One module's trouble never skips the modules after it, and the job says which module failed."""
import subprocess

import stackvitals.ci.cli as cli


def test_a_failing_module_is_reported_and_the_next_modules_still_run(monkeypatch, capsys, tmp_path):
    seen = []

    def bad_ci(env, **kw):
        raise RuntimeError("GitHub said 502")

    def flow(env, **kw):
        seen.append("flow")
        return {"prs": 3, "points": 2, "queue": 1, "pushed": False}

    def community(env, **kw):
        seen.append("community")
        return {"issues": 1, "points": 1, "waiting": 0, "score": None, "pushed": False}
    monkeypatch.setattr(cli, "run_action", bad_ci)
    monkeypatch.setattr(cli, "run_flow_action", flow)
    import stackvitals.community.action as community_action
    monkeypatch.setattr(community_action, "run_community_action", community)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    for key, value in (("GITHUB_EVENT_NAME", "schedule"), ("GITHUB_REPOSITORY", "o/r"), ("STACKVITALS_TOKEN", "tok"),
                       ("STACKVITALS_REMOTE", bare.as_uri()), ("RUNNER_TEMP", str(tmp_path / "tmp"))):
        monkeypatch.setenv(key, value)
    code = cli.action_main(["--modules", "ci,flow,community"])
    out = capsys.readouterr().out
    assert seen == ["flow", "community"]
    assert code == 1
    assert "::error::CI Health could not finish: GitHub said 502" in out
    assert "Team Flow: 3 PRs read" in out


def test_a_clean_run_still_returns_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "run_flow_action", lambda env, **kw: None)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    for key, value in (("GITHUB_EVENT_NAME", "schedule"), ("GITHUB_REPOSITORY", "o/r"), ("STACKVITALS_TOKEN", "tok"),
                       ("STACKVITALS_REMOTE", bare.as_uri()), ("RUNNER_TEMP", str(tmp_path / "tmp"))):
        monkeypatch.setenv(key, value)
    assert cli.action_main(["--modules", "flow"]) == 0
