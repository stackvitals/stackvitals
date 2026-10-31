# Pre-registration: StackVitals and Apache DevLake, run side by side

Written 2026-10-28, before either tool is run for this test. Results are published whatever they show.

## Question

On the same public repos and the same 90 days, how do StackVitals and a real Apache DevLake install compare on what a
team has to run, how long until the first DORA numbers, whether the two tools' DORA numbers agree (and why not when they
don't), what each can say about CI, and whether a number can be traced to its pull requests and deployments?

## Repos

The crawl's repos with 100+ stars, not archived and pushed in the last 30 days, sorted by name and shuffled with seed
28; checked in that order, the first five with, in the 90 days before the run, 10+ GitHub deployments to an environment
named production (or prod, live) and 30 to 300 merged pull requests (`pick.py`, `repos.json`). Repos that DevLake can't
collect (API errors after retries) are replaced by the next eligible repo and counted. (Amended 2026-10-28 before any
tool ran: the first draft drew from the DORA card's labelled repos, which gave only 2 eligible.)

## How each tool is run

- **DevLake:** its own docker-compose release (the latest tagged release on the run day), started on a GitHub Actions
  `ubuntu-latest` runner, configured only through its documented REST API: one GitHub connection (a token, rate limit
  1,000 requests an hour), one project with the five repos, its default transformation for deployments
  (`(deploy|push-image)` on workflow job names) and, separately, a second project using GitHub's Deployments API as
  the deployment source where the release supports it; DORA read from its own domain tables with its dashboard SQL.
- **StackVitals:** `stackvitals delivery owner/repo` and `stackvitals ci report owner/repo` on the same runner, with the
  same token, defaults only.

## Measures

1. **Footprint:** services and containers started, memory and disk used at peak, images pulled (bytes).
2. **Time to first DORA numbers:** wall clock from a clean runner to the first numbers, split into install, configure
   and collect; and the number of steps a person would do by hand (each API call or form a person must fill counts one).
3. **DORA agreement:** for each repo and each of the four measures, both values; the difference; and its cause, read
   from both tools' records (deployment source, counting rule, window edges). Agreement = same tier.
4. **CI:** what each tool reports about CI failures on the same runs (success rate, flaky jobs, re-runs, time to green);
   capabilities only one tool has are listed, not scored.
5. **Traceability:** whether each DORA number can be opened into the pull requests and deployments it came from, and
   how (a screen, a query, a command).
6. **Upkeep:** what has to keep running afterwards (services, schedules, upgrades, database).

## How results are read

No winner is declared overall. Each measure is reported per repo with both tools' numbers. Where the tools disagree
on DORA, the cause is named; neither tool is assumed right without checking the underlying deployments and pull
requests. Known bias: we built StackVitals; DevLake is configured only as its docs describe, with the most generous
documented deployment setting tried too.

## Known limits

Five repos is a small sample; public repos only; one DevLake release; GitHub's Deployments API use depends on the repos.
The runner is a cloud machine, not a laptop or a team's server, so timings are a lower bound for a person doing it.
