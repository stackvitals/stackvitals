# Pre-registration: does the finder's ranking pick issues outsiders get merged?

Written 2026-10-23, before any outcome exists, and committed the same day with the frozen ranking and the scorer.
`prospective.py freeze` stored the finder's ranking of every open beginner issue in the 2026-10-20 snapshot
(`frozen.json.gz`, its SHA-256 in `frozen-manifest.json`); `prospective.py score` refuses to run before 2027-03-20 or
if the frozen file changed, and prints this file's SHA-256 into its results.

## Question

When an outside contributor opens a pull request for an open beginner issue, is it merged more often if the finder
ranked that issue high, compared with the plain "good first issue" filter (every open beginner issue, unranked)?

## Frame

Every open issue in the 2026-10-20 snapshot with a beginner label (the snapshot's `beginner` flag): repo, number, the
finder's `rank_score`, its merge odds `p_merge` and whether it called the issue free (`available`).

## Outcome

From the crawl's pull request tables read on or after 2027-03-20 (the crawl reads each repo at least every four weeks,
so the window below is fully read by then):

- **An attempt:** the first pull request that names the issue among its closing references (`closing_issue_numbers`),
  opened from 2026-10-23 (the freeze) to 2027-01-21 (90 days later), by an outsider. Pull requests opened between the
  snapshot and the freeze don't count.
- **An outsider:** the pull request's author association is not OWNER, MEMBER or COLLABORATOR, and the author merged no
  pull request in that repo in the crawl's tables.
- **Merged:** merged within 30 days of being opened (so by 2027-02-20 at the latest).
- **Repos the crawl doesn't hold** for the window are left out and counted.

## Comparisons

1. **Primary:** the merged share of attempted issues in the finder's top third by `rank_score` (ranked across all
   frozen issues, not within each repo) against all attempted issues (the plain filter), as a difference with a 95%
   range from 2,000 bootstrap draws over repos (seed 23).
2. **Free or not:** attempted issues the finder called free against those it said were taken.
3. **Calibration:** the mean predicted `p_merge` against the observed merged share, in five bands of `p_merge`.

## How results are read

The ranking helps if the primary range is above zero. A range including zero reads "no measurable difference", with the
gap it could have found. Fewer than 100 attempted issues in the top third reads "too few attempts to tell", and the read
is repeated three months later with the same rules.

## Known limits

The crawl reads 300 pull requests per repo over a year, so very busy repos' attempts may be cut; an attempt that never
names the issue is missed equally in both arms. This tests the ranking, not people using the finder: that needs outside
users and `report_outcome`, after launch.
