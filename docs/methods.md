# Methods: the exact settings behind every number

Every headline number in StackVitals carries its sample size and a 95% range. This page lists the method and the
settings each one uses, so anyone can check them against the code (`src/stackvitals/core/stats.py`,
`core/changes.py`, `core/ai_outcomes.py`, `src/mergescout/bench/`) and against the accuracy cards
([accuracy.md](accuracy.md)).

## Shares: Wilson ranges
A share of k in n gets Wilson's score interval at z = 1.96. With no trials, the range is 0 to 1.

## Medians and percentiles: order-statistic ranges
A median or percentile gets a distribution-free range from the binomial order statistics: positions n·q ± 1.96·√(n·q·(1−q)),
with no assumption about the shape of the data. Under 6 values, no range is shown.

## Waiting times: Kaplan-Meier
Time to a first answer counts items still waiting instead of dropping them:
- an item still waiting is censored at the time of the scan;
- an item closed or merged without an answer is censored when it closed.

The median comes with a Brookmeyer-Crowley range on Greenwood's variance. When the curve never clearly drops below one
half, the upper end reads "or more". Under 10 items, the page says "too few".

## Weekly changes: a test per number, then false-alarm control
**The test.** Each scan compares the latest 7 days with the 4 weeks before:
- times use Mann-Whitney (medians shown);
- shares use Fisher's exact test;
- counts use a binomial test against the weekly average.

Fewer than 5 items on either side is not a test: it says "too few to tell" and doesn't count against the others.

**Calibration.** In short: a repo whose numbers usually swing a lot needs a bigger change before it is called a change. Work arrives in batches, so events in a week are not independent. Each number is also tested for each
of the repo's past 8 weeks, and the spread of those results (mean squared z, each capped at 16) widens this week's
test. The spread is blended with a typical swing worth 4 weeks:
- 1.5 for review times, set on half of 20 public repos and checked on the other half;
- 1.0 for shares and counts.

The result is read on a t-distribution with one degree of freedom per week of evidence (an empirical null).

**False-alarm control.** Benjamini-Hochberg at q = 0.1 over every test the scan actually ran. Only survivors read as
changed; the digest says how many numbers it checked.

**Smallest change it could catch.** Each check states the change it would catch about 80% of the time in a scan of
that many checks: a factor for times, points for shares.

## Small repos: shrinkage toward similar repos
A small repo's share (for example first-try green) is pulled toward similar public repos:
- **Prior:** a Beta(a, b) per peer group (same language and size band, published only with 20+ repos), fitted by
  beta-binomial maximum likelihood to the group's (hits, tries).
- **Repo's value:** the posterior Beta(a + k, b + n − k): its mean, with a 95% range from its quantiles.

Raw and shrunken values are both shown, with how far the peers pulled the number.

## AI-assisted work: like with like
**Matching.** AI-assisted and other pull requests are compared only within matched groups:
- the same repo and month;
- the same size band, log2(lines added + deleted + 1);
- for the same-author view, the same author and size band.

**Estimate.** The gap is a Mantel-Haenszel risk difference with Sato's variance, and a 95% range. When every group goes
the same way, the no-gap standard error is used so the range stays honest.

**Groups too small:** a group with fewer than 5 matched PRs says nothing; under 10 PRs on a side, numbers are left out.

**Check:** shuffling the AI labels within groups (200 placebos) shows the spread of gaps when nothing is going on.

These comparisons are observational: matching removes repo, month, size and author differences, not the choice of
which work people give to AI.

## Comparing StackVitals with other rules
On the accuracy cards ([accuracy.md](accuracy.md)), every "ours against theirs" carries a test:
- **Rules scored on the same items:** McNemar's exact test on the items only one of the two got right.
- **Independent samples:** Fisher's exact test.
- **A rival's rate built from several measured parts** (for example "passed on retry", which flags our events plus
  the ones we leave out): a 95% range from 20,000 Jeffreys posterior draws of each part (seed 7), and the range of the
  difference against ours.

A difference whose test or range doesn't exclude zero is printed as "not significant". It never reads as a win.

## Labels
Each card's labelled sample is labelled twice, by two different model families, each blind to StackVitals' verdict:
1. **Claude**, which made the first labels.
2. **Gemini (Flash-Lite)**, from the same codebook and evidence.

Disagreements are settled by a third reading (by Claude) with both answers and the evidence. Cards publish both labellers'
agreement (share and Cohen's kappa) and every changed label. No person has audited the labels yet.

Only links and labels are published, never log text.
