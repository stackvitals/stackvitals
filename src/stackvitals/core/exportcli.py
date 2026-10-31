"""`stackvitals export owner/repo --format devlake`: a repo's pull requests, PR metrics, deployments and incidents in
Apache DevLake's table shapes, with DevLake's DORA dashboard SQL ported to DuckDB beside them (dora.sql)."""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from mergescout.github.graphql import GraphQLError
from stackvitals.ci import cli as ci_cli
from stackvitals.ci.api import APIError, OutOfBudget
from stackvitals.core import export, services

FORMATS = ("devlake", "ctrf", "postgres", "otel")
LABELS = {"deployment_frequency": "Deployment frequency", "lead_time": "Median lead time for changes (hours)",
          "change_failure_rate": "Change failure rate", "recovery": "Recovery time (hours)"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def main(argv: list[str] | None = None, tok: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stackvitals export", description="Export a repo's delivery data in another tool's shape.")
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--format", default="devlake",
                        help="devlake (Apache DevLake's domain tables), ctrf (tests as a CTRF report, with their history) or "
                             "postgres (DevLake's tables as CSV plus postgres.sql to create and load them) or otel "
                             "(CI runs, jobs, steps and failed tests as OpenTelemetry traces, OTLP JSON)")
    parser.add_argument("--out", help="where to write (default: ./<owner>__<name>-devlake, or <owner>__<name>-ctrf.json)")
    parser.add_argument("--days", type=int, default=90, help="history to read (max 90 for CI runs)")
    parser.add_argument("--tests", action="store_true",
                        help="otel: also download test reports, for failed and flaky tests as events (one request per artifact)")
    parser.add_argument("--report", default=None, help="DORA report for the panels: 2023 or 2021 (default: the repo's setting)")
    args = parser.parse_args(argv)
    if args.format not in FORMATS:
        print(f"Unknown format {args.format!r}; formats: {', '.join(FORMATS)}.", file=sys.stderr)
        return 2
    tok = tok or ci_cli.token()
    if not tok:
        print("A GitHub token is needed. Set GITHUB_TOKEN, or run `gh auth login`.", file=sys.stderr)
        return 1
    days = max(1, min(args.days, 90))
    now = _now()
    if args.format == "ctrf":
        return _ctrf(args, tok, days, now)
    if args.format == "otel":
        return _otel(args, tok, days, now)
    try:
        flow, info, ci, issues, cfg = services.delivery_inputs(args.repo, days, tok, ci_cli.home(), now=now,
                                                               log=lambda line: print(line, file=sys.stderr, flush=True))
    except (APIError, OutOfBudget, GraphQLError, httpx.HTTPError) as exc:
        print(f"Could not read {args.repo}: {exc}", file=sys.stderr)
        return 1
    report = args.report or cfg["delivery"]["dora_report"]
    out = Path(args.out or f"{args.repo.replace('/', '__')}-{args.format}")
    start = now - timedelta(days=days)
    tables = export.devlake_tables(args.repo, flow, info, ci, issues, cfg)
    if args.format == "postgres":
        export.write_postgres(tables, out)
        print(f"Wrote {sum(len(v) for v in tables.values())} rows in {len(tables)} tables to {out}. Load them with: "
              f"cd {out} && psql \"$DATABASE_URL\" -f postgres.sql")
        return 0
    export.write(tables, out, start, now, report, args.repo)
    print(f"Wrote {sum(len(v) for v in tables.values())} rows in {len(tables)} DevLake tables to {out} "
          f"({len(tables['cicd_deployment_commits'])} deployments, {len(tables['project_pr_metrics'])} merged PRs).")
    try:
        panels = export.panels(out, start, now, report, args.repo)
    except ImportError:
        print("Install DuckDB (pip install 'stackvitals[sql]') to see DevLake's DORA panels; or run `duckdb < dora.sql` there.")
        return 0
    print(f"DevLake's DORA dashboard ({report} report), computed by its own SQL on this export, last {days} days:")
    for key, label in LABELS.items():
        print(f"  {label}: {panels[key] or 'no data'}")
    print("  Monthly deployments: " + ", ".join(f"{m} {n}" for m, n in panels["monthly"]))
    return 0


def _otel(args, tok: str, days: int, now: datetime) -> int:
    import json

    from stackvitals.ci.api import ActionsAPI
    from stackvitals.ci.collect import collect
    from stackvitals.ci.store import DataStore
    store = DataStore(ci_cli.home() / "ci" / args.repo.replace("/", "__"))
    try:
        collect(ActionsAPI(tok, args.repo, max_requests=3000), store, now, days=days, tests=args.tests,
                log=lambda line: print(line, file=sys.stderr, flush=True))
    except (APIError, OutOfBudget, httpx.HTTPError) as exc:
        print(f"Stopped reading {args.repo} early ({exc}); exporting what was read.", file=sys.stderr)
    traces = export.otel_traces(args.repo, store.load())
    out = Path(args.out or f"{args.repo.replace('/', '__')}-otel.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(traces), encoding="utf-8")
    spans = traces["resourceSpans"][0]["scopeSpans"][0]["spans"]
    print(f"Wrote {sum('parentSpanId' not in s for s in spans)} runs as {len(spans)} spans to {out}. Send it to any "
          f"OpenTelemetry collector: curl -X POST -H 'Content-Type: application/json' --data @{out} <collector>/v1/traces")
    return 0


def _ctrf(args, tok: str, days: int, now: datetime) -> int:
    import json
    try:
        result, source = services.ci_result(args.repo, days, tok, ci_cli.home(),
                                            log=lambda line: print(line, file=sys.stderr, flush=True))
    except (APIError, OutOfBudget, httpx.HTTPError) as exc:
        print(f"Could not read {args.repo}: {exc}", file=sys.stderr)
        return 1
    report = export.ctrf(args.repo, result, now - timedelta(days=result.get("window_days") or days), now)
    out = Path(args.out or f"{args.repo.replace('/', '__')}-ctrf.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    s = report["results"]["summary"]
    print(f"Wrote {s['tests']} tests ({s['failed']} broken now, {sum(t['flaky'] for t in report['results']['tests'])} flaky) "
          f"as CTRF to {out} ({source}).")
    return 0
