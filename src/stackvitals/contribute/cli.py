import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from stackvitals.ci import cli as ci_cli
from stackvitals.ci.api import ActionsAPI, APIError, OutOfBudget
from stackvitals.contribute.brief import BriefError, build_brief, render, write_files
from stackvitals.core import services
from stackvitals.flow import peers
from stackvitals.flow.cli import local_gql
from stackvitals.flow.collect import collect as flow_collect
from stackvitals.flow.preflight import collect_asks
from stackvitals.flow.store import FlowStore


def ci_history(tok: str, repo: str, home: Path, now: datetime, days: int, make_api=ActionsAPI) -> tuple[dict | None, str]:
    """CI Health's findings: the repo's own published file when it runs StackVitals, else a short live read (the same
    reader as the MCP server and the CI CLI)."""
    try:
        result, source = services.ci_result(repo, days, tok, home, make_api=make_api, now=now)
    except (APIError, OutOfBudget, httpx.HTTPError) as exc:
        return None, f"CI history not read ({exc})"
    return result, "the repo's stackvitals-data branch" if source == "stackvitals-data branch" else source


def gather(repo: str, tok: str, now: datetime, months: int, ci_days: int, make_gql=local_gql, make_api=ActionsAPI):
    home = ci_cli.home()
    owner, name = repo.split("/", 1)
    store = FlowStore(home / "flow" / repo.replace("/", "__"))
    gql = make_gql(tok)
    flow_collect(gql, store, owner, name, now, months=months, log=lambda line: print(line, file=sys.stderr, flush=True))
    collect_asks(gql, store, owner, name, store.load()["closed"], cap=1000)
    ci, ci_source = ci_history(tok, repo, home, now, ci_days, make_api) if ci_days else (None, "CI not read")
    return store.load(), store.repo(), store.asks(), ci, peers.load(tok, home / "bench"), ci_source


def main(argv: list[str] | None = None, now: datetime | None = None, tok: str | None = None, gather_fn=gather) -> int:
    parser = argparse.ArgumentParser(prog="stackvitals contribute brief",
                                     description="How changes get merged in a repo, measured from its history (for agents and people).")
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--months", type=int, default=12, help="pull request history to read")
    parser.add_argument("--ci-days", type=int, default=14, help="days of CI runs to read when the repo doesn't run StackVitals (0: skip)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", metavar="DIR", help="also write an AGENTS.md section and Copilot path files into this folder")
    args = parser.parse_args(argv)
    tok = tok or ci_cli.token()
    if not tok:
        print("A GitHub token is needed. Set GITHUB_TOKEN, or run `gh auth login`.", file=sys.stderr)
        return 1
    now = now or datetime.now(timezone.utc)
    data, repo_info, asks, ci, bench, ci_source = gather_fn(args.repo, tok, now, args.months, args.ci_days)
    brief = build_brief(args.repo, data, repo_info, asks, ci, bench, now, months=args.months)
    if args.write:
        try:
            for path in write_files(brief, Path(args.write)):
                print(f"wrote {path}", file=sys.stderr)
        except BriefError as exc:
            print(f"Nothing written: {exc}", file=sys.stderr)
    print(json.dumps({**brief, "ci_source": ci_source}, indent=1) if args.json else render(brief))
    return 0
