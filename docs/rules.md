# Rule reference

Every rule a StackVitals verdict or number rests on, from `bench/accuracy/registry.json`: what it does, the data it was tuned on and checked on, the bar it had to meet (set before the check where a date says so), its result and each change since. The card linked under each rule has the method and the labels. Generated; a test keeps it in step.

## `flaky.event` (version 3)

A job is flaky when the same code failed and passed: a re-run of the same run, or another run on the same tree.

- **Card:** [bench/accuracy/flaky](../bench/accuracy/flaky/README.md)
- **Tuned on:** none (written before sampling)
- **Checked on:** 263 failed jobs in 51 repos (flaky/items.csv)
- **Bar:** event precision lower bound at least 85% (set 2026-10-21)
- **Result:** met (92-99%); ties the plain retry rule scored on the retries it can see (96.9%); history confirms 42 of 112 flagged flakes as not the change and can't refute any
- **How sure:** validated
- **Changed 2026-10-22:** was same-code flips in any workflow; why: all 3 flips that weren't real flakes, and 5 checks of the PR's own text, were pull-request runs of workflows that also run on PR edits or labels; effect: 9 of 108 events left out (3 wrong, 5 PR-text checks, 1 real timing flake); 99 of 99 kept are real
- **Changed 2026-10-23:** was pull-request flips left out in PR-edit workflows; why: held out, all 17 flips in such workflows were real flakes; effect: reverted to the earlier rule

## `flaky.known_flaky` (version 4)

A pull request's job failure is called known flaky (shown as "Likely flaky: check the error, then re-run it", never "safe") only when the job had 3+ flakes in the window, one in the failing step; the failing step's log, up to its first error, shows an outside service, the runner or a wait failing and no failing test; and no line there names a file the pull request changed. A changed file named reads "maybe yours"; anything else reads "flaked before" (look first). It never passes the verdict check on its own.

- **Card:** [bench/accuracy/flaky](../bench/accuracy/flaky/README.md)
- **Tuned on:** masking.py's 36 failures in 9 repos and the first held-out read's 108 calls in 15 repos (heldout.py), which counted as tuning once it was used to write this rule
- **Checked on:** pre-registered 2026-10-28 (flaky/README.md), then scored on a fresh read of 36 repos none of the earlier reads used: 197 known-flaky calls by history in 19 jobs and 9 repos, 44 labelled at most 3 per job (flaky/safe-rule-results.json)
- **Bar:** masking upper bound at most 5% (set 2026-10-21)
- **Result:** bar not met: the rule kept 4 of the 44 fresh calls (9%; 3 jobs, 2 repos), none the change's own (0 of 4, 0-49%); 73 clear calls with none caused would be needed. On the data it was written from, 0 of 31 and 0 of 8. The history rule alone: 5 of 22 clear fresh calls caused (23%)
- **How sure:** bar failed (too few calls to show 5%: the label says "likely", the advice says to check the error first, and the verdict check waits for a green re-run)
- **Changed 2026-10-22:** was any earlier flake; why: 15 of 34 failures it called safe were caused by the change (44%); effect: 7 called safe (5 clearly labelled, 0 caused), all one job; the other 29 now cost a look
- **Changed 2026-10-23:** was a known flake passed the verdict check; why: 13 of 81 held-out safe calls were the change's own failure; matching past flakes' errors didn't separate them; effect: known flaky still reads 'likely a flake, re-run it', but the verdict check passes only once CI is green
- **Changed 2026-10-23:** was a known flake read 'likely a flake, re-run it'; why: in the agent head-to-head a smaller model trusted it on 2 failures the change caused; effect: it asks to check the error isn't from the change before re-running; those 2 were then answered right
- **Changed 2026-10-28:** was 3+ flakes in the window, one in the failing step (history alone); shown as "Known flaky"; why: held out, 13 of 81 such calls were the change's own failure; a flake's sign in the failing step's log and no changed file named separated them on the tuning data (0 of 31 caused when both held; 8 of 8 clear caused when a changed file was named); effect: fresh read: 4 of 44 calls kept, 0 caused (0-49%), so the 5% bar is unproven; shown as "Likely flaky" with its evidence, never "safe"; the rest read flaked before, or maybe yours (4 of 5 clear fresh cases caused)

## `flaky.outside_failure` (version 1)

The failing step's log shows a registry, cache, network or runner error and no failing tests.

- **Card:** [bench/accuracy/flaky](../bench/accuracy/flaky/README.md)
- **Tuned on:** the 284 labelled failures it is scored on (signatures written from common errors, then checked there)
- **Checked on:** 633 unlabelled failures from the same reads (flaky/outside-fresh-results.json), judged by re-runs and the default branch
- **Bar:** none caused by the change among matches (set 2026-10-22)
- **Result:** tuning set: 35 matched, none caused (90-100%); held out: 41 matched, none of 38 clearly labelled caused (0-9%); fresh: 5 of 8 history-decided matches not caused, the other 3 one repo's lasting registry rate limit
- **How sure:** validated
- **Changed 2026-10-22:** was failure-section match including 'failed to download and build'; why: a dependency's own build failing matched; effect: taken out; 4 matches given up for safety
- **Changed 2026-10-22:** was TEST_FAILED matching any 'FAILED:'; why: ninja's 'FAILED:' build lines hid an sccache outage; effect: test-runner forms only
- **Tried and dropped:** withhold 'outside failure' when the pull request edits CI files; why: on 36 fresh matches it caught none of the change-caused cases and took the excuse from 4 real outages

## `flaky.already_failing` (version 1)

A pull request's job failure reads already failing on main when the default branch failed in the same step in the 3 days before with the same error (2 of every 3 error lines shared); it still blocks the verdict check.

- **Card:** [bench/accuracy/flaky](../bench/accuracy/flaky/README.md)
- **Tuned on:** 23 labelled pull-request failures in 12 repos whose step had just failed on the default branch (flaky/already-results.json)
- **Checked on:** 60 held-out candidates in a second, wider read
- **Bar:** caused by the change at most 5% at the upper bound before it may pass the verdict check (set 2026-10-22)
- **Result:** not shown: same error 1 of 6 held out (only 11 of 60 matched), 0 of 12 tuned; the step alone 5 of 51 held out
- **How sure:** early observation (1 of 6 held-out matches with the same error)
- **Changed 2026-10-22:** was the same step alone; why: 4 of 22 such failures were caused by the change, with a different error in that step; effect: 12 matched, none caused

## `flaky.maybe_flaky` (version 1)

A failure with no flake history whose failing step (or test message) shows a wait or deadline running out, a benchmark gate or a live service in a test reads maybe flaky (re-run once to tell); it still blocks.

- **Card:** [bench/accuracy/flaky](../bench/accuracy/flaky/README.md)
- **Tuned on:** the 284 labelled logs and the agent card's misses (flaky/maybe-results.json)
- **Checked on:** 150 never-flaked held-out failures, 2 matched
- **Bar:** caused by the change at most 20% at the upper bound (it asks for a re-run, it doesn't excuse) (set 2026-10-22)
- **Result:** fits: 0 of 22 tuned; held out the signs matched only 2 of 150 (1 the change's): too rare to judge
- **How sure:** early observation (2 held-out matches in 150 failures)
- **Changed 2026-10-23:** was track record over all 24 signature matches; why: the product says maybe flaky only for never-flaked failures (a whole-release review); effect: the track record counts never-flaked matches: 1 of 6 (0 of 4 tuning, 1 of 2 held out)

## `flaky.pr_details` (version 1)

A pull-request failure in a workflow that also runs when the PR's title, description or labels change, with no failing test in the step, whose error lines are about the PR (the pull request, a PR title or label, a label to add or missing, a checkbox, checklist or template left unchecked or incomplete), reads PR details: fix the PR, not the code; it still blocks.

- **Card:** [bench/accuracy/flaky](../bench/accuracy/flaky/README.md)
- **Tuned on:** the agent head-to-head's misses (agents/results2.json): 9 such failures in 4 repos, called known flaky or new
- **Checked on:** none apart from the tuning repos: all 231 labelled pull-request failures (47 repos) were scored, the 9 included
- **Bar:** caused by the change's code at most 20% at the upper bound (it changes the advice, it doesn't excuse) (set 2026-10-23)
- **Result:** 1 of 24 matches the change's code (1-20.2%), in 4 repos: at the bar's edge, from a small sample; 21 of the 24 had read known flaky
- **How sure:** early observation (24 matches in 4 repos, one repo gave most)
- **Changed 2026-10-23:** was error lines mentioning a title, label or description anywhere; why: a test assertion about chart labels matched; effect: the words must be about the PR
- **Changed 2026-10-23:** was only jobs whose steps read the PR (triggers.metadata_jobs); why: label checks gated by `if:` and checks reading the PR in a script were missed (2 matches of 24); effect: any job of a workflow run by PR edits, with the error guard
- **Changed 2026-10-23:** was "checkbox", "template" or "PR" alone; any failing step; why: a whole-release review: a template rendering error in a CI workflow run on labels matched; effect: those words need the PR's wording beside them, and a failing test rules it out; still 24 of 24 matched

## `dora.deploy_source` (version 2)

Deployments API to production, else deploy workflows unless a side service, else non-prerelease releases, else release workflows; workflow names matched on deploy, release, publish or push-image minus 47 deny words.

- **Card:** [bench/accuracy/dora](../bench/accuracy/dora/README.md)
- **Tuned on:** the delivery repos of the platform work
- **Checked on:** 25 untuned repos (dora/sources-labels.csv), then 35 more drawn after the rule was fixed (dora/sources-more-labels.csv)
- **Bar:** none set before sampling
- **Result:** 23 of 25, then 30 of 35 held out: 53 of 60 (78-94%); DevLake default 9 of 60, configured 22 of 60; workflow recall 60% on the held-out repos
- **How sure:** validated
- **Changed 2026-10-21:** was display name checked against the deny list; why: a file named deploy.yml titled 'Check and Publish' hit the deny word 'check'; effect: a file named only deploy, release or publish ships whatever its display name; 22 to 23 of 25

## `dora.fix_chain` (version 2)

A revert links to the pull request it undoes and the deployment that shipped it; never shipped when no deployment ran it.

- **Card:** [bench/accuracy/dora](../bench/accuracy/dora/README.md)
- **Tuned on:** 18 reverts in 23 repos (the same set it is scored on)
- **Checked on:** 99 reverts in 16 more repos chosen for the most reverts (dora/linkage-more-results.json)
- **Bar:** none set before sampling
- **Result:** right on 87 of 89 links checked with the compare API across both samples (73 of 73 held out); time order wrong on 71 of 89
- **How sure:** validated
- **Changed 2026-10-22:** was every revert counted as a failed deployment; why: 11 of 18 undid a change that never shipped; effect: never-shipped reverts are no failed deployment

## `community.regular_responders` (version 2)

People who answered 10+ others' issues or first-reviewed 2+ others' pull requests in a year, or who labelled, assigned, closed or marked as duplicate someone else's issue (only triage rights allow it), count as the project's responders.

- **Card:** [bench/accuracy/community](../bench/accuracy/community/README.md)
- **Tuned on:** 400 comments from 85 repos (community/labels-main.csv)
- **Checked on:** 400 comments from 86 other repos (labels-validation.csv); for version 2 the same set, used once for the decision
- **Bar:** none set before sampling
- **Result:** held out: catches 57% of project answers weighted (47% before), 4 more answers; holds on either labeller's labels
- **How sure:** validated
- **Changed 2026-10-23:** was answers and first reviews only; why: triage acts mark people acting for the project; on the labelled comments the rule missed, they found 8 project answers among 11; effect: held out: 4 more project answers (47% to 57% weighted); on Claude's labels 45% to 53%, on Gemini's 32% to 38%
- **Tried and dropped:** also counting people with 3+ merged pull requests; why: caught 7 more points of project answers on the first set, but 9 of the 15 comments it added were drive-bys or other users' replies

## `community.first_response_km` (version 2)

Time to first project response with items still waiting kept in (Kaplan-Meier); an item closed unanswered is censored at closing.

- **Card:** [bench/accuracy/community](../bench/accuracy/community/README.md)
- **Tuned on:** none
- **Checked on:** 86,733 outside issues in 2,370 repos
- **Bar:** none
- **Result:** median counting waiting issues is 5.2 times the answered-only one
- **How sure:** validated
- **Changed 2026-10-22:** was closed-unanswered items treated as still waiting; why: they stopped being at risk when they closed; effect: censored at closing

## `uncertainty.digest` (version 2)

Benjamini-Hochberg at q = 0.1 over every check in a scan, on p-values calibrated against the repo's past 8 weeks (typical swing 1.5 for times, each past week capped at a four-sigma swing); pickup and opened-to-merged time are also checked over 14 days, calibrated on past windows that don't overlap them.

- **Card:** [bench/accuracy/uncertainty](../bench/accuracy/uncertainty/README.md)
- **Tuned on:** swing chosen on half of 20 public repos; the cap on halves of 29
- **Checked on:** the other halves; the replay on 26 repos
- **Bar:** at most 10% of shuffled scans flag anything (set 2026-10-21)
- **Result:** 7.5% (met); 10x slowdowns caught 25% in their first week, 35% in their second
- **How sure:** validated
- **Changed 2026-10-24:** was weekly checks only; why: in a slowdown's second week the weekly check's baseline holds the first slow week, so 10x slowdowns were caught in 15% of scans; effect: on the same replay, second-week catches of 10x slowdowns 15% to 35%, first-week 31% to 25%, false alarms 7.4% to 7.5%; CUSUM charts tried and dropped (no gain)

## `uncertainty.shrinkage` (version 1)

A small repo's first-try share pulled toward its peer group's beta-binomial prior (maximum likelihood, groups of 20+).

- **Card:** [bench/accuracy/uncertainty](../bench/accuracy/uncertainty/README.md)
- **Tuned on:** half of 6,623 repos fit the priors
- **Checked on:** 1,923 repos of the other half
- **Bar:** lower out-of-sample error under 30 pushes; ranges cover 90-97% (set 2026-10-21)
- **Result:** 29% less squared error at 3 pushes; 94.6% coverage (met)
- **How sure:** validated

## `ai.matched` (version 1)

Agents' and AI-marked PRs compared within the same repo, month and size band (Mantel-Haenszel with Sato's variance).

- **Card:** [bench/accuracy/ai](../bench/accuracy/ai/README.md)
- **Tuned on:** none
- **Checked on:** 1.46 million PRs in 21,804 repos
- **Bar:** shuffled AI labels' range includes zero (set 2026-10-21)
- **Result:** met (-1.2 to +1.5 points)
- **How sure:** validated

## `dora.incident_link` (version 1)

An incident is linked to the last production deployment (or release) finished before it was reported (DevLake's rule).

- **Card:** [bench/accuracy/dora](../bench/accuracy/dora/README.md)
- **Tuned on:** none (DevLake's published rule)
- **Checked on:** 60 regression and incident issues naming a version, 39 crawl repos; 15 named the release that broke
- **Bar:** none set before sampling: a first measurement of a rule we adopted from DevLake (set 2026-10-23)
- **Result:** right 6 of 15 (40%, 20-64%); the version the report names: 10 of 15, held out 4 of 9 against 2 of 9 (p 0.5): kept, with the caveat in docs/dora-guide.md
- **How sure:** early observation (15 reports named the release that broke)

## `ai.adoption` (version 1)

Throughput, people's merged PRs, review wait and merge rate after a repo starts taking agents' PRs, by staggered difference-in-differences against repos that haven't started (preregistration.md).

- **Card:** [bench/accuracy/ai](../bench/accuracy/ai/README.md)
- **Tuned on:** none (pre-registered 2026-10-23)
- **Checked on:** 1,764 adopting and 16,269 comparison repos
- **Bar:** leads and the 3-month-earlier negative control include zero (set 2026-10-23)
- **Result:** merge rate: no measurable change (-2.7 to +0.7 points); throughput and review wait: not credible (adopters already growing)
- **How sure:** validated

## `ai.detection` (version 2)

A PR is an agent's (agent account or agent branch) or AI-assisted (AI trailer in its last 5 commits or its description, an agent task link in the description, or an AI label in any spelling).

- **Card:** [bench/accuracy/ai](../bench/accuracy/ai/README.md)
- **Tuned on:** odd ids of 400 labelled PRs (v2 additions: Jules links, label spellings)
- **Checked on:** even ids (208 decided)
- **Bar:** precision of 95% or more; recall reported as a floor (set 2026-10-23)
- **Result:** met: 191 of 194 (95.5-99.5%); recall 78.8% weighted, 66.3% on the held-out half
- **How sure:** validated
- **Changed 2026-10-23:** was AI trailers in the last 5 commits, labels matched exactly, agent account or branch; why: 5 of 23 missed PRs named the tool in their description; label spellings and Jules task links missed in the tune half; effect: recall 75.0% to 78.8% weighted (63.9% to 66.3% held out); precision 185 of 187 to 191 of 194
