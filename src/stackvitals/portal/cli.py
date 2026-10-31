import argparse
import json
import sys
from datetime import datetime, timezone

from stackvitals.ci.api import ActionsAPI
from stackvitals.ci.cli import ACTION_REF, home, token
from stackvitals.flow.cli import local_gql as _gql
from stackvitals.portal.catalog import build_catalog
from stackvitals.portal.github import NA, read, read_file
from stackvitals.portal.inventory import list_repos

WORKFLOW = """name: StackVitals Portal
on:
  schedule:
    - cron: "41 5 * * *"   # once a day
  workflow_dispatch:
    inputs:
      request:
        description: "A request from the StackVitals app, like a golden path (leave empty for a normal run)"
        required: false
        default: ""
  issues:
    types: [opened]          # golden path requests from the app, run at once
  issue_comment:
    types: [created]         # "/stackvitals approve" on a golden path that needs an approval
permissions:
  contents: write          # keeps the catalog, its history and the pages in this repo's stackvitals-data branch
  issues: write            # one tracking issue per campaign, and answers to requests, in this repo only
concurrency:
  group: stackvitals-portal
  cancel-in-progress: false
jobs:
  portal:
    # Request issues start a run only when someone with access to this repo opened one with a StackVitals block.
    if: >-
      (github.event_name != 'issues' ||
       (contains(github.event.issue.body, '```stackvitals') &&
        contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.issue.author_association))) &&
      (github.event_name != 'issue_comment' ||
       (startsWith(github.event.comment.body, '/stackvitals approve') &&
        contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.comment.author_association)))
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      # Private repos: create an org-owned read-only GitHub App (see docs/modules.md), store its client ID and key, then switch on.
      # - uses: actions/create-github-app-token@64ab729a6294000f5aa4a4bc0b73d1f32bc45510 # v3
      #   id: app
      #   with:
      #     client-id: ${{{{ vars.PORTAL_CLIENT_ID }}}}
      #     private-key: ${{{{ secrets.PORTAL_PRIVATE_KEY }}}}
      #     owner: ${{{{ github.repository_owner }}}}
      - uses: {ref}
        with:
          modules: portal
          # portal-token: ${{{{ steps.app.outputs.token }}}}
"""


def _scorecard_client():
    import httpx
    return httpx.Client(timeout=20)


def app_link(org: str, writes: bool = False) -> str:
    """GitHub's "register an App" form for the org, filled in: read-only permissions Portal needs, no webhook, private;
    with `writes`, also what required checks and golden paths need (checks, contents, pull requests, administration)."""
    from urllib.parse import urlencode
    params = {"name": f"{org} portal {'' if writes else 'reader'}".strip()[:34],
              "description": "StackVitals Portal: the org catalog, owners and scorecards"
              + ("; required checks and golden paths." if writes else " (read-only)."),
              "url": f"https://github.com/{org}", "public": "false", "webhook_active": "false",
              "actions": "read", "contents": "write" if writes else "read", "metadata": "read", "members": "read",
              "organization_custom_properties": "read"}
    if writes:
        params |= {"checks": "write", "pull_requests": "write", "administration": "write", "workflows": "write"}
    return f"https://github.com/organizations/{org}/settings/apps/new?{urlencode(params)}"


def check(api, org: str) -> list[str]:
    """What this token can and can't read, one line per kind of data, so setup problems show before the first run."""
    repos = list_repos(api, org, "local")
    private = [r for r in repos if r["private"]]
    sample = (private or repos or [None])[0]
    out = [f"{len(repos)} repos visible ({len(private)} private)"]
    if sample:
        found = any(read_file(api, sample["name"], p, sample["default_branch"]) is not NA
                    for p in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"))
        out.append(f"CODEOWNERS: {'readable' if found else 'none found in ' + sample['name']}")
        out.append("branch rules: " + ("readable" if read(api, f"/repos/{sample['name']}/rules/branches/{sample['default_branch']}")
                                       is not NA else "not available"))
    out.append("teams: " + ("readable" if read(api, f"/orgs/{org}/teams", {"per_page": 1}) is not NA else "not available"))
    out.append("custom properties: " + ("readable" if read(api, f"/orgs/{org}/properties/values", {"per_page": 1}) is not NA
                                        else "not available"))
    return out


def main(argv: list[str] | None = None, now: datetime | None = None, make_api=ActionsAPI, tok: str | None = None,
         make_gql=None) -> int:
    parser = argparse.ArgumentParser(prog="stackvitals portal", description="Portal: what an org owns, who owns it, and its shape.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rep = sub.add_parser("report", help="Read every repo of an org you can see and show owners with evidence")
    rep.add_argument("org", help="org or user name")
    rep.add_argument("--json", action="store_true")
    rep.add_argument("--budget", type=int, default=3000, help="most API requests to spend; the next run continues")
    rep.add_argument("--no-scorecard", dest="scorecard", action="store_false", help="skip OpenSSF Scorecard results")
    chk = sub.add_parser("check", help="Say what your token can read in an org before the first run")
    chk.add_argument("org", help="org or user name")
    ini = sub.add_parser("init", help="Print the workflow for the org's private portal repo")
    ini.add_argument("--ref", default=ACTION_REF)
    lnk = sub.add_parser("app-link", help="Print a link that opens GitHub's App form with Portal's read-only permissions filled in")
    lnk.add_argument("org", help="org name")
    lnk.add_argument("--writes", action="store_true", help="also the write permissions required checks and golden paths need")
    args = parser.parse_args(argv)
    if args.cmd == "init":
        print(WORKFLOW.format(ref=args.ref), end="")
        return 0
    if args.cmd == "app-link":
        print(app_link(args.org, args.writes))
        print("Then: create the App, install it on the org's repos, save its client ID as the variable PORTAL_CLIENT_ID and a "
              "private key as the secret PORTAL_PRIVATE_KEY, and switch on the token step in the portal workflow.")
        return 0
    tok = tok or token()
    if not tok:
        print("A GitHub token is needed. Set GITHUB_TOKEN, or run `gh auth login`.", file=sys.stderr)
        return 1
    if args.cmd == "check":
        for line in check(make_api(tok, f"{args.org}/portal", max_requests=50), args.org):
            print(line)
        return 0
    now = now or datetime.now(timezone.utc)
    path = home() / "portal" / f"{args.org}.json"
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    from stackvitals.ci import bench as ci_bench
    from stackvitals.flow import peers as flow_peers
    from stackvitals.portal.scorecard import rules_or_default, score_catalog
    make_gql = make_gql or _gql
    catalog = build_catalog(make_api(tok, f"{args.org}/portal", max_requests=args.budget), args.org, "local", now, previous,
                            scorecard_client=_scorecard_client() if args.scorecard else None, gql=make_gql(tok))
    rules, exemptions, _ = rules_or_default(None)
    score_catalog(catalog, rules, exemptions, now, {"ci": ci_bench.load(tok, home() / "bench"),
                                                    "flow": flow_peers.load(tok, home() / "bench")})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=1), encoding="utf-8")
    if args.json:
        print(json.dumps(catalog, indent=1))
        return 0
    active = [r for r in catalog["repos"] if not r.get("archived") and not r.get("fork")]
    judged = [r for r in active if r["name"].split("/")[-1].lower() != ".github"]
    counts = {s: sum(1 for r in judged if (r.get("owners") or {}).get("status") == s) for s in ("valid", "weak", "none")}
    print(f"{args.org}: {len(catalog['repos'])} repos, {len(active)} active (archived repos and forks are listed, not checked). "
          f"Owners: {counts['valid']} valid, {counts['weak']} weak, {counts['none']} none.")
    from stackvitals.portal.pages import catalog_entities
    entities, problems, files = catalog_entities(judged)
    if files:
        print(f"Catalog: {len(entities)} entities from {files} repos' catalog-info.yaml, {len(problems)} problems in them.")
    for r in active:
        o = r.get("owners") or {}
        if r["name"].split("/")[-1].lower() == ".github":
            print(f"  {r['name']:40} {'-':12} {'-':8} the org's shared settings repo: not judged")
            continue
        why = "; ".join(o.get("reasons") or []) + (
            f" (suggested from {o.get('suggested_from') or 'recent commits'}: {', '.join(o['suggested'])})" if o.get("suggested") else "")
        # A scored repo below bronze says so; "-" is left for repos not scored at all.
        level = ((r.get("score") or {}).get("level") or "below bronze") if r.get("score") else "-"
        print(f"  {r['name']:40} {level:12} {o.get('status') or 'not checked yet':8} {why}")
    if not catalog["complete"]:
        print("\n(Not every repo was checked yet; run the same command again to continue.)")
    return 0
