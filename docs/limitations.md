# Known limitations

What each part of StackVitals can't see or do, where its measured accuracy is weak, and what it needs from your repo.
Numbers come from the accuracy cards ([accuracy.md](accuracy.md)).

## Every module

- **Labels:** two model families (Claude, then Gemini 3.5 Flash-Lite) labelled each sample, and Claude settled their
  disagreements blind. No person has audited them. Gemini, settling a sample of the same disputes, agreed with
  Claude's rulings on 15 of 40 ([accuracy.md](accuracy.md)).
- **Ranges:** where a card counts each repo once, that range is quoted, since one busy repo can dominate a sample.
- **Weekly changes:** 7.5% of shuffled scans flag something, but only 25% of 10x slowdowns are caught in their first
  week (35% in their second), and none in a first week with under 5 merged pull requests ([uncertainty card](../bench/accuracy/uncertainty/README.md)). On a small
  repo, "steady" means "can't tell".
- **History:** the `stackvitals-data` branch keeps 400 days of pull requests and issues and 180 days of CI, capped at
  250 MB. The first run reads up to 90 days of CI.
- **Permissions:** a missing one skips that part, and the job summary names it.

- **History in a bucket** (`storage: s3://...`) is kept by the Action only. `stackvitals ui` and `sql`, Explore, the MCP
  server, the Portal's org view and `stackvitals ci quarantine` (skipping flaky tests in your CI) read the stackvitals-data
  branch and don't see a bucket yet. Switching starts a fresh history; the branch isn't copied.

## CI health

- **Scope:** flaky jobs come from GitHub Actions history only. From Jenkins, GitLab CI, CircleCI or Buildkite, test-level
  flakes come through uploaded test reports (`stackvitals ci upload`); their job-level history isn't kept. GitLab CI is the exception: its job (`templates/gitlab/stackvitals.yml`, preview) keeps pipeline history in the project.
**Can't see or do**
- Single flaky tests need uploaded test reports. In a sample of 190 crawled repos, about 3% of active repos kept
  readable ones ([features card](../bench/accuracy/features/README.md)).
- Jobs with rare flakes look like "never flaked" in a short window. Status precision (re-running pinned commits) is
  not measured.
- No verdict lets a failure through, and none says "safe to re-run". Likely flaky, outside failure, already failing,
  maybe flaky and PR details all still block the verdict check until CI is green. GitLab job logs aren't read, so
  there a job that flaked before is never called a likely flake.

**Weak accuracy** ([flaky card](../bench/accuracy/flaky/README.md))
- **Likely flaky (known flaky):** history alone was the change's own failure in 13 of 81 held-out calls (10-26%;
  13 of 38 without lxc/incus). The stricter rule (a flake's sign in the log, no changed file named), pre-registered
  and scored on 36 fresh repos, kept 4 of 44 calls, none the change's, but that is 0-49%: the 5% bar is unproven and
  it covers few failures (9% of history's calls there). So the label says "likely" and the advice says to check the
  error before re-running.
- **Flagged flakes:** 97.2% real (92-99%; 87-99% counting each of 40 repos once), but 80.2% on Gemini's labels.
  Rust jobs: 12 of 15 (55-93%).
- **Misses:** 17.3% of never-flaked failures were intermittent (11-26%); 25.4% on Gemini's labels.
- **PR details:** 1 of 24 matches was the change's code (1-20%; 0-53% counting each repo once). DataDog's API client
  gave 75% of them, so this is preliminary.
- **Already failing on main, same error:** 0 of 12 tuned (0-24%), 1 of 6 held out.
- **Maybe flaky:** held out, the signs matched 2 of 150 never-flaked failures, so they rarely help.

**Model triage** (opt-in, [agents card](../bench/accuracy/agents/README.md))
- At most 3 failures a run. Its view sits beside the verdict and never changes it.
- On 91 failures: StackVitals alone 60 right, with triage 79, an agent reading the log 86 (Sonnet).
- Private logs are sent only with `allow_private = true`; free tiers may keep what they're sent.

**Needs:** `actions: read` (`write` to re-run), `pull-requests: write` for the comment, `checks: write` for the
verdict check, `issues: write` for flaky-test issues.

## Team Flow

- **Reviewer suggestions:** a real reviewer was in the top 3 for 82.2% of 1,186 pull requests (80-84%; 75-89%
  resampling repos, against 70-87% for the busiest reviewers). That is not "the best reviewer", and the check read no
  CODEOWNERS files ([team card](../bench/accuracy/team/README.md)).
- **Automation:** review requests, size labels and the docs label are off until a team turns them on. Requests need
  `pull-requests: write`; size is lines changed only; the docs label never approves.
- **Agreements and pulse:** off until set (agreements) and counts only (pulse); neither has an accuracy card.
- **Needs:** `pull-requests: read`, `checks: read`, `statuses: read`. Without the check permissions it still runs,
  without check status.

## Delivery

([DORA card](../bench/accuracy/dora/README.md))
- **Deployments:** the source was right for 53 of 60 repos (78-94%) and 30 of 35 held out (71-94%). Workflow recall
  was 60% held out (44-73%): plain names like docker, pypi or CD are missed. Check with
  `stackvitals delivery owner/repo --deploys` and set `[delivery] source` or `deploy_workflow`. Only 9 of the 60 repos
  deploy services.
- **Incidents:** each links to the last deployment before it. Where a report named the release that broke, that was
  the last release 6 of 15 times (20-64%; 19-66% counting each of 13 repos once).
- **Reverts:** the fix chain was right on 87 of 89; time order was wrong on 71 of 89 (57-92% by repo). Releases from
  maintenance branches with backports defeat both.
- **Tiers:** on 4,618 repos, 61.9% change tier with the deployment definition.
- **Rework and change failure rate** see only failures that leave a trace (a revert, a hotfix, an incident label or
  tool), never ones nobody linked ([dora-guide.md](dora-guide.md)).
- **AI-assisted outcomes:** markers miss most AI help, so "AI-marked" is a floor, and matching can't see what a pull
  request was for ([AI card](../bench/accuracy/ai/README.md)). Under 5 matched pull requests it says "too few to
  compare". It shows an association, never a cause.
- **Investment:** on pip, pytest and aiohttp 3 to 7% stayed unsorted; titles that name a component leave more unsorted
  until you set `[investment.labels]`.
- **Needs:** `deployments: read`; production environments named production, prod or live, or set `production`.

## Dependencies

([deps card](../bench/accuracy/deps/README.md))
- **Known vulnerabilities:** every package in the lockfiles OSV-Scanner reads (npm, PyPI, Go, Rust, Maven, RubyGems,
  NuGet, Composer and more). On 100 crawled repos, 65 had a lockfile it reads; Maven `pom.xml` files that take versions
  from a parent were read 20 of 46 times, `go.mod` 14 of 17, `Package.resolved` 1 of 3. GitHub's malware advisories are
  matched on the next scheduled or post-CI run without waiting for a full rescan; how often that beats OSV isn't
  measured, and malware detection has no measured recall.
- **Release signs:** npm and PyPI only; a new install script or lost provenance never fired on 296 ordinary releases,
  new dependencies on 5%. Release age alone is a note. GuardDog (opt-in) runs only on Linux runners and is experimental.
- **Runtimes:** read from version files, Dockerfiles and workflow setup steps; a version given as a range (">=18") is
  left out. Old lines in a test matrix are listed, not flagged.
- **Dossiers (deep evidence):** npm and PyPI only, 4,033 packages. The verdict is none when evidence is thin, and never "safe". The
  card measures coverage, not how often the verdict is right.
- **Exploits:** EPSS scores 99% of CVEs. The open-advisory alarm (exploited, or EPSS 10% or more) matched no package in
  the crawl, so it is rare by design.
- **Rollbacks:** 19 in 48,994 merged bot upgrades, a rare flag, not a rate.
- **Paths:** npm and uv lockfiles only; poetry.lock doesn't say which packages are direct, and requirements.txt and Pipfile.lock have no graph.
- **Look-alikes:** only added packages. On npm the name alone flagged 1.1% of legitimate names against 0.25% of
  malicious ones, so a flag also needs under 1,000 weekly downloads. When downloads can't be read (or outside lookups are off), a near name is only a note to check, not an alarm.
- **Reachability:** Go only, from govulncheck you run in the workflow; checked on 3 repos. Standard-library results
  depend on the scan's Go version.
- **Imports (Python, JavaScript, Rust):** whether the repo's own code imports the package, not whether it calls the
  vulnerable code; a package reached only through another reads "no direct import", and a Python package whose import
  name isn't known reads "unknown". Not measured against call-path tools yet.
- **Scorecards:** shown, never deciding a verdict.
- **Needs:** `contents: read` and GitHub's dependency graph (turn it on for private repos). The comment goes only on
  same-repo pull requests.

## Community

([community card](../bench/accuracy/community/README.md))
- **First responses:** held out, regular responders and people who triage catch 57% of project answers the
  roles-only rule misses (46-69%; 38% on Gemini's labels), and about 16% of what they add are drive-bys. About 43% of
  occasional contributors' answers still go uncounted; the rule errs toward "waiting".
- **Traffic:** GitHub deletes it after 14 days and the built-in token can't read it; keeping it needs your own GitHub
  App with "Administration: read".
- **Score:** a fact with too little data is left out.
- **Needs:** `issues: read`.

## Portal

- **Scope:** a lightweight catalog built on GitHub alone: owners, scorecards, campaigns, required checks, golden paths and
  a docs index, with GitHub's own sign-in and repository roles. It doesn't replace an internal developer portal with
  plugins, live service data from clouds or its own access control (Backstage, Port, Cortex, OpsLevel); it exports
  to Backstage instead.
- Golden paths open a pull request in a repo the requester can already write to; they never create repos or run
  arbitrary scripts. Required checks post a check run; a branch rule must still name it.
- The built-in token reads public repos only; private repos need an org-owned read-only App. A public portal repo
  leaves private repos out.
- The org view adds up and takes medians of what each repo published; repos that never ran a module are left out of
  that module's figures, not counted as zero.
- Data the token can't read shows "not available".
- `catalog-info.yaml`: 186 of 198 real files read cleanly (94%); all 12 flagged had real faults
  ([features card](../bench/accuracy/features/README.md)). Levels have no accuracy card.

## Connectors

([connectors.md](connectors.md))
- **Jira and Linear:** Jira Cloud only. The first pull reads 180 days, at most 20 pages a run. On a public repo,
  titles, links and sprint names are never stored. Write-back is tested against recorded answers, not live services.
- **PagerDuty and incident.io:** until `services` or `incident_types` is set, every incident in the account counts.
  Incident links have the weakness under Delivery.
- **Copilot:** needs an org App with "Organization Copilot metrics: read"; the workflow token can't have it. Each day
  arrives two days late.
- **Untested live:** comment commands' access check and uploads from other CI systems are covered by tests only.
- **GitLab:** CI only (flaky jobs, pages, merge request notes; no verdict check); merge requests, deploys and incidents aren't read yet. The GitLab job is tested against a stand-in API, not a live project.

## The app

- It shows what the last run published, nothing newer.
- Pages from a private repo may be public on your plan; set `pages: artifact` (a download kept 7 days) or use
  `stackvitals ui owner/repo`.
- GitHub Pages builds a branch about 10 times an hour at most; busy repos should set `pages: deploy`.
- Explore loads DuckDB from jsDelivr. Its timing (2.8 to 3.2 s for a first query on 20,648 pull requests) dates from
  2026-10-21 and is due a re-check ([scaling.md](scaling.md)).
- Decisions need triage access and settings need write access.

## The MCP server

([agents card](../bench/accuracy/agents/README.md))
- On one failure inside GitHub's log retention it adds nothing: Sonnet 86 right without it, 88 with it, of 91
  (p = 0.63). Questions beyond 90-day retention are not tested yet.
- Its CI and flow tools need a GitHub token. Without published data they read live: up to 90 days of CI, 3 months
  of pull requests.
- It never changes a repo; `propose_change` returns a link a person submits.
- It offers 11 tools by default; the other 24 (Portal, Community, contribution and detail tools) load with
  `--tools all`.

## Failure modes

What happens when something goes wrong mid-run. Each line is held by a test in `tests/test_flow_*.py`.

| What goes wrong | What StackVitals does | Test |
|---|---|---|
| Two runs push at once | The later one re-runs its steps on the fresh data; neither side is lost | `test_overlapping_runs_converge_without_losing_either_side` |
| A run dies before its commit | Nothing is half-written; the next run catches up | `test_a_run_that_dies_before_its_commit_leaves_nothing_and_the_next_run_catches_up` |
| The same event arrives twice | Nothing changes the second time | `test_the_same_event_processed_twice_changes_nothing` |
| One module fails | It is reported; the others still run and save | `test_a_failing_step_does_not_lose_the_other_steps_work_and_is_reported` |
| A comment, chat post or issue is refused | Noted in the summary; the data is already saved | `test_a_hook_that_fails_is_noted_and_the_next_hooks_still_run` |
| The API budget runs out | What was read is saved; the next run resumes | `test_a_run_that_spends_its_budget_still_saves_what_it_read` |
| GitHub asks the issue finder's GraphQL reads to slow down | Waits as told (`Retry-After`), shared by every client on the token | `test_secondary_limit_uses_retry_after` |
| The network drops during the issue finder's reads | Retries, then gives up cleanly with its own error | `test_retries_network_drops_then_gives_up_cleanly` |
| A connector key is refused | Said without the key; what was pulled is kept | `test_a_refused_key_is_said_without_the_key_and_keeps_what_was_pulled` |
| A test report is hostile (an XML bomb) | Refused, never a crash | `test_hostile_xml_is_refused_without_crashing` |
| A JSON test report stopped early | Read and marked as cut short | `test_a_json_report_that_stopped_early_says_so` |
| A pull request's own files try to fool or break the dependency check | Odd file names can't inject workflow commands, a renamed or off-registry package borrows no verdict, an unreadable lockfile is skipped | `test_the_pr_check_cannot_be_fooled_or_broken_by_the_prs_own_files` |

**Not tested yet:** Bors and other merge bots outside GitHub's merge queue, monorepo task runners (Nx, Turborepo,
Bazel) that skip unchanged tests, and GitHub Enterprise Server.
