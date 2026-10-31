"""`stackvitals insights owner/repo`: findings that need two modules' history at once, for any repo, from your machine."""
import argparse
import json
import sys

import httpx

from stackvitals.ci import cli as ci_cli
from stackvitals.ci.api import APIError, OutOfBudget
from stackvitals.core import services
from stackvitals.core.insights import render


def main(argv: list[str] | None = None, tok: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stackvitals insights",
                                     description="What to fix first across modules, and how long merged pull requests sat "
                                                 "with failing checks, traced to the runs.")
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--days", type=int, default=30, help="CI history to read when the repo doesn't run StackVitals (max 90)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    tok = tok or ci_cli.token()
    if not tok:
        print("A GitHub token is needed. Set GITHUB_TOKEN, or run `gh auth login`.", file=sys.stderr)
        return 1
    days = max(1, min(args.days, 90))
    log = lambda line: print(line, file=sys.stderr, flush=True)  # noqa: E731
    try:
        found, _ = services.findings(args.repo, days, tok, ci_cli.home(), log=log)
        out, source = services.red_ci(args.repo, days, tok, ci_cli.home(), log=log)
    except (APIError, OutOfBudget, httpx.HTTPError) as exc:
        print(f"Could not read {args.repo}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"repo": args.repo, "source": source, "findings": found, "red_ci": out}, indent=1))
        return 0
    print("What to fix first:" if found else "What to fix first: nothing stands out yet.")
    for k, f in enumerate(found[:10], 1):
        links = ", ".join(e["url"] for e in f["evidence"][:3] if e["url"].startswith("https://"))
        print(f"  {k}. {f['title']} {f['action'] or ''} (n={f['n']}; {f['hours']} h at stake){' ' + links if links else ''}")
    print()
    print(render(out, args.repo) + f"\n(Source: {source}.)")
    return 0
