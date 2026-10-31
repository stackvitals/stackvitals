"""docs/install.md: the workflow file itself, which module ids exist and what each needs, and every Action input, built
from the template `stackvitals ci init` prints and from action.yml, so the page can't drift from either."""
import yaml

from stackvitals.ci.cli import ACTION_REF, workflow_template
from stackvitals.portal.cli import WORKFLOW as PORTAL_WORKFLOW

# id, what it gives you, when it runs, what it needs besides itself
MODULES = [
    ("ci", "CI Health: flaky and slowing jobs and tests, the PR verdict comment and check, test reports, owners",
     "after each CI run finishes, and every 3 hours", "nothing; alone is fine"),
    ("flow", "Team Flow, and with it the Delivery page (cycle time, DORA, AI-assisted work, investment) and Insights "
             "(fix first, alerts, the weekly digest)",
     "the schedule and manual runs", "nothing; Delivery's CI parts (failed deployments from CI, merge-queue flakes) and "
                                     "Insights' red-CI findings also need `ci`"),
    ("deps", "Dependency Steward: known vulnerabilities and malware in every lockfile, the check on PRs that change a lockfile, runtimes, and the weekly supply chain page",
     "after each CI run (with `ci`) and every 3 hours for vulnerabilities; pull requests that change a lockfile; weekly for the supply chain", "nothing; alone is fine"),
    ("community", "Community: newcomers, first answers, who carries the work, stars and traffic",
     "the schedule and manual runs", "nothing; it reads the PRs itself when `flow` isn't on"),
    ("portal", "Portal: the org's catalog, owners and scorecards",
     "the schedule, from the org's portal repo with its own workflow (below)", "a portal repo; an org App for private repos"),
]


def _inputs(action_yml: str) -> list[str]:
    inputs = (yaml.safe_load(action_yml) or {}).get("inputs") or {}
    rows = ["| Input | Default | What it does |", "|---|---|---|"]
    for name, spec in inputs.items():
        default = spec.get("default")
        shown = f"`{default}`" if default not in (None, "") else ""
        rows.append(f"| `{name}` | {shown} | {' '.join(str(spec.get('description') or '').split())} |")
    return rows


def markdown(action_yml: str) -> str:
    owner_repo = ACTION_REF.split("@", 1)[0]
    lines = ["# Install", "",
             f"StackVitals is a GitHub Action, `uses: {ACTION_REF}`, run by one workflow file in your repo. The file below "
             "is exactly what `stackvitals ci init owner/repo` prints (that command also fills in your CI workflows' "
             "names) and what the app's Setup page commits for you. Save it as `.github/workflows/stackvitals.yml`; "
             "committing it starts the first run. No settings file is needed: a missing `.github/stackvitals.toml` means "
             "the defaults ([settings.md](settings.md)).", "",
             "## Modules", "",
             "Pick modules with the `modules` input, comma separated. To run one alone, list only it, for example "
             "`modules: ci`. Delivery and Insights have no id of their own: they come with `flow`.", "",
             "| Id | What you get | Runs on | Needs |", "|---|---|---|---|"]
    lines += [f"| `{i}` | {what} | {when} | {needs} |" for i, what, when, needs in MODULES]
    lines += ["", "The default is `ci,flow,deps,community`. `stackvitals ci init --modules ci,deps` (or the app's Setup "
              "picker) writes a file with only those modules' triggers and permissions, each lowered to read where nothing "
              "of theirs writes; turning on a writing switch later (like `deps-comments`, which needs `pull-requests: write`) "
              "means raising that permission too.", "",
              "## The workflow file", "",
              "Change `workflows: [\"CI\"]` to the `name:` lines of your CI workflows (the names, not the file names): "
              "`workflow_run` matches names. The permissions are what every default switch needs; each comment says what "
              "to lower to turn a part off. Team Flow's automation (review requests, size labels) and PR comments need "
              "`pull-requests: write`; the weekly digest, commands and flaky-test issues need `issues: write`. A settings "
              "change applied from the app opens a pull request, which needs the repo setting \"Allow GitHub Actions to "
              "create and approve pull requests\" (Settings, Actions, General).", "",
              "```yaml", workflow_template().rstrip(), "```", "",
              "## The portal workflow", "",
              "Portal runs in the org's own portal repo (private is best) with this file, which "
              "`stackvitals portal init` prints; `stackvitals portal check ORG` says what your token can read first.", "",
              "```yaml", PORTAL_WORKFLOW.format(ref=ACTION_REF).rstrip(), "```", "",
              "## Every input", "",
              f"From [action.yml](https://github.com/{owner_repo}/blob/main/action.yml). Inputs use hyphens "
              "(`rerun-flaky`); the same switches in `.github/stackvitals.toml` use underscores (`rerun_flaky`), and the "
              "file wins when both are set.", ""]
    lines += _inputs(action_yml)
    return "\n".join(lines) + "\n"
