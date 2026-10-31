import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from mergescout.github.graphql import GraphQLError
from stackvitals.ci.api import ActionsAPI, APIError, OutOfBudget
from stackvitals.ci.cli import home, token
from stackvitals.community.action import load_benchmarks, write_community_outputs
from stackvitals.community.build import build
from stackvitals.community.collect import _read, collect_issues, collect_stars, collect_traffic
from stackvitals.community.report import render_text
from stackvitals.flow.cli import local_gql
from stackvitals.flow.collect import collect
from stackvitals.flow.store import FlowStore


def local_community(repo: str, tok: str, now: datetime, months: int = 12, make_gql=local_gql, make_api=ActionsAPI,
                    root: Path | None = None, log=None) -> tuple[dict, dict]:
    """Read a repo's PRs (shared with Team Flow's local copy), issues, star history and, if this token may, traffic."""
    owner, name = repo.split("/", 1)
    root = Path(root or home())
    prs = FlowStore(root / "flow" / repo.replace("/", "__"))
    folder = root / "community" / repo.replace("/", "__")
    issues = FlowStore(folder, "issues")
    gql = make_gql(tok)
    got_prs = collect(gql, prs, owner, name, now, months=months, log=log)
    got = collect_issues(gql, issues, owner, name, now, months=months)
    notes = []
    try:
        collect_stars(make_api(tok, repo, max_requests=110), folder, now)
    except (APIError, OutOfBudget) as exc:
        notes.append(f"Star history wasn't read ({exc}).")
    try:
        # Only a token with Administration read on this repo (yours, if you own it) may read traffic.
        collect_traffic(make_api(tok, repo, max_requests=10), folder, now)
    except (APIError, OutOfBudget):
        pass
    bench, star_bench = load_benchmarks(root / "bench", tok)
    result = build(prs.load(), issues.load(), _read(folder / "stars.json"), _read(folder / "traffic.json"), prs.repo(), now,
                   bench=bench, star_bench=star_bench)
    return result, {"complete": got_prs["complete"] and got["complete"], "issues_refused": bool(got.get("refused")),
                    "notes": notes}


def main(argv: list[str] | None = None, now: datetime | None = None, make_gql=local_gql, make_api=ActionsAPI,
         tok: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stackvitals community",
                                     description="Community: where newcomers drop out and how fast they get a first answer.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rep = sub.add_parser("report", help="Read a repo's PRs, issues and stars and show its newcomer funnel and first answers")
    rep.add_argument("repo", help="owner/name")
    rep.add_argument("--months", type=int, default=12, help="history to read on the first run")
    rep.add_argument("--json", action="store_true")
    rep.add_argument("--html", help="also write the page and badges into this folder")
    args = parser.parse_args(argv)
    tok = tok or token()
    if not tok:
        print("A GitHub token is needed. Set GITHUB_TOKEN, or run `gh auth login`.", file=sys.stderr)
        return 1
    now = now or datetime.now(timezone.utc)
    try:
        result, stats = local_community(args.repo, tok, now, months=args.months, make_gql=make_gql, make_api=make_api,
                                        log=lambda line: print(line, file=sys.stderr, flush=True))
    except GraphQLError as exc:
        print(f"GitHub refused: {exc}", file=sys.stderr)
        return 1
    if args.html:
        write_community_outputs(Path(args.html), result, args.repo)
    if args.json:
        print(json.dumps({**result, "collect": stats}, indent=1))
        return 0
    print(render_text(result, args.repo))
    for note in stats["notes"]:
        print(f"\n({note})")
    if not stats["complete"]:
        print("\n(Not all pull requests and issues were read yet; run the same command again to continue.)")
    return 0
