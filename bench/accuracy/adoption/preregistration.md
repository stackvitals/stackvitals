# Pre-registration: does installing StackVitals help a repo?

Written 2026-10-24, before launch, so before any repo has installed it. `study.py freeze` stores this file's SHA-256
and the scorer's in `manifest.json`; `study.py score` refuses to run if either changed, or before 2027-07-01.
Amended and refrozen 2026-10-30, still before launch: the Action's public home became `stackvitals/stackvitals`, so
the code search below looks for that name (the old private name could never be installed by others). Nothing else changed.

## Question

After a public repo installs the StackVitals Action, do its red-CI hours, its review wait and its newcomers' return
change more than they do in similar repos that didn't install it over the same months?

## Who counts

- **Adopters:** public repos whose workflow files use `stackvitals/stackvitals@` (GitHub code search), read on the
  day of scoring. The install day is the oldest commit of the workflow file that uses it (the earliest if several do;
  a workflow file usually
  starts with the line; a file that existed before reads as an earlier install, which moves the after period closer
  to the real install and may take in days before it). Our own repos and forks are left out.
- **Included:** adopters held in the crawl (100+ stars, not archived) that installed at least 180 days before the read
  and still run it, with 10+ pull requests by people and a review wait (below) in the 90 days before installing, and
  at least one comparison repo. Each left-out adopter is counted under its reason.
- **Comparison repos:** for each adopter, up to 3 crawled repos that never used it (not found by the read-day code
  search), with the same main language, the same star tier, a review wait and pull request volume within half to
  double the adopter's in the same 90 days; the 3 closest by their pre-install review wait, ties broken by a seeded
  draw (seed 23) over the candidates sorted by name. Each takes its adopter's dates.

## Outcomes

For each repo, before (the 90 days before installing) and after (days 30 to 120 after installing; the first 30 days are
setup):

1. **Primary, red-CI hours:** hours per 30 days in which the latest completed push run of at least one workflow on the
   default branch had failed (GitHub's Actions API, read at scoring; runs from 7 days before each period set the state
   at its start; a run counts when it ended in success, failure or timed out, so cancelled and skipped runs don't).
   A period with no such run in it has no data, and that repo drops out of this outcome.
2. **Review wait:** the median hours from a person's pull request opening to the first review by a person, counted
   when that person is a maintainer (OWNER, MEMBER or COLLABORATOR) other than the author (the crawl keeps the first
   review only); bots left out; pull requests without such a review are left out.
3. **Newcomers' return:** of the outside people whose first pull request to the repo opened in the period, the share
   who opened another within 60 days (crawl `prs`; outside means not OWNER, MEMBER or COLLABORATOR).

An outcome missing in either period, for the adopter or for all its comparison repos, leaves that adopter out of that
outcome only; each outcome reports how many adopters it used.

## Comparison

A difference in differences: for each adopter, its after-minus-before change minus the mean change of its comparison
repos that have the outcome; then the mean over adopters, with a 95% range from 2,000 bootstrap draws over adopters
(seed 23) and a two-sided bootstrap p-value (twice the smaller share of draws at or below zero and at or above zero, at
least 1/2,000). The three outcomes are read together with a Holm correction at 5% (bootstrap p-values); red-CI hours
is primary. An outcome no adopter has reads "no data" and counts as p = 1 in the correction.

## How results are read

- Installing helped on an outcome if its Holm-adjusted p-value is under 0.05 and its mean change is on the better side
  of zero (fewer red-CI hours, a shorter wait, a higher return share); hurt if under 0.05 and on the worse side;
  otherwise "no measurable difference", with its 95% range. Each outcome reports its mean, 95% range, raw and adjusted
  p-values and the number of adopters it used.
- Fewer than 20 included adopters reads "too few adopters to tell" on every outcome, and the read repeats every three
  months with the same rules until a read includes 20 or 2028-07-01. After a read that includes 20 or more, or after
  2028-07-01, the scorer refuses to score again: the last read stands.
- Every result is published whatever it shows, with the counts of adopters found, included and left out (and why).

## Known limits

Repos that install a tool may already be improving, and matching on language, size and the pre-period only removes part
of that; the comparison repos may run other CI tools. Installing is not using: a repo may install and ignore it. "Never
used it" means not found by the read-day code search, so a repo that tried the Action and removed it can be a
comparison repo. Author association is the value when the crawl read the pull request, so people who later joined the
project count as insiders throughout. Red-CI hours read the current default branch's name, so a default branch renamed
since then reads nothing. This measures public repos only.
