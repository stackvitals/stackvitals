import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from stackvitals.ci.action import run_action, write_outputs
from stackvitals.ci.analyze import analyze
from stackvitals.ci.automation import run_quarantined
from stackvitals.ci.api import ActionsAPI, APIError, OutOfBudget
from stackvitals.ci.report import render_text
from stackvitals.ci.store import DataStore
from stackvitals.core import services
from stackvitals.flow.action import run_flow_action

ACTION_REF = "stackvitals/stackvitals@v0"
WORKFLOW = """name: StackVitals
on:
  workflow_run:
    workflows: {names}   # your CI workflows; each finished run is read right away
    types: [completed]
  schedule:
    - cron: "17 */3 * * *"   # Team Flow every 3 hours, and a CI catch-up
  repository_dispatch:
    types: [stackvitals-deployment, stackvitals-incident]   # sent by `stackvitals record` from any deploy tool
  workflow_dispatch:
    inputs:
      request:
        description: "A change sent from the StackVitals app (leave empty for a normal run)"
        required: false
        default: ""
  push:                      # your settings file applies at once; adding this file starts the first run
    paths: [".github/stackvitals.toml", ".github/workflows/stackvitals.yml"]
  issues:
    types: [opened, closed, reopened]  # requests from the app; flaky-test issues closed as not planned, or reopened
  issue_comment:
    types: [created]         # /stackvitals commands
  pull_request:              # the dependency check, only when a lockfile changes (never runs the PR's code)
    paths: ["**/*.lock", "**/*lock.json", "**/*lock.yaml", "**/npm-shrinkwrap.json", "**/requirements*.txt", "**/go.mod",
            "**/*.lockfile", "**/pom.xml", "**/pylock*.toml", "**/Package.resolved", "**/gems.locked",
            "**/verification-metadata.xml", "**/*.freeze"]
permissions:
  contents: write        # saves history to the stackvitals-data branch; settings changes asked for from the app
  actions: read          # reads your CI runs, jobs and test reports (write: [automation] rerun_flaky re-runs known flakes)
  checks: read           # Team Flow: sees which PRs have failing checks (write: [automation] verdict_check)
  statuses: read
  deployments: read      # Team Flow: delivery from deployments
  issues: write          # the weekly digest, answers to /stackvitals commands, flaky-test and alert issues
  pull-requests: write   # reads PRs for Team Flow; one comment on failed PR runs (set to read to turn comments off)
jobs:
  vitals:
    # Only what concerns StackVitals starts a runner: settings pushed to the default branch, requests and commands from
    # people with access to the repo, and flaky-test issues being closed or reopened.
    if: >-
      (github.event_name != 'push' || github.ref_name == github.event.repository.default_branch) &&
      (github.event_name != 'issues' ||
        (github.event.action == 'opened' && contains(github.event.issue.body, '```stackvitals') &&
         contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.issue.author_association)) ||
        (github.event.action != 'opened' && contains(github.event.issue.labels.*.name, 'flaky-test'))) &&
      (github.event_name != 'issue_comment' ||
        (contains(github.event.comment.body, '/stackvitals') &&
         contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.comment.author_association))) &&
      (github.event_name != 'workflow_run' || !github.event.repository.private ||
        github.event.workflow_run.conclusion != 'success' || vars.STACKVITALS_EVERY_CI_RUN == 'true')
    # Private repos pay for Actions minutes: a CI run that passed starts no job (the 3-hourly run reads it), unless the
    # repo variable STACKVITALS_EVERY_CI_RUN is "true" (the verdict check needs it). On the job, so events it skips never
    # wait in (or cancel) the queue; PR checks and Test connection runs never wait for (or get dropped behind) data runs.
    concurrency:
      group: stackvitals-${{{{ github.event.pull_request.number || (contains(github.event.inputs.request, '"check"') && format('check-{{0}}', github.run_id)) || 'data' }}}}
      cancel-in-progress: false
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: {ref}
        env:
          STACKVITALS_EVERY_CI_RUN: ${{{{ vars.STACKVITALS_EVERY_CI_RUN }}}}
        with:
          modules: ci,flow,deps,community
          jira-email: ${{{{ secrets.JIRA_EMAIL }}}}        # optional: Jira Cloud (see Integrations); unused while unset
          jira-token: ${{{{ secrets.JIRA_API_TOKEN }}}}
          linear-token: ${{{{ secrets.LINEAR_API_KEY }}}}  # optional: Linear
          pagerduty-token: ${{{{ secrets.PAGERDUTY_API_KEY }}}}       # optional: PagerDuty or incident.io incidents
          incident-io-token: ${{{{ secrets.INCIDENT_IO_API_KEY }}}}
          triage-key: ${{{{ secrets.GEMINI_API_KEY }}}}     # optional: a model's view on undecided failures ([ci.triage])
          # traffic-token: ${{{{ steps.app.outputs.token }}}}   # optional: keep traffic past GitHub's 14 days (see docs/modules.md)
"""


def _uncommented(line: str) -> str:
    # The line without its YAML comment; a "#" inside quotes (a workflow name) stays.
    quote = None
    for i, ch in enumerate(line):
        if ch in "\"'" and quote in (None, ch):
            quote = None if quote else ch
        elif ch == "#" and quote is None and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
    return line


MODULES = ("ci", "flow", "deps", "community")


def _for_modules(text: str, modules: tuple[str, ...]) -> str:
    """The workflow trimmed to the modules chosen: only their triggers and the permissions they use, each lowered to
    read where nothing of theirs writes."""
    has = set(modules)
    lines, out, skip = text.splitlines(keepends=True), [], None
    for line in lines:
        key = line.strip().split(":", 1)[0]
        indent = len(line) - len(line.lstrip())
        if skip is not None:
            if indent > skip or not line.strip():
                continue
            skip = None
        # CI Health starts from your CI's finished runs; the dependency check from pull requests that change a lockfile.
        if indent == 2 and ((key == "workflow_run" and "ci" not in has) or (key == "pull_request" and "deps" not in has)):
            skip = indent
            continue
        if indent == 2 and key in ("actions", "checks", "statuses", "deployments", "pull-requests"):
            needs = {"actions": "ci" in has, "checks": has & {"ci", "flow"}, "statuses": has & {"ci", "flow"},
                     "deployments": "flow" in has, "pull-requests": True}[key]
            if not needs:
                continue
            if key == "pull-requests" and not has & {"ci", "flow"}:
                line = "  pull-requests: read    # the dependency check reads the files a pull request changes\n"
        if line.strip().startswith("modules:"):
            line = line.split("modules:")[0] + "modules: " + ",".join(m for m in MODULES if m in has) + "\n"
        out.append(line)
    return "".join(out)


def workflow_template(ref: str = ACTION_REF, names: list[str] | None = None, compact: bool = False,
                      modules: tuple[str, ...] = MODULES) -> str:
    # JSON strings are valid YAML, so any workflow name is quoted safely.
    text = WORKFLOW.format(ref=ref, names="[" + ", ".join(json.dumps(n) for n in (names or ["CI"])) + "]")
    if tuple(modules) != MODULES:
        text = _for_modules(text, tuple(modules))
    if not compact:
        return text
    # Without comments, for a prefilled GitHub link (GitHub refuses links much over 6,500 characters).
    return "\n".join(kept for kept in (_uncommented(line) for line in text.splitlines()) if kept.strip()) + "\n"


_CI = re.compile(r"\b(test|tests|testing|ci|build|builds|lint|check|checks|pre-commit|e2e|unit|integration|verify|validate)\b", re.I)
_CHORE = re.compile(r"\b(lock|stale|label|labeler|greet|welcome|release|publish|deploy|pages|codeql|scorecard|zizmor|dependabot|triage|sync|review)\b", re.I)


def ci_guess(names: list[str]) -> list[str]:
    # The workflows that look like CI (the app's Setup picks the same); none recognised means all of them.
    picked = [n for n in names if _CI.search(n) and not _CHORE.search(n)]
    return picked or list(names)


def workflow_names(api) -> list[str]:
    body = api._get(f"/repos/{api.repo}/actions/workflows", {"per_page": 100})
    return [w["name"] for w in body.get("workflows") or []
            if w.get("state") == "active" and not (w.get("path") or "").startswith("dynamic/")
            and not (w.get("path") or "").endswith("/stackvitals.yml")]


def home() -> Path:
    root = Path(os.environ.get("STACKVITALS_HOME") or Path.home() / ".stackvitals")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _gh_token() -> str | None:
    try:
        run = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout.strip() or None if run.returncode == 0 else None


def token() -> str | None:
    for name in ("STACKVITALS_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "MERGESCOUT_TOKEN"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    return _gh_token()


def _quarantine_set(path: str | None, make_api, tok: str | None) -> set | None:
    # Any problem reading the list means nothing is quarantined: a broken list must never hide failures.
    try:
        if path:
            raw = Path(path).read_bytes()
        else:
            repo = os.environ.get("GITHUB_REPOSITORY")
            if not repo:
                return None
            raw = make_api(tok or token(), repo).file("ci/quarantine.json", "stackvitals-data")
        items = json.loads(raw)
        return {str(i) for i in items} if isinstance(items, list) else None
    except (OSError, ValueError, APIError, OutOfBudget):
        return None


def main(argv: list[str] | None = None, now: datetime | None = None, make_api=ActionsAPI, tok: str | None = None) -> int:
    # These parse their own flags; argparse's REMAINDER would reject a leading flag such as --base or --help.
    if argv and argv[0] in ("impact", "retry", "validate"):
        return __import__(f"stackvitals.ci.{argv[0]}", fromlist=["main"]).main(argv[1:])
    if argv and argv[0] == "gitlab-action":
        from stackvitals.ci.gitlab_action import main as gitlab_main
        return gitlab_main(argv[1:])
    if argv and argv[0] == "upload":
        import stackvitals.ci.upload as upload
        return upload.main(argv[1:])
    parser = argparse.ArgumentParser(prog="stackvitals ci", description="CI health: flaky and slow jobs.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="Analyse any repo's CI from your machine (no install in the repo needed)")
    r.add_argument("repo", help="owner/name")
    r.add_argument("--days", type=int, default=14, help="days of history to read (GitHub keeps at most 90)")
    r.add_argument("--window", type=int, default=14, help="days the report covers")
    r.add_argument("--budget", type=int, default=3000, help="most API requests to spend")
    r.add_argument("--html", help="also write the dashboard to this folder")
    r.add_argument("--tests", action="store_true", help="also read test reports (JUnit, CTRF, Jest/Vitest, Go, TRX) from run artifacts")
    r.add_argument("--json", action="store_true")
    q = sub.add_parser("quarantine", help="Run your test command; pass if only quarantined (known flaky) tests failed")
    q.add_argument("--reports", action="append", default=[], help="glob of test report files the command writes")
    q.add_argument("--list", help="quarantine list file (default: read from the stackvitals-data branch)")
    q.add_argument("--print", choices=("pytest", "jest", "vitest", "go", "playwright", "maven", "dotnet"),
                   help="print the flags that make that test runner skip (or, for pytest, tolerate) quarantined tests, and exit")
    q.add_argument("command", nargs=argparse.REMAINDER, help="-- then your test command")
    gl = sub.add_parser("gitlab", help="Analyse a GitLab project's CI the same way (read-only; GITLAB_TOKEN if private)")
    gl.add_argument("project", help="group/project on gitlab.com")
    gl.add_argument("--days", type=int, default=14, help="days of pipelines to read")
    gl.add_argument("--budget", type=int, default=600, help="most GitLab requests to spend")
    gl.add_argument("--base", default="https://gitlab.com/api/v4", help="a self-managed GitLab's API url")
    gl.add_argument("--json", action="store_true")
    b = sub.add_parser("burn-in", help="Run the tests a PR adds or changes several times; fail if one passes and fails")
    b.add_argument("--base", default="origin/main", help="what the PR is compared with (git diff BASE...HEAD)")
    b.add_argument("--times", type=int, default=5, help="how many times to run them")
    b.add_argument("--reports", action="append", default=[], help="glob of test report files each run writes")
    b.add_argument("--only-new", action="store_true", help="fail only when a test the default branch never ran flakes "
                                                              "(reads the stackvitals-data branch: git fetch origin stackvitals-data)")
    b.add_argument("command", nargs=argparse.REMAINDER, help="-- then your test command, with {files} for the test files")
    sh = sub.add_parser("shards", help="Split test files into N shards that take about the same time, by recorded times")
    sh.add_argument("repo", nargs="?", help="owner/name: times from the newest green run on its default branch with test reports")
    sh.add_argument("--n", type=int, required=True, help="how many shards")
    sh.add_argument("--reports", action="append", default=[], help="glob of test report files on this machine to read instead")
    sh.add_argument("--files", action="append", default=[], help="glob of test files to place even with no recorded time")
    sh.add_argument("--index", type=int, help="print only shard INDEX (1 to N), space-separated, for a CI matrix")
    sh.add_argument("--py-paths", action="store_true", help="turn pytest's dotted module names into file paths")
    sh.add_argument("--json", action="store_true")
    im = sub.add_parser("impact", add_help=False, help="The test files a change can affect (or all), from names and past failures")
    im.add_argument("rest", nargs=argparse.REMAINDER)
    rt = sub.add_parser("retry", add_help=False, help="Re-run only the failed tests in the same job, never known-broken ones")
    rt.add_argument("rest", nargs=argparse.REMAINDER)
    v = sub.add_parser("validate", add_help=False, help="Check test report files are read as you expect, before CI does")
    v.add_argument("rest", nargs=argparse.REMAINDER)
    i = sub.add_parser("init", help="Print the workflow file that installs StackVitals in a repo")
    i.add_argument("repo", nargs="?", help="owner/name: fill in that repo's own workflow names")
    i.add_argument("--ref", default=ACTION_REF)
    i.add_argument("--modules", default=",".join(MODULES),
                   help="the modules to install, comma-separated (ci, flow, deps, community); the file asks only for what they use")
    args = parser.parse_args(argv)
    if args.cmd == "impact":
        from stackvitals.ci.impact import main as impact_main
        return impact_main(args.rest)
    if args.cmd == "retry":
        from stackvitals.ci.retry import main as retry_main
        return retry_main(args.rest)
    if args.cmd == "validate":
        from stackvitals.ci.validate import main as validate_main
        return validate_main(args.rest)
    if args.cmd == "quarantine" and args.print:
        from stackvitals.ci.quarantine_runtime import LIST_FILE, runtime_args
        ids = _quarantine_set(args.list, make_api, tok) or set()
        if args.print == "pytest" and ids:
            # The pytest plugin reads the list from this file, so the flags alone are enough.
            Path(LIST_FILE).write_text(json.dumps(sorted(ids)) + "\n", encoding="utf-8")
        # One argument per line, for a shell array: mapfile -t args < <(stackvitals ci quarantine --print jest)
        print("\n".join(runtime_args(ids, args.print)))
        return 0
    if args.cmd == "quarantine":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            print("Give the test command after --, e.g. stackvitals ci quarantine --reports 'out/*.xml' -- pytest",
                  file=sys.stderr)
            return 2
        return run_quarantined(command, args.reports, _quarantine_set(args.list, make_api, tok))
    if args.cmd == "gitlab":
        from stackvitals.ci import gitlab
        now = now or datetime.now(timezone.utc)
        store = DataStore(home() / "ci" / ("gitlab__" + args.project.replace("/", "__")))
        lab = gitlab.GitLab(args.project, gitlab.token(), args.base, max_requests=args.budget)
        try:
            got = gitlab.collect(lab, store, now, args.days)
        except APIError as exc:
            print(f"GitLab refused: {exc}", file=sys.stderr)
            return 1
        result = analyze(store.load(), now, args.days, default_branch=store.state().get("default_branch"))
        if args.json:
            print(json.dumps({k: v for k, v in result.items() if k != "history"}, indent=1))
        else:
            print(render_text(result, args.project))
        if got["stopped"]:
            print(f"\n(Not all pipelines were read yet ({got['stopped']}); run the same command again to continue.)")
        return 0
    if args.cmd == "burn-in":
        from stackvitals.ci.burnin import burn_in, changed_tests
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command or not args.reports:
            print("Give --reports and the test command after --, e.g. stackvitals ci burn-in --reports 'out/*.xml' -- "
                  "pytest {files}", file=sys.stderr)
            return 2
        from stackvitals.ci.burnin import flaky_rates, known_tests
        code, out = burn_in(command, args.reports, max(1, min(args.times, 50)), changed_tests(args.base),
                            known=known_tests(), only_new=args.only_new, rates=flaky_rates())
        for p in out.get("fix_proofs") or []:
            print(f"{p['id']}: passed {p['passes']} of {p['passes']} after failing {p['rate']:.0%} of runs before; "
                  f"{p['chance']:.1%} chance of that without a fix, so the fix is "
                  f"{'shown' if p['shown'] else 'not shown yet (run more repeats with --times)'}.")
        if out.get("new") is not None and out["runs"]:
            print(f"{len(out['new'])} of the tests are new (the default branch never reported them).")
        elif args.only_new and out["runs"]:
            print("The stackvitals-data branch couldn't be read (git fetch origin stackvitals-data), so every flake counts.")
        if out.get("problem"):
            print(out["problem"], file=sys.stderr)
        elif not out["runs"]:
            print("No test files were added or changed, so nothing was run.")
        else:
            print(f"Ran {len(out['files'])} changed test file(s) {out['runs']} times: {out['tests']} tests.")
            for tid in out["flaky"]:
                print(f"flaky: {tid} passed and failed across the runs")
            for tid in out["always_failed"]:
                print(f"failed every time: {tid}")
        return code
    if args.cmd == "shards":
        from stackvitals.ci import shards
        return shards.run(args, make_api, None if args.reports else tok or token())
    tok = tok or token()
    if args.cmd == "init":
        names = None
        if args.repo and tok:
            try:
                names = ci_guess(workflow_names(make_api(tok, args.repo))) or None
            except APIError as exc:
                print(f"Couldn't read {args.repo}'s workflows ({str(exc)[:120]}); printing the template with [\"CI\"].",
                      file=sys.stderr)
        chosen = tuple(m.strip() for m in args.modules.split(",") if m.strip())
        if not chosen or set(chosen) - set(MODULES):
            print(f"--modules takes some of {', '.join(MODULES)}; Portal has its own: stackvitals portal init", file=sys.stderr)
            return 2
        print(workflow_template(args.ref, names, modules=chosen), end="")
        if not names:
            print("# Replace [\"CI\"] with the names of your CI workflows (or run: stackvitals ci init owner/repo).",
                  file=sys.stderr)
        return 0
    if not tok:
        print("A GitHub token is needed (GitHub allows only 60 requests an hour without one). "
              "Set GITHUB_TOKEN, or run `gh auth login`.", file=sys.stderr)
        return 1
    now = now or datetime.now(timezone.utc)
    try:
        # The same reader as the MCP server and the brief; a budget stop keeps what was read and the report covers it.
        result, _source = services.ci_result(args.repo, args.days, tok, home(), make_api=make_api, now=now, budget=args.budget,
                                             tests=args.tests, window=args.window, owners=True,
                                             log=lambda line: print(line, file=sys.stderr, flush=True))
    except APIError as exc:
        print(f"GitHub refused: {exc}", file=sys.stderr)
        return 1
    except OutOfBudget as exc:
        print(f"Stopped early ({exc}); run again later to continue.", file=sys.stderr)
        return 1
    if args.html:
        write_outputs(Path(args.html), result, args.repo, site=".", data_readme=False)
    stopped = (result.get("collect") or {}).get("stopped")
    if args.json:
        # Scripts reading the JSON must see an early stop too, not just people reading the text.
        print(json.dumps({k: v for k, v in result.items() if k != "history"}, indent=1))
        if stopped:
            print(f"Not all history was read yet ({stopped}); run the same command again to continue.", file=sys.stderr)
    else:
        print(render_text(result, args.repo))
        if stopped:
            print(f"\n(Not all history was read yet ({stopped}); run the same command again to continue.)")
    return 0


SWITCHES = ("pr_comments", "rerun_flaky", "quarantine", "issues", "mention_owners", "preflight_comments", "deps_comments",
            "label_stuck")


def switches(args, cfg: dict | None) -> dict[str, bool]:
    """The Action's on/off switches: the settings file's [automation] wins over the workflow input when it is set."""
    auto = (cfg or {}).get("automation") or {}
    out = {k: auto[k] if auto.get(k) is not None else getattr(args, k).strip().lower() == "true" for k in SWITCHES}
    out["assign_owners"] = bool(auto.get("assign_owners"))
    out["verdict_check"] = bool(auto.get("verdict_check"))
    return out


def _print_digest(found: dict) -> None:
    d = found["Digest"]
    if os.environ.get("STACKVITALS_READ_ONLY"):
        print(f"Digest: week {d['week']} written to the local data, not sent (read-only local run).")
    else:
        print(f"Digest: week {d['week']} sent to {', '.join(d['channels'])}.")


def action_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stackvitals action", description="Run inside GitHub Actions.")
    parser.add_argument("--modules", default="ci")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--budget", type=int, default=800)
    parser.add_argument("--tests", default="true", help="read test reports from artifacts (true/false)")
    parser.add_argument("--test-artifacts", default="", help="regex for artifact names holding test reports")
    for flag, default in (("--pr-comments", "true"), ("--rerun-flaky", "false"), ("--quarantine", "false"),
                          ("--issues", "false"), ("--preflight-comments", "false"), ("--deps-comments", "false"),
                          ("--mention-owners", "false"), ("--label-stuck", "false")):
        parser.add_argument(flag, default=default)
    args = parser.parse_args(argv)
    modules = {m.strip() for m in args.modules.split(",") if m.strip()}
    unknown = modules - {"ci", "flow", "deps", "community", "portal"}
    if unknown:
        print(f"Unknown modules: {', '.join(sorted(unknown))}. Available now: ci, flow, deps, community, portal", file=sys.stderr)
        return 2
    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        # On a pull request only the dependency check runs: the others write to the data branch, and a fork's token can't.
        if "deps" in modules:
            import stackvitals.deps.action as deps_action
            from stackvitals.core.settings import read
            token = os.environ.get("STACKVITALS_TOKEN") or os.environ.get("GITHUB_TOKEN")
            cfg = read(ActionsAPI(token, os.environ.get("GITHUB_REPOSITORY", ""), max_requests=2))
            try:
                out = deps_action.run_deps_action(dict(os.environ), comments=switches(args, cfg)["deps_comments"],
                                                  policy=cfg["deps"]["policy"], outside=cfg["deps"]["outside_lookups"],
                                                  scan=True, deep=cfg["deps"]["guarddog"], deny=cfg["deps"]["licenses"]["deny"])
            except Exception as exc:  # noqa: BLE001
                # The check informs; its own trouble (GitHub limits, an odd file) must never fail the PR.
                print(f"::warning::The dependency check could not finish: {deps_action._annotation(str(exc))}")
                return 0
            print(f"Dependency check: {out['changed']} changed packages in {out['lockfiles']} lockfile"
                  f"{'' if out['lockfiles'] == 1 else 's'}, {out['investigate']} to investigate, {out['monitor']} to monitor.")
        return 0
    from stackvitals.core.workspace import run_job
    from stackvitals.flow.action import FLOW_EVENTS
    env, now = dict(os.environ), datetime.now(timezone.utc)
    scheduled = env.get("GITHUB_EVENT_NAME") in FLOW_EVENTS
    steps = []
    # Switches are decided when each step runs, after the job has read the settings file.
    sw = lambda ws: switches(args, ws.cache.get("settings"))
    from stackvitals.core import requests as requests_mod
    # First, on every run: a request or command (and any a cancelled run missed) changes what the modules then work on.
    steps.append(("Requests", lambda ws: requests_mod.requests_step(ws, env, now)))
    # A Test connection request from the app runs alone, so its answer comes back in seconds.
    light = requests_mod.check_only(env)
    if light:
        modules, scheduled = set(), False
    if env.get("GITHUB_EVENT_NAME") == "repository_dispatch":
        from stackvitals.core.recorded import record_step
        # A deployment or incident sent from another tool: kept alone, and counted by the next scheduled run.
        steps.append(("Record", lambda ws: record_step(ws, env, now)))
        modules, scheduled = set(), False
    if "ci" in modules:
        steps.append(("CI Health", lambda ws: run_action(
            env, now=now, days=args.days, budget=args.budget, tests=args.tests.strip().lower() != "false",
            artifact_pattern=args.test_artifacts or None, pr_comments=sw(ws)["pr_comments"],
            rerun_flaky=sw(ws)["rerun_flaky"], quarantine=sw(ws)["quarantine"], issues=sw(ws)["issues"],
            webhook=env.get("STACKVITALS_WEBHOOK") or None, mention_owners=sw(ws)["mention_owners"],
            assign_owners=sw(ws)["assign_owners"], verdict_check=sw(ws)["verdict_check"], workspace=ws)))
    for name, label in (("flow", "Team Flow"), ("community", "Community"), ("portal", "Portal")):
        if name in modules and not scheduled:
            print(f"{label}: runs on the schedule and manual runs only.")
    if "flow" in modules and scheduled:
        steps.append(("Team Flow", lambda ws: run_flow_action(env, now=now, preflight_comments=sw(ws)["preflight_comments"],
                                                              workspace=ws)))
    if "community" in modules and scheduled:
        import stackvitals.community.action as community_action
        # Team Flow's PR history is reused when it ran earlier in this job; otherwise Community reads the PRs itself.
        steps.append(("Community", lambda ws: community_action.run_community_action(env, now=now, workspace=ws)))
    if "portal" in modules and scheduled:
        import stackvitals.portal.action as portal_action
        steps.append(("Portal", lambda ws: portal_action.run_portal_action(env, now=now, workspace=ws)))
    from stackvitals import connectors
    if scheduled:
        # Jira, Linear: before Delivery, which joins their issues and incidents with the PRs and deployments.
        steps.append(("Connectors", lambda ws: connectors.connectors_step(ws, env, now)))
    if "deps" in modules and (scheduled or env.get("GITHUB_EVENT_NAME") == "workflow_run"):
        from stackvitals.deps.vulns import vulns_step
        # Every lockfile in every ecosystem: scanned when they change, and every 6 hours for new advisories.
        steps.append(("Vulnerabilities", lambda ws: vulns_step(ws, env, now)))
    if "deps" in modules and scheduled:
        from stackvitals.deps.supply import supply_step
        # Once a week: the SBOM, licences and Scorecards of what the repo depends on.
        steps.append(("Supply chain", lambda ws: supply_step(ws, env, now)))
    if "deps" in modules and scheduled:
        from stackvitals.security.probes import security_step

        def security(ws):
            import httpx
            # The badge lookup names the repo to bestpractices.dev, so private repos skip it.
            public = not (ws.cache.get("repo_info") or {}).get("private")
            return security_step(ws, env, now, get_json=(lambda u: httpx.get(u, timeout=20, follow_redirects=True).json()) if public else None)
        # Once a week: the repo's own security checks (workflows, protection, policy, releases, binaries, fuzzing).
        steps.append(("Security", security))
    if "flow" in modules and scheduled:
        from stackvitals.core.delivery_report import delivery_step
        # After Team Flow and Community: joins their PRs and issues with CI Health's runs.
        steps.append(("Delivery", lambda ws: delivery_step(ws, env, now, label_stuck=sw(ws)["label_stuck"])))
    if steps:
        from stackvitals.core.insights import insights_step
        # Last: joins whatever CI runs and pull requests the checkout now holds.
        steps.append(("Insights", lambda ws: insights_step(ws, env, now)))
    if "flow" in modules and scheduled:
        from stackvitals.core.alerts import alerts_step
        # Thresholds on the delivery numbers, sent once per change of state.
        steps.append(("Alerts", lambda ws: alerts_step(ws, env, now)))
    if steps and env.get("GITHUB_EVENT_NAME") in ("schedule", "workflow_dispatch"):
        from stackvitals.core.digest import digest_step
        # Last: the weekly digest reads the pages every module just wrote.
        steps.append(("Digest", lambda ws: digest_step(ws, env, now)))
    if light:
        steps = steps[:1]
    if not steps:
        return 0
    # One checkout and one commit for every module; a module's trouble is reported and the others still run.
    from stackvitals.core.settings import prepare
    job = run_job(env, steps, now, prepare=prepare(env))
    if job.get("pages") and env.get("GITHUB_OUTPUT"):
        # The Action's deploy steps run only when this job changed what the monitor shows.
        with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write("pages=true\n")
    for label, err in job["errors"].items():
        print(f"::error::{label} could not finish: {err}")
    saved, found = "saved" if job["outcome"] == "pushed" else "unchanged", job["results"]
    if found.get("CI Health"):
        out = found["CI Health"]
        print(f"CI health: {out['collect']['runs']} runs read ({out['collect']['requests']} requests), "
              f"{out['flaky']} flaky job(s), data {saved}.")
    if found.get("Team Flow"):
        flow = found["Team Flow"]
        print(f"Team Flow: {flow['prs']} PRs read ({flow['points']} points), {flow['queue']} waiting, data {saved}.")
    if found.get("Community"):
        com = found["Community"]
        score = f"{com['score']}/100" if com["score"] is not None else "not yet"
        print(f"Community: {com['issues']} issues read ({com['points']} points), {com['waiting']} newcomer"
              f"{'' if com['waiting'] == 1 else 's'} waiting, score {score}, data {saved}.")
    for name, got in (found.get("Connectors") or {}).items():
        print(f"{connectors.NAMES[name]}: " + (got["error"] if got["error"] else
              f"{got['read']} updated issue(s) read{'' if got['complete'] else ' (more next run)'}, data {saved}."))
    if found.get("Delivery"):
        dl = found["Delivery"]
        print(f"Delivery: {dl['prs']} merged PRs, {dl['deployments']} deployments, data {saved}.")
    if found.get("Insights"):
        ins = found["Insights"]
        print(f"Insights: {ins.get('findings', 0)} findings; {ins['red_prs']} of {ins['prs']} merged PRs spent time with "
              "failing checks.")
    if found.get("Alerts"):
        al = found["Alerts"]
        levels = ", ".join(f"{k.split('_')[0]} {v}" for k, v in al["levels"].items())
        print(f"Alerts: {al['events']} sent; {levels}.")
    if found.get("Requests"):
        req = found["Requests"]
        print(f"Requests: {req.get('decisions', 0)} decision(s) recorded; settings "
              f"{'changed' if req.get('settings') else 'unchanged'}.")
        if req.get("checks") is not None:
            print(f"Connection checks: {req.get('working', 0)} of {req['checks']} working (details in the job summary).")
    if found.get("Digest"):
        _print_digest(found)
    if found.get("Portal"):
        portal = found["Portal"]
        print(f"Portal: {portal['repos']} repos ({portal['mode']} mode), data {saved}.")
    for note in job["notes"]:
        print(f"::warning::{note}")
    return 1 if job["errors"] else 0
