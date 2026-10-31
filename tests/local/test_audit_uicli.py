"""Pre-launch audit: `stackvitals ui` passed the token to git with -c, visible in the process list; now via the environment."""
from stackvitals.core import uicli


def test_the_token_goes_to_git_through_env_and_keeps_existing_env_config(monkeypatch):
    seen = []
    monkeypatch.setattr(uicli.subprocess, "run", lambda args, **k: seen.append((args, k.get("env"))))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    uicli._git(["fetch", "x"], "github_pat_secret", None)
    args, env = seen[0]
    assert args == ["git", "fetch", "x"] and not any("github_pat" in a or "extraheader" in a for a in args)
    assert env["GIT_CONFIG_COUNT"] == "2" and env["GIT_CONFIG_KEY_0"] == "core.fsmonitor"
    assert env["GIT_CONFIG_KEY_1"] == "http.extraheader" and env["GIT_CONFIG_VALUE_1"].startswith("AUTHORIZATION: basic ")
    uicli._git(["fetch", "x"], None, None)
    uicli._git(["fetch", "x"], "tok", "file:///local")
    assert seen[1][1] is None and seen[2][1] is None


def test_git_really_reads_the_header_from_env(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    real = subprocess.run

    def show(args, **k):
        return real(["git", "config", "--get", "http.extraheader"], **k)
    monkeypatch.setattr(uicli.subprocess, "run", show)
    out = uicli._git(["fetch"], "tok", None)
    assert out.stdout.strip().startswith("AUTHORIZATION: basic ")
