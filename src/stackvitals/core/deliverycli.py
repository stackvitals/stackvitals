"""`stackvitals delivery owner/repo`: cycle time phases, DORA, stuck pull requests and sizes for any repo, from the repo's
published file when it runs StackVitals, else from its pull requests and CI runs read with your token."""
import argparse
import json
import sys

import httpx

from mergescout.github.graphql import GraphQLError
from stackvitals.ci import cli as ci_cli
from stackvitals.ci.api import APIError, OutOfBudget
from stackvitals.core import services
from stackvitals.core.delivery_report import NAMES, _h


def main(argv: list[str] | None = None, tok: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stackvitals delivery", description="Cycle time, DORA and stuck pull requests.")
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--days", type=int, default=90, help="history to read and measure (max 90 for CI runs)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--deploys", action="store_true",
                        help="the deploy dry run: which deployments count, which workflows and environments don't, and why")
    parser.add_argument("--gitlab", action="store_true", help="a GitLab project (group/project): merge requests and deployments")
    parser.add_argument("--bitbucket", action="store_true", help="a Bitbucket Cloud repo (workspace/repo): pull requests and deployments")
    parser.add_argument("--azure", action="store_true", help="an Azure DevOps repo (org/project/repo): pull requests")
    args = parser.parse_args(argv)
    if args.gitlab or args.bitbucket or args.azure:
        host = "gitlab" if args.gitlab else "bitbucket" if args.bitbucket else "azure"
        out, source = (_gitlab if host == "gitlab" else _host)(args.repo, max(1, min(args.days, 90)), *([] if host == "gitlab" else [host]))
        if out is None:
            return 1
        return _show(args, out, source)
    tok = tok or ci_cli.token()
    if not tok:
        print("A GitHub token is needed. Set GITHUB_TOKEN, or run `gh auth login`.", file=sys.stderr)
        return 1
    try:
        out, source = services.delivery(args.repo, max(1, min(args.days, 90)), tok, ci_cli.home(),
                                        log=lambda line: print(line, file=sys.stderr, flush=True))
    except (APIError, OutOfBudget, GraphQLError, httpx.HTTPError) as exc:
        print(f"Could not read {args.repo}: {exc}", file=sys.stderr)
        return 1
    return _show(args, out, source)


def _gitlab(project: str, days: int):
    from datetime import datetime, timezone

    from stackvitals.ci.gitlab import GitLab, token
    from stackvitals.core.config import parse
    from stackvitals.core.delivery import build
    from stackvitals.flow import gitlab_mr
    now = datetime.now(timezone.utc)
    try:
        flow, repo = gitlab_mr.collect(GitLab(project, token()), now, days)
    except (APIError, OutOfBudget, httpx.HTTPError) as exc:
        print(f"Could not read {project} on GitLab: {exc}", file=sys.stderr)
        return None, None
    return build(flow, repo, {"runs": []}, [], now, days, parse("")[0]), "GitLab merge requests"


def _host(repo: str, days: int, host: str):
    from datetime import datetime, timezone

    from stackvitals.core.config import parse
    from stackvitals.core.delivery import build
    from stackvitals.flow import code_hosts
    now = datetime.now(timezone.utc)
    name = {"bitbucket": "Bitbucket", "azure": "Azure DevOps"}[host]
    try:
        flow, facts = getattr(code_hosts, host)(repo, now, days)
    except (APIError, OutOfBudget, httpx.HTTPError, ValueError) as exc:
        print(f"Could not read {repo} on {name}: {exc}", file=sys.stderr)
        return None, None
    return build(flow, facts, {"runs": []}, [], now, days, parse("")[0]), f"{name} pull requests"


def _show(args, out: dict, source: str) -> int:
    if args.json:
        print(json.dumps({"repo": args.repo, "source": source, "delivery": out}, indent=1))
        return 0
    if args.deploys:
        print(deploy_dry_run(args.repo, out.get("deploy_check") or {}))
        return 0
    d = out["dora"]
    print(f"Delivery in {args.repo}: {out['prs']} merged PRs in {out['window_days']} days ({source}).")
    for name, label in NAMES.items():
        s = out["phases"][name]
        if not s.get("enough", True):
            print(f"  {label:20} not enough data (n={s['n']}, needs 10)")
            continue
        print(f"  {label:20} P50 {_h(s['p50_h']):>10}  P75 {_h(s['p75_h']):>10}  n={s['n']}"
              + (f"  ({s['linearb_band']})" if s["linearb_band"] else ""))
    def tier(value):
        return value or "not enough data"
    cfr = "-" if d["change_failure_rate"] is None else f"{d['change_failure_rate']:.0%}"
    print(f"DORA {d['report']} (deployments from {out['deploy_source'] or 'none found'}, {d['deployments']} in the window): "
          f"{d['deployment_days_per_week']} deployment days a week ({tier(d['frequency_tier'])}), lead time "
          f"{_h(d['lead_time_hours'])} ({tier(d['lead_time_tier'])}), change failure rate {cfr} ({tier(d['cfr_tier'])}), "
          f"recovery {_h(d['recovery_hours'])} ({tier(d['recovery_tier'])}).")
    if out.get("deploy_confidence") == "low":
        names = ", ".join(f"{x['name']} ({x['n']})" for x in out.get("deploy_names") or [])
        print(f"Deployments are a guess from workflow names: {names}. If that is not how this repo ships, set "
              "source or deploy_workflow under [delivery] in .github/stackvitals.toml.")
    peers = out.get("peers")
    if peers:
        print(f"Compared with {peers['group']} ({peers['repos']} repos in the daily crawl, measured the crawl's way):")
        for m in peers["metrics"]:
            good = f"; {m['linearb']['good']:.0%} of them inside LinearB's good band" if m.get("linearb") else ""
            print(f"  {m['name']}: {_h(m['you'])}, typical {_h(m['typical'])} ({_h(m['low'])}-{_h(m['high'])}), "
                  f"{m['place']}{good}")
    for key, items in out["stuck"].items():
        if items:
            print(f"Stuck, {key.replace('_', ' ')}: " + ", ".join(f"#{x['pr']}" for x in items[:15]))
    return 0


def deploy_dry_run(repo: str, c: dict) -> str:
    """The deploy dry run as plain lines."""
    s = c.get("settings") or {}
    out = [f"Deployments in {repo}: {c.get('deployments', 0)} from {c.get('source') or 'no source'} "
           f"([delivery] source = \"{s.get('source')}\", deploy_workflow = \"{s.get('deploy_workflow')}\", "
           f"production = {s.get('production')})."]
    for x in c.get("considered") or []:
        out.append(f"  {'counted' if x['used'] else 'passed over':12} {x['source']}: {x['found']}")
    if c.get("order_reason"):
        out.append(f"  ({c['order_reason']})")
    flows = c.get("workflows") or []
    if flows:
        out.append("Workflows:")
        for f in flows:
            if not f["kind"]:
                runs = ""
            elif f.get("used"):
                runs = f" ({f['counted']} runs counted, {f['skipped']} skipped: failed, or not a release or the default branch)"
            else:
                runs = f" (passed over: {c['source'] or 'nothing'} is the source used)"
            out.append(f"  {f['name']} ({f['path']}): {f['why']}{runs}")
    envs = c.get("environments") or []
    if envs:
        out.append("Environments:")
        out += [f"  {e['name']}: {e['deployments']} deployments, {'counted' if e['counted'] else 'not counted'} ({e['as']})"
                for e in envs]
    r = c.get("releases") or {}
    out.append(f"Releases: {r.get('published', 0)} published, {r.get('prereleases_skipped', 0)} prereleases skipped.")
    out.append("To change what counts, set source, deploy_workflow or production under [delivery] in .github/stackvitals.toml.")
    return "\n".join(out)
