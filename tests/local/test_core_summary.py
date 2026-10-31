"""Tier 1: small summary files in the data branch that any SQL engine (DuckDB locally, DuckDB-WASM in the browser)
can query without a server, and the `stackvitals sql` command over them."""
import json
from datetime import datetime, timedelta, timezone

from stackvitals.core import summary

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def at(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, au="newbie", assoc="NONE", st="MERGED", cr=100, mg=80, reviewer="maint"):
    ev = [["review", at(cr - 10), reviewer, "APPROVED", "MEMBER", "User", False]] if reviewer else []
    if st == "MERGED":
        ev.append(["merged", at(mg), reviewer or "maint"])
    return {"t": "pr", "n": n, "ti": f"PR {n}", "draft": False, "st": st, "cr": at(cr), "up": at(1), "mg": at(mg) if st == "MERGED" else None,
            "cl": at(mg) if st != "OPEN" else None, "add": 10, "del": 2, "files": 1, "au": au, "at": "User", "as": assoc, "rq": [],
            "ev": ev, "cm": [], "ci": "SUCCESS", "lc": at(cr), "lb": ["bug"], "paths": ["src/a.py"]}


CI_RESULT = {"window_days": 30, "generated": at(0), "runs": 90,
             "jobs": [{"workflow": ".github/workflows/ci.yml", "job": "e2e", "state": "flaky", "flake_events": 5, "runs": 60,
                       "flake_rate": 0.08, "rate_low": 0.03, "rate_high": 0.18, "failures": 6, "last_flake": at(30),
                       "top_step": "Run tests", "retry_minutes": 30, "prs_affected": [7], "median_s": 300, "p95_s": 400, "slower": None}],
             "tests": [{"id": "tests/test_a.py::test_x", "suite": "junit", "runs": 80, "failures": 4, "flake_events": 4,
                        "flake_rate": 0.05, "rate_low": 0.02, "rate_high": 0.12, "state": "flaky", "last_flake": at(40),
                        "message": "ConnectionResetError", "prs_affected": [7, 9], "workflow": ".github/workflows/ci.yml"}]}


def test_pr_rows_carry_roles_stages_and_devlake_dates(tmp_path):
    data = {"open": [pr(3, st="OPEN", reviewer=None)], "closed": [pr(1), pr(2, au="maint", assoc="MEMBER", cr=50, mg=40)]}
    written = summary.write_pr_summary(tmp_path, data, NOW)
    assert written == ["summary/prs.jsonl"]
    rows = [json.loads(line) for line in (tmp_path / "summary" / "prs.jsonl").read_text(encoding="utf-8").splitlines()]
    by_n = {r["number"]: r for r in rows}
    assert by_n[1]["role"] == "outsider" and by_n[2]["role"] == "insider" and by_n[1]["author_kind"] == "person"
    assert by_n[1]["pickup_s"] == 10 * 3600 and by_n[1]["cycle_s"] == 20 * 3600 and by_n[1]["reviews"] == 1
    assert by_n[1]["merged_at"] == at(80) and by_n[1]["status"] == "MERGED" and by_n[3]["status"] == "OPEN"
    assert by_n[3]["pickup_s"] is None and by_n[1]["additions"] == 10 and by_n[1]["labels"] == ["bug"]
    manifest = json.loads((tmp_path / "summary" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == 1 and manifest["files"]["prs.jsonl"]["rows"] == 3 and manifest["generated"] == at(0)


def test_ci_rows_hold_jobs_and_tests_with_their_evidence_counts(tmp_path):
    written = summary.write_ci_summary(tmp_path, CI_RESULT, NOW)
    assert written == ["summary/ci_jobs.jsonl", "summary/tests.jsonl"]
    job = json.loads((tmp_path / "summary" / "ci_jobs.jsonl").read_text(encoding="utf-8"))
    assert job["job"] == "e2e" and job["flake_events"] == 5 and job["runs"] == 60 and job["prs_affected"] == 1 and job["window_days"] == 30
    test = json.loads((tmp_path / "summary" / "tests.jsonl").read_text(encoding="utf-8"))
    assert test["test_id"] == "tests/test_a.py::test_x" and test["state"] == "flaky" and test["prs_affected"] == 2
    manifest = json.loads((tmp_path / "summary" / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["files"]) == {"ci_jobs.jsonl", "tests.jsonl"}
    # A later PR summary joins the manifest instead of replacing it.
    summary.write_pr_summary(tmp_path, {"open": [], "closed": [pr(1)]}, NOW)
    manifest = json.loads((tmp_path / "summary" / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["files"]) == {"ci_jobs.jsonl", "tests.jsonl", "prs.jsonl"}


def test_the_sql_command_queries_summaries_from_a_folder_or_a_repo(tmp_path, capsys):
    from stackvitals.core.sqlcli import main
    summary.write_pr_summary(tmp_path, {"open": [], "closed": [pr(1), pr(2, au="maint", assoc="MEMBER", cr=50, mg=40)]}, NOW)
    summary.write_ci_summary(tmp_path, CI_RESULT, NOW)
    assert main(["--dir", str(tmp_path), "select role, count(*) as n from prs group by role order by role"]) == 0
    out = capsys.readouterr().out
    assert "insider" in out and "outsider" in out and "n" in out
    assert main(["--dir", str(tmp_path), "--json", "select job, flake_events from ci_jobs"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"job": "e2e", "flake_events": 5}]

    class Api:
        def __init__(self, token, repo, **kw):
            self.calls = []

        def file(self, path, ref):
            assert ref == "stackvitals-data"
            return (tmp_path / path).read_bytes()
    assert main(["--repo", "o/r", "select count(*) as n from tests"], make_api=Api, tok="tok") == 0
    assert "1" in capsys.readouterr().out
    assert main(["--dir", str(tmp_path / "nowhere"), "select 1"]) == 1
    assert "No summaries" in capsys.readouterr().err
