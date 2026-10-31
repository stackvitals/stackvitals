# Ranges, weekly changes and pulled shares: how well they hold up

StackVitals shows every headline number with its sample size and a likely range, flags a weekly change only when it
survives a false-alarm control, and pulls a small repo's first-try share toward similar public repos. This folder holds
the two checks behind those claims, their results, and what they can't show.

## Weekly changes: false alarms and what gets caught

**Claim:** the weekly digest and the CI and Delivery pages flag a change only when it is unlikely to be ordinary
week-to-week variation.

**How each number is checked:** the latest seven days against the four weeks before (Fisher's exact test for shares,
Mann-Whitney for times, a binomial test for counts). Pickup and opened-to-merged time are also checked over the latest 14
days against the four weeks before those, so a slowdown that lasts is still caught in its second week (when the weekly
check's own baseline already holds the first slow week). Work arrives in batches, so events in one week aren't
independent and those tests overstate certainty; each check is therefore also run for the eight weeks before (for the
14-day checks, only past windows that don't overlap the current one), and how widely those results swing (blended with a
typical swing worth four weeks, each past week counted as at most a four-sigma swing) scales this week's result, read on
a t-distribution. Benjamini-Hochberg at 10% then runs over every check in the scan that had enough items to be a test. A
slowdown flagged both weekly and over 14 days is listed once.

**Replay** (`nulls.py`): 26 public repos' merged pull requests and deployments (aiohttp, django, numpy, pandas, pytest,
react, tokio and others), 259 weekly scans, each repeated 20 times with the six weeks it looks at shuffled, so any flag is
ordinary variation.

Each rule is scored twice on the same scans:
- **False alarms:** the shuffled weeks, where nothing really changed.
- **Detection:** the real weeks with the review times of the last week (or the last two weeks) made 2 or 10 times longer.

Every rule gets the same calibrated p-values; they differ only in the cut-off and in false-alarm control across the
numbers in a scan.

| What a digest would report | False alarms (shuffled scans that flag anything) | Caught, last week 2x / 10x longer | Caught, last two weeks 2x / 10x longer |
|---|---|---|---|
| Every difference ("pickup up 2.1 h") | 97.9% | 86% / 96% | 86% / 94% |
| Each number at p < 0.1 (the digest's own level, no control) | 20.8% | 22% / 45% | 27% / 53% |
| Each number at p < 0.05, no control | 11.3% | 14% / 32% | 16% / 41% |
| StackVitals (false-alarm control, q = 0.1) | **7.5%** (bar: at most 10%) | 11% / 25% | 12% / 35% |

- **Control is what keeps the bar:** with the 14-day checks a scan checks seven numbers, and a fixed cut-off's false
  alarms grow with each (on the same six-week replay, p < 0.05 went from 6.5% with five numbers to 11.3%, over the
  bar); with control they went from 7.4% to 7.5%.
- **What the 14-day checks bought** (the same replay with the weekly checks only: `nulls-before-results.json` and
  `nulls-2week-before-results.json`): a 10x slowdown in its second week was caught in 15% of scans before them and is in
  35% now (5x: 15% to 29%). The cost is the first week: 31% to 25% of 10x slowdowns, 22% to 18% of 5x, since two more
  checks share the same false-alarm budget.
- **Tried and dropped** (an exploratory run whose numbers aren't kept): CUSUM charts over weekly shifts, in six settings,
  caught no more than the 14-day checks; replacing the weekly time checks with 14-day ones caught lasting slowdowns
  best but about halved first-week catches, which makes the digest a week late.
- **Detection is still the weak side for every rule that keeps false alarms down:** a week or two of a small repo's PRs
  can't separate even a 10x slowdown from noise (the next table).

**What gets caught:** the same real scans with the last one or two weeks' pickup and opened-to-merged times made longer.

| PRs merged in the last week | Scans | Last week slower: 2x | 3x | 5x | 10x | Last two weeks slower: 2x | 3x | 5x | 10x |
|---|---|---|---|---|---|---|---|---|---|
| under 5 | 29 | 0% | 0% | 0% | 0% | 7% | 14% | 17% | 24% |
| 5 to 9 | 67 | 3% | 4% | 6% | 6% | 3% | 9% | 12% | 13% |
| 10 to 19 | 85 | 7% | 11% | 14% | 20% | 8% | 14% | 27% | 35% |
| 20 to 39 | 51 | 16% | 20% | 27% | 39% | 16% | 25% | 37% | 43% |
| 40 or more | 27 | 44% | 56% | 59% | 85% | 41% | 59% | 70% | 81% |
| all scans | 259 | 11% | 14% | 18% | 25% | 12% | 20% | 29% | 35% |

Review times within one repo spread over orders of magnitude, so one week of a small repo's pull requests can't tell
even a large slowdown from noise (the table: under 5 PRs, not even 10x shows in one week). A digest that says "pickup up
30%" is reporting that noise. StackVitals says "steady within noise" and how big a change it could have shown that week.
The two-week results are in `nulls-2week-results.json` (`nulls.py --slow-weeks 2`); the two `-before` files are the
same replay run on commit d6c7767's detector (weekly checks only), kept as files since today's code can't make them.

## Pulled first-try shares and their ranges

**Claim:** with few pushes, a repo's first-try green share pulled toward similar repos predicts its other pushes better
than its raw share, and a 95% range for the share of its later pushes is honest.

**Check** (`shrinkage.py`): the crawl's CI records of 6,623 public repos (2026-10-16 to 10-21). Half the repos fit the
Beta prior per language and size group, as the benchmark file does; for 1,923 repos of the other half, 3, 5, 10 or 20 of
their pushes are drawn at random and the share of the rest (at least 10) is predicted.

| Pushes seen | Repos | Error, raw (RMSE) | Error, pulled | Squared error cut | 95% range for later pushes held |
|---|---|---|---|---|---|
| 3 | 1,923 | 0.181 | 0.152 | 29% | 94.6% |
| 5 | 1,745 | 0.147 | 0.132 | 20% | 94.8% |
| 10 | 1,243 | 0.115 | 0.110 | 8% | 94.8% |
| 20 | 601 | 0.093 | 0.091 | 3% | 94.9% |

Coverage is the randomized PIT (the fair measure for counts; counted inclusively the ranges hold 98%). The CI page shows
the narrower range for the share itself; checked the same way against later pushes it holds 77-90% (`rate_range_coverage`
in the results), as a range for a rate should when later pushes add their own noise. The pulled share is the best guess
under squared error; on absolute error it is no better than the raw share from 5 pushes up.


### Finer peer groups don't help (`shrinkage.py --group`)

Should similar repos be matched on more than language and size? The crawl's CI records also give each repo's typical
time from push to all checks done (a sign of test style: unit tests against containers and long builds) and its number
of workflows. Each finer grouping was fitted and tested the same way, falling back to language and size, then all
repos, under 20 repos (`shrinkage-groups-results.json`).

| Peer group | Error after 3 pushes | After 5 | After 10 | After 20 | Range coverage (3 pushes) |
|---|---|---|---|---|---|
| Language and size (today) | **0.152** | **0.132** | **0.110** | 0.091 | 94.6% |
| Plus typical duration | 0.153 | 0.133 | 0.110 | 0.091 | 94.2% |
| Plus number of workflows | 0.152 | 0.132 | 0.110 | 0.091 | 94.3% |
| Plus both | 0.155 | 0.134 | 0.110 | 0.092 | 93.9% |

None lowers the error, and the finest grouping is slightly worse: groups get small, and their priors noisier. Peer
groups stay language and size, as the rule set before the test required.

## Limits

- The crawl started reading CI on 2026-10-16 and reads each repo once in four weeks, so these checks hold back pushes
  within one reading; a check across consecutive readings (real drift between months) follows from mid-November.
- The weekly replay covers Delivery's checks on public repos; CI's weekly checks use the same tests and calibration but
  no repo here kept 13 weeks of CI runs to replay them.
- Shuffling weeks treats all of a repo's real week-to-week differences as noise; a team may see a real but routine
  difference (a release week) as worth knowing.

## Reproduce

```
# Pull request history: `stackvitals delivery owner/repo` keeps it under ~/.stackvitals/flow/<owner>__<repo>
python bench/accuracy/uncertainty/nulls.py <folder of the 26 repos' flow workspaces> --points 12 --shuffles 20 --seed 13
# CI records: the crawl's daily ci-YYYY-MM-DD.ndjson.gz files (public at launch)
python bench/accuracy/uncertainty/shrinkage.py <folder of ci files> --draws 20 --seed 13
```

Results: `nulls-results.json`, `shrinkage-results.json`. The 26 repos are the keys of `repos` in `nulls-results.json`;
their histories were read on 2026-10-21, and a later read holds later weeks, so its numbers will differ a little.
