import json
from datetime import datetime, timezone

from stackvitals.deps.lockfiles import read_lockfile

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def test_package_lock_v3_and_v1(tmp_path):
    v3 = tmp_path / "package-lock.json"
    v3.write_text(json.dumps({"lockfileVersion": 3, "packages": {
        "": {"name": "app"}, "node_modules/lodash": {"version": "4.17.21"},
        "node_modules/@babel/core": {"version": "7.24.0"}, "node_modules/a/node_modules/lodash": {"version": "3.0.0"}}}))
    assert read_lockfile(v3) == [("npm", "@babel/core", "7.24.0"), ("npm", "lodash", "3.0.0"), ("npm", "lodash", "4.17.21")]
    v1 = tmp_path / "v1" / "package-lock.json"
    v1.parent.mkdir()
    v1.write_text(json.dumps({"lockfileVersion": 1, "dependencies": {"axios": {"version": "1.7.0", "dependencies": {
        "follow-redirects": {"version": "1.15.6"}}}}}))
    assert read_lockfile(v1) == [("npm", "axios", "1.7.0"), ("npm", "follow-redirects", "1.15.6")]


def test_python_requirements_uv_poetry_and_pipfile(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("# pinned\nRequests[socks]==2.32.3 ; python_version >= '3.9'\nflask>=3\n-e .\n--hash=sha256:abc\nuvicorn\n")
    assert read_lockfile(req) == [("pypi", "flask", None), ("pypi", "requests", "2.32.3"), ("pypi", "uvicorn", None)]
    uv = tmp_path / "uv.lock"
    uv.write_text('version = 1\n[[package]]\nname = "app"\nversion = "0.1.0"\nsource = { editable = "." }\n\n'
                  '[[package]]\nname = "httpx"\nversion = "0.28.1"\nsource = { registry = "https://pypi.org/simple" }\n')
    assert read_lockfile(uv) == [("pypi", "httpx", "0.28.1")]
    poetry = tmp_path / "poetry.lock"
    poetry.write_text('[[package]]\nname = "Django"\nversion = "5.1.2"\n')
    assert read_lockfile(poetry) == [("pypi", "django", "5.1.2")]
    pipfile = tmp_path / "Pipfile.lock"
    pipfile.write_text(json.dumps({"default": {"click": {"version": "==8.1.7"}}, "develop": {"pytest": {"version": "==8.3.0"}}}))
    assert read_lockfile(pipfile) == [("pypi", "click", "8.1.7"), ("pypi", "pytest", "8.3.0")]


def test_an_unknown_file_says_which_ones_are_read(tmp_path):
    f = tmp_path / "yarn.lock"
    f.write_text("x")
    try:
        read_lockfile(f)
    except ValueError as exc:
        assert "package-lock.json" in str(exc) and "uv.lock" in str(exc)
    else:
        raise AssertionError("expected a clear error")


def evidence_files(tmp_path):
    files = {
        "map": {"packages": {"pypi:requests": {"ecosystem": "pypi", "package": "requests", "version": "2.32.3", "repo": "psf/requests",
                                               "link": "verified", "licenses": ["Apache-2.0"], "deprecated": False, "status": None,
                                               "releases_12m": 6, "last_release": "2026-05-14", "first_release": "2011-02-14"}},
                "built_at": "2026-10-18T09:55:00Z"},
        "ledger": {"cells": [{"ecosystem": "pypi", "package": "requests", "bump": "minor", "prs": 56, "repos": 49, "merged": 44,
                              "closed_unmerged": 5, "ci_known": 50, "ci_failed": 7, "expected_failed": 6.5, "extra_commits": 4,
                              "reverted": 0}], "built_at": "2026-10-18T09:55:00Z"},
        "trends": {"repos": {}, "built_at": "2026-10-18T09:55:00Z"},
        "osv": {"packages": {"pypi:requests": {"advisories": 8, "last_2y": 2, "unfixed": 0, "latest": "2026-03-25", "severity": {},
                                               "malware": False, "ids": []}}, "complete": True, "built_at": "2026-10-18T09:55:00Z"},
    }
    env = {}
    for name, data in files.items():
        path = tmp_path / f"deps-{name}.json"
        path.write_text(json.dumps(data))
        env[f"STACKVITALS_DEPS_{name.upper()}_URL"] = str(path)
    return env


def test_check_prints_the_verdict_with_counts_and_never_says_safe(tmp_path, monkeypatch, capsys):
    from stackvitals.deps.cli import main
    for k, v in evidence_files(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("STACKVITALS_HOME", str(tmp_path / "home"))
    assert main(["check", "pypi:Requests"], now=NOW) == 0
    out = capsys.readouterr().out
    assert "pypi:requests: use" in out and "56 PRs in 49 repos" in out and "safe" not in out.replace("never mean", "")
    assert main(["check", "requests", "--json"], now=NOW) == 0
    assert json.loads(capsys.readouterr().out)[0]["verdict"] == "use"


def test_scan_lists_what_needs_a_look_first(tmp_path, monkeypatch, capsys):
    from stackvitals.deps.cli import main
    for k, v in evidence_files(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("STACKVITALS_HOME", str(tmp_path / "home"))
    req = tmp_path / "requirements.txt"
    req.write_text("requests==2.32.3\nnever-heard-of-it==1.0\n")
    assert main(["scan", str(req)], now=NOW) == 0
    out = capsys.readouterr().out
    assert "2 packages" in out and "1 use" in out and "1 not enough evidence" in out


def test_agents_can_ask_before_adding_a_package_and_scan_a_lockfile(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, "tests/local")
    from test_ci_mcp import mcp_call, server_with
    for k, v in evidence_files(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("STACKVITALS_HOME", str(tmp_path / "home"))
    server = server_with(lambda request: None, tmp_path)
    out = mcp_call(server, "check_package", {"name": "requests"})
    assert out["results"][0]["verdict"] == "use" and "never" in out["note"]
    req = tmp_path / "requirements.txt"
    req.write_text("requests==2.32.3\n")
    out = mcp_call(server, "scan_lockfile", {"path": str(req)})
    assert out["counts"]["use"] == 1 and out["packages"][0]["package"] == "requests"
