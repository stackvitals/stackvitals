# StackVitals settings

Put these in `.github/stackvitals.toml` on your default branch. A merged change applies on the next run (the workflow
runs when the file is pushed). A missing file means the defaults; a value StackVitals can't use keeps its
default and is named in the job summary. The app's Settings page edits the same file.


## [ci.monitors.pass_on_retry]

| Key | Default | What it does |
|---|---|---|
| `min_events` | `2` | Fail-then-pass events with no code change before a test or job is flaky. |
| `quiet_days` | `14` days | Days without a flake before the pass-on-retry monitor lets go. |
| `quiet_runs` | `10` runs | Clean runs in a row before a flaky test counts as fixed. |

## [ci.monitors.failure_rate]

| Key | Default | What it does |
|---|---|---|
| `enabled` | `true` | Watch each test's failure share on the default branch. |
| `window_runs` | `50` runs | Latest default-branch runs the failure rate looks at. |
| `min_runs` | `20` runs | Runs needed before the failure-rate monitor can fire. |
| `activate` | `0.15` | Failure share that turns the monitor on. |
| `resolve` | `0.05` | The monitor stays on while the failure share is above this. |

## [ci.monitors.broken]

| Key | Default | What it does |
|---|---|---|
| `streak` | `3` runs | Default-branch runs in a row that all failed: the test keeps failing (broken). |
| `window_runs` | `5` runs | Latest runs the broken monitor looks at. |
| `activate` | `0.8` | Failure share in that window that marks a test broken. |
| `resolve` | `0.5` | A broken test stays broken while its failure share is at least this. |

## [ci.monitors.slow]

| Key | Default | What it does |
|---|---|---|
| `p50_ms` | `5000` ms | Label a test slow when its median passing time is above this. |

## [ci.monitors.timeout_inflation]

| Key | Default | What it does |
|---|---|---|
| `ratio` | `2.0` x | Label a test when its median failure time is at least this many times its P95 pass time. |
| `min_failures` | `3` | Failures needed before that label shows. |

## [ci.mute]

| Key | Default | What it does |
|---|---|---|
| `"test id or pattern"` | `{} (none)` | Test ids or glob patterns muted until a date: still measured, but no alert and no new issue. |

## [ci.quarantine]

| Key | Default | What it does |
|---|---|---|
| `always` | `[] (none)` | Test ids always on the quarantine list, flaky or not. |
| `never` | `[] (none)` | Test ids never quarantined, even when flaky. |
| `max_days` | `0` | Days a flaky test may stay in quarantine on its own before it fails builds again and is listed as overdue for a fix; 0 never ends it. Tests someone quarantined by hand stay. |

## [ci.coverage]

| Key | Default | What it does |
|---|---|---|
| `min_patch` | `0.0` | The verdict check fails when fewer of a pull request's added lines ran than this (from the coverage report CI uploads); 0 is off. |

## [ci.triage]

| Key | Default | What it does |
|---|---|---|
| `provider` | `"off"` | A model reads the log of up to 3 failures the history can't decide and says whether they look like the change, beside the verdict (never in it); needs the triage-key input (docs/triage.md says how). Setups for each provider: docs/triage.md (gemini has a free tier). |
| `model` | `""` | The model to ask (empty: the provider's suggested small model). |
| `url` | `""` | Another OpenAI-compatible endpoint (https) instead of the provider's own. |
| `allow_private` | `false` | Send a private repo's failing logs too (off: free tiers may keep what they're sent). |

## [delivery]

| Key | Default | What it does |
|---|---|---|
| `deploy_workflow` | `"(?i)(deploy|release|publish|push-image)"` | Workflow names that count as deployments when the repo has no production deployments. |
| `production` | `["production", "prod", "live"]` | GitHub deployment environments that count as production (matched on the first word). |
| `incident_labels` | `["incident", "outage", "sev1", "sev-1", "sev2", "sev-2", "p0"]` | Issue labels that mark an incident. |
| `hotfix_labels` | `["hotfix"]` | Pull request labels that mark a hotfix (counted as an incident). |
| `source` | `"auto"` | Where deployments come from; auto tries deployments, deploy workflows, then releases; merges counts every merged pull request as one (only when chosen: it is a poor guess for most repos). |
| `fix_patterns` | `[] (none)` | Regular expressions on a merged pull request's title or branch that mark it as a fix, with one group naming the pull request it fixes, like ^fix.*#([0-9]+) or ^hotfix/([0-9]+)-; the incident blames the deployment that shipped that pull request. |
| `incident_sources` | `[] (none)` | Where incidents come from: any of issues, reverts, hotfixes, fixes, pager, tracker, recorded; empty keeps the automatic choice (a pager tool's alone when connected, else all of GitHub's). |
| `production_branches` | `[] (none)` | Branches besides the default one that ship to production (globs, like production or release/*): deploy workflows on them count, and so do pull requests merged into them. |
| `ignore_reverts_of` | `[] (none)` | Reverts that are not incidents: of pull requests touching only these paths (globs, like docs/**) or by these authors (like dependabot[bot]). |
| `dora_report` | `"2023"` | The DORA report whose tiers DevLake's dashboard uses. |

## [investment]

| Key | Default | What it does |
|---|---|---|
| `labels` | `{} (none)` | Your own labels for each kind of work (feature, fix, maintenance, security, docs), like maintenance = ["area: platform"] under [investment.labels]; checked before the common ones, for where the work went. |

## [rules]

| Key | Default | What it does |
|---|---|---|
| `rules` | `[] (none)` | PR rules as code: each [[rules]] has a name, a when (author, paths, lines_over, risk, labels, first_time) and a then (label, reviewers, comment); dry_run = true only reports. Each action happens once per pull request; the Pull Requests page shows what each rule matched before and now. |

## [calendar]

| Key | Default | What it does |
|---|---|---|
| `weekends` | `[] (none)` | Days the team doesn't work, like saturday and sunday; left out of review phases and cycle time (DORA's DevLake-matching numbers stay in calendar time, with a working-time lead time beside them). |
| `holidays` | `[] (none)` | Dates the team doesn't work, like 2026-12-25; left out the same way. |

## [services]

| Key | Default | What it does |
|---|---|---|
| `services` | `{} (none)` | Services inside this repo (a monorepo): under [services.<name>], paths is a list of CODEOWNERS-style patterns (like ["services/api/", "libs/shared/**"]) and deploy an optional pattern matched against each deployment's environment or workflow name. Delivery then shows review phases per service, and DORA per service for those with a deploy pattern; a pull request touching two services counts in both. |

## [identity]

| Key | Default | What it does |
|---|---|---|
| `bots` | `[] (none)` | Logins that are bots even if GitHub says otherwise. |
| `people` | `[] (none)` | Logins that are people even if they look like bots. |
| `aliases` | `{} (none)` | Old login to current login, so one person's history stays together. A key can also be a tool's id (`jira:<account id>`, `linear:<user id>`, `slack:<member id>`, `discord:<user id>`) or an email, so one person counts once across tools. |
| `teams` | `{} (none)` | Team name to its members' logins, for numbers by team. |
| `knowledge_names` | `false` | On a public repo, name the person behind each area in the knowledge map (folders one person knows, authors gone quiet). Off by default: public pages show the areas only. Private repos always show names. |

## [alerts]

| Key | Default | What it does |
|---|---|---|
| `pickup_p75_hours` | `4.0` h | Alert when 3 in 4 PRs wait longer than this for a first comment or review (last 28 days); 0 turns it off. |
| `review_p75_hours` | `14.0` h | Alert when 3 in 4 reviews take longer than this; 0 turns it off. |
| `cycle_p75_hours` | `72.0` h | Alert when 3 in 4 PRs take longer than this from first commit to merge; 0 turns it off. |
| `change_failure_rate` | `0.15` | Alert when more than this share of deployments led to an incident; 0 turns it off. |
| `channels` | `["webhook"]` | Where alerts go: the webhook from the workflow, and/or one issue in this repo. |

## [events]

| Key | Default | What it does |
|---|---|---|
| `send` | `["alert", "newly_flaky", "pr_verdict"]` | Which findings go out as events once the events-url input or dispatch_repo is set: delivery alerts, newly flaky tests, pull request verdicts (CDEvents custom events; names and counts, never log text). |
| `dispatch_repo` | `""` | A repo (owner/name) that gets each event as a repository_dispatch, so its workflows can react; needs the events-token input with write access to its contents. |

## [automation]

| Key | Default | What it does |
|---|---|---|
| `pr_comments` | `on (input pr-comments)` | One comment on failed PR runs saying which failures are known flakes. |
| `rerun_flaky` | `off (input rerun-flaky)` | Re-run failed jobs once when every failure is a known flake (needs actions: write). |
| `quarantine` | `off (input quarantine)` | Keep the quarantine list for the stackvitals ci quarantine command. |
| `issues` | `off (input issues)` | One issue per flaky test or job, closed once fixed (needs issues: write). |
| `mention_owners` | `off (input mention-owners)` | @-mention code owners in those issues (off: owners are named without a notification). |
| `assign_owners` | `off` | Assign a new flaky-test issue to its first code owner who is a person. |
| `preflight_comments` | `off (input preflight-comments)` | One note on new outside PRs that miss what merged PRs here usually include. |
| `deps_comments` | `off (input deps-comments)` | One comment on same-repo PRs listing changed packages and their verdicts. |
| `review_requests` | `false` | Off until turned on: request the top suggested reviewer (who knows the folders, who reviewed the author's PRs, eased by load) on ready PRs nobody was asked to review; once per PR. Needs pull-requests: write. |
| `fix_requests` | `false` | Off until turned on: one issue per failure that breaks the default branch every run, closed with proof once fixed. Needs issues: write. |
| `fix_by_copilot` | `false` | With fix_requests: assign each new one to Copilot's coding agent. |
| `size_labels` | `false` | Off until turned on: a size/XS to size/XL label on each open PR by lines changed (under 10, 100, 500, 1000). |
| `docs_label` | `false` | Off until turned on: label PRs that only change docs (Markdown, docs/, README) as low risk: docs only; never approves. |
| `label_stuck` | `off (input label-stuck)` | Label PRs whose asked-for review has not started after 3 days, and unlabel them later. |
| `verdict_check` | `off` | A "StackVitals verdict" check on pull requests: one required check that waits for every workflow on the newest commit and passes once CI is green (and patch coverage holds); known flakes are re-run, never let through (with rerun_flaky, automatically). Needs checks: write. On a private repo also set the repository variable STACKVITALS_EVERY_CI_RUN to true, so passing CI runs start a job. |
| `verdict_strict` | `off` | With the verdict check: when a failure the comment called likely from this change goes green on a re-run of the same code, the check stays red until someone with triage access comments /stackvitals accept rerun on the pull request. Off by default (a green re-run passes). |

## [agreements]

| Key | Default | What it does |
|---|---|---|
| `review_within_hours` | `0` h | Agreement: every PR gets a first comment or review within this many hours; 0 is off. |
| `merge_within_days` | `0` days | Agreement: PRs merge within this many days of being ready; 0 is off. |
| `max_pr_lines` | `0` lines | Agreement: PRs stay under this many changed lines; 0 is off. |
| `linked_issue` | `false` | Agreement: every PR links the issue it solves. |
| `review_before_merge` | `false` | Agreement: nothing merges without a review. |

## [digest]

| Key | Default | What it does |
|---|---|---|
| `enabled` | `true` | Post a weekly digest: what changed, what to fix first, decisions ending soon. |
| `pulse` | `true` | With the issue digest, three pulse questions (flow, friction, satisfaction) answered by reaction; next week's digest shows only the counts (GitHub shows reactions to anyone who can see the issue; on a public repo only the team's own people count). |
| `day` | `"monday"` | The day the digest goes out (the first scheduled run after the hour). |
| `hour` | `6` UTC | The hour, in UTC, from which the digest may go out on that day. |
| `channels` | `["issue"]` | Where the digest goes: one pinned issue in this repo, and/or the webhook. |

## [deps.policy]

| Key | Default | What it does |
|---|---|---|
| `min_scorecard` | `none (off)` | Projects behind the dependencies scoring under this OpenSSF Scorecard (0 to 10) are listed on the supply page, unless a decision accepted the package. Empty is off. |
| `max_severity` | `none (off)` | The pull request check flags a changed package with an open advisory rated above this (low, moderate, high or critical). Empty is off. |

## [deps]

| Key | Default | What it does |
|---|---|---|
| `outside_lookups` | `true` | Look dependencies' public package names up at deps.dev, OpenSSF Scorecard, OSV, npm/PyPI release data, endoflife.date and the registries' download counts (docs/privacy.md); off scans with downloaded OSV databases, skips release checks, runtimes and GuardDog, and keeps every dependency name in the repo. |
| `guarddog` | `false` | Off by default: the pull request check also runs DataDog's GuardDog on each npm or PyPI package version it adds or upgrades (at most 10), which downloads the package and looks for malicious code (install hooks, obfuscation, data sent out); a finding is a reason to look first. Needs outside_lookups on; Linux runners only. |

## [deps.licenses]

| Key | Default | What it does |
|---|---|---|
| `deny` | `[] (none)` | SPDX licence ids the repo's dependencies must not use (* allowed, like GPL-3.0*); a package offering an allowed choice is fine. Empty is off. |

## [benchmarks]

| Key | Default | What it does |
|---|---|---|
| `share` | `false` | Off by default: each CI run's summary offers a link that files this repo's rounded CI figures (pushes, time to green, first-try share; no names, no code) as an issue on StackVitals' public repo, so private repos get peer groups once 10+ of a kind have shared. Nothing is sent unless a person opens the link and files it. |
| `name` | `false` | With benchmarks.share on: include this repo's name in the shared figures. Off shares them without it. |

## [community]

| Key | Default | What it does |
|---|---|---|
| `capacity` | `""` | Who maintains the project and how much time they have, in your words (like "two volunteers, evenings and weekends"); shown on the Community page so the numbers are read against it. |
| `norms` | `""` | How the project works with people, in your words (like "issues are triaged on Mondays; ideas go to Discussions first"); shown on the Community page. |

## [connectors.jira]

| Key | Default | What it does |
|---|---|---|
| `url` | `""` | Your Jira Cloud site, like https://acme.atlassian.net. The API token goes in the JIRA_API_TOKEN secret, never here. |
| `email` | `""` | The Jira account's email, when it is not in the JIRA_EMAIL secret. |
| `scope_jql` | `""` | JQL for the issues to read, like project in (WEB, API); empty reads every issue the account can see. |
| `incident_jql` | `""` | JQL for the issues that are incidents, like issuetype = Incident; they count in DORA's change failure rate and recovery. |
| `key_expires` | `""` | When the Jira API token expires (a year at most); a warning shows 14 days before. |
| `write_back` | `false` | Comment on the Jira issue a merged pull request names (the account must be able to comment); off by default. |
| `done_transition` | `""` | With write-back on, the transition to move that issue through, like Done; empty only comments. |
| `flaky_tickets` | `false` | Open a Jira issue for each test that turns flaky, in ticket_project, and comment and move it to done_transition (or Done) once fixed; the key must be able to write. |
| `ticket_project` | `""` | The Jira project key flaky-test issues go in, like WEB. |
| `team_field` | `""` | A Jira field that names each issue's team (its name, like Team, or its id, like customfield_10001): done issues are counted per team. Private repos only. |
| `severity_field` | `""` | A Jira field that gives each incident's severity (name or id), shown with the incident. |

## [connectors.linear]

| Key | Default | What it does |
|---|---|---|
| `teams` | `[] (none)` | Linear team keys to read, like ENG; empty reads every team the key can see. |
| `incident_labels` | `["incident"]` | Linear labels that mark an incident. |
| `key_expires` | `""` | When the Linear key expires, if it does; a warning shows 14 days before. |
| `write_back` | `false` | Comment on the Linear issue a merged pull request names (the key needs write access); off by default. |
| `done_state` | `""` | With write-back on, the team's workflow state to move that issue to, like Done; empty only comments. |
| `flaky_tickets` | `false` | Open a Linear issue for each test that turns flaky, in ticket_team, and comment and move it to done_state (or Done) once fixed; the key must be able to write. |
| `ticket_team` | `""` | The Linear team key flaky-test issues go in, like ENG. |

## [connectors.discourse]

| Key | Default | What it does |
|---|---|---|
| `url` | `""` | The project's Discourse forum, like https://discuss.example.org; its public topics are read with no key (times and flags only, never text or usernames). |
| `team` | `[] (none)` | Forum usernames whose replies count as the project's (forum staff always do). |
| `groups` | `[] (none)` | Forum groups whose members' replies count as the project's. |

## [connectors.slack]

| Key | Default | What it does |
|---|---|---|
| `channels` | `[] (none)` | Slack support channel ids to read (the bot from the slack-token input must be in each); only times and flags are kept. |
| `team` | `[] (none)` | Slack user ids whose replies count as the project's. |
| `key_expires` | `""` | When the Slack bot token expires, if it does; a warning shows 14 days before. |

## [connectors.discord]

| Key | Default | What it does |
|---|---|---|
| `channels` | `[] (none)` | Discord channel ids to read (the bot from the discord-token input needs View Channel and Read Message History); only times and flags are kept. |
| `team` | `[] (none)` | Discord user ids whose replies count as the project's. |
| `key_expires` | `""` | When the Discord bot token expires, if it does; a warning shows 14 days before. |

## [connectors.pagerduty]

| Key | Default | What it does |
|---|---|---|
| `services` | `[] (none)` | PagerDuty service ids whose incidents count; empty counts every service the key can see. |
| `urgencies` | `["high"]` | Which PagerDuty urgencies count as production incidents. |
| `key_expires` | `""` | When the PagerDuty key expires, if it does; a warning shows 14 days before. |

## [connectors.incident_io]

| Key | Default | What it does |
|---|---|---|
| `incident_types` | `[] (none)` | incident.io incident types that count, like Platform; empty counts every type (test and tutorial incidents never count). |
| `key_expires` | `""` | When the incident.io key expires, if it does; a warning shows 14 days before. |

## [connectors.copilot]

| Key | Default | What it does |
|---|---|---|
| `org` | `""` | The organization whose Copilot usage reports to keep; empty means this repo's owner. |
| `key_expires` | `""` | When the Copilot reports token expires, if it does; a warning shows 14 days before. |

## [connectors.sonar]

| Key | Default | What it does |
|---|---|---|
| `url` | `"https://sonarcloud.io"` | SonarCloud (https://sonarcloud.io) or your SonarQube server. |
| `project` | `""` | The Sonar project key, like myorg_myrepo; its quality gate and measures are read each day. A private project or SonarQube server needs the SONAR_TOKEN secret. |
| `key_expires` | `""` | When the Sonar token expires, if one is used; a warning shows 14 days before. |

## [connectors.ai_spend]

| Key | Default | What it does |
|---|---|---|
| `key_expires` | `""` | When the soonest of the AI spend admin keys (Anthropic, OpenAI, Cursor) expires, if it does; a warning shows 14 days before. |

Example:

```toml
[alerts]
pickup_p75_hours = 6
channels = ["webhook", "issue"]

[ci.mute]
"tests/test_api.py::test_slow_network" = 2026-12-31

[automation]
issues = true
```
