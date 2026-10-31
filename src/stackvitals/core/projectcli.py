"""`stackvitals project NAME owner/a owner/b ...`: one project's DORA across several repos, as an Apache DevLake project
counts it (its own SQL on the repos' tables pooled), next to each repo's own; no DevLake, MySQL or Grafana running."""
import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import httpx

from mergescout.github.graphql import GraphQLError
from stackvitals.ci import cli as ci_cli
from stackvitals.ci.api import APIError, OutOfBudget
from stackvitals.core import export, services

PANELS = ("deployment_frequency", "lead_time", "change_failure_rate", "recovery")


def project_dora(name: str, tables_by_repo: dict, start: datetime, end: datetime, report: str = "2023") -> dict:
    """{"project": DevLake's four panels on the pooled tables, "repos": {repo: its own four}}."""
    def four(tables: dict, project: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            export.write(tables, tmp)
            got = export.panels(tmp, start, end, report, project)
        return {k: got.get(k) for k in PANELS}
    return {"project": four(export.pool(tables_by_repo, name), name),
            "repos": {repo: four(t, repo) for repo, t in tables_by_repo.items()}}


def main(argv: list[str] | None = None, tok: str | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stackvitals project", description="DORA for one project across several repos.")
    ap.add_argument("name", help="the project's name")
    ap.add_argument("repos", nargs="+", help="owner/name of each repo in it")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    tok = tok or ci_cli.token()
    if not tok:
        print("A GitHub token is needed. Set GITHUB_TOKEN, or run `gh auth login`.", file=sys.stderr)
        return 1
    now = datetime.now(timezone.utc)
    days = max(1, min(a.days, 90))
    tables, report = {}, "2023"
    for repo in a.repos:
        try:
            flow, info, ci, issues, cfg = services.delivery_inputs(repo, days, tok, ci_cli.home(), now=now,
                                                                   log=lambda line: print(line, file=sys.stderr, flush=True))
        except (APIError, OutOfBudget, GraphQLError, httpx.HTTPError) as exc:
            print(f"Could not read {repo}: {exc}", file=sys.stderr)
            return 1
        report = cfg["delivery"]["dora_report"]
        tables[repo] = export.devlake_tables(repo, flow, info, ci, issues, cfg)
    try:
        out = project_dora(a.name, tables, now - timedelta(days=days), now, report)
    except ImportError:
        print("This needs DuckDB: pip install 'stackvitals[sql]'.", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps({"name": a.name, "days": days, **out}, indent=1, default=str))
        return 0
    print(f"{a.name}: {len(a.repos)} repos, last {days} days, DORA as Apache DevLake counts a project:")
    for k in PANELS:
        print(f"  {k.replace('_', ' '):24} {out['project'][k]}")
    for repo, p in out["repos"].items():
        print(f"  {repo}: " + "; ".join(f"{k.replace('_', ' ')} {p[k]}" for k in PANELS))
    return 0
