import gzip
import json
import subprocess
from datetime import timedelta

import httpx
from ci_fake import NET_LOG, T0, FakeGitHub, Run, iso, job
from stackvitals.ci import bench
from stackvitals.ci.action import run_action
from stackvitals.ci.api import ActionsAPI
from stackvitals.ci.report import render_html

from mergescout.bench.ci import TokenPool, fetch_all, repo_stats


def many_runs(n):
    return [Run(k + 1, T0 + timedelta(hours=k), [("success", [job(k * 10 + 1, "test", "success", T0 + timedelta(hours=k), 60)])],
                sha=f"s{k}", tree=f"t{k}") for k in range(n)]


def setup(tmp_path, runs, extra=None, logs=None):
    fake, reruns = FakeGitHub(runs, logs=logs), []

    def handler(request):
        path = request.url.path
        if path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main"})
        if extra and (resp := extra(request)) is not None:
            return resp
        if path.endswith("/rerun-failed-jobs"):
            reruns.append(int(path.split("/")[6]))
            return httpx.Response(201, json={})
        return fake.handle(request)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    make_api = lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),  # noqa: E731
                                                    sleep=lambda s: None, **kw)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}
    return env, make_api, reruns, bare


def test_a_run_that_spends_its_budget_still_saves_what_it_read(tmp_path):
    env, make_api, _, bare = setup(tmp_path, many_runs(30))
    out = run_action(env, now=T0 + timedelta(days=2), make_api=make_api, budget=12)
    assert out["pushed"] and not out["collect"]["complete"]
    assert subprocess.run(["git", "show", "stackvitals-data:docs/data.json"], cwd=bare, capture_output=True).returncode == 0


def test_a_failing_pr_comment_never_stops_a_decided_rerun(tmp_path):
    t = lambda d: T0 + timedelta(days=d)  # noqa: E731
    runs = [Run(k, t(k), [("failure", [job(k * 10 + 1, "e2e", "failure", t(k), 30)]),
                          ("success", [job(k * 10 + 2, "e2e", "success", t(k) + timedelta(minutes=10), 30, attempt=2)])],
                tree=f"x{k}") for k in (1, 2, 3)]
    runs.append(Run(9, t(4), [("failure", [job(91, "e2e", "failure", t(4), 30)])], tree="x9", event="pull_request", pr=12))

    def comments_forbidden(request):
        if "/issues/" in request.url.path:
            return httpx.Response(403, json={"message": "Resource not accessible by integration"})
        return None
    env, make_api, reruns, _ = setup(tmp_path, runs, comments_forbidden, logs={91: NET_LOG})
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"workflow_run": {"id": 9, "event": "pull_request", "conclusion": "failure", "run_attempt": 1,
                                                  "head_branch": "main", "pull_requests": [{"number": 12}]}}))
    env |= {"GITHUB_EVENT_NAME": "workflow_run", "GITHUB_EVENT_PATH": str(event)}
    run_action(env, now=t(4) + timedelta(minutes=15), make_api=make_api, rerun_flaky=True)
    assert reruns == [9]


def test_a_tag_push_of_an_old_commit_is_its_own_push():
    def r(k, branch, hours_ago, secs=300):
        cr = T0 - timedelta(hours=hours_ago)
        return {"id": k, "head_sha": "same" if k == 99 else f"s{k}", "head_branch": branch, "path": "ci.yml",
                "conclusion": "success", "run_attempt": 1, "status": "completed", "created_at": iso(cr),
                "run_started_at": iso(cr), "updated_at": iso(cr + timedelta(seconds=secs))}
    runs = [r(k, "main", k + 1) for k in range(5)] + [r(99, "main", 80), {**r(99, "v1", 2), "id": 100}]
    s = repo_stats(runs)
    assert s["pushes"] == 7 and s["p90_s"] == 300


def test_a_bad_benchmark_file_is_ignored_and_never_injected(tmp_path, monkeypatch):
    you = {"pushes": 9, "median_s": 400, "p90_s": 500, "first_try_share": 0.9, "fail_share": 0.1, "rerun_share": 0.0}
    q = {"p10": 1, "p25": 2, "p50": 3, "p75": 4, "p90": 5}
    bad = {"groups": {"all|all": {"repos": "<img src=x onerror=alert(1)>", "median_s": q, "first_try_share": q},
                      "Go|all": {"repos": 30, "median_s": q}}}
    assert bench.compare(you, bad, "Go", 50) is None
    src = tmp_path / "b.json"
    src.write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setenv("STACKVITALS_BENCH_URL", str(src))
    assert bench.load(None, tmp_path / "c") is None
    good = {"groups": {"all|all": {"repos": 30, "median_s": q, "first_try_share": q}}}
    html = render_html({"window_days": 30, "generated": iso(T0), "runs": 1, "rerun_share": 0, "infra_events": 0,
                        "queue": {"median_s": 1, "p95_s": 1}, "minutes": {"linux": 1, "windows": 0, "macos": 0, "other": 0},
                        "jobs": [], "tests": [], "slow_tests": [], "has_test_reports": False,
                        "benchmark": bench.compare(you, good, "Go", 50)}, "o/r")
    assert "Compared with 30 public repos" in html


def test_one_broken_repo_answer_never_loses_the_days_sample():
    def handler(request):
        if "bad" in request.url.path:
            return httpx.Response(200, content=b"not json")
        return httpx.Response(200, json={"workflow_runs": []}, headers={"x-ratelimit-remaining": "4000"})
    pool = TokenPool(["tok"], client=httpx.Client(transport=httpx.MockTransport(handler)), reserve=100)
    out = fetch_all(pool, [{"name": n, "language": "Go", "stars": 500} for n in ("o/bad", "o/ok")], T0, workers=1)
    assert out["complete"] is False and out["records"] == []


def test_a_second_run_on_the_same_day_adds_to_that_days_file(tmp_path):
    from mergescout.bench.__main__ import publish
    files = {}

    class Rel:
        def upload(self, tag, path, name=None):
            files[(tag, name or path.name)] = path.read_bytes()

        def get(self, tag):
            return {"tag_name": tag} if any(t == tag for t, _ in files) else None

        def assets(self, release):
            return [{"name": n, "tag": t} for t, n in files if t == release["tag_name"]]

        def download_asset(self, asset, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(files[(asset["tag"], asset["name"])])
    rec = lambda i: {"repo": f"o/p{i}", "language": "Go", "stars": 500, "median_s": 1, "p90_s": 1, "fail_share": 0,  # noqa: E731
                     "first_try_share": 1, "rerun_share": 0, "pushes": 9, "day": "2026-10-01"}
    now = T0
    publish(tmp_path / "a", Rel(), [rec(i) for i in range(30)], now, log=lambda m: None)
    publish(tmp_path / "b", Rel(), [rec(99)], now, log=lambda m: None)
    day = gzip.decompress(files[("bench-2026-W40", "ci-2026-10-01.ndjson.gz")]).decode().splitlines()
    assert len(day) == 31
