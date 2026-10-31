# Pre-registration: StackVitals and Middleware, run side by side

Written 2026-10-29, before either tool is run for this test. Results are published whatever they show.

## Question

On the same five public repos and the same 90 days as the DevLake side-by-side, how do StackVitals and Middleware
(middlewarehq/middleware, the open-source DORA tool) compare on what a team has to run, how long until the first DORA
numbers, and whether the numbers agree (and why not when they don't)?

## Repos and window

The five repos of [../devlake/repos.json](../devlake/repos.json) (drawn by a pre-registered rule there), 90 days back
from the run.

## How each tool is run

- **Middleware:** its single Docker image (`middlewareeng/middleware`, digest recorded) on a GitHub Actions
  `ubuntu-latest` runner, configured only through its own HTTP API with curl ([run.sh](run.sh)): one team per repo in
  its `PR_MERGE` mode (every merge into the default branch is a deployment), since it can't read GitHub's Deployments
  API, which all five repos use. Sync history set to 90 days. It needs a personal access token that can call
  `GET /user`, kept in the `MW_PAT` secret; read-only, public repos only.
- **StackVitals:** `stackvitals delivery owner/repo --days 90 --json` twice: with its defaults (Deployments API) and
  with `source = "merges"`, the same rule Middleware uses.

## Measures

1. Footprint: image size, memory, start time, configuration steps.
2. Time to first numbers.
3. DORA agreement per repo: deployments, lead time, change failure rate, recovery. Middleware reports means in seconds
   and StackVitals medians in hours, so the per-PR lead times are compared too, not only the headline numbers.
4. Incidents: Middleware counts revert PRs; StackVitals counts reverts, hotfix labels and incident issues.

## Known limits

Five repos; public repos only; one Middleware release; Middleware's GitHub client has no rate-limit pacing, so the token's
remaining requests are recorded before and after.
