# Pre-registration: what happens to a repo after it starts taking coding agents' pull requests

Written on 2026-10-23, before any outcome below was computed. The only data looked at beforehand: column names, the
CI state field's fill rate (98% empty, so CI outcomes are left out), fetch dates, and how many repos hit the crawl's
per-repo cap. `adoption.py` prints this file's SHA-256 into its results, so any later edit shows.

## Question

When a public repo starts merging work from coding agents, do its merged pull requests, its people's pull requests,
their wait for a first review and their merge rate change, against similar repos that haven't started yet?

## Data

The crawl's pull request tables (first full crawl, fetched 2026-10-16 to 18): 23,100 public repos with 100+ stars,
pull requests created in the year before the fetch, at most 300 per repo (newest first).

- **Covered months:** whole calendar months from 2025-11 to 2026-09. A repo that hit the 300 cap is covered only from
  the month after its oldest crawled pull request.
- **Kinds:** bots (dependency and CI bots, by account) are left out everywhere. An agent's PR is one from an agent's
  branch (codex/, copilot/, cursor/, devin/, claude/) or an agent's account; every other PR is a person's (AI-assisted
  ones included).

## Groups

- **Adopters:** the first covered month with an agent's PR is the adoption month g; at least 2 agent PRs in g to g+2
  (one-off trials are left out of both groups); at least 3 covered months before g and 1 after.
- **Comparison repos:** for adoption month g and month t, repos with no agent PR in any covered month up to t (never
  adopters, and later adopters before they start), in the same activity band.
- **Activity band:** terciles of a repo's mean monthly non-bot pull requests over its first 3 covered months (before
  adoption for every adopter, by the rule above).

## Outcomes (per repo and month, by the month a pull request was created)

1. **Merged PRs** (primary): log(1 + non-bot PRs created that month that were merged).
2. **People's merged PRs** (primary): log(1 + people's PRs created that month that were merged).
3. **Wait for a first human review:** log of the median hours from creation to the first review by a person, over
   people's PRs that got one; months with fewer than 3 such PRs are left out.
4. **People's merge rate:** merged among people's PRs created that month that were closed or merged; months with fewer
   than 3 are left out.

Outcomes 3 and 4 skip 2026-09 (pull requests too young to have been reviewed or closed).

## Estimator

Callaway and Sant'Anna's group-time effects: for each adoption month g and month t, the adopters' mean change from
g-1 to t minus the comparison repos' mean change over the same months, within activity bands and weighted by adopters.
Event-time effects average them for e = t - g from -4 to +3 (e = -1 is zero by construction); the overall effect is the
mean of e = 0 to 3. 95% ranges from 400 bootstrap draws of repos (seed 23).

## Checks and how results are read

- **Pre-trends:** the effects at e = -4 to -2 must have ranges that include zero; an outcome whose leads don't is
  reported as "not credible: adopters were already changing".
- **Negative control:** each adopter's adoption moved 3 months earlier and only its months before the real adoption
  used; the overall effect must have a range including zero.
- **An effect** is claimed only when the overall range excludes zero and both checks pass; otherwise "no measurable
  change", with the range.
- **Secondary, by activity band:** the overall effect per band, read as description, not as a claim.

## Known limits, stated before the results

Adoption isn't random: repos that start using agents may be growing anyway (the pre-trend check covers some of it, not
all). Agents' PRs are found by branch and account only, so a repo that uses agents under people's branches counts as a
comparison repo, which pulls effects toward zero. The crawl covers active public repos with 100+ stars, not private
teams. Eleven months is short; effects past three months aren't estimated.
