# StackVitals and Apache DevLake, run side by side

Run 2026-10-28 on the five repos the pre-registered rule drew ([preregistration.md](preregistration.md), [pick.py](pick.py),
[repos.json](repos.json)). Apache DevLake `v1.0.3-beta18` (the latest tag that day), started with its own
docker-compose on a GitHub Actions `ubuntu-latest` runner and configured through its documented REST API
([run.py](run.py)). DORA for each repo computed with DevLake's own dashboard SQL on the tables it collected
([score.py](score.py)), next to `stackvitals delivery` with defaults. Window: 2026-07-30 to 2026-10-28 (90 days).
No overall winner is declared. All numbers: [head-to-head-results.json](head-to-head-results.json).

## What it took to run

| | DevLake | StackVitals |
|---|---|---|
| What runs | 4 containers: DevLake server, config UI, Grafana, MySQL | One Python process (`stackvitals delivery`), nothing left running |
| Images pulled | 9.2 GB (DevLake 5.92 GB, dashboards 2.3 GB, MySQL 810 MB, config UI 197 MB) | none (a `pip install`) |
| Memory while running | 1.69 GB across the 4 containers (MySQL 702 MB, Grafana 539 MB, DevLake 444 MB) | one process |
| Disk after the run | 11.7 GB images + 1.7 GB volumes (the runner's own images included in the image total) | the data branch (a few MB per repo) |
| Pull and start | 102 s pull + 51 s start | 0 |
| Configure | 6 API calls a person would make (connection, scope config, scopes, project, blueprint, trigger) | 0 (defaults) |
| Collect and compute, 5 repos | **7,771 s (2 h 10 min)** at its 900 requests an hour token limit | **584 s on the same runner** (dexto 132, nodejs.org 267, bug-bounties 80, dotagents 77, run 28 s) |

## DORA, per repo (2023 report tiers)

StackVitals' first run (2026-10-28) kept only the newest 100 deployments of any environment, so on repos with many
preview deployments most production ones were lost (nodejs.org: 16 of 111). The side-by-side found it; it was fixed
(deployments are now paged back to the window and kept across runs) and StackVitals re-run on 2026-10-29 with the same
90-day window. Both runs are shown.

| Repo | Deploy days a week, DevLake | StackVitals, first run | StackVitals, fixed | Lead time, DevLake | StackVitals, fixed |
|---|---|---|---|---|---|
| getsentry/dotagents | 1 (high), 48 prod. deployments | 1 (high), 44 | 1 (high), 48 | 1.8 h (elite) | 1.6 h (elite) |
| vercel-labs/run | 1 (high), 55 | 1 (high), 33 | 1 (high), 55 | 1.5 h (elite) | 0.83 h (elite) |
| truffle-ai/dexto | 1 (high), 61 | 0, no tier, 27 | 1 (high), 61 | 0.6 h (elite) | 0.55 h (elite) |
| lissy93/bug-bounties | no tier ("N/A"), 40 | 0, no tier, 40 | 0, no tier, 40 | 1.5 h (elite) | 1.58 h (elite) |
| nodejs/nodejs.org | 3 (high), 114 | 0, no tier, 16 | 3 (high), 111 | 53.9 h (high) | 61.4 h (high) |

Same tier after the fix: deployment frequency 5 of 5 (first run 2 of 5), lead time 5 of 5 (first run 4 of 5).
Change failure rate and recovery: neither tool found an incident on these repos in the window (DevLake: "N/A, check
if you have collected incidents"; StackVitals: no failed deployment), so they can't be compared.

## Why they differed, and still differ a little

- **Both read GitHub's Deployments API.** Every deployment DevLake counted came from it (its `_raw_github_graphql_deployment`
  table); its job-name rule `(deploy|push-image)` matched no job on these repos. So the "second project" with the
  Deployments API as the source, planned in the pre-registration, is what this run already was.
- **The first-run gap was our bug,** not a difference in rules: 100 newest deployments of any environment, where
  nodejs.org makes about 10 a day, mostly previews.
- **bug-bounties has no tier in either tool.** All 40 deployments fell between July 31 and August 22, so the median
  deployment days per week and per month are both 0, and 90 days can't show six months: DevLake prints "N/A" and
  StackVitals "no tier". The original write-up called this "DevLake found none"; that was wrong.
- **Small remaining differences:** StackVitals counts one commit sent to several stages within a day once (nodejs.org
  111 against 114) and matches each PR to the first production deployment containing its merge, so lead times differ
  by minutes to hours (nodejs.org 61 h against 54 h, the same tier).

## CI, traceability and upkeep (capabilities, not scored)

- **CI:** DevLake's dashboards show CI build counts and success rates from the jobs it collects. StackVitals' CI
  Health additionally names flaky tests and jobs (same code, different results), groups failures, and re-runs or
  quarantines flaky ones; DevLake has no flaky-test detection.
- **Traceability:** in DevLake, a number is traced by writing SQL against its MySQL tables (`cicd_deployment_commits`,
  `project_pr_metrics`). In StackVitals every DORA number opens into its deployments and pull requests in the app,
  and `stackvitals explain owner/repo lead-time` prints them with GitHub links.
- **Upkeep:** DevLake keeps four services and a database running, with upgrades and backups; StackVitals keeps a data
  branch in the repo and a scheduled workflow.

## Where this run departed from the protocol

- DevLake's second project (GitHub's Deployments API as the deployment source) was not run as a separate project: its
  tables show the first project already counted only Deployments API rows (above).
- StackVitals was re-run on 2026-10-29 after the deployment-history fix, same window, from a laptop.
- The CI job recorded StackVitals' output under the wrong key (a bug in `run.py`, now fixed), so the StackVitals side
  was re-run on 2026-10-28 around 16:00 UTC from a laptop with the same version, about 2.5 hours after DevLake's window
  ended. The times above are the CI runner's own (`stackvitals_total_s` in the results; per repo from the job's log,
  run 40696254408); the per-repo `stackvitals_seconds` in the results (dexto 223, nodejs.org 341, bug-bounties 23,
  dotagents 26, run 2 s) are that laptop re-run's.
- `stackvitals ci report` was not run, so the CI comparison above is of capabilities, not of numbers.
- DevLake's token limit was 900 requests an hour (the protocol said 1,000); collection time scales with it.
- The first attempt (run 40677986230) lost DevLake's tables to a text-encoding error in our export script, fixed
  before this run (40696254408).

## Reading it

On these five repos the two tools agree on deployment frequency and lead time tiers once StackVitals reads all
production deployments, which this side-by-side made it do. The cost of running each differs a lot: 9.2 GB of images,
four services and 2 hours 10 minutes against one process and under 10 minutes (about 13 times faster here).
