import json
import subprocess
from datetime import timedelta

import httpx
from ci_fake import T0, FakeGitHub, Run, job
from stackvitals.ci import cli as ci_cli
from stackvitals.ci.action import run_action
from stackvitals.ci.api import ActionsAPI

NOW = T0 + timedelta(days=2)
BENCH = {"version": 1, "repos": 900, "built_at": "2026-10-03T06:30:00Z", "groups": {
    "Python|all": {"repos": 412, "median_s": {"p10": 100, "p25": 200, "p50": 300, "p75": 400, "p90": 500},
                   "first_try_share": {"p10": 0.5, "p25": 0.7, "p50": 0.85, "p75": 0.95, "p90": 1.0}}}}


def pushes():
    return [Run(k + 1, T0 + timedelta(hours=k), [("success", [job(k * 10 + 1, "test", "success", T0 + timedelta(hours=k), 600)])],
                sha=f"s{k}", tree=f"t{k}") for k in range(6)]


def fake_api(runs, calls):
    fake = FakeGitHub(runs)

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main", "private": False, "language": "Python",
                                             "stargazers_count": 3000})
        return fake.handle(request)
    return lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),
                                                sleep=lambda s: None, **kw)


def env(tmp_path, url):
    return {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": url,
            "GITHUB_WORKFLOW_REF": "o/r/.github/workflows/stackvitals.yml@refs/heads/main",
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"), "RUNNER_TEMP": str(tmp_path / "tmp")}


def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare


def show(bare, path):
    return subprocess.run(["git", "show", f"stackvitals-data:{path}"], cwd=bare, capture_output=True, text=True,
                          check=True).stdout


def test_action_publishes_a_badge_and_the_comparison(tmp_path, monkeypatch):
    src = tmp_path / "bench.json"
    src.write_text(json.dumps(BENCH), encoding="utf-8")
    monkeypatch.setenv("STACKVITALS_BENCH_URL", str(src))
    bare, calls = remote(tmp_path), []
    run_action(env(tmp_path, bare.as_uri()), now=NOW, make_api=fake_api(pushes(), calls))
    data = json.loads(show(bare, "docs/data.json"))
    assert data["pushes"]["pushes"] == 6 and data["benchmark"]["group"] == "Python repos"
    assert json.loads(show(bare, "docs/badge.json"))["message"] == "100%"
    assert "Compared with 412 Python repos" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_action_without_a_benchmark_source_asks_github_for_nothing_extra(tmp_path, monkeypatch):
    monkeypatch.delenv("STACKVITALS_BENCH_URL", raising=False)
    bare, calls = remote(tmp_path), []
    run_action(env(tmp_path, bare.as_uri()), now=NOW, make_api=fake_api(pushes(), calls))
    assert not [c for c in calls if "releases" in c]
    assert json.loads(show(bare, "docs/data.json")).get("benchmark") is None
    assert json.loads(show(bare, "docs/badge.json"))["label"] == "CI first try"


def test_local_report_compares_when_benchmarks_can_be_read(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STACKVITALS_HOME", str(tmp_path / "home"))
    src = tmp_path / "bench.json"
    src.write_text(json.dumps(BENCH), encoding="utf-8")
    monkeypatch.setenv("STACKVITALS_BENCH_URL", str(src))
    calls = []
    assert ci_cli.main(["report", "o/r", "--days", "3", "--window", "3"], now=NOW, make_api=fake_api(pushes(), calls),
                       tok="tok") == 0
    assert "Compared with 412 Python repos" in capsys.readouterr().out
    # Without a source the private release is tried through the same client: a miss just leaves the section out.
    monkeypatch.delenv("STACKVITALS_BENCH_URL")
    assert ci_cli.main(["report", "o/r", "--days", "3", "--window", "3"], now=NOW, make_api=fake_api(pushes(), calls),
                       tok="tok") == 0
    assert "Compared with" not in capsys.readouterr().out
    assert any("/releases/tags/bench-latest" in c for c in calls)
