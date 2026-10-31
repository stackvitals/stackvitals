# Modules

What each StackVitals module does, how to try it on any public repo from your machine, and how to set it up in your own repo. The [README](../README.md) has the overview and the [quickstart](quickstart.md) the five-minute setup.

## CI Health

**Try it on any public repo from your machine** (needs a GitHub token in `GITHUB_TOKEN`, or `gh auth login`):

```
stackvitals ci report owner/repo --days 14 --html ./ci-report
```

**Install it in a repo**, any of three ways ([docs/quickstart.md](quickstart.md); the whole file, every module id and every input: [docs/install.md](install.md)):

- `stackvitals init owner/repo`: commits the workflow, follows the first run and turns on Pages for a public repo; a private repo opens with `stackvitals ui owner/repo`.
- The StackVitals app's Setup page: the same in a few clicks once GitHub is connected (one token, made from a prefilled GitHub page).
- By hand: print it and save it as `.github/workflows/stackvitals.yml`:

```
stackvitals ci init owner/repo
```

Committing it starts the first run. After that it runs after each of your CI runs finishes, every 3 hours, and whenever `.github/stackvitals.toml` changes on your default branch. Each run:

1. reads new CI runs, including every re-run attempt and its jobs and steps;
2. stores them in the `stackvitals-data` branch of your repo, one compressed file per day;
3. rebuilds the dashboard in that branch's `docs/` folder.

To view the dashboard on a public repo, set GitHub Pages to deploy from branch `stackvitals-data`, folder `/docs`.

**The app:** `https://OWNER.github.io/REPO/` opens one app over every module that ran. Overview shows installation health, each area's state, the trend you pick, what needs a decision, what to fix first and decisions ending soon. Each page (Insights, CI Health, Pull Requests, Delivery, Community, Dependencies, Investment, Portal, Explore) has its charts and tables; Settings, Activity, Setup, Connections, Agents and Help sit beside them, with a tab bar on phones. With a GitHub token (kept in the tab unless you ask to remember it) the app sets up more repos in a few clicks, saves settings and decisions, and tests connections. The app itself runs only its own files (no CDN); Explore and the printable pages load DuckDB and Chart.js from public CDNs ([docs/privacy.md](privacy.md)). For a private repo, `stackvitals ui owner/repo` opens the same app on your machine; `?demo=1` shows three example repos. The older pages (`ci.html`, `flow.html`, ...) stay as printable views, each with an "Open in the app" link. How to use it: [docs/app.md](app.md).

**Your data branch:** every module writes into one checkout and the job makes one commit. The branch keeps 400 days of pull requests, issues and Portal history and 180 days of CI runs and test results (`retention-days`, `ci-retention-days`), and at most 250 MB of history in all (`size-cap-mb`; the oldest days go first; the pages never count). `squash-history: true` rewrites the branch to a single commit every 1,000 commits: the files stay byte for byte, only the git history behind them goes, and the branch is force-pushed, so leave it off if anything else commits there. Every published file carries a `schema` number. The `summary/` folder holds one row per pull request, job and test as JSON lines, small enough for a browser or any SQL engine to read without a server; `stackvitals sql --repo owner/name "select role, count(*) from prs group by role"` queries them with DuckDB (`pip install 'stackvitals[sql]'`; tables `prs`, `ci_jobs`, `tests` and DevLake's `devlake_*`).

**Explore:** `docs/explore.html` runs SQL over the `summary/` files in your browser, with DuckDB (WebAssembly, loaded from jsDelivr at a pinned version; its worker and WebAssembly are checked against integrity hashes). Saved queries include Apache DevLake's own dashboard SQL (its DORA panels, PR cycle time, and panels from its GitHub, Engineering Overview and Contributor Experience dashboards), ported to DuckDB and run on DevLake-shaped tables of your repo (`summary/devlake_*.jsonl`), plus our own (merged PRs per week, insiders and outside contributors, flakiest jobs, tests that fail most). On public repos the tables are published beside the pages (`docs/summary/`), so it reads them from your own site.

**On your machine, for private repos too:** `stackvitals ui owner/repo` keeps a copy of the data branch and opens every page, Explore included, on `127.0.0.1` (the token is used for that one git command and never stored).

**Exports:** `stackvitals export owner/repo --format devlake` (DevLake's tables and its DORA SQL as `dora.sql`), `--format ctrf` (every test with its history over the window, as a CTRF report) `--format postgres` (DevLake's tables as CSV and `postgres.sql` to load them into Neon, Supabase or any Postgres) or `--format otel` (CI runs, jobs and steps as OpenTelemetry traces, OTLP JSON for Grafana Tempo, Honeycomb, Datadog or any collector; `--tests` adds failed and flaky tests as events). Several repos at once: `stackvitals sql --repo org/a --repo org/b "select repo, ..."`. How it grows from one repo to an org, with measured sizes and the free Postgres tiers: [docs/scaling.md](scaling.md); what it reads and from where, and the GitLab plan: [docs/connectors.md](connectors.md).

The CI health, Team Flow, Delivery, Insights, Community, Portal and Explore pages share one header. Long tables can be searched and filtered. Weekly and monthly trends are drawn as charts (Chart.js, loaded from cdnjs at a pinned version with an integrity hash); each chart is drawn from the numbers table under it, which is all you see with JavaScript off. Every flaky or failing test and job gets its own page in `docs/history/`: its runs over the kept history, newest first, with flakes marked and each run linked.

**Private repos:** Pages from a private repo is public on most plans, so it would expose test names. Use `stackvitals ui OWNER/REPO`, `pages: artifact` (a download kept 7 days) or the job summary instead.

**Badge:** each run writes `docs/badge.json`, the share of pushes whose checks all passed on the first try. On a public repo, add this to your README (replace OWNER/REPO):

```
![CI first try](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/OWNER/REPO/stackvitals-data/docs/badge.json)
```

**Compared with similar repos:** reports put two numbers next to the typical public repo of the same language and size: the time from a push until all its checks finish, and the share of pushes green on the first try. Each comparison names how many repos it covers. The numbers come from a daily sample of about 90,000 active public repos with 100+ stars (each read once every 4 weeks). A group is shown only when it has at least 20 repos. Under 30 pushes, the first-try share also comes pulled toward the group's pattern, with its range: on 6,623 crawled repos, predicting held-out pushes from 3 to 20 of them, the pulled share cut squared error by 29% to 3%, and a 95% range for the share of later pushes held 95% of them (the page's range is for the share itself, so it is narrower). Set `STACKVITALS_BENCH_URL` to a benchmarks file or URL to choose the source.

**Peers that aren't public open source (opt-in):** with `[benchmarks] share = true`, each CI run's summary offers a link that files this repo's rounded figures (pushes to the nearest 10, time to green to the nearest 30 seconds, first-try, failing and re-run shares to the nearest point; language and star tier; no names, no code, the repo's name only with `name = true`) as an issue on StackVitals' public repo, through a labelled issue form, with a random id kept in the data branch so next month's figures replace this month's. Nothing is sent unless a person opens the link and files it; the issue shows the account that files it, and closing it withdraws the figures. The daily job turns the latest month of each shared repo into peer groups, published only with 10+ repos of a kind and counting one figure set per GitHub account, and an id only for the account that first filed it (filed figures can't be verified); with sharing on, the CI comparison uses those groups first and says so.

**Single flaky tests:** save your test results with `actions/upload-artifact`, under a name containing `test-results`, `junit` or `ctrf` (or `jest`, `vitest`, `go-test`, `trx`). StackVitals reads JUnit XML from pytest, Maven, Gradle and others, CTRF JSON (Playwright and others), Jest and Vitest JSON, `go test -json` output and .NET TRX files from each run before GitHub deletes the files. A test that a retry plugin re-ran and passed within the same job (Gradle test-retry, Surefire, pytest-rerunfailures, Playwright retries, jest.retryTimes, gotestsum's re-runs) counts as flaky. Each parameter of a parametrized test is tracked on its own (pytest's `[...]`, Go subtests, .NET data rows), and when a run's order was random (Surefire's random order, `go test -shuffle`) the seed is kept, so a failure can be replayed.

**Why a test is flaky, and since when:** each test's state comes from monitors you can tune, and the page says which ones hold it there and since when (kept in `ci/status.json`, with every change logged in `ci/transitions/`):

| Monitor | Switches on | Switches off |
|---|---|---|
| Pass on retry | failed and passed on the same code twice in the window | after 14 quiet days |
| Failure rate | 15% or more of the last 50 default-branch runs failed (at least 20 runs) | below 5% |
| Keeps failing | the last 3 default-branch runs failed, or 80% of the last 5 | below 50% |

Labels: **slow** (median over 5 seconds) and **timeout inflation** (failures take at least twice as long as the 95th percentile of passes). Change any threshold, mute a test until a date, or pin the quarantine list in `.github/stackvitals.toml` on your default branch (read on every run, so a merged change applies at once; a bad value keeps its default and is named in the job summary). Every setting is listed in [docs/settings.md](settings.md):

```toml
[ci.monitors.pass_on_retry]
quiet_days = 7          # Trunk's default

[ci.mute]
"tests/test_network.py::*" = 2026-12-31   # measured, but no alerts or issues until then

[ci.quarantine]
always = ["tests/e2e/test_upload.py::test_resume"]
never = ["tests/test_billing.py::test_charge"]
```

**Failure groups:** every failure gets a fingerprint in Sentry's order: the root cause's exception type (the last "Caused by", not the wrapper) and the innermost frames of your own code, leaving out the language, the test framework and installed packages; the message counts only when there is no stack. Failures with one fingerprint are one group across tests and runs, so the page shows "the same failure in 9 tests since October 1" with a link to the latest run, and a failed PR's comment says so. Checked on 53 hand-labelled real failures from netty (Java), pandas-datareader and Context-Engine (Python) and rayfin (TypeScript): no two different causes merged, 98% of same-cause pairs grouped. Works for Java and Kotlin, Python (pytest and plain tracebacks), JavaScript and TypeScript (Jest, Vitest), Go, Rust and C#.

**Test reports from other CI systems:** run `stackvitals ci upload --sha "$SHA" --branch "$BRANCH" --run-id "$BUILD_ID" --provider jenkins test-results/*.xml` at the end of a Jenkins, GitLab, CircleCI or Buildkite job, with `STACKVITALS_TOKEN` set to a token that can write the repo and `--repo owner/name`. The reports join the same history; pass `--attempt 2` when your CI re-runs a job, and a test that failed then passed on the same commit counts as flaky.

**On pull requests:** when a PR's CI fails, StackVitals posts one comment and edits it on later runs. Each failure gets one verdict:

| Verdict | When | What to do |
|---|---|---|
| Likely flaky | The job flaked 3 or more times lately, once in the step that failed now; that step's log shows a flake's sign (an outside service, the runner or a wait failing with no failing test) and names no file the pull request changed. The row shows that evidence, and how often it failed on the default branch: a change can make a flaky test fail far more often. | Check the error, then re-run it. |
| Maybe yours | The job flaked before, but its failing step names a file the pull request changed. | Look at your change first. |
| Outside service or runner | The failing step's log says an outside service or the runner failed. | Re-run it. |
| Flaked before, needs a look | The job flaked before, but too rarely, elsewhere or with no flake's sign to rule out the change. | Look before re-running. |
| Already failing on main | The default branch fails with the same error (checked in the log: the same step alone isn't enough, since on labelled data 4 of 20 such failures were the change's own). | Not caused by this pull request. |
| Maybe flaky | It never flaked, but failed the way flaky checks do (a wait running out, a benchmark gate, a live service). When it passed all of 20 or more recent default-branch runs, the row says so. | Re-run it once to tell. If the re-run passes, the comment still asks for a look before merging. |
| PR details | A check on the pull request itself (a changelog label, a description checkbox, a title prefix) in a workflow that runs again when the PR is edited; 23 of 24 labelled matches were this. | Fix the PR, not the code. |
| New | None of the above; or every flake in the last 30 days came from this same pull request (a race or order dependence it added fails now and then and passes on a re-run); or a likely flake failed on this pull request far more often than on the default branch (2 or more failures, under a 5% chance at main's rate). | Likely from this change. If a re-run of the same commit passes, the comment says a green re-run doesn't clear it. |

A flaky failure also says what kind it looks like: the environment (timing, network, infrastructure, concurrency) or, when none of those shows, the test's own code (a resource leak, an async wait, time and time zones, randomness, floating point, state shared between tests, files, ordering), and a flaky job or test says when it began: its first flake, how many runs before it were clean, whether that could be chance, and the commits that reached the default branch the day before, worded only as surely as the history allows. Those commits are context, not a culprit: on 5 clear starts in 45 public repos they touched tests or the workflow 9 of 12 times, about as often as random commits there (8 of 12).

Nothing is called safe to re-run, and a likely flake is a reason to re-run, never to let a failure through: on 81 clearly labelled held-out calls in 15 public repos (labelled by two model families, no person audit), history alone was the change's own failure 13 times (16%); the stricter rule, pre-registered and scored on 36 fresh repos, called 4 of 44 such failures likely flakes and none was the change's, but 4 calls can't show the 5% bar (0-49%), so the verdict check waits for a green run and a re-run decides ([bench/accuracy/flaky](../bench/accuracy/flaky/README.md)).

To get it, the workflow `stackvitals ci init owner/repo` prints runs on each finished CI run of that repo.

**Opt-in automation (all off by default):**

| Input | What it does | Permission it needs |
|---|---|---|
| `rerun-flaky: true` | Re-runs failed jobs once when every failure is a known flake | `actions: write` |
| `issues: true` | Keeps one issue per flaky test or job, closed when fixed | `issues: write` |
| `mention-owners: true` | @-mentions the code owners in those issues (otherwise they are named without a notification) | `issues: write` |
| `webhook:` (a secret) | Posts to Slack (Block Kit with link buttons), Microsoft Teams Workflows (an Adaptive Card), Discord or any URL when something newly turns flaky | none |
| `team-webhooks:` (a secret) | One `@org/team = https://...` line per CODEOWNERS team: a team's newly flaky tests go to its own chat | none |
| `quarantine: true` | Keeps a quarantine list for the command below | none |

**Fix requests for real breaks (verified self-healing):** with `fix_requests = true` under `[automation]`, a failure
that breaks the default branch every run (never a flake) gets one issue labelled `stackvitals-fix`: what fails, where,
the runs that show it (CI text fenced as data an agent must not obey), and what done means, these exact tests passing
on the default branch. When they do, StackVitals comments with that and closes the issue; it reopens if they break
again, and one closed as "not planned" stays closed. At most two new ones a run. With `fix_by_copilot = true` too, each
new one is assigned to GitHub's Copilot coding agent, which opens a pull request for review (the agent must be enabled
for the repo; if it can't be assigned, the issue still stands and the summary says so). StackVitals never pushes code:
the fix is a pull request a person reviews and merges, and the issue closes only on what CI shows afterwards.

**What CI costs:** billed minutes and money over the last 30 days, by workflow and by job, at GitHub's published
per-minute prices for each runner (standard and larger Linux, Windows and macOS runners; each job rounded up to a whole
minute, as GitHub bills it), and the minutes and money spent on attempts that failed and then passed on a re-run, which
is what flaky jobs cost. On a public repo standard runners are free, so the page also says what the same use would cost
on a private one; larger runners are never free. Self-hosted runners are counted in minutes only. Each flaky test's cost is listed too: the job minutes of the attempts it flaked in (split evenly when several tests flaked in one attempt) and how many pull requests it got in the way of.

**Matrix variants:** a flaky test's flakes are counted by the test report they came from (an OS or a version in a
matrix, as the artifact names it), so a test that only flakes on macOS says so on its page.

**Owners:** if the repo has a CODEOWNERS file, each flaky test or job names its owners on the dashboard, on its history page, in its issue and in the webhook alert. They are looked up with GitHub's own rules (the last matching line wins, and owners GitHub ignores, such as people without write access, are left out) for the test's file, else for the workflow file. A test's file comes from its id (`tests/test_api.py::test_x`), or from its class name matched against the repo's files (`tests.test_api`, `com.acme.ApiTest`); when two files fit, the workflow's owners are used instead.

**PR checks that read the PR itself:** a job that reads a PR's title, description or labels, in a workflow that also runs when those change (a PR template check, say), can pass and fail on the same code. Same-code differences in such a job are not counted as flakes; a failed job that passes on a re-run still is, and test reports are always judged. Each workflow file run by pull requests is read once a week.

**Catch a flaky test before it merges:** run the tests a pull request adds or changes several times; the step fails when one of them both passes and fails:

```
stackvitals ci burn-in --base origin/main --times 5 --reports "out/*.xml" -- pytest {files} --junitxml out/results.xml
```

`{files}` becomes the added or changed test files (pytest, Go, Jest/Vitest, JUnit-style Java, Kotlin and C# names); with none, nothing runs. After `git fetch origin stackvitals-data` it also knows which tests the default branch has never run, and says how many of the repeated tests are new; `--only-new` fails the step only when a new test both passes and fails, since known flaky ones are quarantine's job. It also shows a fix on the pull request itself: a test the data branch calls flaky that passes every repeat is reported with the chance it would have anyway at its old failure rate (a test that failed 40% of runs passes 10 in a row 0.6% of the time), and the fix counts as shown under 5%; otherwise it asks for more repeats. A test failing every time is listed, and your normal CI run fails for it.

**Quarantine command:** wrap your test command like this:

```
stackvitals ci quarantine --reports "out/*.xml" -- pytest --junitxml out/results.xml
```

It passes only when every failure is a quarantined test. If the quarantine list can't be read, nothing is quarantined.

**Or inside the test runner:** `stackvitals ci quarantine --print jest` (or `vitest`, `go`, `pytest`, `playwright`, `maven` for Surefire, `dotnet`) prints, one per
line, the arguments that keep quarantined tests from failing a run, so the CI command stays as it is:

```
mapfile -t skip < <(stackvitals ci quarantine --print jest) && npx jest "${skip[@]}"
pytest $(stackvitals ci quarantine --print pytest)
```

Jest and Vitest get a name pattern that skips each quarantined test by its name (inside `describe` blocks too; another
test ending in the same name is skipped as well), `go test` a `-skip` pattern (top-level Test, Fuzz and Example names),
and for pytest the list is written to `.stackvitals-quarantine.json` and a plugin loaded that still runs each quarantined
test (matched by its file, class and name) but marks it an expected failure, so its result stays in the report. Only
tests on the list are touched; a test failing every time (broken, not flaky) is never put on the list by StackVitals. Quarantine can end: `max_days` under `[ci.quarantine]` takes a flaky test out after that many days, so it fails builds again until someone fixes it, and the CI page lists it as overdue; tests someone quarantined by hand (or listed under `always`) stay.

**Run only the tests a change can affect:** `stackvitals ci impact --base origin/main --tests 'tests/**/*.py'`
prints the test files to run (or `all`, or nothing for a change no test touches, like docs). A test file is picked when
it changed, when its name matches a changed file (`cart.py` and `test_cart.py`), or when it failed before on pull
requests that changed the same folder; a change to build, lock or settings files (`pyproject.toml`, `package.json`,
`conftest.py`, `.github/`...) runs everything. No coverage agent is needed. Each run of the Action learns the folders
and failures from the repo's own pull requests (`ci/impact.json` on the data branch, which the command reads after
`git fetch origin stackvitals-data`) and replays the rule on them, each judged with only what was known before it:
the CI page shows how many of their real failures it would have run and how much it would have skipped. Treat it as
a fast first pass until that number is high on your repo. On public repos it can't be measured yet: of 329,177 test results read from five repos that keep test reports, one failure was on a pull request run ([bench/accuracy/impact](../bench/accuracy/impact/README.md)).

**Retry only what failed, never what is broken:** `stackvitals ci retry --reports 'out/*.xml' -- pytest --junitxml
out/r.xml --then pytest --lf --junitxml out/r.xml` runs the suite and, when it fails, reads which tests failed. If one of
them is a test the data branch calls broken (failing every time on the default branch), the job fails at once and
says so, since a retry would only hide it; otherwise your runner's own "only failures" command (`pytest --lf`,
`jest --onlyFailures`, `rspec --only-failures`) runs up to `--times` times, and the job passes when a retry does. The
retried tests' results land in the same reports, so their flakes are counted.

**Check a report before CI reads it:** `stackvitals ci validate 'build/test-results/**/*.xml'` reads each file as the
Action does and names what would quietly break things: no tests in it, test cases with no name, none naming a file or
class (owners, shards and test impact need one), every duration 0, a suite count that doesn't match its cases, or a
timestamp from another week (an old report left in the folder). It exits non-zero on errors, so it can run as a CI step.

**Shards that finish together:** split your test files into N groups by their recorded times, read from the newest green run on the default branch that kept test reports (or from report files on your machine with `--reports`):

```
stackvitals ci shards owner/repo --n 4                       # all four shards and their expected time
pytest $(stackvitals ci shards owner/repo --n 4 --index 2 --py-paths)   # one shard, for a CI matrix job
```

Files with no recorded time yet (`--files "tests/**/*.py"`) count as a typical file. An empty shard prints nothing and says so, since most test runners run everything when given no files.

**Coverage, from the reports CI already uploads:** Cobertura (`coverage.xml` from coverage.py, Istanbul or Go
converters), LCOV (`lcov.info`) or JaCoCo XML in an artifact whose name says coverage. Each run's total is kept, so the
default branch's line coverage has a daily trend; on pull requests, StackVitals reads the PR's diff and says how many of
the added lines ran ("patch coverage") and which did not. With `min_patch` under `[ci.coverage]` (a share, 0 is off) the
verdict check fails when fewer added lines ran than that. Line hits are read once and never stored; only the totals are.

**New and skipped tests:** a test is named as new the first time a report shows it (after the first run, which only learns what exists), with how it has done since; the app lists tests added in the last 14 days, the ones already failing or flaky first. Tests skipped on the default branch are listed with since when (as far back as the stored reports go) and in how many matrix jobs, newly skipped ones marked. Slow tests and jobs carry their daily median time.

**An investigation prompt per failure group:** the app's Failure groups tab has a "Copy prompt" button, and the MCP tool `failure_group` returns the same text: what failed, where, how often, the runs that show it, which of its tests are known flaky, and what to find out. Paste it into Claude Code, Codex or Copilot to start from the history instead of one log.

**In your editor:** `stackvitals editor vscode` (or `cursor`, `vscodium`) installs a small extension that marks flaky and broken tests where they are declared (Python, Go, JS/TS, Java, Kotlin, C#, Rust), with how often each flaked, its usual failure and a link to the latest run that shows it. It reads `docs/data.json` from the `stackvitals-data` branch through your own git, so it needs no token and works for private repos; "StackVitals: Refresh flaky tests" fetches the newest.

**For AI agents:** `stackvitals serve` is one MCP server (in Claude Code: `claude mcp add stackvitals -- uvx stackvitals serve`), a memory for coding agents: what this repo's history knows that a live search can't (is this failure a known flake, already failing on main, how changes get merged here, who should review, how an upgrade went elsewhere). By default it offers 11 tools (`ci_failure`, `is_known_flake`, `ci_health`, `repo_brief`, `preflight`, `who_should_review`, `pr_queue`, `check_package`, `scan_lockfile`, `insights`, `delivery_health`), which keeps an agent's context small (in an informal check, on 11 everyday questions, a Haiku agent picked the right tool from the 11 and from all 35 alike); `stackvitals serve --tools all` (or `STACKVITALS_MCP_TOOLS=all`) adds the rest; the skills below and the MCP registry entry use all of them. All tools: the MergeScout tools plus `ci_health`, `is_known_flake`, `ci_failure` (now with each failure's group), `ci_slowest` (with daily medians, new and skipped tests), `test_status` (state, monitors, since when, mutes, group) and `failure_group` (with an investigation prompt). The skill in `skills/stackvitals-ci/` tells Claude Code or Codex to check history before "fixing" a failing test; `skills/` has one for every module (flow, delivery, deps, community, portal, contribute), each naming only tools the server has (a test checks). Every answer carries `as_of` (when its numbers are from) and `sources` (where they came from). StackVitals is the evidence an agent reads, not a replacement for one: on a single failure inside GitHub's log retention, an agent reading the log does as well on its own; the edge is kept history and comparisons with similar repos, which an agent can't rebuild in one chat ([bench/accuracy/agents](../bench/accuracy/agents/)).

**What counts as flaky:** a job that failed and then passed with no code change. Either a re-run of the same run passed, or another push or PR run of the identical code, on the same branch or tag, passed. Each flaky item links to the runs that prove it.

**What is ignored:**

- outages, where most jobs fail together;
- "gatekeeper" jobs that only fail because another job failed or was cancelled;
- scheduled and triggered runs;
- GitHub-managed workflows such as Dependabot.

**States:**

| State | Meaning |
|---|---|
| flaky | 2 or more flakes in 30 days |
| one flake seen | 1 flake in 30 days |
| fixed | at least 14 quiet days and 10 or more clean runs after being flaky |
| keeps failing | the last 3 runs on the default branch failed |

**Security:**

- GitHub is read with the built-in `GITHUB_TOKEN` only; the optional Jira and Linear keys live in your repo's secrets, are sent only to your own Jira Cloud site or Linear, and are only used to read unless you turn on write-back ([docs/connectors.md](connectors.md)). Everything a run sends anywhere: [docs/privacy.md](privacy.md). The template asks for `contents: write` (the `stackvitals-data` branch), `pull-requests: write` (the PR comment, review requests and size labels), `issues: write` (the weekly digest, commands and flaky-test issues), and read access to `actions`, `checks`, `statuses` and `deployments` ([docs/install.md](install.md)). Opt-in features need one more: `actions: write` to re-run known flakes, `issues: write` for flaky-test and alert issues.
- Job names can come from fork PRs, so they are escaped everywhere they are shown.
- Nothing goes to a StackVitals server (there is none); what can leave the repo, like alerts you set up and the optional keys above, is listed in [privacy.md](privacy.md).

## Insights: what to fix first

When Team Flow runs, each job also writes `docs/insights.html` and `docs/insights.json`, and the job summary starts with the top three. Each finding is one sentence with its number, how many pull requests it rests on, links to the evidence and what to do, and they are ranked by the hours of waiting (or outage) at stake:

- a CI job or test that failed and then passed on the same code, by the hours it kept pull requests red (the runs linked);
  when its flaking clearly began on a day, the finding names the pull requests merged just before ("right after #N
  merged: look there first") and links them, a place to look and never a blamed change;
- review requests not started after 3 days, and older ones (over 30 days) to review or close;
- how long merged pull requests sat with failing checks, and dependency updates that did;
- an incident (a revert, a hotfix or an `incident` issue) and the deployment before it;
- outside contributors waiting much longer than insiders for a first review.

The page ends with an estimated opportunity: the hours at stake across the findings, each hour counted once (a flaky job's hours sit inside the red-CI hours, so they are shown as part of them, not added). It is an estimate of what fixing them could save, not a measured saving.

Each finding keeps how big it was when first seen and the days it ranked first (findings someone acknowledged or snoozed never count as the top one). Under the list, a track record says how many findings ranked first in the last 90 days, how many later shrank to half their hours or less, and how many cleared (not seen for a week): whether the top finding gets acted on, read over months. The page is built from the public numbers only, so it never names a reviewer. For any public repo from your machine: `stackvitals insights owner/repo` (MCP: `insights`).

**Does ranking flaky jobs by PR-hours beat counting failures? Not shown, so not claimed.** We ranked jobs from 60 days of history and measured how much of the next 30 days' flaky waiting each ranking's top three covered, against rankings by failure count, pass-on-retry count and PRs affected, on pip, pytest, guidellm, aiohttp, dask/distributed and astronomer-cosmos. Waits that only a re-run cleared were rare on pull requests (0 to 22 a month per repo) and moved between matrix jobs from month to month, so no ranking predicted the next month well and none beat the others. One difference held: the count-based rankings put label and PR-template gates in their top three (2 of 18 picks), ours never did, because checks that read a pull request's own labels or title don't count as flaky CI here; the test also found a label gate read through a script that the filter had missed (fixed).

**Alerts.** Thresholds on the last 28 days, set under `[alerts]` in `.github/stackvitals.toml`; the defaults are LinearB's 2026 "good" band (P75 pickup 4 h, review 14 h, cycle time to merge 72 h) and a 15% change failure rate, and `0` turns one off. A heads-up comes at 80% of a threshold and a miss once the number's likely range (95%) is past it; a number past the threshold whose range still reaches under it is a heads-up that says so. Each is sent once (and once more when it recovers); with a new threshold the job summary says how many times it would have fired over the last 90 days. They go to the `webhook` input (Slack, Discord, Microsoft Teams Workflows, or any URL as JSON) and, with `channels = ["webhook", "issue"]`, to one "StackVitals: delivery alerts" issue kept up to date.

**Fixing, only when you turn it on:** re-run flaky jobs (`rerun-flaky`), quarantine (`quarantine`), one issue per flaky test (`issues`), name owners (`mention-owners`), and a `stackvitals: waiting for review` label on pull requests whose asked-for review has not started after 3 days, taken off once one has (`label-stuck`). With `verdict_check = true` under `[automation]` (and `checks: write`), every pull request gets a "StackVitals verdict" check that passes when its newest code is green (known flakes are re-run, with `rerun-flaky` automatically, never let through); it stays in progress while other workflows on that commit still run, and a cancelled or timed-out run never passes. Require it in your branch rules instead of a flaky job; merge-queue commits get it too (list every CI workflow under `workflow_run` so each finished run updates it).

**How the verdict decides, exactly:**
- Every workflow on the pull request's newest commit has finished and passed: **pass**. That includes a job that failed
  and then passed when re-run on the same commit, the way GitHub's own required checks treat a re-run.
- Anything failed, was cancelled or timed out on the newest commit: **fail**, whatever the comment called it. A known
  flake is never let through; it is re-run (by hand, or with `rerun-flaky`), and the check passes only if the re-run does.
- Other workflows on that commit still running: **in progress**.
- With patch coverage under `[ci.coverage] min_patch`: **fail**.
- **Strict mode** (`verdict_strict = true` under `[automation]`): when the comment called a failure on this commit
  likely from the change (or flaky only before, in another step) and a re-run of the same commit then passed, the check
  stays **failed** until someone with triage access comments `/stackvitals accept rerun` on the pull request. A green
  re-run doesn't prove the change clean: on public CI history, between 3 of 45 and 15 of 52 known-flaky calls that a
  re-run turned green were the change's own failure, depending on the labeller
  ([bench/accuracy/replay](../bench/accuracy/replay/README.md)).
- On a private repo, set the repository variable `STACKVITALS_EVERY_CI_RUN` to `true` so passing CI runs start a job and
  the check can pass at once ([scaling.md](scaling.md#actions-minutes-private-repos)).

**Alerts within seconds:** the Action runs on a schedule, so for in-the-moment messages (checks failed on a pull request, a review requested, a pull request approved) deploy the small Cloudflare Worker in [`worker/`](../worker/README.md) to your own free account; it checks GitHub's signature on every request.

## Decide on GitHub, hear back every week

**Commands.** Anyone with triage or write access can type a command in a comment on any issue or pull request. StackVitals answers on the issue and logs who decided what, when and why in the `stackvitals-data` branch (`decisions/log.ndjson`); every page shows it.

| Command | What it does |
|---|---|
| `/stackvitals quarantine` (on a flaky-test issue, or with `test:<id>`) | puts the test on the quarantine list for 30 days |
| `/stackvitals unquarantine test:<id>` | keeps a flaky test off the list, so it still blocks |
| `/stackvitals mute job:"ci.yml / lint" for 7d` | still measured, but no alert and no new issue |
| `/stackvitals acknowledge` | the team lives with it: no alert and no issue until someone reopens it |
| `/stackvitals snooze finding:review_wait for 14d` | takes a finding off "what to fix first" until then |
| `/stackvitals exclude` (on a pull request, or `#123`) | leaves it out of every number; the `stackvitals: exclude` label does the same |
| `/stackvitals confirm test:<id>` or `dispute ... because <why>` | says StackVitals' verdict on it was right or wrong; it changes nothing else, and CI health shows how often your team confirmed each kind of verdict, with a range |
| `/stackvitals accept rerun` (on a pull request) | in the verdict's strict mode, lets a green re-run pass after a failure that looked like the change's own |

Add `for 14d`, `for 2 weeks` or `until 2026-12-31`, and `because <reason>`, to any command; temporary decisions end on their own and the digest lists those ending within a week. Closing a flaky-test issue as *not planned* counts as acknowledged, and the issue stays closed; reopening it undoes that. An issue closed as done stays closed unless the test flakes again after the close. A command whose run GitHub cancelled while it waited (a burst of commands) is picked up by the next run.

**Requests from the app.** The app's buttons open a prefilled issue with a `stackvitals` block. The workflow checks that you have the access, applies it, changes `.github/stackvitals.toml` when asked (or opens a pull request when the branch is protected), answers and closes the issue. Issues from people without access start no run. With "Apply now with my token" the app starts the workflow itself instead (a fine-grained token with Actions read and write on that one repo, kept in the page's memory). AI agents get the same link without changing anything: `stackvitals propose owner/repo --set alerts.pickup_p75_hours=6 --decide "/stackvitals mute test:<id> for 7d because <reason>"` (MCP: `propose_change`) prints it for a person to submit.

**Weekly digest.** Every Monday after 06:00 UTC, one comment on the pinned "StackVitals weekly digest" issue (subscribe to it for e-mail) and, with `channels = ["issue", "webhook"]`, your webhook: what changed this week in CI and delivery, what to fix first, newcomers waiting, and decisions ending soon. Nobody is mentioned. Each number's latest week is checked against the four before it and judged against how much that repo's weeks usually swing; only changes that survive a false-alarm control (Benjamini-Hochberg at 10%) are reported. On 26 public repos with shuffled weeks, 8% of digests flagged anything, against 95% for a digest that reports every difference; a steady week says how big a change it could have shown. The checks, the replay and its results: [bench/accuracy/uncertainty](../bench/accuracy/uncertainty/). Set the day, hour and channels under `[digest]`.

## Insights: red CI on pull requests

When CI Health and Team Flow both run, each job also writes the red-CI part of `docs/insights.json` and a section of the job summary: how many of the people's pull requests merged in the last 90 days sat ready for review with a failing check on their newest commit, for how long in all and per PR (with ranges), which waits ended only with a re-run that passed on the same code (flaky checks) and the jobs behind them, the longest waits with a link to the run that started each one, and open PRs that are red right now. The clock starts at the first failing job, as GitHub's own PR view turns red, and stops at a new commit, a passing re-run or the merge. Time as a draft, checks that read the PR's own title or labels, and `pull_request_target` runs (they run the base branch's workflow) never count. For any public repo from your machine: `stackvitals insights owner/repo` (MCP: `insights`).

Checked on 37 pull requests of pip, pytest and guidellm against GitHub's Checks API, a different source from the runs it reads: 36 matched exactly; the last differed only because GitHub no longer lists a commit that was force-pushed away. Across those repos 14-18% of merged PRs went red, from 8 hours in all on pip (most of it flaky re-runs) to 222 hours on guidellm.

## Delivery: cycle time and DORA

When Team Flow runs, each scheduled job also writes `docs/delivery.html` and `docs/delivery.json`. For any public repo from your machine: `stackvitals delivery owner/repo` (`--json` for the numbers). MCP: `delivery_health`, `cycle_time`, `stuck_prs`, `reviewer_load`.

**Check what counts before trusting it:** `stackvitals delivery owner/repo --deploys` (and the "What counts as a deployment" box on the app's Delivery page) shows which source counts as deployments and why the others were passed over, each workflow counted or skipped with the reason, and each environment counted as production or shown as staging or publishing. These numbers describe a team's system, never a person: [docs/dora-guide.md](dora-guide.md) says what each one can't tell and how each gets gamed.

- **Cycle time in LinearB's four phases** (as its [metrics glossary](https://linearb.helpdocs.io/article/1s38stsugw-glossary-metrics) defines them): coding (first commit to opened), pickup (ready for review to the first comment or review by someone else), review (that to merge) and deploy, with review also split into LinearB's time to approve and time to merge, with P50, P75, a range for the median and the number of PRs. Drafts count from when they were marked ready; bots and coding agents are left out; PRs over 60 days, and above the 98th percentile once there are 30+, are left out as LinearB does. Under 10 PRs a phase says "not enough data".
- **DORA's five metrics.** The first four (deployment frequency, change lead time, change fail rate, failed deployment recovery time) use DevLake's definitions and table shapes, counted as its DORA dashboard counts them (an incident blames the last production deployment before it). Beside the change fail rate the page also shows the rate with each revert blamed on the deployment that shipped what it undid, because on 89 checked reverts the last deployment didn't contain the reverted change 71 times: deployment days per week and month (weeks with none count as zero), median lead time of the PRs each deployment shipped, the share of deployments followed by an incident, and the time from a failed deployment to the fix. Tiers come from DevLake's 2023 table, or 2021 if you choose it. Each key shows its likely range (95%: Wilson for rates, order statistics for medians), and when that range crosses a tier line, the page says which tiers it could be. DORA's fifth metric, **deployment rework rate** (an instability metric DORA added in 2024), is the share of deployments that shipped a revert, a hotfix or a pull request whose title names an incident issue; it has no tier until DORA publishes one, so the page shows the number and how many deployments it covers.
- **What DORA's numbers can't tell:**
  - They describe a team's delivery system, never a person, and StackVitals never ranks people by them.
  - Used as targets, they get gamed: tiny deploys that ship nothing, incidents filed late or not at all, hotfixes
    logged as features.
  - A tier depends on what counts as a deployment: on 4,618 public repos it changed between "every merge" and "every
    release" for 62% ([bench/accuracy/dora](../bench/accuracy/dora/)). So every tier shows its definition and source,
    and its range when that crosses a tier line.
- **Deployments, with no setup, and how sure it is:** GitHub deployments to a production environment (sure), else a deploy workflow that runs on a good share of the default branch's commits (a guess), else published versions (alpha, beta and rc tags left out; several packages released from one commit count once), else release workflows run on a version tag. Workflows that only prepare, preview, check, sign, notify or open release PRs are skipped: on 51 workflows of 15 repos it was not tuned on, 85% of the ones it kept really ship (47% when matching the name alone). No setting-free rule is right everywhere: on 8 public repos it picked the right source for 5; the others deploy from another repo or a hosting service. So the page names the source, says when it is a guess, lists what it counted, and one line in the settings fixes it.
- **Merge queue health, which GitHub doesn't report:** how long pull requests wait from entering the merge queue to merging (median and 9 in 10), why they were taken out (merge conflicts, failed checks), and which removals followed a merge-group run that failed only on jobs CI Health knows to be flaky.
- **Where the work went:** each merged pull request by people or coding agents in the last 6 months, sorted into feature, fix, maintenance, security or docs work, month by month, with how each was decided: your own label rules first (`[investment.labels]`, like `maintenance = ["area: platform"]`), then a security label, the linked Jira or Linear issue's type, common labels, its changelog fragment (`news/123.bugfix.rst`, `changelog/`, `CHANGES/`), the title's prefix (`fix:`, `docs:`), the files it changed (only docs, tests or CI), and the title's first verb. Release PRs count as maintenance, and update bots' PRs are counted apart. On pip, pytest and aiohttp 3 to 7% stayed unsorted; repos whose titles name a component instead of a kind of work keep more unsorted until a label rule is set.
- **Jira Cloud and Linear, with one optional key each:** issue lead and cycle time by type, sprints and cycles (scope, done, carried over, added after start), tracker incidents in DORA, and pull requests linked to issues by key. The key stays in your repo's secrets and is only used to read; setup and details in [docs/connectors.md](connectors.md), and the app's Integrations section shows each one's status.
- **PagerDuty or incident.io, with one optional key:** their incidents then count in DORA's change failure rate and time to restore instead of labels, reverts and hotfixes, and every page names the source ([docs/connectors.md](connectors.md)).
- **GitHub Copilot usage, kept day by day:** with an org App that can read the Copilot usage reports, the org's active users, suggestions accepted and pull requests by Copilot are copied into the data branch each day, so the history outlasts GitHub's own, and shown beside what happened after AI-assisted pull requests merged.
- **Incidents without a paid tracker:** issues labelled `incident` (or `outage`, `sev1`, `p0`...), merged revert PRs and merged `hotfix` PRs, each tied to the last deployment before it.
- **Release and GitFlow branches:** a pull request merged into `develop` counts once a deployment's commits hold its
  merge commit (develop merged into main later), with no setting. `production_branches` (globs, like `release/*` or
  `production`) also counts deploy workflow runs on those branches and pull requests merged into them.
- **Any dates:** pick any range in the last year and the four DORA numbers are counted for it in the page, from
  compact rows of each deployment (finished, followed by an incident, recovery) and each shipped pull request (lead
  time), with DevLake's rules: deployment days in the median week (weeks with none count), the median lead time, the
  share of deployments followed by an incident and the median recovery.
- **Week by week:** lead time, change fail rate, recovery and deployments for each of the last 13 weeks, each week
  counted with the same DevLake rules as the window, in the chart picker at the top of the page.
- **Deployments:** the window's last 30 deployments, each with the pull requests it shipped, how many people wrote
  them, their median lead time and the incidents blamed on it, linked to the commit on GitHub.
- **Deploy attempts:** every deploy in the window, failed and cancelled ones too: how many succeeded and how long a
  successful one took at the median (Deployments API: from creation to success; deploy workflows: run start to end).
  DORA still counts successful deployments only, as DevLake does; this line shows what didn't make it.
- **Your own incident rules** (`[delivery]` in `.github/stackvitals.toml`): `fix_patterns` marks fix PRs by their
  title or branch, with one group naming the PR they fix (`"^fix.*#([0-9]+)"`, `"^hotfix/([0-9]+)-"`), and the
  incident blames the deployment that shipped that PR; `incident_sources` picks exactly which sources count (`issues`,
  `reverts`, `hotfixes`, `fixes`, `pager`, `tracker`, `recorded`), so a team with a pager can still count its reverts;
  `ignore_reverts_of` leaves out reverts of PRs that touched only some paths (`docs/**`) or came from some authors
  (`dependabot[bot]`). Teams that ship every merge can set `source = "merges"`; it is never picked on its own, since
  on our checked repos every merge matched real deployments 8% of the time.
- **Stuck PRs** by LinearB's published cut-offs (review asked 3+ days ago and not started, open 30+ days, 10+ comments), plus failing checks nobody acted on for a day; PR size bands, merged without review, reviews under 20 minutes, review depth and merge frequency.
- **By team:** cycle time per team in your settings and per owning team in CODEOWNERS (single people are never listed). Teams in your settings also get all four DORA metrics, from the deployments that shipped their members' pull requests (DevLake's DORA by team).
- **Code that lasted (AI-assisted work tab):** of the lines a squash-merged pull request added, the share git blame
  still gives to it in the default branch 30 and 90 days after it merged, for people's and agents' pull requests.
  Each pull request is measured once at each age (about 12 a run, through GitHub's API), pull requests merged with a
  merge commit are left out (their lines belong to other commits), and so are ones touching more than 8 files.
- **Releases:** for each of the last six releases (pre-releases left out), the pull requests merged since the release
  before it, the share that were fixes, which of them a later revert undid, and the incidents in the two weeks after it
  went out ("so far" until two weeks have passed). DevLake's release quality dashboard counts the first two; the rest
  is what happened to the release afterwards.
- **Bugs:** the bug backlog week by week, as DevLake's weekly bug retro shows it: bugs opened and closed each week, how
  many were still open at the end of it, and the oldest open ones. Bugs are GitHub issues with a bug label (`bug`,
  `type: bug`, `kind/bug` and the like), plus Jira and Linear bugs when connected; cancelled ones don't count.
- **Change risk:** which open pull requests look risky by this repo's own history. A merged pull request counts as
  having caused trouble when a revert undid it, it shipped in a small deployment that failed, or a fix (by its title or
  a label) changed the same files within 14 days (the lightweight form of SZZ; files most pull requests touch, like a
  lockfile or the changelog, link nothing). Each open pull request gets a chance of needing a fix, from its folders'
  record, its size, whether its author has changed those folders before, whether tests changed and whether a coding
  agent wrote it, with the reasons. The score is learnt on the older 70% of merged pull requests and checked on the
  newest 30% first, and shown only when it ranks trouble there clearly better than chance (AUC 0.65 or more);
  otherwise the tab says so. On 13 public repos it reached AUC 0.72 to 0.80 on six (pytest, pip, aiohttp,
  astronomer-cosmos, guidellm, vercel-labs/run), 0.65 on nodejs.org and about chance on three, which is why each
  repo is checked on its own.
- **Working calendar:** with `[calendar] weekends = ["saturday", "sunday"]` and `holidays = ["2026-12-25", ...]`, those
  days (whole UTC days) are left out of every review phase and cycle time, so a pull request opened on Friday evening
  isn't charged the weekend. DORA's numbers stay in calendar time so they still match DevLake and the DORA report, and
  a working-time lead time is shown beside them.
- **By service (monorepos):** name the services inside the repo under `[services.<name>]` with `paths` (CODEOWNERS-style
  patterns) and, optionally, `deploy` (a pattern matched against each deployment's environment or workflow name). Each
  service gets its review phases, and with `deploy` its deployments, lead time and change failure rate, counted the
  same way as the repo's. A pull request touching two services counts in both; the repo's own numbers don't change.
- **Compared with similar public repos:** your P75 pickup, review and opened-to-merged, measured the same way as for thousands of public repos of the same language and size in the daily crawl, with the typical repo's value, a 95% range for it, your place, and the share of those repos inside LinearB's good band. The page says who is in the comparison and what it can't see (private teams; pickup counted from opening, since the crawl doesn't keep draft history).
- **AI-assisted work, compared like with like, totals only:** coding agents' PRs (an agent's account, or a branch an agent opened such as `codex/`) and people's AI-marked PRs (an AI co-author trailer or a coding tool's label such as `claude-code-assisted`) are kept apart. A person's AI-marked PRs are compared with the same person's other PRs of a similar size; agents' PRs with people's PRs of the same month and size; each on reverts, CI failures, failed deployments, merges and merges by someone other than the author, with a 95% range, the share of PRs that found a match, and the gap it could have detected when it finds none. Small repos read "too few to compare", with the same like-for-like gap across similar public repos beside it. On 1.46 million crawled PRs, agents' PRs trail people's by 9 points in merges by someone else, and the gap is gone within the same repo, month and size (+0.5, -0.0 to +1.1); by agent, Copilot's and Cursor's agent PRs are merged at all about 14 points less often like with like (agents' PRs and people's AI-marked PRs are separate groups and never pooled) ([bench/accuracy/ai](../bench/accuracy/ai/)). An association, never a cause (matching removes repo, month, size and author differences, not the choice of what work goes to an agent), and never a person.

**Working agreements:** a team's own rules under `[agreements]` (first review within N hours, merged within N days, PRs under N lines, PRs link an issue, reviewed before merge), all off until set. The Delivery page lists the pull requests of the last 14 days that broke one (open ones already past a time limit too), the digest counts them, and the app previews how often a rule would have been broken week by week.

**Settings** in `.github/stackvitals.toml` (all optional; the full list is in [docs/settings.md](settings.md)):

```toml
[delivery]
deploy_workflow = "(?i)(deploy|release|publish|push-image)"  # which workflow names ship
production = ["production", "prod", "live"]                    # deployment environments that count
incident_labels = ["incident", "outage"]
hotfix_labels = ["hotfix"]
source = "auto"          # or deployments, workflows, releases
dora_report = "2023"     # or 2021

[services.api]                      # a monorepo's services (optional)
paths = ["services/api/", "libs/shared/**"]
deploy = "api-prod"                 # its deployments' environment or workflow name

[identity]
bots = ["release-captain"]          # accounts to treat as bots
people = ["build-bot-jane"]         # accounts to treat as people

[identity.aliases]                  # an old login, or one person's id in another tool, names the GitHub login
"old-login" = "new-login"
"jira:5b10a2844c20165700ede21g" = "amy"   # a Jira account id (Profile, or the assignee in an issue's JSON)
"linear:2f6b1c3e-..." = "amy"             # a Linear user id
"slack:U0123ABC" = "bob"                  # a Slack member id (Profile, More, Copy member ID)
"discord:81384788765712384" = "bob"       # a Discord user id (Developer Mode, Copy User ID)
"bob@acme.com" = "bob"                    # an email Jira or Linear shows for the assignee

[identity.teams]
web = ["amy", "bob"]

[alerts]
pickup_p75_hours = 4     # P75 over the last 28 days; 0 turns an alert off
review_p75_hours = 14
cycle_p75_hours = 72
change_failure_rate = 0.15
channels = ["webhook", "issue"]
```

**One project across several repos:** `stackvitals project web org/frontend org/api org/worker` pools the repos'
DevLake tables into one DevLake project and runs DevLake's own DORA SQL on it: deployment days across all of them,
the median lead time of every pull request any of them shipped, and the share of all their deployments followed by an
incident, next to each repo's own (`--json` for the numbers; needs `pip install 'stackvitals[sql]'`). That is what a
DevLake project of those repos shows, with no DevLake, MySQL or Grafana running.

**Open in DevLake's shape:** `stackvitals export owner/repo --format devlake` writes DevLake's domain tables (`pull_requests`, `project_pr_metrics`, `cicd_deployment_commits`, `cicd_pipelines`, `cicd_tasks`, `cicd_pipeline_commits`, `incidents`, `issues` and the project links; every run also writes them to the data branch's `summary/` as `devlake_<table>.jsonl`, with the last 90 days of CI runs) as JSON lines, plus `dora.sql`: DevLake's own DORA dashboard SQL ported to DuckDB. Run `duckdb < dora.sql` in that folder (or install `stackvitals[sql]` and the command prints it) to see DevLake's DORA panels and its PR cycle time panel computed on your data, with no DevLake, MySQL or Grafana running. Our tests run that SQL on 42 generated repos and require the same answers as our page.

## Team Flow

**Try it on any public repo:**

```
stackvitals flow report owner/repo
```

It answers "what is blocking this repo's pull requests, and who has to act next?":

- **Who acts next, per open PR:** the reviewers asked, the author (changes requested or failing checks), or the maintainers (approved but not merged, or nobody asked to review), with the event that put it there and since when.
- **Overdue** means waiting longer than usual for this repo (its own 75th percentile for that step, judged separately for insiders and outside contributors) and over a day. PRs waiting over 30 days are counted as stale backlog. Drafts and PRs stacked on another open PR are never blamed on reviewers.
- **Review stages,** with GitHub's own boundaries: ready for review to first review, first to final review, final review to merge. Bots, the author and Copilot are left out.
- **Insiders and outside contributors** side by side: merge rate and how long the first review takes.
- **PR rules as code:** `[[rules]]` in `.github/stackvitals.toml`, each with a `name`, a `when` and a `then`:

  ```toml
  [[rules]]
  name = "Agent changes to payments"
  when = { author = "agent", paths = ["payments/"] }      # author: agent, person or bot
  then = { label = "needs-second-review", reviewers = ["amy", "@acme/payments"], comment = "An agent changed payments code." }

  [[rules]]
  name = "Big risky change"
  when = { lines_over = 400, risk = "high" }              # risk: this repo's change risk (where its backtest works)
  then = { label = "risky" }
  dry_run = true                                         # only reports what it matches
  ```

  `when` can also ask for `labels` (any of) and `first_time = true` (an author with no merged pull request yet). Each
  action happens once per pull request: a label someone removes stays removed, a comment is never repeated. The Pull
  Requests page lists each rule with the open pull requests it matches and what it matched among the last 200 merged
  ones, so a new rule can be checked (with `dry_run`) before it acts. It runs on the workflow's own token (needs
  `pull-requests: write`), with no app to install.
- **Suggested reviewers** for PRs nobody was asked to review: maintainers who wrote and reviewed merged PRs in the same folders, who reviewed this author's earlier PRs, plus CODEOWNERS, eased off by how many reviews each already has open. Only people who can review there are suggested. On 1,186 PRs in 26 public repos a real reviewer was in the top 3 82% of the time, against 79% for the three busiest reviewers ([bench/accuracy/team](../bench/accuracy/team/README.md)).
- **Team automation, off until you turn it on** (each part under `[automation]` in `.github/stackvitals.toml`, or from the app's Settings page): the top suggested reviewer is requested once on ready PRs nobody was asked to review (`review_requests`), every open PR gets a `size/XS` to `size/XL` label (`size_labels`), and docs-only PRs get "low risk: docs only" (`docs_label`; never an approval). The job summary says what it did. With working agreements set and a webhook, each open PR breaking one is announced once in chat. The weekly digest issue asks three pulse questions (flow, friction, satisfaction) answered by reaction, and the next digest shows the counts beside the numbers, never who answered (`[digest] pulse`). Each week's counts are kept for a year (`docs/pulse.json`), and the Pull Requests page shows the trend with each question beside the number it explains (flow with pickup time, friction with first-try green, satisfaction with deployments); a week with fewer than 5 answers to a question shows no share.
- **Knowledge map:** folders known mostly by one person, main authors who have gone quiet, and the busiest folders (lock files left out).
- **Delivery:** releases per week, how long a merge waits for a release, and how many releases were followed by a revert or hotfix within 7 days (a proxy for change failure, labelled as such).

**In the Action,** add `flow` to `modules:` (the template from `stackvitals ci init` has `ci,flow,deps,community`). It runs on the schedule (every 3 hours) and manual runs, keeps PR history in the `stackvitals-data` branch and writes `docs/flow.html`. One GitHub request reads about 25 pull requests with their review history, so a year of history loads in one run.

**People:** the public page shows who a PR is waiting on and open requests per reviewer, never speed rankings. Each reviewer's own answer time appears only in the local `flow report` view.

- **Pre-flight:** what merged PRs touching the same folders usually include (tests, a changelog entry, docs) and how big they are, plus what maintainers most often ask for in review there. `stackvitals flow preflight owner/repo --paths src/db/pool.py --lines 120` lists what a planned change is missing. Review comments are sorted into plain categories as they are read; their text is never stored.
- **Pre-flight note on PRs (off by default):** with `preflight-comments: true`, a new PR from an outside contributor that misses a local habit gets one short note. Never twice, never on PRs that were already open.

- **Compared with similar repos:** time to the first maintainer review, opened to merged, how many outside PRs get merged and typical PR size, next to public repos of the same language and size from a daily crawl of active repos (groups of 50+ repos, with the number of repos shown).
- **Triage of outside PRs (private, for maintainers):** `stackvitals flow triage owner/repo` gives each open outside PR's chance of being merged within 30 days and the main reasons (the author's past PRs here: none, some but none merged, or merged ones; size; a linked issue; how this repo usually treats outside PRs). The model is trained on real outcomes of outside PRs across public repos and checked on repos it never saw; the file says how well. It is computed on demand with your own token and is never stored, shown on a page or posted on a PR. It scores the PR's chances, not the person.

**For AI agents:** `pr_queue`, `flow_health`, `who_should_review`, `preflight` and `triage_pr` in `stackvitals serve`.

## Dependency Steward

**Known vulnerabilities in every lockfile, every ecosystem:** after CI runs and on the schedule, the Action reads the
default branch's lockfiles through the API (npm, yarn, pnpm and bun; pip requirements, Poetry, uv, Pipenv and PDM; Go;
Cargo; Bundler; Composer; NuGet and .NET project files; Gradle and Maven; SPDX and CycloneDX SBOMs; and more) and scans them with Google's OSV-Scanner, pinned to a
version and checked against its published SHA-256 (no Docker, no checkout of your code). Each finding shows the advisory,
its severity, the version that fixes it, the lockfile and the day it was first seen; fixed ones move to "fixed lately". An advisory the repo ignores in `osv-scanner.toml` at its root (`[[IgnoredVulns]]` with an `id`, an `ignoreUntil` date and a `reason`, the file OSV-Scanner itself reads) stays listed, marked ignored with its reason, and isn't named as new; once the date passes it counts again. Each fix comes with a plan, as OSV-Scanner's guided remediation gives one: the smallest version that fixes it, whether that is a patch, minor or major jump (a major one may break things; 0.x minors count as major), and the command that makes it in that ecosystem (npm install, pip or uv, go get, cargo update --precise, composer require, dotnet add package...). A package only development uses is marked "dev only" where the lockfile says so (npm's and pnpm's `dev: true`, Pipfile.lock's develop section), so it can wait behind what ships; other lockfiles don't record it, so nothing is guessed. The GitHub Actions your workflows use are checked too, since no lockfile lists them: each action used by tag (`tj-actions/changed-files@v45`) is matched against OSV's GitHub Actions advisories (their version ranges are read and compared here, as OSV's API doesn't match versions for actions; a major-only tag like `v4` counts only when no 4.x release is fixed); actions pinned to a full commit can't be matched to a version. The open findings are also written as `docs/vulns.sarif` for GitHub's Security tab: the Dependencies page in the app makes `.github/workflows/stackvitals-code-scanning.yml`, which uploads it (and `docs/security.sarif`) with `github/codeql-action/upload-sarif@v4` after each StackVitals run, and adds it in one click (GitHub's editor, or a pull request with a token; it needs `security-events: write`).
Lockfiles are rescanned when they change and every 6 hours for new advisories. On 100 crawled repos in ten languages it
read 24,003 packages; the deep evidence below covered a third of them ([bench/accuracy/deps](../bench/accuracy/deps/README.md)).
With `[deps] outside_lookups = false` it downloads OSV's databases instead, so no package name leaves the runner.

**Malware between scans:** on each scheduled or post-CI run, GitHub's newest malware advisories are matched against
every package the last scan read, so a compromised release listed there is flagged without waiting for the next full
rescan or for OSV. A match stays open while the package is still in a lockfile. The day each bad version was found in the
repo is kept. How much earlier this is than OSV hasn't been measured.

**On pull requests:** the check lists the known vulnerabilities a pull request adds or removes in any ecosystem
("lodash 4.17.15: GHSA-35jh-r3h4-6jhm, high, fixed in 4.17.21"), and, for npm and PyPI packages it adds or upgrades,
signs that can come before any advisory (checked on known attacks in [bench/accuracy/deps](../bench/accuracy/deps/README.md#release-signs-on-known-attacks-incidentspy)): a new install script, new dependencies, or build provenance the previous version had
and this one lacks make it "look first"; a release under 48 hours old is noted. With `[deps] guarddog = true`, DataDog's
GuardDog also reads each new version's code (Linux runners; experimental).

**Does your code import it:** for Python, JavaScript/TypeScript and Rust, run `stackvitals deps imports --out imports.json` in a step after checkout and pass `imports-json: imports.json`: each known vulnerability then says whether your own code imports the package (tests and vendored code left out). An import is a hint for which advisories to read first, not proof the vulnerable code runs, and a package with no direct import may still run through another package. Go gets call paths from govulncheck (`govulncheck-json`), shown on each Go advisory in the vulnerability list ("your code calls it", imported, or only required, with the call path on hover); for Rust the check reads `use` lines and paths like `tokio::spawn`, since its call analysis needs a full build.

**Runtimes:** the Node.js, Python, PHP, Ruby and Go versions the repo runs on (version files, Dockerfiles, workflow setup
steps) are checked against their support dates: a line out of support gets no security fixes, and a pinned patch older
than the newest misses the fixes since. Runtime flaws (a flaw in the runtime itself, like a PHP security release) are not package advisories, so lockfile
scans never see them. Container base images count too, with no Docker: the operating system under each Dockerfile image (debian:bookworm, ubuntu:22.04, alpine:3.18, or the codename at the end of a language image like python:3.11-slim-bullseye) is checked the same way, since an end-of-life base gets no security fixes for its packages.

**Update hygiene, from the pull requests already kept:** open Dependabot and Renovate updates by age, security updates waiting more than 48 hours, how fast updates merge, and a warning when the bot has opened nothing for 30 days (Dependabot pauses itself after 90 days without interaction), in `docs/deps.json` and the digest. `/stackvitals accept package:<name> until 2026-12-31 because <reason>` takes a security update off the overdue list until then.

**This repo's own security, once a week:** OpenSSF Scorecard's checks, run by your workflow on the repo itself, so
they work on private repos too. Each probe uses Scorecard's name where the two overlap, says why it matters and what to
do, and points at the file and job:

- workflows: a `pull_request_target` or `workflow_run` workflow checking out the pull request's code (one behind a
  label, actor or author-association guard is shown as guarded, not as a hole), outsider text pasted into a `run:`
  script, no read-only `permissions:` at the top, actions used by tag instead of a full commit, and `curl | sh`;
- branch protection in Scorecard's five tiers, read from rulesets, classic protection, and without an admin token from
  the branch's public summary (classic protection on, which blocks force pushes and deletion, and the checks it
  requires); what still can't be read is "can't read", never a pass, and protection that got weaker since last week is
  called out;
- SECURITY.md (in the repo or the owner's `.github` repo) and whether private vulnerability reporting is on; signed or
  attested assets on the last five releases; an SBOM; a publishing workflow; code scanning (CodeQL, Semgrep,
  SonarCloud); committed binaries (by Scorecard's list of extensions, and executable files with no extension read for an ELF, Mach-O or Windows header, as Scorecard does); fuzzing (OSS-Fuzz, ClusterFuzzLite, fuzz folders); the OpenSSF Best Practices badge
  (looked up for public repos only).

One 0-10 score weighs the probes by risk (critical 10, high 7.5, medium 5, low 2.5) among those that could be read, and
each week's score is kept. `docs/security.sarif` holds the workflow findings for GitHub's Security tab: the same
`stackvitals-code-scanning.yml` workflow from the Dependencies page uploads it with `github/codeql-action/upload-sarif@v4`
(it needs `security-events: write`). Side by side with Scorecard's published results on 16 repos drawn from the crawl, the two agreed on 137 of 139
checks both could read ([bench/accuracy/scorecard](../bench/accuracy/scorecard/README.md)); classic branch protection
needs an admin token, so it often says "can't read" where Scorecard counts it as met.

**Supply chain, once a week:** the repo's SBOM from GitHub's dependency graph (through the asynchronous report that
replaces the synchronous endpoint closing on 13 November 2026), each package's licence (from deps.dev when GitHub's SBOM
leaves it blank), a licence rule (`deny` under `[deps.licenses]`, like `["GPL-3.0*", "AGPL-*"]`; a package that offers an
allowed choice is fine), licence changes between quarterly snapshots, and the OpenSSF Scorecard of each project behind the
packages, with drops of a point or more and scores under 4. The actions your workflows use are listed too, with their own
repos' Scorecards (the licence rule skips them: they run in CI and don't ship).
The same rule runs on pull requests: each package version a PR brings in has its licence looked up on deps.dev, and a denied one is named in the check (an annotation, the job summary and the PR note when comments are on) before it merges.
`/stackvitals accept package:<name> for 30d because <reason>` accepts a denied licence. The workflow needs
`contents: read` (it has it) and the dependency graph turned on (Settings, Code security; public repos have it already).
MCP: `supply_chain`.

**Security depth:** each advisory's CVE is checked against CISA's known-exploited list and FIRST's EPSS (the chance of
exploitation in the next 30 days), daily and free: a package with an exploited or likely-exploited open advisory is
flagged, whatever its severity label (on the crawl, about half of the exploited or likely-exploited advisories are rated
below high). In a pull request, the version being installed is checked against each advisory's affected range ("2.30.0
is affected by GHSA-..., fixed in 2.31.0"), and a flagged package pulled in by another names the way it came ("via
express → body-parser → qs", from npm and uv lockfiles). Your own policy goes in `[deps.policy]`:
`max_severity` flags a changed package with an open advisory rated above it, `min_scorecard` lists the projects under
it; Scorecard stays one input and never decides a verdict ([bench/accuracy/deps](../bench/accuracy/deps/README.md)).

**Before a CVE exists:** a package a pull request adds whose name is one edit from a popular one ("exprses", "reqests")
and that almost nobody downloads (under 1,000 a week) is flagged as a likely look-alike; on OpenSSF's malicious-packages
list every sampled malicious look-alike had at most 75 downloads a week, and every legitimate neighbour (extend and
xtend) hundreds of thousands. **Is the vulnerable code even called?** For Go, add govulncheck to the workflow
(`go install golang.org/x/vuln/cmd/govulncheck@latest && govulncheck -format json ./... > govulncheck.json`) and pass
`govulncheck-json: govulncheck.json` to the Action: the supply page then says which advisories your code calls, with
the call path (on three public Go repos, about half the third-party advisories were never called).

Should you add, keep or upgrade a package? Evidence over time, for npm and PyPI: the 1,000 most-used packages of each (by repos depending on them, from ecosyste.ms) and every package that crawled repos upgrade.

```
stackvitals deps check requests
stackvitals deps scan package-lock.json      # also requirements*.txt, uv.lock, poetry.lock, Pipfile.lock
```

- **Upgrades in other repos:** how Dependabot and Renovate upgrades of the package went across public repos: merged, closed, failed CI next to the failure rate those same repos usually see, needed extra commits, reverted within 14 days. Rates are shown from 30 PRs in 10 repos; below that it says how much evidence there is.
- **Its maintainers over time:** whether outside PRs still get merged and how fast maintainers answer, quarter by quarter, next to repos of similar size.
- **Who publishes it:** a daily watch of npm publishers and maintainers and PyPI owners; a release published without the trusted CI publishing used before, or a new maintainer, is flagged with its date.
- **Advisories and malware:** OSV history with duplicate ids merged, open advisories, bursts of new ones, and any malware record ever, with the versions it names.
- **Its source repo:** proven by a signed build or publish, or claimed by the package and checked against that repo's own manifest.

The verdict is use, monitor or investigate, with the evidence lines behind it, or none when evidence is thin. It weighs what happened; it never calls a package safe.

**On pull requests:** with the `deps` module, a PR that changes a lockfile gets each added or changed package's verdict in the job summary, with an annotation for anything to investigate or monitor. Files are read through the API at the base and head commits; the PR's code is never checked out or run. A PR comment is opt-in (`deps-comments: true`) and only on PRs from the same repo.

**For AI agents:** `check_package` (ask before adding a dependency) and `scan_lockfile` in `stackvitals serve`.

## Community

**Try it on any public repo:**

```
stackvitals community report owner/repo
```

It answers "is our project growing, and where do contributors drop out?":

- **Newcomers waiting:** open PRs and issues that are someone's first contribution and that nobody has answered yet, oldest first. These are the replies that matter most.
- **The funnel, last 12 months:** first-time contributors, how many came back within 90 days, regulars (active in 3 of the last 4 quarters) and active maintainers.
- **First answers:** how often and how fast outside PRs and issues get a first answer from a maintainer: a review or reply, or a merge or close by someone other than the author. Maintainers are owners, members, collaborators and anyone who merges PRs; on issues, a reply from a regular responder counts too (someone who answered 10 or more other people's issues or first-reviewed 2 or more of their PRs in the last year, often a triager GitHub shows as a plain contributor). Bots and accounts opening 20 or more PRs or issues in a day are left out. Issues still waiting stay in the median (Kaplan-Meier), so a slow repo can't look fast by answering only the easy ones. Newcomers (a first contribution here) and regulars are measured apart, so you can see whether first-timers wait longer.
- **Who carries the work:** for the last 180 days of merged pull requests by people, how many people merged work, the most active person's share and the bus factor (CHAOSS: the fewest people behind half of it), next to the typical value for similar public repos from the crawl. No names, and no ranking.
- **Newcomers who came back, by first answer (public repos):** from our crawl, the share of first-time contributors who came back with new work (a day or more later, within 90 days), by how long their first PR waited for an answer. Across 259,586 newcomers in 48,745 public repos (October 2026): answered within two weeks, 19-24% came back; after more than two weeks, 13%; never answered, 8%. Merged first PRs brought 22% back, closed ones 15%, ones left open 9%: silence loses the most. This is a correlation, not a promise.
- **Score and badges:** the score (0-100) is, on average, the share of similar public repos (same language and size) this repo does better than, on three facts shown next to it: first-answer speed, newcomers answered within two weeks, newcomers who come back. A fact with too little data is left out, never counted as zero. Two shields.io badges are written to the data branch: `docs/community-badge.json` (the facts) and `docs/community-score.json` (the score).
- **In the project's own words (optional):** `capacity` and `norms` under `[community]` in `.github/stackvitals.toml` say who maintains the project and how much time they have, and how it works with people (like "two volunteers, evenings and weekends"). They're shown in the Community page's "What the project states" box and in the summary's "Who carries the work", so the numbers are read against what the project can give.
- **Stars:** GitHub's weekly star history (no names) and growth next to similar repos.
- **Traffic (optional):** GitHub deletes views, clones and referrers after 14 days, and the built-in token can't read them. To keep them, create your own GitHub App with the repository permission "Administration: read", install it on the repo, store its ID and private key as secrets, and pass a token from `actions/create-github-app-token` as `traffic-token:`. Without it, everything else runs.

**People:** the public page lists waiting PRs and issues by number, never people. Nobody is ranked and nobody is listed as having left.

**In the Action,** add `community` to `modules:` (the template has it) and `issues: read` to the permissions. It runs on the schedule and manual runs and reuses Team Flow's PR history.

**For AI agents:** `community_health` and `newcomers_waiting` in `stackvitals serve`.

## Portal

Light by design: no server, one daily run, pages in a private repo. It covers the catalog, checked ownership,
scorecards against similar public repos, campaigns, scorecards as required checks, golden paths, a docs index and a
Backstage export. Ten repos' files are read in one GraphQL query, six repos are checked at a time and unchanged answers are read
conditionally: a run costs about 4 requests a repo instead of 10 (under 3 on later runs, when little changed), so the
built-in token covers about 180 to 260 repos a run (70 before), and a 10,000-repo catalog reaches the app as about a
1 MB compressed download (8.4 MB unpacked), estimated from a real org's entries ([bench/accuracy/portal](../bench/accuracy/portal/README.md)).

**Try it on any org you can see:**

```
stackvitals portal check my-org     # what your token can read
stackvitals portal report my-org
```

It answers "what do we own, who owns it, and is it in good shape?":

- **Every repo** with its language, last push, branch rules, custom properties (tier, lifecycle) and, where the suite runs, its CI health, review flow and community score. Archived repos and forks are listed but not judged.
- **Owners, checked:** the CODEOWNERS file GitHub would use, GitHub's own error check for it, teams that actually have members, and named users who are still in the org. Each repo is valid, weak (with the reasons) or has no file; without a file, recent committers are offered as suggestions, never as owners.
- **Scorecards:** each repo reaches bronze, silver or gold when every rule of that level and the levels below passes. Each result carries its evidence. Data the token can't read is "not available", never a fail. The default rules:
  - bronze: a CODEOWNERS file, reviews required on the default branch, a README and a licence;
  - silver: owners that check out, a contributing guide, CI green on the first try and first reviews at least as good as half of similar public repos;
  - gold: first reviews faster than three quarters of similar repos, and OpenSSF Scorecard's Security-Policy and Token-Permissions checks (public repos).

  Where CI Health doesn't run, Portal measures the newest 50 push runs itself, the same way the benchmark does. To change the rules, put a `portal.toml` in the portal repo (`[[rule]]` with `id`, `check`, `level` and `peer` or `min`; `[[exemption]]` with `repo`, `rule`, `until` and `reason`). Your own checks: `check = "file"` with a `path` (the file must exist), plus `contains` or `lacks` with a pattern (a runbook with an on-call section, no `:latest` image tags); only yes or no is kept, never the file. `check = "catalog"` asks for a `catalog-info.yaml` with the `fields` you list, and `check = "catalog_owner"` for its owner to match CODEOWNERS. Any rule can take `from = 2027-01-01`: until then it shows what it would say ("not counted yet") without changing a level, so teams see it coming.
- **Typed catalog:** each repo's `catalog-info.yaml`, Backstage's format (which Port and Cortex also read), becomes a Catalog tab: components, APIs, resources and systems with their type, lifecycle, owner, system and what they depend on, whether CODEOWNERS agrees with the owner, and any problems in the file. Read with safe YAML only, one request per repo. On 12 public repos' files it read every one with no problems; the owner check passed for grafana's and caught real mismatches in three others.
- **Org view:** one tab adds up what every repo published (flaky and broken jobs, open and stale pull requests,
  deployments, findings, newcomers waiting) and takes medians of the rest (first-try share, pickup, review and cycle
  hours, change failure rate, community score), with the five worst repos on each; a repo that never ran a module is
  left out of that module's figures, never counted as zero.
- **History:** a line per repo per day, so the page says since when ("weak since 2026-10-17", "bronze since ...").
- **Required checks (opt-in):** `[checks] level = "silver"` in `portal.toml`, with the org App allowed to write checks,
  puts a "StackVitals portal" check on each repo's default branch and open pull requests: it passes at that level and
  lists the rules that keep a repo below it. Branch protection can require it, but it is posted once a day: a pull
  request's new commits get it on the next portal run, so requiring it can hold a PR for up to a day. At most 300 checks
  a run; each run starts where the last one stopped.
- **Golden paths (opt-in):** `[[golden_path]]` entries in `portal.toml` (`id`, `title`, `kind = "repo"` with a
  `template` repo, or `kind = "files"` with a `folder` of the portal repo). From the app's Golden paths tab, someone with
  write access to the portal repo creates a repo from the template, or, with write access to the target repo too,
  opens a pull request adding the folder's files (a standard CI workflow, a CODEOWNERS) to it; the org App carries it
  out on the portal workflow's next run (at once for a request issue) and each run is recorded. With `approvals = 1` on a
  `[[golden_path]]` in `portal.toml` (0 or 1), a request waits until someone else with write access to the portal repo
  comments `/stackvitals approve <code>` on the request issue; the waiting note gives the code, which changes if the
  request is edited, so what was approved is what runs. The requester needs write access too, and can't approve their
  own request; the approver is recorded beside them. A portal repo set up before this needs its workflow printed again
  (`stackvitals portal init`) for the `issue_comment` trigger. A "run now" from the app can't wait for approval: send
  those paths as a request.
- **Docs:** a Docs tab lists every repo's `docs/` pages in one search, each opening on GitHub; each repo also says how
  it runs (Kubernetes, a container, Terraform, serverless) from its root folder.
- **Backstage:** `portal/entities.yaml` on the data branch holds a Component for every repo without its own
  `catalog-info.yaml`, with its owner from CODEOWNERS, its StackVitals level as an annotation and a link to the portal;
  register its URL as one location in Backstage.
- **Campaigns:** a goal with a date, in `portal.toml` (`[[campaign]]` with `id`, `title`, `rules`, optional `repos` like `acme/api-*` and `language`, and `until`). The page shows how many targeted repos pass, which still fail and the failing count over time; one tracking issue per campaign in the portal repo is kept up to date as a checklist (ticked again on every run) and closed when every repo passes; a reminder comment names the repos still failing 7 days and 1 day before the date.

**In your org:** create a private repo (for example `portal`) and save the workflow from `stackvitals portal init` in it. It runs daily and keeps the catalog, its history and a Markdown page in that repo's `stackvitals-data` branch, which only people who can read the repo can open.

- **Public mode (no setup):** with the built-in token, Portal reads the org's public repos.
- **Private mode:** to include private repos, an org owner creates an org-owned GitHub App with read-only permissions and no webhook, installs it on the org's repos, stores its client ID and private key, and switches on the token step in the workflow. This is not a personal token. `stackvitals portal app-link my-org` prints a link that opens GitHub's form with the permissions filled in (Actions, Contents, Metadata, Members and Custom properties, all read only).
- **Required checks and golden paths** need an App that may also write: `stackvitals portal app-link my-org --writes`
  fills in checks, contents, pull requests and workflows write, and administration write (to create repos). Without
  them Portal stays read-only.
- **Privacy:** if the portal repo is public, private repos are left out of every page and file it writes.

**For AI agents:** `org_catalog`, `repo_scorecard` and `owners_health` in `stackvitals serve` read the org's published catalog (or build a quick one live).

## Contribute (MergeScout)

`mergescout` (or `stackvitals contribute`) runs the MergeScout MCP server and CLI: issues an outsider can realistically get merged, with merge rates, review times and live availability checks.

**How changes get merged in a repo** (`stackvitals contribute brief owner/repo`, or the MCP tool `repo_brief`): a short brief, measured from the repo's last 12 months of pull requests, of the things its files don't say:

- per folder: what merged PRs usually include (tests, a changelog entry, docs), their usual size, what maintainers most often ask for, who reviews there and how fast, and the CODEOWNERS;
- CI jobs and tests known to be flaky (re-run before chasing a failure);
- how outside contributors' PRs fare here (maintainers are recognised by what they do, not only by their badge), by size, against similar public repos, with a best estimate for a new PR and how far off that kind of estimate was on other repos.

Every number carries the count it comes from; thin history is said, not guessed. `--write DIR` also writes it as a marked section of `AGENTS.md` (read by many coding agents; the rest of the file is kept, and the run stops rather than guess if the markers were edited) and as GitHub Copilot path files (`.github/instructions/*.instructions.md`). Names that contributors control (test and folder names) are written as plain text, never as instructions. In a small test on 41 recently merged PRs in six repos (the same model, no tools or live search, planning each PR with and without the brief), the brief helped modestly: the actual first reviewer was in the model's top two 29 times against 23, and sizes were guessed a little better. On famous repos the model already knew, it added little.
