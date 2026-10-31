"""Explore: the page pins DuckDB-WASM with integrity hashes, carries DevLake's ported SQL and our own queries, is written by
the job only when its text changes, and every saved query runs in DuckDB on real-shaped tables."""
import json
import subprocess
from datetime import timedelta

import pytest

from stackvitals.core import explore, export
from stackvitals.core.config import parse
from stackvitals.core.summary import pr_rows, write_ci_summary, write_devlake_summary, write_pr_summary
from stackvitals.core.workspace import run_job
from test_core_delivery import NOW
from test_core_export import fixture

duckdb = pytest.importorskip("duckdb")


def test_the_page_pins_duckdb_with_integrity_and_lists_devlakes_and_our_queries():
    page = explore.render("o/r")
    assert "@duckdb/duckdb-wasm@1.32.0/dist/" in page and "apache-arrow@17.0.0" in page
    assert all(h in page for h in explore.SRI.values()) and "integrity" in page
    titles = [q["title"] for q in explore.queries()]
    assert len(titles) == 6 + 4 + 5 and "DORA: deployment frequency" in titles and "Flakiest CI jobs" in titles
    assert '"o/r"' in page and "raw.githubusercontent.com" in page and "</script>" not in page.split("QUERIES = ")[1].split("const BASE")[0]


def test_the_job_writes_explore_once_there_are_summaries_and_leaves_it_alone_after(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}
    flow, _repo, _issues = fixture()

    def seed(ws):
        write_pr_summary(ws.path, flow, NOW, "o/r")
        return {}
    run_job(env, [("seed", seed)], NOW)
    page = subprocess.run(["git", "show", "stackvitals-data:docs/explore.html"], cwd=bare, capture_output=True, text=True)
    assert page.returncode == 0 and "Explore" in page.stdout
    head = subprocess.run(["git", "rev-parse", "stackvitals-data"], cwd=bare, capture_output=True, text=True).stdout
    run_job(env, [("seed", seed)], NOW + timedelta(hours=3))
    assert subprocess.run(["git", "rev-parse", "stackvitals-data"], cwd=bare, capture_output=True, text=True).stdout == head


def test_every_saved_query_runs_on_the_summaries_and_devlake_tables(tmp_path):
    flow, repo, issues = fixture()
    cfg = parse("")[0]
    write_pr_summary(tmp_path, flow, NOW, "o/r")
    write_ci_summary(tmp_path, {"window_days": 90, "jobs": [{"workflow": "CI", "job": "tests", "state": "flaky", "runs": 40,
                                                             "failures": 6, "flake_events": 5, "flake_rate": 0.125}],
                                "tests": [{"id": "t::a", "suite": "s", "state": "broken", "runs": 40, "failures": 9}]}, NOW)
    write_devlake_summary(tmp_path, export.devlake_tables("o/r", flow, repo, {"runs": []}, issues, cfg), NOW)
    con = duckdb.connect()
    folder = tmp_path / "summary"
    for path in sorted(folder.glob("*.jsonl")):
        name = path.stem
        literal = str(path).replace("\\", "/")
        # The same typed reading as the page: DevLake's columns, or ours for prs, ci_jobs and tests.
        from stackvitals.core.summary import table_types
        table, types = (name[8:] if name.startswith("devlake_") else name), table_types(name)
        spec = ", ".join(f"'{c}': '{t}'" for c, t in types.items())
        if path.stat().st_size:
            con.execute(f"create table \"{table}\" as select * from read_json('{literal}', format='newline_delimited', columns={{{spec}}})")
        else:
            con.execute(f"create table \"{table}\" ({', '.join(f'{chr(34)}{c}{chr(34)} {t}' for c, t in types.items())})")
    con.execute("create table calendar_months as select strftime(m, '%y/%m') as month, cast(m as date) as month_timestamp "
                "from range(TIMESTAMP '2000-01-01', TIMESTAMP '2100-01-01', INTERVAL 1 MONTH) t(m)")
    start, end = NOW - timedelta(days=90), NOW
    fill = {"{{FROM}}": start.strftime("%Y-%m-%d 00:00:00"), "{{TO}}": end.strftime("%Y-%m-%d 23:59:59"),
            "{{PROJECT}}": "o/r", "{{REPORT}}": "2023"}
    answered = 0
    for q in explore.queries():
        sql = q["sql"]
        for k, v in fill.items():
            sql = sql.replace(k, v)
        rows = con.execute(sql).fetchall()  # every saved query must run, whatever it returns
        answered += bool(rows)
    assert answered >= 12
    merged = con.execute("select merged from (" + explore.OURS[0][1] + ") limit 1").fetchone()
    assert merged and merged[0] >= 1
    assert json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["files"]["devlake_pull_requests.jsonl"]["rows"] == 41
    assert pr_rows(flow, NOW, "o/r")
