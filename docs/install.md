# Install

StackVitals has two parts: a GitHub Action, `uses: stackvitals/stackvitals@v0`, that runs in your repo, and the `stackvitals` command on your machine, which sets the Action up, opens a private repo's dashboard and runs the MCP server for AI agents. The Action needs nothing installed; the command is one `pip install`.

## Get the command

```sh
pip install stackvitals      # Python 3.11 or newer
gh auth login                # once; or set GITHUB_TOKEN
```

Or run any command without installing, with [uv](https://docs.astral.sh/uv/): `uvx stackvitals init owner/repo`. Upgrade with `pip install -U stackvitals`. `stackvitals sql` needs the SQL extra: `pip install "stackvitals[sql]"`. The same package holds the CLI, `stackvitals ui` (a dashboard on your machine) and the MCP server (`stackvitals serve`).

## Set up a repo

```sh
stackvitals init owner/repo
```

`init` commits the workflow file below (or opens a pull request when the branch is protected or a different `stackvitals.yml` is there), follows the first run and turns on GitHub Pages for a public repo. A private repo keeps Pages off, since a Pages site is public on most plans: open its dashboard with `stackvitals ui owner/repo`. The app's Setup page does the same without a terminal. More: [quickstart.md](quickstart.md).

`stackvitals/stackvitals@v0` follows the latest release; to pin an exact one, use its version tag (`stackvitals/stackvitals@vX.Y.Z`, listed under [releases](https://github.com/stackvitals/stackvitals/releases)).

The rest of this page is the reference for doing it by hand. The file below is exactly what `stackvitals ci init owner/repo` prints (that command also fills in your CI workflows' names) and what `init` and the app's Setup page commit for you. Save it as `.github/workflows/stackvitals.yml`; committing it starts the first run. No settings file is needed: a missing `.github/stackvitals.toml` means the defaults ([settings.md](settings.md)).

## Modules

Pick modules with the `modules` input, comma separated. To run one alone, list only it, for example `modules: ci`. Delivery and Insights have no id of their own: they come with `flow`.

| Id | What you get | Runs on | Needs |
|---|---|---|---|
| `ci` | CI Health: flaky and slowing jobs and tests, the PR verdict comment and check, test reports, owners | after each CI run finishes, and every 3 hours | nothing; alone is fine |
| `flow` | Team Flow, and with it the Delivery page (cycle time, DORA, AI-assisted work, investment) and Insights (fix first, alerts, the weekly digest) | the schedule and manual runs | nothing; Delivery's CI parts (failed deployments from CI, merge-queue flakes) and Insights' red-CI findings also need `ci` |
| `deps` | Dependency Steward: known vulnerabilities and malware in every lockfile, the check on PRs that change a lockfile, runtimes, and the weekly supply chain page | after each CI run (with `ci`) and every 3 hours for vulnerabilities; pull requests that change a lockfile; weekly for the supply chain | nothing; alone is fine |
| `community` | Community: newcomers, first answers, who carries the work, stars and traffic | the schedule and manual runs | nothing; it reads the PRs itself when `flow` isn't on |
| `portal` | Portal: the org's catalog, owners and scorecards | the schedule, from the org's portal repo with its own workflow (below) | a portal repo; an org App for private repos |

The default is `ci,flow,deps,community`. `stackvitals ci init --modules ci,deps` (or the app's Setup picker) writes a file with only those modules' triggers and permissions, each lowered to read where nothing of theirs writes; turning on a writing switch later (like `deps-comments`, which needs `pull-requests: write`) means raising that permission too.

## The workflow file

Change `workflows: ["CI"]` to the `name:` lines of your CI workflows (the names, not the file names): `workflow_run` matches names. The permissions are what every default switch needs; each comment says what to lower to turn a part off. Team Flow's automation (review requests, size labels) and PR comments need `pull-requests: write`; the weekly digest, commands and flaky-test issues need `issues: write`. A settings change applied from the app opens a pull request, which needs the repo setting "Allow GitHub Actions to create and approve pull requests" (Settings, Actions, General).

```yaml
name: StackVitals
on:
  workflow_run:
    workflows: ["CI"]   # your CI workflows; each finished run is read right away
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
      group: stackvitals-${{ github.event.pull_request.number || (contains(github.event.inputs.request, '"check"') && format('check-{0}', github.run_id)) || 'data' }}
      cancel-in-progress: false
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: stackvitals/stackvitals@v0
        env:
          STACKVITALS_EVERY_CI_RUN: ${{ vars.STACKVITALS_EVERY_CI_RUN }}
        with:
          modules: ci,flow,deps,community
          jira-email: ${{ secrets.JIRA_EMAIL }}        # optional: Jira Cloud (see Integrations); unused while unset
          jira-token: ${{ secrets.JIRA_API_TOKEN }}
          linear-token: ${{ secrets.LINEAR_API_KEY }}  # optional: Linear
          pagerduty-token: ${{ secrets.PAGERDUTY_API_KEY }}       # optional: PagerDuty or incident.io incidents
          incident-io-token: ${{ secrets.INCIDENT_IO_API_KEY }}
          triage-key: ${{ secrets.GEMINI_API_KEY }}     # optional: a model's view on undecided failures ([ci.triage])
          # traffic-token: ${{ steps.app.outputs.token }}   # optional: keep traffic past GitHub's 14 days (see docs/modules.md)
```

## The portal workflow

Portal runs in the org's own portal repo (private is best) with this file, which `stackvitals portal init` prints; `stackvitals portal check ORG` says what your token can read first.

```yaml
name: StackVitals Portal
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
      #     client-id: ${{ vars.PORTAL_CLIENT_ID }}
      #     private-key: ${{ secrets.PORTAL_PRIVATE_KEY }}
      #     owner: ${{ github.repository_owner }}
      - uses: stackvitals/stackvitals@v0
        with:
          modules: portal
          # portal-token: ${{ steps.app.outputs.token }}
```

## Every input

From [action.yml](https://github.com/stackvitals/stackvitals/blob/main/action.yml). Inputs use hyphens (`rerun-flaky`); the same switches in `.github/stackvitals.toml` use underscores (`rerun_flaky`), and the file wins when both are set.

| Input | Default | What it does |
|---|---|---|
| `modules` | `ci,flow,deps,community` | Modules to run, comma separated. Available now - ci (CI health), flow (Team Flow, on schedule and manual runs), deps (dependency check on pull requests that change a lockfile), community (newcomers, first answers, stars and traffic, on schedule and manual runs), portal (the org catalog, run from the org's private portal repo) |
| `token` | `${{ github.token }}` | Token that can read Actions and write the stackvitals-data branch |
| `portal-token` |  | Optional token from an org-owned read-only GitHub App, so Portal reads the org's private repos (without it, public repos only) |
| `portal-org` |  | The org Portal catalogs (default - the owner of the repo it runs in) |
| `traffic-token` |  | Optional token from your own GitHub App with Administration read, so Community keeps traffic past GitHub's 14 days (the built-in token can't read traffic) |
| `days` | `90` | Days of history to fill in on the first runs (GitHub keeps at most 90) |
| `budget` | `800` | Most API requests per run (the built-in token allows 1,000 an hour) |
| `tests` | `true` | Read test reports (JUnit XML or CTRF JSON) from your run artifacts to find single flaky tests |
| `test-artifacts` |  | Regex for the artifact names that hold test reports (empty = names with junit, test-results, ctrf...) |
| `pr-comments` | `true` | One comment on failed PR runs saying which failures are known flakes (needs pull-requests write) |
| `rerun-flaky` | `false` | Re-run failed jobs once when every failure is a known flake (needs actions write) |
| `quarantine` | `false` | Keep a list of flaky tests for the stackvitals ci quarantine command |
| `preflight-comments` | `false` | Team Flow - one note on new outside PRs that miss what merged PRs here usually include (needs pull-requests write) |
| `deps-comments` | `false` | Dependency check - one comment on same-repo PRs listing changed packages and their verdicts (needs pull-requests write) |
| `issues` | `false` | Keep one issue per flaky test or job, closed once fixed (needs issues write) |
| `mention-owners` | `false` | @-mention a flaky test's code owners in the issues StackVitals opens (off: owners are named without a notification) |
| `webhook` |  | Slack, Discord, Microsoft Teams (Workflows) or any JSON webhook URL (pass a secret) to hear when something newly turns flaky and when a delivery number crosses its threshold |
| `team-webhooks` |  | One "@org/team = https://..." line per team (pass a secret); a team's newly flaky tests go to its own chat, the rest to webhook |
| `jira-email` |  | The Jira Cloud account's email (pass a secret); with jira-token and [connectors.jira] url, issues, sprints and incidents are read |
| `jira-token` |  | A Jira Cloud API token for that account (pass a secret; it expires within a year, so set key_expires to be warned) |
| `linear-token` |  | A Linear personal API key (pass a secret); issues and cycles of the teams under [connectors.linear] are read |
| `pagerduty-token` |  | A PagerDuty REST API key, read-only (pass a secret); its incidents then count in DORA instead of labels, reverts and hotfixes |
| `incident-io-token` |  | An incident.io API key with read access (pass a secret); its incidents then count in DORA instead of labels, reverts and hotfixes |
| `sonar-token` |  | A SonarQube or SonarCloud token (pass a secret), only for a private project or your own server; public SonarCloud projects need none |
| `copilot-token` |  | A token that can read the org's Copilot usage reports (an org App with "Organization Copilot metrics" read, or a fine-grained token); kept day by day |
| `anthropic-admin-key` |  | An Anthropic Admin API key (sk-ant-admin..., pass a secret); the organisation's daily Claude API cost is set beside AI-involved pull requests |
| `openai-admin-key` |  | An OpenAI admin key (pass a secret); the organisation's daily API cost is set beside AI-involved pull requests |
| `cursor-admin-key` |  | A Cursor admin API key (pass a secret); the team's billing-cycle spend and daily agent use are set beside AI-involved pull requests |
| `slack-token` |  | A Slack bot token (channels:history) that reads the support channels under [connectors.slack]; only times and flags are kept |
| `discord-token` |  | A Discord bot token (View Channel, Read Message History) that reads the support channels under [connectors.discord]; only times and flags are kept |
| `imports-json` |  | Path to the list of packages your code imports (`stackvitals deps imports --out imports.json` in an earlier step, after checkout) for Python, JavaScript and Rust repos; known vulnerabilities then say whether your code imports the package (an import, not a call path) |
| `govulncheck-json` |  | Path to govulncheck's JSON output (`govulncheck -format json ./... > govulncheck.json` in an earlier step) for Go repos; the supply page then says which advisories the code really calls |
| `triage-key` |  | A model API key (pass a secret, e.g. a free Gemini key from Google AI Studio) for [ci.triage]; up to 3 undecided failures per run get a model's view beside the verdict |
| `label-stuck` | `false` | Label pull requests whose asked-for review has not started after 3 days ("stackvitals: waiting for review"), and take the label off once one has (needs pull-requests or issues write) |
| `retention-days` | `400` | Days of pull request, issue and Portal history kept in the data branch |
| `ci-retention-days` | `180` | Days of CI run and test history kept in the data branch |
| `size-cap-mb` | `250` | Most history kept in the data branch, in MB; the oldest days go first |
| `squash-history` | `false` | Every 1,000 commits, rewrite the data branch to one commit (files unchanged; the branch is force-pushed) |
| `pages` | `branch` | "branch" (default): GitHub Pages serves the stackvitals-data branch. "deploy": this job publishes the monitor itself (Pages source "GitHub Actions"; the job needs pages and id-token write and the github-pages environment), for busy repos past 10 Pages builds an hour. "artifact": no Pages; each run that changed the app uploads it as a workflow artifact (kept 7 days, or less if your org sets a shorter limit) to download and open locally, for private repos; anyone who can read the repo can download it |
| `storage` | `git` | Where history is kept: "git" (default, the stackvitals-data branch) or an S3-compatible bucket as s3://bucket/prefix (AWS S3, Cloudflare R2, MinIO: the service must support replace-only-if-unchanged writes, If-Match), for very busy repos and big orgs. Switching starts a fresh history (the branch is not copied). With a bucket, publish the app with pages "deploy" or "artifact"; the tools that read the stackvitals-data branch (stackvitals ui and sql, Explore, the MCP server, the Portal org view, quarantine in your CI) do not read a bucket yet |
| `s3-endpoint` |  | The bucket service's endpoint, like https://s3.us-east-1.amazonaws.com or https://<account>.r2.cloudflarestorage.com |
| `s3-region` | `auto` | The bucket's region ("auto" for R2) |
| `s3-key-id` |  | An access key id that can read, write, delete and list that prefix (pass a secret) |
| `s3-secret` |  | Its secret (pass a secret) |
