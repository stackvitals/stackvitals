"""Exports in other tools' shapes. DevLake: its domain tables (pull_requests, project_pr_metrics, cicd_deployment_commits,
incidents, issues and the project links) as JSON lines, with DevLake's own DORA dashboard SQL ported to DuckDB, so its
five DORA panels can be read off our data with no DevLake, MySQL or Grafana running."""
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from importlib import resources
from pathlib import Path

from stackvitals.connectors import tracker as tracked
from stackvitals.core import delivery
from stackvitals.core.delivery import _minutes_down, _minutes_up
from stackvitals.core.model import ChangeRequest, Issue, PipelineRun, cicd_result, entity_id

# Column types, so DuckDB reads an empty table too.
COLUMNS = {
    "project_mapping": {"project_name": "VARCHAR", "table": "VARCHAR", "row_id": "VARCHAR"},
    "pull_requests": {"id": "VARCHAR", "base_repo_id": "VARCHAR", "pull_request_key": "BIGINT", "title": "VARCHAR",
                      "status": "VARCHAR", "author_name": "VARCHAR", "author_id": "VARCHAR", "created_date": "TIMESTAMP",
                      "merged_date": "TIMESTAMP", "closed_date": "TIMESTAMP", "merge_commit_sha": "VARCHAR",
                      "additions": "BIGINT", "deletions": "BIGINT", "is_draft": "BOOLEAN", "base_ref": "VARCHAR",
                      "head_ref": "VARCHAR", "url": "VARCHAR"},
    "project_pr_metrics": {"id": "VARCHAR", "project_name": "VARCHAR", "first_commit_authored_date": "TIMESTAMP",
                           "pr_coding_time": "BIGINT", "pr_pickup_time": "BIGINT", "pr_review_time": "BIGINT",
                           "pr_deploy_time": "BIGINT", "pr_cycle_time": "BIGINT", "deployment_commit_id": "VARCHAR",
                           "first_comment_date": "TIMESTAMP", "pr_created_date": "TIMESTAMP", "pr_merged_date": "TIMESTAMP",
                           "pr_deployed_date": "TIMESTAMP"},
    "cicd_deployment_commits": {"id": "VARCHAR", "cicd_deployment_id": "VARCHAR", "cicd_scope_id": "VARCHAR", "name": "VARCHAR",
                                "result": "VARCHAR", "status": "VARCHAR", "environment": "VARCHAR", "commit_sha": "VARCHAR",
                                "finished_date": "TIMESTAMP", "source": "VARCHAR"},
    "incidents": {"id": "VARCHAR", "incident_key": "VARCHAR", "title": "VARCHAR", "status": "VARCHAR", "source": "VARCHAR",
                  "created_date": "TIMESTAMP", "resolution_date": "TIMESTAMP", "lead_time_minutes": "BIGINT",
                  "scope_id": "VARCHAR", "table": "VARCHAR", "url": "VARCHAR"},
    "project_incident_deployment_relationships": {"id": "VARCHAR", "project_name": "VARCHAR", "deployment_id": "VARCHAR"},
    "issues": {"id": "VARCHAR", "issue_key": "VARCHAR", "title": "VARCHAR", "type": "VARCHAR", "original_type": "VARCHAR",
               "status": "VARCHAR", "original_status": "VARCHAR", "story_point": "DOUBLE", "priority": "VARCHAR",
               "created_date": "TIMESTAMP", "updated_date": "TIMESTAMP", "resolution_date": "TIMESTAMP",
               "lead_time_minutes": "BIGINT", "creator_name": "VARCHAR", "url": "VARCHAR"},
    "issue_changelogs": {"id": "VARCHAR", "issue_id": "VARCHAR", "field_name": "VARCHAR", "original_from_value": "VARCHAR",
                         "original_to_value": "VARCHAR", "from_value": "VARCHAR", "to_value": "VARCHAR", "created_date": "TIMESTAMP"},
    "sprints": {"id": "VARCHAR", "name": "VARCHAR", "status": "VARCHAR", "started_date": "TIMESTAMP", "ended_date": "TIMESTAMP",
                "completed_date": "TIMESTAMP"},
    "sprint_issues": {"sprint_id": "VARCHAR", "issue_id": "VARCHAR"},
    "pull_request_issues": {"pull_request_id": "VARCHAR", "issue_id": "VARCHAR", "pull_request_key": "BIGINT", "issue_key": "VARCHAR"},
    "cicd_pipelines": {"id": "VARCHAR", "name": "VARCHAR", "result": "VARCHAR", "status": "VARCHAR", "original_status": "VARCHAR",
                       "original_result": "VARCHAR", "duration_sec": "BIGINT", "queued_duration_sec": "BIGINT",
                       "created_date": "TIMESTAMP", "queued_date": "TIMESTAMP", "started_date": "TIMESTAMP",
                       "finished_date": "TIMESTAMP", "environment": "VARCHAR", "type": "VARCHAR", "cicd_scope_id": "VARCHAR",
                       "display_title": "VARCHAR", "url": "VARCHAR"},
    "cicd_tasks": {"id": "VARCHAR", "name": "VARCHAR", "pipeline_id": "VARCHAR", "result": "VARCHAR", "status": "VARCHAR",
                   "original_status": "VARCHAR", "original_result": "VARCHAR", "type": "VARCHAR", "environment": "VARCHAR",
                   "duration_sec": "BIGINT", "queued_duration_sec": "BIGINT", "started_date": "TIMESTAMP",
                   "finished_date": "TIMESTAMP", "created_date": "TIMESTAMP", "queued_date": "TIMESTAMP", "cicd_scope_id": "VARCHAR"},
    "cicd_pipeline_commits": {"pipeline_id": "VARCHAR", "commit_sha": "VARCHAR", "branch": "VARCHAR", "repo_id": "VARCHAR",
                              "repo_url": "VARCHAR"},
}
PANELS = ("deployment_frequency", "lead_time", "change_failure_rate", "recovery", "monthly", "pr_cycle_time")


def devlake_tables(repo: str, flow: dict, info: dict, ci: dict, issues: list[dict], cfg: dict,
                   tracker: dict | None = None, ci_since: str | None = None) -> dict[str, list[dict]]:
    """Our records in DevLake's domain layer: ids, names and enums as DevLake writes them, its PR metrics in whole minutes;
    with a connected tracker, its issues, status changes, sprints and the PRs that name them too."""
    flow = delivery.apply_identity(flow, cfg.get("identity"))
    deps, _source, rows = delivery.shipped(flow, info, ci, cfg)
    scope = entity_id("Repo", repo, repo)
    deployment_row = {d["id"]: entity_id("CicdDeploymentCommit", repo, d["id"]) for d in deps}
    out = {name: [] for name in COLUMNS}
    out["project_mapping"] = [{"project_name": repo, "table": t, "row_id": scope} for t in ("repos", "cicd_scopes")]
    out["cicd_deployment_commits"] = [
        {"id": deployment_row[d["id"]], "cicd_deployment_id": entity_id("CicdDeployment", repo, d["id"]), "cicd_scope_id": scope,
         "name": d.get("name"), "result": "SUCCESS", "status": "DONE", "environment": "PRODUCTION", "commit_sha": d.get("sha"),
         "finished_date": d["finished"], "source": d.get("source")} for d in deps]
    closed, opened = flow.get("closed") or [], flow.get("open") or []
    for rec in closed + opened:
        row = ChangeRequest.from_flow(rec, repo).to_devlake()
        out["pull_requests"].append({**{k: row.get(k) for k in COLUMNS["pull_requests"]}, "base_repo_id": scope,
                                     "merge_commit_sha": rec.get("mc")})
    for p, ph, dep in rows:
        first = ph["first_activity"]
        out["project_pr_metrics"].append({
            "id": entity_id("PullRequest", repo, p["n"]), "project_name": repo, "first_commit_authored_date": p.get("fa"),
            "pr_coding_time": _minutes_up(p.get("fa"), p["cr"]), "pr_pickup_time": _minutes_up(p["cr"], first),
            "pr_review_time": _minutes_up(first, p["mg"]), "pr_deploy_time": _minutes_up(p["mg"], dep["finished"]) if dep else None,
            "pr_cycle_time": ph["devlake_cycle_min"], "deployment_commit_id": deployment_row[dep["id"]] if dep else None,
            "first_comment_date": first, "pr_created_date": p["cr"], "pr_merged_date": p["mg"],
            "pr_deployed_date": dep["finished"] if dep else None})
    for inc in delivery.incidents_for(closed + opened, issues, deps, cfg, tracker)[0]:
        key = entity_id("Incident", repo, f"{inc['source']}:{inc['number']}")
        kind = "issues" if inc["source"] == "issue" else "pull"
        out["incidents"].append({"id": key, "incident_key": str(inc["number"]), "title": None,
                                 "status": "DONE" if inc["resolved"] else "TODO", "source": inc["source"],
                                 "created_date": inc["created"], "resolution_date": inc["resolved"],
                                 "lead_time_minutes": _minutes_down(inc["created"], inc["resolved"]), "scope_id": scope,
                                 "table": "repos", "url": inc.get("url") or f"https://github.com/{repo}/{kind}/{inc['number']}"})
        if inc["deployment"]:
            out["project_incident_deployment_relationships"].append(
                {"id": key, "project_name": repo, "deployment_id": entity_id("CicdDeployment", repo, inc["deployment"])})
    labels = cfg["delivery"]["incident_labels"]
    for rec in issues or []:
        i = Issue.from_community(rec, repo, incident_labels=[x.lower() for x in labels])
        out["issues"].append({**dict.fromkeys(COLUMNS["issues"]), "id": i.id, "issue_key": str(i.number), "type": i.type,
                              "status": i.status, "created_date": i.created_at, "resolution_date": i.closed_at,
                              "lead_time_minutes": _minutes_down(i.created_at, i.closed_at), "creator_name": i.author,
                              "url": f"https://github.com/{repo}/issues/{i.number}"})
    # Every CI run attempt with its jobs, as DevLake's cicd tables (pipelines, tasks, the commit each ran on).
    jobs = defaultdict(list)
    for j in (ci or {}).get("jobs") or []:
        jobs[(j["run"], j.get("att", 1))].append(j)
    for run in (ci or {}).get("runs") or []:
        if ci_since and (run.get("cr") or "") < ci_since:
            continue  # the summary on the data branch keeps recent runs only; `stackvitals export` keeps them all
        rows = PipelineRun.from_ci(run, jobs[(run["id"], run.get("att", 1))], repo).to_devlake(scope)
        out["cicd_pipelines"].append(rows["cicd_pipelines"])
        out["cicd_tasks"] += rows["cicd_tasks"]
        out["cicd_pipeline_commits"] += rows["cicd_pipeline_commits"]
    if tracker:
        _tracker_rows(out, repo, closed + opened, tracker)
    return out


def _tracker_rows(out: dict, repo: str, prs: list[dict], tracker: dict) -> None:
    category = {i.get("status"): i.get("cat") for i in tracker["issues"]}
    for i in tracker["issues"]:
        done = i.get("cat") == "DONE"
        out["issues"].append({**dict.fromkeys(COLUMNS["issues"]), "id": i["id"], "issue_key": i["key"], "title": i.get("title"),
                              "type": i.get("type"), "original_type": i.get("original_type"), "status": i.get("cat"),
                              "original_status": i.get("status"), "story_point": i.get("points"), "priority": i.get("priority"),
                              "created_date": i.get("created"), "updated_date": i.get("updated"),
                              "resolution_date": i.get("resolved") if done else None,
                              "lead_time_minutes": _minutes_down(i.get("created"), i.get("resolved"))
                              if done and not i.get("canceled") else None, "url": i.get("url")})
        out["sprint_issues"] += [{"sprint_id": sid, "issue_id": i["id"]} for sid in i.get("sprints") or []]
    for c in tracker["changes"]:
        status = c.get("field") == "status"
        text = (lambda v: v) if status else (lambda v: ",".join(v or []))
        out["issue_changelogs"].append({"id": c["id"], "issue_id": c["issue"], "field_name": "status" if status else "Sprint",
                                        "original_from_value": text(c.get("from")), "original_to_value": text(c.get("to")),
                                        "from_value": category.get(c.get("from")) if status else text(c.get("from")),
                                        "to_value": category.get(c.get("to")) if status else text(c.get("to")),
                                        "created_date": c.get("at")})
    out["sprints"] = [{"id": s["id"], "name": s.get("name"), "status": s.get("state"), "started_date": s.get("start"),
                       "ended_date": s.get("end"), "completed_date": s.get("complete")} for s in tracker["sprints"]]
    ids = {i["key"]: i["id"] for i in tracker["issues"]}
    out["pull_request_issues"] = [{"pull_request_id": entity_id("PullRequest", repo, n), "issue_id": ids[key],
                                   "pull_request_key": n, "issue_key": key} for n, key in tracked.pr_links(prs, tracker["issues"])]


def _sql_text() -> str:
    return resources.files("stackvitals.core").joinpath("devlake_dora.sql").read_text(encoding="utf-8")


def _literal(path: Path | str) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def setup_sql(folder: Path | str | None = None) -> str:
    """CREATE TABLE statements reading each exported file (relative names when no folder is given)."""
    lines = []
    for name, cols in COLUMNS.items():
        spec = ", ".join(f"'{c}': '{t}'" for c, t in cols.items())
        where = _literal(Path(folder) / f"{name}.jsonl") if folder else f"{name}.jsonl"
        lines.append(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_json('{where}', format='newline_delimited', "
                     f"columns={{{spec}}});")
    lines.append("CREATE OR REPLACE TABLE calendar_months AS SELECT strftime(m, '%y/%m') AS month, CAST(m AS date) AS month_timestamp "
                 "FROM range(TIMESTAMP '2000-01-01', TIMESTAMP '2100-01-01', INTERVAL 1 MONTH) t(m);")
    return "\n".join(lines)


def panel_sql(start: datetime, end: datetime, report: str, project: str) -> dict[str, str]:
    """DevLake's five DORA panels with the time range, project and report filled in."""
    fill = {"{{FROM}}": start.strftime("%Y-%m-%d %H:%M:%S"), "{{TO}}": end.strftime("%Y-%m-%d %H:%M:%S"),
            "{{PROJECT}}": project.replace("'", "''"), "{{REPORT}}": "2021" if report == "2021" else "2023"}
    out = {}
    for chunk in _sql_text().split("-- panel: ")[1:]:
        name, body = chunk.split("\n", 1)
        for key, value in fill.items():
            body = body.replace(key, value)
        out[name.strip()] = body.strip()
    return out


def write(tables: dict[str, list[dict]], folder: Path | str, start: datetime | None = None, end: datetime | None = None,
          report: str = "2023", project: str | None = None) -> Path:
    """One JSON-lines file per table, and dora.sql: run `duckdb < dora.sql` inside the folder to see DevLake's panels."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        with open(folder / f"{name}.jsonl", "w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    script = [setup_sql()]
    if start and end and project:
        script += [f"-- {name}\n{sql}" for name, sql in panel_sql(start, end, report, project).items()]
    (folder / "dora.sql").write_text("\n\n".join(script) + "\n", encoding="utf-8")
    return folder


def pool(tables_by_repo: dict[str, dict[str, list[dict]]], project: str) -> dict[str, list[dict]]:
    """Several repos' DevLake tables as one DevLake project: rows side by side (their ids already name the repo), and
    every repo's scopes mapped to the project, so DevLake's own SQL gives the project's DORA across them."""
    out = {name: [] for name in COLUMNS}
    for tables in tables_by_repo.values():
        for name, rows in tables.items():
            if name == "project_mapping":
                out[name] += [{**r, "project_name": project} for r in rows]
            else:
                out.setdefault(name, []).extend(rows)
    return out


def panels(folder: Path | str, start: datetime, end: datetime, report: str, project: str) -> dict:
    """DevLake's DORA panels computed by DuckDB on an export folder: four strings as DevLake shows them, and the
    monthly deployments as (month, count) rows."""
    import duckdb
    con = duckdb.connect()
    for stmt in setup_sql(folder).split(";\n"):
        con.execute(stmt.rstrip(";"))
    out = {}
    for name, sql in panel_sql(start, end, report, project).items():
        rows = con.execute(sql.rstrip(";")).fetchall()
        out[name] = [tuple(r) for r in rows] if name in ("monthly", "pr_cycle_time") else (rows[0][0] if rows else None)
    return out


def ctrf(repo: str, result: dict, start: datetime, end: datetime) -> dict:
    """CI Health's tests as a CTRF report: each test once, failed when it is broken now, flagged flaky when it flakes,
    with its history over the window under `extra`."""
    tests = []
    for t in result.get("tests") or []:
        test = {"name": t["id"], "status": "failed" if t.get("state") == "broken" else "passed", "duration": 0,
                "suite": t.get("suite"), "flaky": t.get("state") == "flaky",
                "extra": {k: t.get(k) for k in ("runs", "failures", "flake_events", "flake_rate", "state", "since")}}
        if t.get("message"):
            test["message"] = t["message"]
        tests.append(test)
    failed = sum(1 for t in tests if t["status"] == "failed")
    return {"results": {"tool": {"name": "stackvitals"},
                        "summary": {"tests": len(tests), "passed": len(tests) - failed, "failed": failed, "skipped": 0,
                                    "pending": 0, "other": 0, "start": int(start.timestamp() * 1000),
                                    "stop": int(end.timestamp() * 1000)},
                        "tests": tests,
                        "environment": {"repositoryName": repo, "repositoryUrl": f"https://github.com/{repo}"}}}


PG_TYPES = {"VARCHAR": "TEXT", "TIMESTAMP": "TIMESTAMPTZ", "BIGINT": "BIGINT", "BOOLEAN": "BOOLEAN", "DOUBLE": "DOUBLE PRECISION"}


def _ns(ts: str | None) -> str:
    return str(int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 10 ** 9)) if ts else "0"


def _span_id(*parts, n: int = 16) -> str:
    # The same run always gets the same ids, so sending an export twice doesn't make two traces.
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:n]


def _attrs(values: dict) -> list[dict]:
    return [{"key": k, "value": {"intValue": str(v)} if isinstance(v, int) and not isinstance(v, bool) else {"stringValue": str(v)}}
            for k, v in values.items() if v is not None]


def _status(conclusion: str | None) -> dict:
    return {"code": 2 if conclusion in ("failure", "timed_out") else 1 if conclusion == "success" else 0}


def otel_traces(repo: str, data: dict) -> dict:
    """The CI history as OpenTelemetry traces (OTLP JSON): one trace per run attempt, a span per job and per step, and
    each failed or flaky test as an event on the run, with OpenTelemetry's CI/CD attribute names."""
    jobs, tests = defaultdict(list), defaultdict(list)
    for j in data.get("jobs") or []:
        jobs[(j["run"], j["att"])].append(j)
    for t in data.get("tests") or []:
        tests[(t["run"], t["att"])].append(t)
    spans = []
    for run in sorted(data.get("runs") or [], key=lambda r: (r.get("cr") or "", r["id"], r["att"])):
        key = (run["id"], run["att"])
        trace, root = _span_id(repo, *key, n=32), _span_id(repo, *key, "run")
        attrs = {k: v for k, v in PipelineRun.from_ci(run, jobs[key], repo).to_otel().items() if v is not None}
        events = [{"name": f"test.{kind}", "timeUnixNano": _ns(run.get("up")),
                   "attributes": _attrs({"test.case.name": tid, "test.suite.name": rep.get("name"),
                                         **({"exception.message": msg} if msg else {})})}
                  for rep in tests[key] for kind, rows in (("failed", rep.get("failed") or []), ("flaky", rep.get("flaky") or []))
                  for tid, msg in ((r[0], r[2] if len(r) > 2 else None) if isinstance(r, list) else (r, None) for r in rows)]
        # A job or step with no times of its own takes its parent's, so no span starts in 1970.
        run_start, run_end = run.get("st") or run.get("cr"), run.get("up") or run.get("st") or run.get("cr")
        spans.append({"traceId": trace, "spanId": root, "name": f"{run.get('wfn') or run.get('path')} #{run['id']}", "kind": 1,
                      "startTimeUnixNano": _ns(run_start), "endTimeUnixNano": _ns(run_end),
                      "attributes": _attrs(attrs), "status": _status(run.get("c")), "events": events})
        for j in sorted(jobs[key], key=lambda j: (j.get("st") or "", j["id"])):
            job = _span_id(repo, *key, j["id"])
            job_start, job_end = j.get("st") or run_start, j.get("en") or run_end
            spans.append({"traceId": trace, "spanId": job, "parentSpanId": root, "name": j.get("n") or "job", "kind": 1,
                          "startTimeUnixNano": _ns(job_start), "endTimeUnixNano": _ns(job_end),
                          "attributes": _attrs({"cicd.pipeline.task.name": j.get("n"), "cicd.pipeline.task.run.id": j["id"],
                                                "cicd.pipeline.task.run.result": cicd_result(j.get("c")).lower(),
                                                "cicd.worker.labels": ",".join(j.get("lb") or []) or None}),
                          "status": _status(j.get("c"))})
            for step in j.get("steps") or []:
                number, name, conclusion = step[0], step[1], step[2]
                spans.append({"traceId": trace, "spanId": _span_id(repo, *key, j["id"], number), "parentSpanId": job,
                              "name": name or f"step {number}", "kind": 1,
                              "startTimeUnixNano": _ns((step[3] if len(step) > 3 else None) or job_start),
                              "endTimeUnixNano": _ns((step[4] if len(step) > 4 else None) or job_end), "attributes": [],
                              "status": _status(conclusion)})
    return {"resourceSpans": [{"resource": {"attributes": _attrs({"service.name": "ci", "vcs.repository.name": repo})},
                               "scopeSpans": [{"scope": {"name": "stackvitals"}, "spans": spans}]}]}


def postgres_ddl() -> str:
    """CREATE TABLE statements for DevLake's tables in Postgres (Neon, Supabase, Aiven or your own), from the same columns
    the export writes; `table` is quoted as Postgres needs."""
    out = []
    for name, cols in COLUMNS.items():
        lines = [f'  "{c}" {PG_TYPES[t]}' if c == "table" else f"  {c} {PG_TYPES[t]}" for c, t in cols.items()]
        if "id" in cols and name != "project_incident_deployment_relationships":
            lines.append("  PRIMARY KEY (id)")
        out.append(f"CREATE TABLE IF NOT EXISTS {name} (\n" + ",\n".join(lines) + "\n);")
    return "\n\n".join(out)


def write_postgres(tables: dict[str, list[dict]], folder: Path | str) -> Path:
    """One CSV per table and postgres.sql: `psql "$DATABASE_URL" -f postgres.sql` in that folder creates and loads them."""
    import csv
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    loads = []
    for name, rows in tables.items():
        cols = list(COLUMNS[name])
        with open(folder / f"{name}.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for r in rows:
                w.writerow(["" if r.get(c) is None else r.get(c) for c in cols])
        if rows:
            loads.append(f"\\copy {name} FROM '{name}.csv' WITH (FORMAT csv, HEADER true)")
    text = ("-- DevLake's tables from a StackVitals export. Run in this folder: psql \"$DATABASE_URL\" -f postgres.sql\n"
            "-- Loading twice adds the rows again: start from an empty database, or delete the rows first.\n\n"
            + postgres_ddl() + "\n\n" + "\n".join(loads) + "\n")
    (folder / "postgres.sql").write_text(text, encoding="utf-8", newline="\n")
    return folder
