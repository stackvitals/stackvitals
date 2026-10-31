# Does the finder pick issues outsiders get merged? (prospective, read from 2027-03-20)

MergeScout ranks open beginner issues by how likely an outsider's pull request is to be merged. Merge odds fitted on
the past can always look good on the past, so this test was set up before its outcome exists:

- **Frozen 2026-10-23:** the finder's ranking of all 13,496 open beginner issues in 3,878 repos of the 2026-10-20
  snapshot (`frozen.json.gz`, SHA-256 in `frozen-manifest.json`): each issue's rank score, merge odds and whether it was
  called free.
- **Pre-registered:** [preregistration.md](preregistration.md) fixes the outcome (an outsider's first linked pull
  request, opened within 90 days, merged within 30), the comparisons (the finder's top third against the plain "good
  first issue" filter; free against taken; calibration of the merge odds) and how each result is read.
- **Read:** `prospective.py score` (written and tested on 2026-10-23, before any outcome) refuses to run before
  2027-03-20, once the 90-day attempt window and 30-day merge window have closed and the crawl has read them.

This tests the ranking, not people using the finder; that needs outside users reporting outcomes (`report_outcome`),
after launch.

## Reproduce

```
python bench/accuracy/contribute/prospective.py freeze --snapshot ~/.mergescout/mergescout.sqlite   # done 2026-10-23
python bench/accuracy/contribute/prospective.py score --crawl <crawl folder>                         # 2027-03-20 on
```
