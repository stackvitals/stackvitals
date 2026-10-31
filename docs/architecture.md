# How StackVitals works

StackVitals has no hosted backend. Everything happens in three places you already have: a GitHub Actions job in your
repo, a branch of your repo, and the reader's browser. The diagram shows one run from start to finish; the sections
under it walk through it panel by panel.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/architecture-detailed-dark.png">
  <img alt="StackVitals in detail: six triggers start a run; it collects from the GitHub API and optional connectors, analyses with six modules plus Insights using the rules registry and peer benchmarks, saves one commit to the stackvitals-data branch, and serves the web app, PR comments, alerts, the MCP server and the CLI. The project's crawler builds the public benchmarks separately." src="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/architecture-detailed-light.png">
</picture>

## Reading the diagram

Blue arrows are data moving through a run. Dashed blue lines are optional or public data. The dashed grey line is the
way back: settings and decisions made in the app.

### 1. What starts a run

A run starts when any of these happens: a CI run finishes (`workflow_run`), the 3-hour schedule comes round, a deploy or
incident is sent from another tool (`stackvitals record`), someone makes a request in the app (`workflow_dispatch`),
someone comments `/stackvitals` on an issue or pull request, or the workflow or settings file changes (`push`). Each
start is the same job; what it reads depends on what started it.

### 2. Collect

The job reads from GitHub with the repo's own token: Actions runs and their logs, test reports (JUnit and the other
formats in [quickstart.md](quickstart.md#what-next)), pull requests and reviews, issues and comments, deployments and
releases, and the lockfiles and workflows in the repo. It reads only what is new since the last run. When the API
budget runs low it saves what it has, and the next run carries on.

Connectors are optional and use keys you add as repository secrets: Jira, Linear, PagerDuty, incident.io, SonarQube,
Copilot usage, Slack, Teams and Discord ([connectors.md](connectors.md)).

### 3. Analyse

Six modules read the same collected data in one pass: CI Health (flaky tests and the verdict on each failing pull
request), Team Flow (who has to act next), Delivery and DORA (deploys, lead time and failures), Dependencies (vulnerable
and risky packages), Community (newcomers and first answers) and Portal (owners and scorecards). Insights then puts
every module's findings in one list, ranked by the hours at stake.

Every verdict stands on two things: the **rules registry**, where each rule has an accuracy card measured on public repos
with its losses ([rules.md](rules.md), [accuracy.md](accuracy.md)), and the **peer benchmarks**, updated daily, that say
how similar repos compare.

### 4. Save

The job opens one shallow checkout of the `stackvitals-data` branch, writes what every module found and makes one
commit. If another run pushed first, every step runs again on the fresh data, so overlapping runs never lose each
other's work. Housekeeping keeps each stream for its retention period and holds the branch under a size cap (250 MB by
default), dropping the oldest days first.

### 5. Data branch

`stackvitals-data` is a branch of your own repo, so it has the repo's access rules: on a private repo, only people who
can read the repo can read it. It holds plain files, no database:

| Folder | What it holds |
|---|---|
| `ci/` `flow/` `deps/` `community/` `portal/` `connectors/` | the history, one gzipped file per day per stream |
| `summary/` | the tables the app, Explore and agents read |
| `decisions/log.ndjson` | every decision and settings change: who made it and why |
| `docs/` | the web app's files, which GitHub Pages serves |

### 6. What you get

- **Web app**: on your GitHub Pages for a public repo, or on your machine with `stackvitals ui owner/repo` for a private
  one. It is static files that read `summary/`; Explore runs SQL in your browser.
- **PR comment and verdict check**: one comment sorts each CI failure as likely flaky, already failing on main, or new.
- **Issues and alerts**: issues for flaky tests, and messages to Slack, Teams or Discord. These are sent only after the
  save, so a re-run never posts twice.
- **MCP server**: AI agents ask the same data (`stackvitals serve`).
- **CLI**: reports, setup, SQL and exports from a terminal (`pip install stackvitals`).

Settings and decisions made in the app come back as issues (or, with your own token, as commits); the next run applies
them and records them in `decisions/log.ndjson`.

### Project side

What one repo can't know on its own, like how similar repos compare, comes from the project's own crawler: scheduled
workflows that sample about 125,000 public repos and publish only aggregates, never any repo's data, to the public
`bench-latest` release. Your job downloads those numbers; it never sends your data back.

## More detail

### One job, one commit

Each run of the Action opens one shallow checkout of the `stackvitals-data` branch, runs every module named in
`modules:` against it, keeps house (retention, the size cap) and commits once
([core/workspace.py](../src/stackvitals/core/workspace.py)). If another run pushed first, the push is rejected and
every step runs again on the fresh data, so overlapping runs converge without losing either side. What talks to people
(comments, issues, chat) runs only after the commit, so a refused comment never loses data and a re-run never posts
twice.

A module that fails is reported in the job summary; the others still run and save. A run that runs out of API budget
saves what it read and says what it left; the next run carries on.

### Storage

History is plain files: one gzipped NDJSON file per day per stream, with retention per stream (CI days 180 days,
transitions and closed pull requests 400, Copilot 730) and a size cap (250 MB by default) that drops the oldest days
first ([scaling.md](scaling.md)). Busy public repos store about 1 KB per CI run. An opt-in squash rewrites the branch's
git history to one commit every 1,000 commits; the files stay byte for byte.

Nothing in the branch is a secret: tokens and keys live in Actions secrets, and on a public repo, tracker titles,
links and people's affiliations are never written ([privacy.md](privacy.md)).

### The app

The app is static: Preact and TypeScript bundled ahead of time (`web/`, built into the package) and copied into the
branch's `docs/` folder as `index.html` and `app/`, with a content security policy that allows only its own scripts. Explore and the printable module pages are separate pages
that load DuckDB and Chart.js from public CDNs at pinned versions. It reads the JSON tables the job wrote. Settings and
decisions made in the app are sent as GitHub issues or comments that the next job applies, or, with the person's own
GitHub token, committed or run straight from the browser; either way GitHub checks the sender's permissions and the
change is recorded in `decisions/log.ndjson`. Explore loads DuckDB in the browser
(from jsDelivr) to run SQL over the same tables.

### Rules and their evidence

The verdicts and headline numbers come from rules listed in [bench/accuracy/registry.json](../bench/accuracy/registry.json):
what it was tuned on, the held-out data it was checked on, the bar it had to meet and every change since
([rules.md](rules.md)). Each card in `bench/accuracy/` holds the method and the results;
[accuracy.md](accuracy.md) is generated from them, and a test fails when a page and its data disagree.

### Cross-repo evidence

What a single repo can't know (how similar repos compare, whether an upgrade broke other projects, how a maintainer
reviews outsiders) comes from a crawl of public repos (a list of about 125,000, about 90,000 of them sampled for CI benchmarks) run by
the project's own scheduled workflows
in `deploy/crawler/`. It publishes aggregates only. Your job reads them; it never sends your data back.

### Code map

| Folder | What it holds |
|---|---|
| `src/stackvitals/ci` | CI Health: collecting runs and test reports, flake detection, the PR verdict, automation |
| `src/stackvitals/flow` | Team Flow: who acts next, review stages, preflight |
| `src/stackvitals/core` | the shared job (workspace, store, settings, decisions), Delivery and DORA, Insights, Explore, the app's data |
| `src/stackvitals/deps` | Dependency Steward |
| `src/stackvitals/community` | Community health |
| `src/stackvitals/portal` | Portal: catalog, owners, scorecards, campaigns, golden paths, the org view |
| `src/stackvitals/connectors` | Jira, Linear, PagerDuty, incident.io, Copilot, Slack, Discord, Discourse |
| `src/stackvitals/web` | the app and the site |
| `src/stackvitals/mcp_server.py` | the MCP server |
| `src/mergescout` | Contribute (MergeScout) |
| `bench/accuracy` | accuracy cards, the rule registry and the generators for the accuracy pages |
| `worker/` | optional Cloudflare Worker for instant alerts |
| `deploy/crawler` | the crawler's workflows |
