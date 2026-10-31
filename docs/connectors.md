# What StackVitals reads, and from where

## How each integration was tested

**Live** means run against the real service; **recorded** means tested against saved answers in the shape the
service's documentation gives, with no account of ours; **experimental** means built but not yet checked either way.

| Integration | Tested | How |
|---|---|---|
| GitHub (Actions, pull requests, issues, deployments, checks, dependency graph) | Live | A sandbox repo with the built-in token, and public repos' history |
| Jira Cloud | Live for reading, recorded for write-back | A public site read without a key, and a keyed test site (2026-10-28) |
| Linear, PagerDuty | Live sign-in and read, recorded for write-back and full collection | Test accounts of ours (2026-10-28) |
| incident.io, GitHub Copilot usage | Recorded | incident.io's free plan has no API; Copilot usage needs an organisation with seats |
| Slack and Discord alerts | Live | A test message posted through each service's webhook (2026-10-28) |
| Microsoft Teams alerts; the instant-alerts Worker | Recorded | Payloads checked against Teams' format |
| Discourse | Live | Five public forums (cpython, rust, pytorch, julia, transformers) |
| Slack and Discord community channels | Live sign-in and channel read | A test workspace and server of ours (2026-10-28) |
| GitHub Discussions | Recorded | |
| GitLab CI | Live | gitlab-org/cli's pipelines |
| GitLab CI job (data branch, Pages, merge request note) | Token check live, job recorded | A test project's token checked for api and write_repository (2026-10-28); the job itself against a stand-in API |
| Test reports from Jenkins, CircleCI, Buildkite | Recorded | The upload command with sample reports |
| SonarQube and SonarCloud | Live for public projects, recorded with a token | A public SonarCloud project's quality gate and measures read without a key (2026-10-29) |
| Bitbucket Cloud and Azure DevOps (pull requests, Bitbucket deployments) | Live | Public repos read without a key: atlassian-connect-express and PowerShell (2026-10-29) |
| GitLab merge requests and deployments | Live | gitlab-org/cli, 153 merge requests |
| Deployments and incidents from any tool (`stackvitals record`, repository_dispatch) | Recorded | The command and the dispatch payload against a stand-in API |
| CDEvents and Flux deployments and incidents (repository_dispatch) | Recorded | Events built from the CDEvents 0.4.1 and 0.5.1 schemas and Flux's documented event; no cluster run |
| Findings as events (CloudEvents to a URL, repository_dispatch to a repo) | Recorded | Against a stand-in receiver; the event types checked against CDEvents' custom-event schema |
| GitHub Enterprise Server | Recorded | The API and GraphQL URLs pointed at a stand-in server |
| AI spend | Live for OpenAI, recorded for Anthropic, Claude Code and Cursor | An OpenAI admin key read 30 days of costs (2026-10-29) |
| Backstage `catalog-info.yaml` | Live | 198 real files from public repos |
| DevLake tables, Postgres, OpenTelemetry exports | Recorded | DevLake's own SQL run on our export of 42 generated repos; OTel spans written from a real repo's runs |
| OSV, deps.dev, CISA KEV, EPSS, OpenSSF Scorecard | Live | The crawler's daily runs |
| Model triage (Gemini) | Live | Public failures |
| OSV-Scanner (every lockfile) | Live | 100 crawled repos in ten languages, and lockfiles in eight ecosystems |
| GuardDog (opt-in code check) | Experimental | Runs only on Linux runners; checked against recorded output |
| Test connection: Discourse, Gemini triage | Live | Checked against the real services on 2026-10-24 (a public forum; a free Gemini key) |
| Test connection: Jira, Linear, PagerDuty, Slack, Discord, chat webhooks, GitLab | Live | `stackvitals connectors check` against test accounts of ours on 2026-10-28; every one passed |
| Test connection: incident.io, Copilot, S3 bucket | Recorded | Each service's success and refusal answers, saved; no keyed accounts of ours |

## Test a connection

The app's Test connection button starts a manual run with the request `{"version": 1, "check": ["jira", "slack"]}` (or
`"check": "all"` for every connector set up); a request issue with that block, or a `/stackvitals check jira slack`
comment from someone with write access, does the same. A Test connection run from the app gets its own concurrency
group, so a busy data queue never drops it; its write to the data branch retries on top of any run that pushed first.
That run does nothing else: it makes one cheap call per
connector, writes the result under the connector's entry in `docs/connectors.json` as `"check": {"ok", "as", "detail",
"checked_at", "fix"}`, and puts one line per connector in the job summary (or the answer on the issue). What each check
calls: Jira, your account and a one-issue search with `scope_jql`; Linear, the key's user and teams; PagerDuty, each
configured service and a one-incident list; incident.io, a one-incident list; Slack, `auth.test` and a one-message read
of each channel; Discord, the bot's user and a one-message read of each channel; Discourse, the forum's `latest.json`
(no key); GitLab, the project and the token's own scopes (it needs `api` and `write_repository`; at
`CI_API_V4_URL` for a self-hosted GitLab); the bucket, a list of the prefix, then a tiny `.stackvitals-check` object written and
deleted; model triage, the provider's model list; Copilot, the org's usage report for one day. The chat webhooks
(`webhook` and each team webhook) get one message titled "StackVitals connection test", only when a check is asked
for, and never retried, so a slow chat doesn't get it twice. If the bucket kept the test object (the key can't
delete), the result says where it was left so you can delete it. A failure says what went wrong (a missing secret by name, a wrong or expired key, a missing permission or scope, a
wrong site, team, service or channel, or a service that is down) and the next step. Results never hold a key, and on a
public repo they name no account, bot, project or bucket (only the forum and the model provider are named), and a
failure says "one configured channel" (or team, service, bucket) instead of its id. To test your keys locally, set the same variables the Action
uses (`STACKVITALS_JIRA_TOKEN`, `STACKVITALS_SLACK_TOKEN`, ...; a `.env` file works, and the repository secret names
such as `JIRA_API_TOKEN` or `SLACK_BOT_TOKEN` are read too) and run
`stackvitals connectors check jira slack` (or `--all`, `--json`).

## Read a service again

When a service's numbers look off (a key was wrong for a week, an outage at the service), read just that service
again from a date instead of starting over: the **Read again** button on the app's Data health page opens a request
issue (change the date in it first if you like), or comment `/stackvitals resync jira since 2026-09-01` (several
services at once, or no date for the whole 180 days), or send `{"version": 1, "resync": [{"source": "jira", "since":
"2026-09-01"}]}` as the workflow's request. Someone with write access is needed, as for settings. The same run reads
the service again from that date (Jira, Linear, PagerDuty, incident.io, Copilot; Slack, Discord and Discourse read
their whole window). The two GitHub sources work the same way: `ci` lists each day's runs again from the date and
fetches only the runs it doesn't have (about one request a day), and `flow` reads every pull request updated since
the date again; what was kept stays, and records read again win by id, so nothing is counted twice. The run
answers with what it will read and the Activity page logs who asked.

## GitHub (built in)

| Module | What it reads | Permission in the workflow |
|---|---|---|
| CI Health | workflow runs, their attempts and jobs; test reports (JUnit, CTRF, Jest/Vitest, Go, TRX) in run artifacts | `actions: read` (`write` to re-run flaky jobs) |
| Team Flow | pull requests with their reviews, review requests, comments, labels, checks; releases and deployments | `pull-requests: read`, `checks: read`, `statuses: read`, `deployments: read` |
| Delivery | what Team Flow and CI Health read, plus production deployments (GitHub's Deployments API), deploy workflows and releases | as above |
| Community | issues and pull requests with their first answers; optionally traffic through your own GitHub App | `issues: read` |
| Portal | the org's repos, CODEOWNERS, teams, branch rules (an org-owned read-only App for private repos) | an App token |
| Dependency Steward | the lockfiles changed in a pull request; package evidence from the daily crawl | `contents: read` |

All of it goes into the repo's own `stackvitals-data` branch. Without a permission, that part is skipped and the job
summary names the permission to add.

## Issue trackers: Jira Cloud and Linear (one optional key each)

Each is read by your own workflow run with one key from your repo's secrets, on the schedule and manual runs, and kept in
`connectors/<name>/` on the data branch. The first pull reads 180 days of issues; later pulls read only what changed (at
most 20 pages a run, so a big backlog fills in over a few runs, each run carrying on where the last one stopped). Nothing
goes through a server of ours, and the keys are only used to read unless you turn on write-back (below).

- A public repo's data branch is as public as its pages, so for one that isn't known to be private, issue titles, issue
  links and sprint names are never stored; sprints are named by their end date instead.
- Changing a connector's settings (or making the repo public) makes it read everything again from 180 days back, so
  narrower settings drop what they now leave out and wider ones fill in the past.
- On a private repo, Jira and PagerDuty also keep each answer as the service sent it (`connectors/<name>/raw/`), so
  when a StackVitals update reads records differently, they are rebuilt from those answers with no new calls, and the
  job summary says so. A public repo keeps no answers (they hold titles) and reads again instead. Answers follow
  the records' 400-day rule and count toward the branch's size cap.
- Every connector asks its service the same way: a dropped connection or a server error is tried again, a rate limit
  asking to wait up to a minute is waited out, and a longer one stops that run, which the next run carries on.
- Flaky-test tickets: `flaky_tickets = true` with `ticket_project = "WEB"` under `[connectors.jira]` (or
  `ticket_team = "ENG"` under `[connectors.linear]`) opens one ticket per test that turns flaky, with its flake count,
  runs and usual failure, at most 5 a run; once the test counts as fixed the ticket gets a comment and moves to
  `done_transition` / `done_state` (or Done). What was filed is kept on the data branch, so a test is never filed
  twice. Jira tickets are Bugs, or Tasks in projects without that type. Checked live on 2026-10-29: Jira SCRUM-9 and
  Linear ENG-5, each opened and closed.
- Jira custom fields: `team_field` and `severity_field` under `[connectors.jira]` name a field by its name (`Team`) or
  id (`customfield_10001`). Each issue keeps its value as text: done issues are counted per tracker team in the Issues
  view, and an incident shows its severity. A public repo never keeps the team.
- On a private repo, Jira and Linear issues keep who they are assigned to (an account id and, when the service
  shows it, an email). With `[identity] aliases` naming those people's GitHub logins, Delivery counts issues done
  per team, and Slack and Discord count a reply from an aliased team member as the team's, so nobody is listed twice.
  Without an alias, an assignee whose email name is a GitHub login of this repo (`bo@acme.com` for `bo`) counts as
  that login; one whose email or name only reads like a login (`jane.doe@` or "Jane Doe" for
  `jdoe`) is not counted, but the Issues view offers the alias line to paste. A public repo keeps no assignee.
- Only connectors whose key is in the workflow count: remove a key, and its issues and incidents stop counting (what
  was pulled stays on the branch and counts again if the key comes back).
- Like the rest of the history, connector day files are kept 400 days (Copilot reports two years) and count toward
  the branch's size cap.

| | Jira Cloud | Linear |
|---|---|---|
| Key | an API token for the account to read as, plus its email: secrets `JIRA_API_TOKEN` and `JIRA_EMAIL` | a personal API key with read access: secret `LINEAR_API_KEY` |
| Workflow lines (new installs have them) | `jira-email: ${{ secrets.JIRA_EMAIL }}`, `jira-token: ${{ secrets.JIRA_API_TOKEN }}` | `linear-token: ${{ secrets.LINEAR_API_KEY }}` |
| Settings | `[connectors.jira]` `url` (your `https://<name>.atlassian.net` site; no other host is accepted, so the key can't be sent elsewhere), `scope_jql`, `incident_jql`, `key_expires` | `[connectors.linear]` `teams`, `incident_labels`, `key_expires` |
| Read | issues (type, status, created, resolved, points, labels), status and sprint changes, sprints | issues (state, created, completed or canceled, estimate, labels), state and cycle changes, cycles |
| API | REST v3 enhanced search (`/rest/api/3/search/jql`), resuming from the newest update read | GraphQL, one fixed span per pass, resuming from its cursor |

What they unlock: issue lead time (created to done) and cycle time (first in-progress status to done) by type; sprints
and cycles with scope, done by the end, carried over and added after start; incidents (Jira issues found by
`incident_jql`, Linear issues with an incident label) in DORA's change failure rate and recovery, linked to the last
deployment before them; pull requests linked to issues by a key in the title or branch (`WEB-12`, `feature/web-12-x`);
and DevLake's `issues`, `issue_changelogs`, `sprints`, `sprint_issues` and `pull_request_issues` tables. The app's
Connections page shows each connector's light, its last pull, any error in plain words, and a warning 14 days before
`key_expires`; a refused key or an answer that isn't JSON never loses what was pulled before or stops the other
modules. A Jira issue in a done status without a resolution date counts as done from its last move into that status.

**Write-back (opt-in, off by default):** with `write_back = true` under `[connectors.jira]` or `[connectors.linear]`,
each run comments on the issue a newly merged pull request names ("Pull request o/r#12 merged on 2026-10-21" with its
link), and moves it through `done_transition` (Jira) or to `done_state` (Linear) when one is set. Only merges after
write-back was last turned on count, so switching it on (or back on) never floods old issues; reverts never count. Each
pull request and issue is written at most once, at most 10 a run, and only after the run has saved its history, so a
retried run never writes twice. The key then needs permission to comment and move issues; the job summary says what
was written, a refused comment stops that run's writing (those aren't retried), and a refused move is said while the
comments go on. Reading never stops. Tested against recorded API answers, not a live Jira or Linear.

**Filing a flaky test in Linear:** with `[connectors.linear] teams` set, each flaky-test issue StackVitals opens has a
"File it in Linear" link that opens a new Linear issue prefilled with the test and its evidence (no write key needed).
Jira's prefilled create link needs a numeric project id, so Jira teams link the GitHub issue with Jira's own GitHub
integration instead.

## Community channels: Discourse, Slack and Discord

Questions asked outside GitHub count too. Each channel keeps, per question, only when it was asked, when anyone first
replied and when the team did, and (on Discourse) whether it was solved: no text, usernames or user ids. The Community
page shows the team's median first answer with questions still waiting counted, beside issues and Discussions.

| | Discourse | Slack | Discord |
|---|---|---|---|
| Key | none: its public JSON | a bot token with `channels:history`, invited to each channel: secret `SLACK_BOT_TOKEN`, input `slack-token` | a bot with View Channel and Read Message History (message content isn't needed): secret `DISCORD_BOT_TOKEN`, input `discord-token` |
| Settings | `[connectors.discourse]` `url` (https), `team` (usernames), `groups` (group names) | `[connectors.slack]` `channels` (ids like C0123), `team` (user ids) | `[connectors.discord]` `channels`, `team` (ids) |
| A question | a topic opened by someone outside the team | a top-level message; replies are its thread | a message that isn't a reply; replies point at it |
| The team | forum staff, plus `team` and `groups` | the `team` user ids | the `team` user ids |

Name the team: on five public forums, staff first-answered from 1% to 13% of last month's topics while someone answered
from 23% to 83% ([bench/accuracy/community](../bench/accuracy/community/README.md)), so staff alone undercount the
people who answer for a project.
A run reads at most 120 forum topics and 150 Slack threads; the next run carries on. Slack and Discord readers
signed in and read a channel live; reading whole threads is tested on recorded answers.

## Incidents: PagerDuty and incident.io

With either key, DORA's change failure rate and time to restore use that tool's incidents instead of incident labels,
reverts and hotfixes (which would count the same outage twice), and every page names where incidents came from. Each
incident is linked to the last production deployment before it began, as DevLake does. Until `services` (PagerDuty) or
`incident_types` (incident.io) is set, every incident in the account counts for this repo, and the Connections page
says so.

| | PagerDuty | incident.io |
|---|---|---|
| Key | a read-only REST API key: secret `PAGERDUTY_API_KEY`, input `pagerduty-token` | an API key that can view incidents: secret `INCIDENT_IO_API_KEY`, input `incident-io-token` |
| Settings | `[connectors.pagerduty]` `services` (empty: all), `urgencies` (default `["high"]`), `key_expires` | `[connectors.incident_io]` `incident_types` (names; empty: all), `key_expires` |
| Read | List incidents (v2) by when they began, the last two weeks again on each pull for late resolutions | List incidents (v2) by last update; declined, canceled, merged, test and tutorial incidents never count; resolved time from "Resolved at" |

## Code quality: SonarQube or SonarCloud

Set `project` under `[connectors.sonar]` (the project key, like `myorg_myrepo`) and, for your own SonarQube, `url`.
Once a day the Action reads the project's quality gate and its measures (bugs, vulnerabilities, code smells, security
hotspots, coverage, duplication, size and the three ratings) and keeps each day's reading; Delivery's Code quality tab
shows the gate, each measure with how it moved over the month, and coverage by day, beside the delivery numbers.
SonarCloud's public projects need no key; a private project or a SonarQube server needs a token in the `SONAR_TOKEN`
secret passed as `sonar-token`.

## AI spend

What the organisation pays for AI tools, set beside the agents' and AI-marked pull requests merged in the same days
(Delivery, AI-assisted work). Any one key is enough; each is read by your own workflow run and goes only to its
own provider:

| Provider | Key (repository secret) | Workflow line | What is read |
|---|---|---|---|
| Anthropic | an Admin API key (`sk-ant-admin...`): `ANTHROPIC_ADMIN_KEY` | `anthropic-admin-key: ${{ secrets.ANTHROPIC_ADMIN_KEY }}` | the cost report, per day (`/v1/organizations/cost_report`), and Claude Code's daily analytics (`/v1/organizations/usage_report/claude_code`: sessions, lines, commits, PRs, edits accepted) |
| OpenAI | an admin key: `OPENAI_ADMIN_KEY` | `openai-admin-key: ${{ secrets.OPENAI_ADMIN_KEY }}` | the costs, per day (`/v1/organization/costs`) |
| Cursor | a team admin API key: `CURSOR_ADMIN_KEY` | `cursor-admin-key: ${{ secrets.CURSOR_ADMIN_KEY }}` | the billing cycle's spend (`/teams/spend`) and daily agent requests and accepted lines (`/teams/daily-usage-data`) |

The first pull reads 90 days; later pulls read from the last one, two days back, since cost reports fill in late.
Amounts are kept in dollars to the cent, day by day, for two years, in `connectors/ai_spend/`. The page shows the last
30 days per provider (Cursor's current billing cycle, which can't be split by day), the total, and the total over
the AI-involved pull requests merged in those days. That last number is an association: the keys cover all of an
organisation's API use, not only coding, and an unmarked pull request can still have had AI help.
With the Anthropic key, Claude Code's analytics and Cursor's daily use sit side by side in one table (lines added,
pull requests opened, edits accepted, sessions or agent requests). Claude Code's own cost estimate is already in
Anthropic's cost report, so it is never added to the spend twice. Its analytics cover Claude Code signed in to your
Console organisation, not Claude subscription plans.

## GitHub Copilot usage reports

GitHub's report API (it replaced the old metrics API in April 2026) hands out a daily report per organization and per
repository, kept by GitHub for a limited time. StackVitals copies each day into `connectors/copilot/`, so the history
lasts as long as your data branch: the org's active users, suggestions accepted, and pull requests by Copilot, org-wide
and for this repo. The Delivery page's AI-assisted tab shows the last 28 days beside what happened after AI-assisted
pull requests merged. The reports need "Organization Copilot metrics: read", which the workflow's own token can't have:
an org owner registers a private GitHub App with that permission (no webhook), installs it on the org, and the workflow
makes a token with `actions/create-github-app-token` and passes it as `copilot-token`. `[connectors.copilot] org` picks
another org than the repo's owner. A first pull reads the last 60 days; later pulls ask for each new day two days after it
ends, and ask again on later runs until GitHub has it.

## Chat: Slack, Microsoft Teams, Discord

The webhook in `webhook` gets the newly flaky tests, delivery alerts and the weekly digest, each in the chat's own
shape: Slack Block Kit with a header and link buttons (and Slack's own markdown), a Teams Adaptive Card with open-link
actions (for Teams Workflows, which replaced the old Office 365 connectors in 2026), a Discord embed, or plain JSON with
the numbers for anything else. With `team-webhooks` (a secret with one `@org/team = https://...` line per CODEOWNERS
team), a team's newly flaky tests go to its own chat and the rest to `webhook`. Buttons only open links (the app, the
alerts issue, the workflow runs), so nothing needs a server to answer clicks.

## Other CI systems

`stackvitals ci upload` sends test reports (JUnit, CTRF, Jest or Vitest JSON, `go test -json`, TRX) from any CI (GitLab
CI, Jenkins, CircleCI, Buildkite, ...) into the
same branch as one run, so flaky tests, failure groups and monitors work there too. Failure fingerprints strip each of
those systems' checkout folders, so the same failure groups together wherever it ran.

## Deployments and incidents from elsewhere

- Deployments: GitHub deployments to a production environment are read first (Vercel and many hosting services create
  them), then deploy workflows, then releases. If your deploys happen in another repo or a tool GitHub can't see,
  set `source` or `deploy_workflow` under `[delivery]` in `.github/stackvitals.toml`.
- Incidents: issues with an incident label (configurable), revert pull requests and hotfix pull requests.
- **From any tool (Argo CD, Jenkins, Spinnaker, a script, Opsgenie or Rootly webhooks):** send each deployment or
  incident to GitHub as a `repository_dispatch` event. The StackVitals workflow keeps it on the data branch
  (`delivery/recorded.ndjson`) and the next scheduled run counts it like GitHub's own: a production deployment joins
  the deployments, and recorded incidents are used alone, as a pager tool's are. Sending the same `id` again updates
  the record (an incident's `resolved_at`, a deployment's status). The token needs write access to the repo's
  contents, GitHub's rule for dispatch events; no server of ours is involved.

  ```bash
  stackvitals record deployment owner/repo --id argo-1287 --sha "$GIT_SHA" --environment production --tool argo-cd
  stackvitals record incident owner/repo --id INC-42 --at 2026-10-29T09:12:00Z --resolved-at 2026-10-29T10:03:00Z
  # or without StackVitals installed:
  curl -X POST -H "Authorization: Bearer $TOKEN" https://api.github.com/repos/owner/repo/dispatches     -d '{"event_type":"stackvitals-deployment","client_payload":{"id":"argo-1287","sha":"'"$GIT_SHA"'","finished_at":"2026-10-29T09:00:00Z"}}'
  ```

  Fields: deployments take `id`, `finished_at`, and optionally `sha`, `environment` (default production), `status`
  (success or failure), `started_at` and `tool`; incidents take `id`, `created_at`, and optionally `resolved_at` and
  `tool`. A refused event says what to fix in the run's summary. Workflows set up before this need the
  `repository_dispatch` trigger added (the current template has it).

  Ready recipes (each sends the deployment when it has finished; `$TOKEN` is a token with write access to the repo's
  contents, kept in the tool's secret store):

  - **Argo CD** (its notifications engine, in `argocd-notifications-cm`; subscribe the app to `on-deployed`):

    ```yaml
    service.webhook.stackvitals: |
      url: https://api.github.com/repos/owner/repo/dispatches
      headers:
      - name: Authorization
        value: Bearer $stackvitals-token
    template.stackvitals-deployed: |
      webhook:
        stackvitals:
          method: POST
          body: |
            {"event_type":"stackvitals-deployment","client_payload":{"id":"{{.app.metadata.name}}-{{.app.status.operationState.syncResult.revision}}","sha":"{{.app.status.operationState.syncResult.revision}}","finished_at":"{{.app.status.operationState.finishedAt}}","environment":"production","tool":"argo-cd"}}
    ```

  - **Jenkins** (a `post { success { ... } }` step): `sh 'stackvitals record deployment owner/repo --id "jenkins-$BUILD_TAG" --sha "$GIT_COMMIT" --tool jenkins'`
  - **GitLab CI** (a job after the deploy job): `stackvitals record deployment owner/repo --id "gitlab-$CI_PIPELINE_ID" --sha "$CI_COMMIT_SHA" --environment "$CI_ENVIRONMENT_NAME" --tool gitlab`
  - **Spinnaker, Octopus, a script:** the `curl` line above, with the pipeline's id and commit.

- **As CDEvents (Argo, Tekton, Keptn, Jenkins' CDEvents plugin):** send the CDEvent as the dispatch event's
  `client_payload` and its `context.type` as `event_type`. Read: `service.deployed` and `service.upgraded` (a
  deployment), `service.rolledback` (a failed deployment) and `incident.detected` / `incident.resolved` (one incident,
  matched by `subject.id`), in spec versions 0.5 (`...0.3.0` types) and 0.4 (`...0.2.0`). The environment comes from
  `subject.content.environment.id` and the commit, when the event has one, from `customData.sha`. Other CDEvents are
  left alone. Workflows set up before 0.2.0, or from the app's one-click file (kept short to fit a link), need these
  types added to `repository_dispatch`; `stackvitals init` writes them. For example, Argo CD's notifications engine:

  ```yaml
  template.stackvitals-cdevent: |
    webhook:
      stackvitals:
        method: POST
        body: |
          {"event_type":"dev.cdevents.service.deployed.0.3.0","client_payload":{"context":{"specversion":"0.5.1","id":"{{.app.metadata.name}}-{{.app.status.operationState.syncResult.revision}}","source":"/argocd/{{.app.metadata.name}}","type":"dev.cdevents.service.deployed.0.3.0","timestamp":"{{.app.status.operationState.finishedAt}}"},"subject":{"id":"{{.app.metadata.name}}","source":"/argocd","content":{"environment":{"id":"production"},"artifactId":"pkg:generic/{{.app.metadata.name}}@{{.app.status.operationState.syncResult.revision}}"}},"customData":{"sha":"{{.app.status.operationState.syncResult.revision}}"}}}
  ```

- **Flux:** its `githubdispatch` provider sends each event to the repo. A finished reconciliation
  (`ReconciliationSucceeded`, `InstallSucceeded` or `UpgradeSucceeded` at info severity) counts as a production
  deployment of the commit in its revision; Flux's other events are left alone. Point an Alert for your production
  Kustomization or HelmRelease at the provider (add `eventMetadata: {environment: staging}` to name another
  environment), and add its event type, `Kustomization/<name>.<namespace>`, to the workflow's `repository_dispatch`
  types:

  ```yaml
  apiVersion: notification.toolkit.fluxcd.io/v1beta3
  kind: Provider
  metadata: {name: stackvitals, namespace: flux-system}
  spec: {type: githubdispatch, address: "https://github.com/owner/repo", secretRef: {name: stackvitals-token}}
  ---
  apiVersion: notification.toolkit.fluxcd.io/v1beta3
  kind: Alert
  metadata: {name: stackvitals, namespace: flux-system}
  spec:
    providerRef: {name: stackvitals}
    eventSeverity: info
    eventSources: [{kind: Kustomization, name: webapp, namespace: apps}]
  ```

  These recipes are checked against each tool's documented payload, not run on a cluster.

## Findings as events

StackVitals can send what it finds to other tools, so a workflow, a collector or an automation can react: a delivery
alert crossing its limit or coming back under it, a test or job newly turning flaky, and the verdict on a pull request's
failures. Each is a CDEvents custom event (`dev.cdeventsx.stackvitals-alert.raised.0.1.0`,
`dev.cdeventsx.stackvitals-flakytest.detected.0.1.0`, `dev.cdeventsx.stackvitals-verdict.posted.0.1.0`), with an id
that stays the same for the same finding so a receiver can drop repeats. Nothing is sent until you set a target:

- **A URL** (the `events-url` input, from a secret): each event is POSTed as a CloudEvent in structured mode
  (`application/cloudevents+json`), the form CDviz's collector, Argo Events, Knative and n8n read.
- **A repo** (`[events] dispatch_repo = "owner/name"` and the `events-token` input, a token with write access to that
  repo's contents): each event arrives there as a `repository_dispatch` whose `event_type` is the event's type, so a
  workflow with `on: repository_dispatch: types: [dev.cdeventsx.stackvitals-verdict.posted.0.1.0]` runs on it.

`[events] send` picks which kinds go out (all three by default). Events carry names and counts, never log text; test
and job names are made inert as in chat messages; a pull request from a fork never sends one; a verdict goes out once
per CI run that triggered it.

## Bitbucket and Azure DevOps

**Delivery, read-only:** `stackvitals delivery workspace/repo --bitbucket` and `stackvitals delivery org/project/repo
--azure` read the window's merged pull requests with their activity (the first answer from someone else, approvals) and
run the same Delivery build as for GitHub: review phases, and DORA from Bitbucket Pipelines' deployments to production.
Azure DevOps keeps deployments in release pipelines, outside its Git API: send them with `stackvitals record`, or count
merges (`source = "merges"`). Public projects need no token; set `BITBUCKET_TOKEN` (an access token) or
`AZURE_DEVOPS_TOKEN` (a PAT with Code read) for private ones. Bots (Renovate, Dependabot) are left out of people's
numbers as on GitHub. Checked live on atlassian/atlassian-connect-express (Bitbucket) and powershell/PowerShell (Azure
DevOps).

## GitLab

**CI, read-only (built):** `stackvitals ci gitlab group/project` reads a GitLab project's pipelines and jobs (retries
included) and reports them like GitHub Actions: flaky jobs, slow jobs, re-run share. A retried job becomes a re-run
attempt, merge request pipelines count as pull requests, and a job allowed to fail never fails its pipeline. Public
projects need no token; set `GITLAB_TOKEN` for private ones, and `--base` for a self-managed GitLab. Checked on
gitlab-org/cli (78 pipelines in 7 days read with 80 requests).

**Delivery, read-only (built):** `stackvitals delivery group/project --gitlab` reads the window's merged merge
requests with their notes (the first answer from someone else, approvals, draft and ready) and the project's
deployments, and runs the same Delivery build as for GitHub: review phases, DORA from successful production
deployments, deploy attempts with failed ones. gitlab.com shows notes only with a token, even on public projects;
without `GITLAB_TOKEN` the phases end at the merge. Checked on gitlab-org/cli: 153 merge requests in 30 days.

**The rest (later):** GitLab issues with an incident label as incidents, and the same inside the GitLab CI template.

**CI inside GitLab (built, preview):** include `templates/gitlab/stackvitals.yml` in `.gitlab-ci.yml` and add a masked
CI/CD variable `GITLAB_TOKEN` (a project access token with `api` and `write_repository`). Its job runs in the last stage
(`.post`) of merge request, default-branch and scheduled pipelines, and of branch pipelines with an open merge request
(so the note works with merge request pipelines or plain branch pipelines): it reads the finished pipelines, keeps them
in the project's `stackvitals-data` branch, writes CI Health into `public/` for GitLab Pages, and when the merge
request's pipeline failed it leaves one note (edited on later pipelines, and to "CI is passing now" once green) saying
which failures are known flakes or also fail on the default branch. If the push to `stackvitals-data` is refused (a
protected branch, a push rule, or a token without `write_repository`), the job fails and says so. GitLab has no "after
the pipeline" trigger, so the job reads its own pipeline while it runs; there is no verdict check to block a merge. It
is tested against a stand-in GitLab API, not a live project yet.

The merge request, deployment and incident records above come next, in the same job.
