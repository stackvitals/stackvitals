import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from mergescout.github.graphql import GitHubGraphQL, GraphQLError
from stackvitals.ci.cli import home, token
from stackvitals.flow.action import write_flow_outputs
from stackvitals.flow.build import build
from stackvitals.flow import peers
from stackvitals.flow.collect import collect
from stackvitals.flow.preflight import collect_asks, gaps, norms, preflight
from stackvitals.flow import triage as triage_mod
from stackvitals.flow.report import render_text
from stackvitals.flow.store import FlowStore


def local_gql(tok: str) -> GitHubGraphQL:
    # On the user's machine a short wait for the limit is fine.
    return GitHubGraphQL(tok, max_wait=120)


def load_model(tok: str | None) -> dict | None:
    from stackvitals.ci import bench as ci_bench
    return ci_bench.load(tok, home() / "bench", name=triage_mod.MODEL_FILE, url_env="STACKVITALS_TRIAGE_URL",
                         validate=triage_mod.valid, default_url=None)


def main(argv: list[str] | None = None, now: datetime | None = None, make_gql=local_gql, tok: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stackvitals flow", description="Team Flow: who acts next on pull requests.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rep = sub.add_parser("report", help="Read a repo's pull requests and show who acts next and how review flows")
    rep.add_argument("repo", help="owner/name")
    rep.add_argument("--months", type=int, default=12, help="history to read on the first run")
    rep.add_argument("--window", type=int, default=90, help="days the flow numbers cover")
    rep.add_argument("--json", action="store_true")
    rep.add_argument("--html", help="also write a dashboard into this folder (without people's answer times)")
    pre = sub.add_parser("preflight", help="What merged PRs here usually include, and what a planned PR is missing")
    pre.add_argument("repo", help="owner/name")
    pre.add_argument("--paths", nargs="+", default=[], help="files the PR changes")
    pre.add_argument("--lines", type=int, default=0, help="lines the PR adds plus removes")
    pre.add_argument("--months", type=int, default=12)
    tri = sub.add_parser("triage", help="Private: chance each open outside PR gets merged within 30 days, and why")
    tri.add_argument("repo", help="owner/name")
    tri.add_argument("--pr", type=int, default=0, help="only this PR")
    tri.add_argument("--months", type=int, default=12)
    args = parser.parse_args(argv)
    tok = tok or token()
    if not tok:
        print("A GitHub token is needed. Set GITHUB_TOKEN, or run `gh auth login`.", file=sys.stderr)
        return 1
    now = now or datetime.now(timezone.utc)
    owner, name = args.repo.split("/", 1)
    store = FlowStore(home() / "flow" / args.repo.replace("/", "__"))
    try:
        gql = make_gql(tok)
        stats = collect(gql, store, owner, name, now, months=args.months,
                        log=lambda line: print(line, file=sys.stderr, flush=True))
        collect_asks(gql, store, owner, name, store.load()["closed"], cap=1000)
    except GraphQLError as exc:
        print(f"GitHub refused: {exc}", file=sys.stderr)
        return 1
    if args.cmd == "triage":
        model = load_model(tok)
        if model is None:
            print("The triage model could not be read (it is published with the daily data).", file=sys.stderr)
            return 1
        data = store.load()
        if args.pr:
            data = {"open": [p for p in data["open"] if p["n"] == args.pr], "closed": data["closed"]}
        print(json.dumps(triage_mod.triage(data, model, now), indent=1))
        return 0
    if args.cmd == "preflight":
        data = store.load()
        prs = data["open"] + data["closed"]
        habits = norms(prs, args.paths, now)
        out = {"repo": args.repo, **habits, "gaps": gaps({"paths": args.paths, "add": args.lines}, habits),
               "asks": preflight(prs, store.asks(), args.paths, now)["asks"][:5]}
        print(json.dumps(out, indent=1))
        return 0
    # This view is the user's own, so it may include each reviewer's answer time.
    result = build(store.load(), store.repo(), now, owner=owner, people_speed=True, window_days=args.window,
                   asks=store.asks(), bench=peers.load(tok, home() / "bench"))
    if args.html:
        write_flow_outputs(Path(args.html), result, args.repo)
    if args.json:
        print(json.dumps({**result, "collect": stats}, indent=1))
    else:
        print(render_text(result, args.repo))
        if not stats["complete"]:
            print("\n(Not all pull requests were read yet; run the same command again to continue.)")
    return 0
