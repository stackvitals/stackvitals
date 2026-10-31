"""The DevLake-shaped export: its tables carry DevLake's domain names, and DevLake's own DORA dashboard SQL (ported to
DuckDB) run on them gives the same five panels as our Delivery numbers."""
import json
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest

from stackvitals.core import delivery, export
from stackvitals.core.config import parse
from test_core_delivery import NOW, at, pr, review

duckdb = pytest.importorskip("duckdb")


def fixture():
    merged = []
    for k in range(40):
        h = 24 * 80 - k * 46  # one PR about every two days over 80 days
        merged.append(pr(100 + k, cr=h, mg=h - 5 - k % 7, fa=h + 3 + k % 5, mc=f"m{k}", ev=[review(h - 2)]))
    merged.append(pr(300, cr=24 * 30, mg=24 * 30 - 1, fa=24 * 30 + 1, mc="rv", ti='Revert "Add cache"', ev=[review(24 * 30 - 0.5)]))
    releases = [{"tag": f"v{k}", "at": at(24 * 79 - k * 24 * 6), "pre": False, "sha": f"m{3 * k}"} for k in range(13)]
    repo = {"default_branch": "main", "deployments": [], "releases": releases}
    issues = [{"t": "issue", "n": 9, "cr": at(24 * 50), "cl": at(24 * 49), "lb": ["incident"], "st": "CLOSED", "au": "zed"},
              {"t": "issue", "n": 10, "cr": at(24 * 20), "cl": None, "lb": ["bug"], "st": "OPEN", "au": "zed"}]
    return {"closed": merged, "open": []}, repo, issues


def half_up(x, places=1):
    return str(Decimal(str(x)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


@pytest.mark.parametrize("report", ["2023", "2021"])
def test_devlakes_own_dora_sql_on_the_export_matches_our_numbers(tmp_path, report):
    flow, repo, issues = fixture()
    cfg = parse(f'[delivery]\ndora_report = "{report}"\n')[0]
    ours = delivery.build(flow, repo, {"runs": []}, issues, NOW, 90, cfg)["dora"]
    tables = export.devlake_tables("o/r", flow, repo, {"runs": []}, issues, cfg)
    export.write(tables, tmp_path)
    panels = export.panels(tmp_path, NOW - timedelta(days=90), NOW, report, project="o/r")
    assert ours["deployments"] > 10 and ours["lead_time_n"] > 10 and ours["failed_deployments"] >= 1

    freq = panels["deployment_frequency"]
    if ours["frequency_tier"] in ("elite", "high"):
        unit = "week" if report == "2023" or ours["frequency_tier"] == "elite" else "month"
        n = ours[f"deployment_days_per_{unit}"]
        assert freq == f"{n} deployment days per {unit}({ours['frequency_tier']})"
    else:
        assert ours["frequency_tier"] in (None, "medium", "low") and freq is not None
    assert panels["lead_time"] == f"{half_up(ours['lead_time_minutes'] / 60)}({ours['lead_time_tier']})"
    rate = ours["failed_deployments"] / ours["deployments"] * 100
    assert panels["change_failure_rate"] == f"{half_up(rate)}%({ours['cfr_tier']})"
    minutes = ours["recovery_minutes"] if report == "2023" else ours["mttr_minutes"]
    assert panels["recovery"] == f"{half_up(minutes / 60)}({ours['recovery_tier']})"
    assert panels["monthly"] == [(m["month"], m["deployments"]) for m in ours["monthly"]]


def test_the_tables_use_devlake_names_ids_and_enums(tmp_path):
    flow, repo, issues = fixture()
    cfg = parse("")[0]
    tables = export.devlake_tables("o/r", flow, repo, {"runs": []}, issues, cfg)
    assert {"pull_requests", "project_pr_metrics", "cicd_deployment_commits", "incidents", "issues",
            "project_incident_deployment_relationships", "project_mapping"} <= set(tables)
    pr0 = tables["pull_requests"][0]
    assert pr0["id"].startswith("github:PullRequest:o/r:") and pr0["status"] == "MERGED" and pr0["merge_commit_sha"]
    dep = tables["cicd_deployment_commits"][0]
    assert dep["result"] == "SUCCESS" and dep["environment"] == "PRODUCTION" and dep["cicd_deployment_id"]
    metric = next(m for m in tables["project_pr_metrics"] if m["deployment_commit_id"])
    assert isinstance(metric["pr_cycle_time"], int) and metric["project_name"] == "o/r"
    assert {i["type"] for i in tables["issues"]} == {"INCIDENT", "BUG"}
    export.write(tables, tmp_path)
    rows = [json.loads(line) for line in (tmp_path / "pull_requests.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == len(tables["pull_requests"]) and (tmp_path / "dora.sql").is_file()


def expected(ours, report):
    """DevLake's panel strings built from our numbers, N/A cases included."""
    freq_tier, unit = ours["frequency_tier"], None
    if freq_tier == "elite":
        unit = "week"
    elif freq_tier == "high":
        unit = "week" if report == "2023" else "month"
    elif freq_tier == "medium":
        unit = "month" if report == "2023" else "six_months"
    elif freq_tier == "low":
        unit = "month" if report == "2023" else "six_months"
    freq = (f"{ours['deployment_days_per_' + unit]} deployment days per {unit.replace('_', ' ')}({freq_tier})" if unit
            else "N/A. Please check if you have collected deployments.")
    lead = ours["lead_time_minutes"]
    lead_s = f"{half_up(lead / 60)}({ours['lead_time_tier']})" if lead is not None else \
        "N/A. Please check if you have collected deployments/pull_requests."
    cfr = None if ours["change_failure_rate"] is None else ours["failed_deployments"] / ours["deployments"] * 100
    return {"deployment_frequency": freq, "lead_time": lead_s,
            "change_failure_rate": None if cfr is None else f"{half_up(cfr)}%({ours['cfr_tier']})",
            "monthly": [(m["month"], m["deployments"]) for m in ours["monthly"]]}


@pytest.mark.parametrize("seed", range(40))
def test_a_random_sweep_of_repos_gives_devlakes_panels(tmp_path, seed):
    import random
    rnd = random.Random(seed)
    span = rnd.choice([60, 90, 200, 400])
    n_rel = rnd.randint(1, 60)
    rel_h = sorted(rnd.uniform(1, 24 * span) for _ in range(n_rel))
    releases = [{"tag": f"v{k}", "at": at(h), "pre": False, "sha": f"r{k}"} for k, h in enumerate(rel_h)]
    merged = []
    for k in range(rnd.randint(0, 80)):
        cr = rnd.uniform(2, 24 * span)
        mg = cr - rnd.uniform(0.01, min(cr - 1, 24 * 20))
        merged.append(pr(1000 + k, cr=cr, mg=mg, fa=cr + rnd.uniform(-1, 30), ti='Revert "x"' if rnd.random() < 0.1 else "Fix",
                         ev=[review(cr - rnd.uniform(0, cr - mg))] if rnd.random() < 0.8 else []))
    issues = [{"t": "issue", "n": k, "cr": at(c), "cl": at(c - rnd.uniform(0.01, c - 0.5)) if rnd.random() < 0.8 else None,
               "lb": [rnd.choice(["incident", "bug"])], "st": "CLOSED", "au": "zed"}
              for k, c in enumerate(rnd.uniform(1, 24 * span) for _ in range(rnd.randint(0, 6)))]
    report = rnd.choice(["2023", "2021"])
    cfg = parse(f'[delivery]\ndora_report = "{report}"\n')[0]
    flow, repo = {"closed": merged, "open": []}, {"default_branch": "main", "deployments": [], "releases": releases}
    days = rnd.choice([30, 90, 180])
    ours = delivery.build(flow, repo, {"runs": []}, issues, NOW, days, cfg)["dora"]
    export.write(export.devlake_tables("o/r", flow, repo, {"runs": []}, issues, cfg), tmp_path)
    got = export.panels(tmp_path, NOW - timedelta(days=days), NOW, report, project="o/r")
    want = expected(ours, report)
    assert got["deployment_frequency"] == want["deployment_frequency"]
    assert got["lead_time"] == want["lead_time"]
    if want["change_failure_rate"] is not None:
        assert got["change_failure_rate"] == want["change_failure_rate"]
    else:
        assert got["change_failure_rate"].startswith("N/A")
    assert got["monthly"] == want["monthly"]
    cycle = delivery.build(flow, repo, {"runs": []}, issues, NOW, days, cfg)["devlake_pr_cycle"]
    assert [str(m) for m, _h in got["pr_cycle_time"]] == [c["month"] for c in cycle]
    assert all(abs(float(h) - c["avg_hours"]) < 0.005 for (_m, h), c in zip(got["pr_cycle_time"], cycle))
    minutes = ours["recovery_minutes"] if report == "2023" else ours["mttr_minutes"]
    if minutes is not None:
        assert got["recovery"] == f"{half_up(minutes / 60)}({ours['recovery_tier']})"
    else:
        assert got["recovery"] in (None, "No data") or got["recovery"].startswith("N/A")


def test_the_export_command_writes_the_tables_and_prints_devlakes_panels(tmp_path, monkeypatch, capsys):
    from stackvitals.core import exportcli
    flow, repo, issues = fixture()
    cfg = parse("")[0]
    monkeypatch.setattr(exportcli.services, "delivery_inputs",
                        lambda repo_name, days, tok, home, **kw: (flow, repo, {"runs": []}, issues, cfg))
    monkeypatch.setattr(exportcli, "_now", lambda: NOW)
    out = tmp_path / "dl"
    assert exportcli.main(["o/r", "--format", "devlake", "--out", str(out)], tok="tok") == 0
    printed = capsys.readouterr().out
    assert (out / "cicd_deployment_commits.jsonl").is_file() and (out / "dora.sql").is_file()
    assert "Deployment frequency: 1 deployment days per week(high)" in printed and "85.0(high)" in printed
    assert "TIMESTAMP '2026-07-22 12:00:00'" in (out / "dora.sql").read_text(encoding="utf-8")
    assert exportcli.main(["o/r", "--format", "linearb", "--out", str(out)], tok="tok") == 2


def test_the_ctrf_export_writes_each_tests_history_in_ctrf_shape(tmp_path, monkeypatch, capsys):
    from stackvitals.core import exportcli
    result = {"tests": [{"id": "tests/test_net.py::test_fetch", "suite": "pytest", "runs": 40, "failures": 6, "flake_events": 5,
                         "flake_rate": 0.125, "state": "flaky", "since": "2026-10-01", "message": "TimeoutError"},
                        {"id": "tests/test_db.py::test_pool", "suite": "pytest", "runs": 40, "failures": 12, "flake_events": 0,
                         "flake_rate": 0.0, "state": "broken", "since": "2026-10-18", "message": "AssertionError"},
                        {"id": "tests/test_ok.py::test_fine", "suite": "pytest", "runs": 40, "failures": 0, "flake_events": 0,
                         "flake_rate": 0.0, "state": "healthy", "since": None, "message": None}],
              "window_days": 90}
    monkeypatch.setattr(exportcli.services, "ci_result", lambda repo, days, tok, home, **kw: (result, "read live"))
    monkeypatch.setattr(exportcli, "_now", lambda: NOW)
    out = tmp_path / "ctrf.json"
    assert exportcli.main(["o/r", "--format", "ctrf", "--out", str(out)], tok="tok") == 0
    report = json.loads(out.read_text(encoding="utf-8"))["results"]
    assert report["tool"]["name"] == "stackvitals" and report["summary"]["tests"] == 3
    assert report["summary"]["failed"] == 1 and report["summary"]["passed"] == 2
    by = {t["name"]: t for t in report["tests"]}
    assert by["tests/test_net.py::test_fetch"]["flaky"] is True and by["tests/test_net.py::test_fetch"]["status"] == "passed"
    assert by["tests/test_db.py::test_pool"]["status"] == "failed" and by["tests/test_db.py::test_pool"]["message"] == "AssertionError"
    assert by["tests/test_net.py::test_fetch"]["extra"]["flake_events"] == 5
    assert report["environment"]["repositoryUrl"] == "https://github.com/o/r"
    assert "3 tests" in capsys.readouterr().out


def test_the_postgres_export_writes_csv_and_ddl_that_parses_and_loads(tmp_path):
    flow, repo, issues = fixture()
    tables = export.devlake_tables("o/r", flow, repo, {"runs": []}, issues, parse("")[0])
    export.write_postgres(tables, tmp_path)
    sql = (tmp_path / "postgres.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS pull_requests" in sql and "TIMESTAMPTZ" in sql and "PRIMARY KEY (id)" in sql
    assert "\\copy pull_requests FROM 'pull_requests.csv' WITH (FORMAT csv, HEADER true)" in sql
    # Checked without a server: DuckDB's Postgres-derived parser runs the DDL, then loads each CSV the same way.
    con = duckdb.connect()
    ddl = "\n".join(line for line in sql.splitlines() if not line.startswith(("--", "\\copy")))
    for stmt in [s for s in ddl.split(";") if s.strip()]:
        con.execute(stmt)
    for name in tables:
        literal = str(tmp_path / f"{name}.csv").replace("\\", "/")
        con.execute(f"INSERT INTO {name} SELECT * FROM read_csv('{literal}', header=true, all_varchar=false)") if tables[name] else None
    assert con.execute("select count(*) from pull_requests").fetchone()[0] == len(tables["pull_requests"])


def test_the_export_command_writes_a_postgres_folder(tmp_path, monkeypatch, capsys):
    from stackvitals.core import exportcli
    flow, repo, issues = fixture()
    monkeypatch.setattr(exportcli.services, "delivery_inputs",
                        lambda repo_name, days, tok, home, **kw: (flow, repo, {"runs": []}, issues, parse("")[0]))
    monkeypatch.setattr(exportcli, "_now", lambda: NOW)
    assert exportcli.main(["o/r", "--format", "postgres", "--out", str(tmp_path / "pg")], tok="tok") == 0
    assert (tmp_path / "pg" / "postgres.sql").is_file() and (tmp_path / "pg" / "pull_requests.csv").is_file()
    assert 'psql "$DATABASE_URL" -f postgres.sql' in capsys.readouterr().out
