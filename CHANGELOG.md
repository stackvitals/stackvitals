# Changelog

## 0.2.0 (2026-11-01)

- **Compared with other tools:** [docs/compare](docs/compare/README.md) has a page each for Apache DevLake, Middleware,
  CDviz, Pelorus, Liatrio's Backstage plugin, Faros Community Edition, GrimoireLab, LinearB, Swarmia, and Trunk with
  BuildPulse: what each does better, what StackVitals does differently, and what was measured side by side, with
  sources. The README has a short table; `llms.txt` opens with a list of facts.
- **Deployments and incidents as CDEvents or from Flux:** a `repository_dispatch` carrying a CDEvent (spec 0.4 or 0.5)
  is read: `service.deployed` and `service.upgraded` as deployments, `service.rolledback` as a failed deployment,
  `incident.detected` and `incident.resolved` as one incident. A finished Flux reconciliation sent by its
  `githubdispatch` provider counts as a production deployment. Recipes for Argo CD and Flux are in
  [docs/connectors.md](docs/connectors.md).
  **To use it in a workflow set up before 0.2.0**, add the CDEvents types to `repository_dispatch` (`stackvitals init`
  writes them now); for Flux, add your `Kustomization/<name>.<namespace>`.
- **Findings as events:** delivery alerts, newly flaky tests and pull request verdicts can go out as CDEvents custom
  events, as CloudEvents to a URL (the new `events-url` input) and/or as `repository_dispatch` to a repo you name
  (`[events] dispatch_repo` and the `events-token` input), so other tools and workflows can react. Off until set;
  names and counts only, never log text; nothing for pull requests from forks.

## 0.1.4 (2026-10-31)

- PR verdicts catch more failures a change causes (from user feedback):
  - a failure whose flakes in the last 30 days all came from this same pull request reads **New**, not likely flaky: a
    race the change added fails now and then and passes on a re-run;
  - a likely flake that fails on this pull request far more often than on the default branch (2 or more failures, under
    a 5% chance at main's rate) reads **New**: the change made it worse;
  - a likely flake shows its failure rate on the default branch; a first flaky-looking failure of a check that passed
    every recent default-branch run says so;
  - when a failure blamed on the change, or one of those checks, passes on a re-run of the same commit, the comment
    says a green re-run doesn't clear it, instead of "CI is passing now".
  These rules are new and not yet measured on labelled failures; [rules.md](docs/rules.md) says so.
- A public demo site, https://stackvitals.github.io/stackvitals/, built with `stackvitals site build --demo-only`: it
  fetches nothing outside itself, and its setup links point at the README. The landing page uses the app's font.
- `glama.json`, so the Glama listing of the MCP server is maintained by the project.

## 0.1.3 (2026-10-31)

- The app's About page and the project site say Apache 2.0 (they said MIT); the site shows the cube logo and the
  one-command setup.
- The app's Setup page and Help give `stackvitals init owner/repo` as the terminal way to set a repo up.
- PyPI lists the project's links (home, docs, source, issues, changelog).
- Docs: the install page says how to get the command; guides, quickstart and modules lead with `stackvitals init`;
  contradictions fixed (golden paths, GitLab, GitHub Enterprise Server, sign-in, private repos' CI runs, cycle-time
  phases); the PR verdicts are a table; the settings page says which switches are on by default; the architecture
  diagrams list every trigger and show Portal running from the org's repo; a release checklist with the real steps.
- A code of conduct (Contributor Covenant 2.1), with reports through the repository's private reporting form.

## 0.1.2 (2026-10-31)

- `stackvitals init owner/repo` sets StackVitals up in one command: commits the workflow (or opens a pull request), follows
  the first run and turns on Pages for a public repo; a private repo keeps Pages off and opens with `stackvitals ui`.
- The StackVitals cube is the app's logo in the sidebar, the browser tab and the splash; the logo picker is gone.
- The README opens with the logo, a short tour and the architecture; the architecture docs open with a detailed diagram.

## 0.1.1 (2026-10-31)

- The Action's description is shorter, to fit the GitHub Marketplace listing. No other change.

## 0.1.0 (2026-10-31)

First release of StackVitals: one Action, one CLI and one MCP server over these modules. History stays in your repo's
`stackvitals-data` branch, with an app on your repo's GitHub Pages (or `stackvitals ui owner/repo` on your machine).

**CI Health**
- Finds flaky jobs and tests from your GitHub Actions history: a failure that later passed with no code change, on a re-run or on another run of the same code. Outages, gatekeeper jobs and GitHub-managed workflows are ignored.
- Calls a failure likely flaky only with a flake's sign in the log and no changed file named; likely flakes are re-run once, never passed by the verdict check.
- Reads JUnit XML and CTRF JSON test reports from run artifacts (or `stackvitals ci upload` from any CI, GitLab CI included), groups failures by root cause, names the matrix variant flakes came from, and keeps each test's state with the day it began.
- One comment per pull request: which failures are known flakes, which already fail on the default branch (with the same error), and which are new.
- What each flaky test cost and the pull requests it got in the way of; what CI costs by workflow and job; the first-try share opened into the pushes that missed it.
- Opt-in automation: re-run known flakes once, retry only failed tests in the job, quarantine inside Playwright, Maven and dotnet test runs (ending after `max_days`), burn-in for new tests, one issue or Jira/Linear ticket per flaky test, verified fix requests for real CI breaks, and Slack, Discord or Teams alerts.
- Test impact: picks the tests a change can affect, with a replay of the rule on past pull requests.

**Team Flow and Delivery**
- Who acts next on each open pull request, review stages, insiders and outside contributors, suggested reviewers, size labels and PR rules as code.
- LinearB's six cycle-time phases with P50 and P75 (weekends and holidays left out with a working calendar), and DORA counted exactly as DevLake's dashboard counts it, with an export in DevLake's table shapes.
- Deployments from the Deployments API, releases, merges or workflow runs, with release and GitFlow branches; deployments and incidents from any tool through `repository_dispatch`; GitLab merge requests and deployments.
- A deployments tab, all four DORA metrics week by week, per team and per service in a monorepo, several repos pooled into one project, and every DORA number opened into the pull requests and deployments behind it (`stackvitals explain` in the terminal).
- Coding agents' work, review load and how much of people's and agents' code lasts 30 and 90 days; AI tool usage and spend beside AI-involved pull requests.
- Change risk on open pull requests where the repo's own backtest shows it works; what changed in the hours before an incident; a capitalisation CSV for finance.

**Insights and alerts**
- One ranked list of what to fix first, in hours at stake, and alerts when pickup, review, cycle time or change failure rate crosses a threshold.

**Dependency Steward**
- Known vulnerabilities and malware in every lockfile OSV-Scanner reads, .NET project files and SBOMs, the Actions your workflows use and container base images; exploited advisories, dependency paths, development-only packages and Go reachability.
- The smallest fixing upgrade with its command, licence checks on new packages, look-alike package names, `osv-scanner.toml` ignores honoured, SARIF for GitHub's Security tab, and OpenSSF Scorecard's checks run on the repo itself.

**Community, Portal and Explore**
- Newcomers waiting for a first answer (maintainers, regular responders and triagers count as the project's answer), the contributor funnel, cohorts and star history, with forums and chat.
- An org catalog with owners, scorecards, golden paths, required checks, an org-wide view and a Backstage export.
- SQL over your history in the browser, with links to share a query.

**Contribute (MergeScout)**
- Open-source issues an outsider can get merged, with evidence, from a daily snapshot of public repos.

**The app**
- One page per module in the Instrument design, with Overview and Insights first, a Data health page, a demo at `?demo=1`, and decisions and settings saved from the browser.
- One-click setups for more repos once GitHub is connected, and a test call for every connection.

**Decisions and the weekly digest**
- `/stackvitals` commands in comments (quarantine, unquarantine, mute, acknowledge, snooze, exclude) from people with access, each logged with who, why and until when; temporary ones end on their own.
- Requests from the app as prefilled issues, applied by the workflow (settings changes open a pull request when the branch is protected).
- A weekly digest on one pinned issue and/or the webhook; findings keep "open since" and how much of the last 90 days they were active.

**Integrations**
- Jira Cloud, Linear, PagerDuty, incident.io, SonarQube or SonarCloud, Copilot usage reports, Claude Code analytics, Anthropic, OpenAI and Cursor spend, Slack, Teams, Discord, Discourse, Bitbucket, Azure DevOps, GitLab, Backstage and DevLake's tables; GitHub Enterprise Server's API addresses are followed from the job.
- A service can be read again from a chosen date instead of starting over.

**Settings and install**
- `.github/stackvitals.toml`, read on every run; every key is listed in docs/settings.md.
- Modules can be installed one at a time, each asking only for the permissions it uses.

**Measured, with the losses published**
- Accuracy cards with ranges for every headline rule, labels checked by two model families and a model panel, and one command to reproduce each result ([docs/accuracy.md](docs/accuracy.md)).
- Pre-registered side-by-side runs against Apache DevLake, Middleware and OpenSSF Scorecard on public repos.

**Security**
- Every action pinned to a commit, release files signed with Sigstore with an SBOM and build provenance, locked installs, and test reports from forks not trusted.

**For AI agents**
- `stackvitals serve`: one MCP server with every module's tools (11 core tools by default, all 35 with `--tools all`), each answer stamped with when and where it came from, a skill pack and `llms.txt`.
