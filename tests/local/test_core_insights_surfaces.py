"""The red-CI insight on every surface: the Action writes it from the job's checkout, the CLI and MCP read the repo's
published file or compute it from this machine's copies, and the text never lets a job name ping or link anyone."""
import json
import subprocess
from datetime import datetime, timezone

import httpx

from stackvitals.ci.api import ActionsAPI
from stackvitals.ci.store import DataStore
from stackvitals.core import services
from stackvitals.core.insights import render
from stackvitals.core.workspace import run_job
from stackvitals.flow.store import FlowStore
from test_core_insights import NOW, at, job, pr, run

RESULT = {"definition": "Time a ready pull request ...", "since": "2026-09-01T00:00:00Z", "until": "2026-10-20T12:00:00Z",
          "prs": 40, "without_checks": 2, "red_prs": 12, "red_hours_total": 96.5, "rerun_hours_total": 6.0, "rerun_waits": 2,
          "measures": {"insight.red_ci_share": {"metric": "insight.red_ci_share", "version": 1, "value": 0.3, "n": 40, "low": 0.18,
                                                "high": 0.45, "unit": "share", "as_of": "x", "window_days": 90, "note": None},
                       "insight.red_ci_hours": {"metric": "insight.red_ci_hours", "version": 1, "value": 5.25, "n": 12, "low": 2.0,
                                                "high": 9.5, "unit": "h", "as_of": "x", "window_days": 90, "note": None}},
          "cycle_hours": {"red": {"median": 70.0, "n": 12}, "clear": {"median": 20.0, "n": 28}},
          "rerun_jobs": [{"workflow": "CI", "job": "e2e @admins [x](http://evil)", "hours": 6.0, "prs": 2}],
          "top": [{"pr": 7, "hours": 30.0, "waits": [{"from": "a", "to": "b", "hours": 30.0, "ended_by": "push",
                                                      "failed": {"run": 99, "attempt": 1, "workflow": "CI", "jobs": ["tests"]},
                                                      "cleared": {"sha": "s2", "run": 100}}]}],
          "open_red": [{"pr": 9, "since": "x", "hours": 12.0}]}


def test_the_text_gives_counts_ranges_evidence_links_and_neutralises_job_names():
    text = render(RESULT, "o/r", markdown=True)
    assert "12 of 40" in text and "30%, range 18-45%" in text and "median 5.2 h per PR (range 2.0-9.5 h)" in text
    assert "https://github.com/o/r/actions/runs/99/attempts/1" in text and "#7" in text and "#9 for 12 h" in text
    assert "an association, not a cause" in text.lower()
    assert "@admins" not in text and "](http" not in text


def test_the_service_reads_the_published_insight_before_reading_github(tmp_path):
    def handler(request):
        if request.url.path == "/repos/o/r/contents/docs/insights.json":
            return httpx.Response(200, content=json.dumps({"schema": 1, "red_ci": RESULT}).encode())
        return httpx.Response(404, json={"message": "Not Found"})
    make = lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),  # noqa: E731
                                                sleep=lambda s: None, **kw)
    out, source = services.red_ci("o/r", 30, "tok", tmp_path, make_api=make)
    assert out["red_prs"] == 12 and source == "stackvitals-data branch"


FINDINGS = [{"kind": "review_wait", "hours": 250.0, "n": 1, "title": "1 pull requests have waited over 3 days for a review.",
             "action": "Pick them up.", "evidence": [{"label": "#5", "url": "https://github.com/o/r/pull/5"}], "as_of": "x"}]


def test_the_cli_prints_the_insight_or_its_json(monkeypatch, capsys):
    from stackvitals.core import insightscli
    monkeypatch.setattr(insightscli.services, "red_ci", lambda repo, days, tok, home, **kw: (RESULT, "read live"))
    monkeypatch.setattr(insightscli.services, "findings", lambda repo, days, tok, home, **kw: (FINDINGS, "read live"))
    assert insightscli.main(["o/r", "--days", "30"], tok="tok") == 0
    out = capsys.readouterr().out
    assert "12 of 40" in out and "read live" in out and out.index("What to fix first") < out.index("12 of 40")
    assert "waited over 3 days" in out
    assert insightscli.main(["o/r", "--json"], tok="tok") == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["red_ci"]["red_prs"] == 12 and shown["findings"][0]["kind"] == "review_wait"


def test_the_findings_service_reads_the_published_file_first(tmp_path):
    def handler(request):
        if request.url.path == "/repos/o/r/contents/docs/insights.json":
            return httpx.Response(200, content=json.dumps({"schema": 1, "red_ci": RESULT, "findings": FINDINGS}).encode())
        return httpx.Response(404, json={"message": "Not Found"})
    make = lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),  # noqa: E731
                                                sleep=lambda s: None, **kw)
    out, source = services.findings("o/r", 30, "tok", tmp_path, make_api=make)
    assert out[0]["kind"] == "review_wait" and source == "stackvitals-data branch"


def test_the_action_writes_the_insight_from_the_jobs_checkout(tmp_path):
    from stackvitals.core.insights import insights_step
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    summary = tmp_path / "summary.md"
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_STEP_SUMMARY": str(summary)}

    def seed(ws):
        store = DataStore(ws.path)
        store.add([run(10, "s1", 99, "failure"), run(11, "s2", 95, "success"),
                   job(100, 10, "tests", "failure", 98.5), job(110, 11, "tests", "success", 94.5)], "2026-10-16")
        store.save_state({"scanned": {f"2026-10-{d:02d}": "done" for d in range(10, 21)}})
        FlowStore(ws.path).put([pr(1, 100, mg=90)], "2026-10-16")
        return {}
    out = run_job(env, [("seed", seed), ("Insights", lambda ws: insights_step(ws, env, NOW))], NOW)
    assert out["errors"] == {} and out["results"]["Insights"] == {"prs": 1, "red_prs": 1, "findings": 0}
    shown = json.loads(subprocess.run(["git", "show", "stackvitals-data:docs/insights.json"], cwd=bare, capture_output=True,
                                      text=True).stdout)
    assert shown["schema"] == 1 and shown["red_ci"]["red_hours_total"] == 3.5 and shown["red_ci"]["top"][0]["pr"] == 1
    assert "1 of 1" in summary.read_text(encoding="utf-8")
    # Without both histories in the checkout there is nothing to join: the step stays quiet.
    empty = tmp_path / "empty.git"
    subprocess.run(["git", "init", "-q", "--bare", str(empty)], check=True)
    quiet = run_job({**env, "STACKVITALS_REMOTE": empty.as_uri()}, [("Insights", lambda ws: insights_step(ws, env, NOW))], NOW)
    assert quiet["results"]["Insights"] is None and quiet["outcome"] in ("unchanged", "pushed")


def test_the_action_writes_findings_and_a_page_and_leaves_them_alone_when_only_the_clock_moved(tmp_path):
    from datetime import timedelta

    from stackvitals.core.insights import insights_step
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    summary = tmp_path / "summary.md"
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_STEP_SUMMARY": str(summary)}
    stuck = {"schema": 1, "stuck": {"hanging_review": [{"pr": 5, "since": "2026-10-10T00:00:00Z", "hours": 250.0}]}, "incidents": []}

    def seed(ws):
        if (ws.path / "flow" / "closed").is_dir():
            return {}
        FlowStore(ws.path).put([pr(1, 100, mg=90)], "2026-10-16")
        (ws.path / "docs").mkdir(parents=True, exist_ok=True)
        (ws.path / "docs" / "delivery.json").write_text(json.dumps(stuck), encoding="utf-8")
        return {}
    out = run_job(env, [("seed", seed), ("Insights", lambda ws: insights_step(ws, env, NOW))], NOW)
    assert out["errors"] == {}
    shown = json.loads(subprocess.run(["git", "show", "stackvitals-data:docs/insights.json"], cwd=bare, capture_output=True,
                                      text=True).stdout)
    # Team Flow alone is enough for findings; the red-CI part waits for CI Health's history.
    assert shown["red_ci"] is None and shown["findings"][0]["kind"] == "review_wait"
    page = subprocess.run(["git", "show", "stackvitals-data:docs/insights.html"], cwd=bare, capture_output=True, text=True).stdout
    assert "What to fix first" in page and "https://github.com/o/r/pull/5" in page
    assert "what to fix first" in summary.read_text(encoding="utf-8").lower()
    head = subprocess.run(["git", "rev-parse", "stackvitals-data"], cwd=bare, capture_output=True, text=True).stdout
    later = NOW + timedelta(minutes=30)
    run_job(env, [("seed", seed), ("Insights", lambda ws: insights_step(ws, env, later))], later)
    assert subprocess.run(["git", "rev-parse", "stackvitals-data"], cwd=bare, capture_output=True, text=True).stdout == head
