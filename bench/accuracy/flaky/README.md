# Flaky CI: what the detector calls a flake, and what it hides

StackVitals calls a CI job flaky when the same code both failed and passed: a later attempt of the same run passed
(retry), or another run on the same files got a different result (flip). It leaves out attempts where most of the run
failed at once (an outage) and jobs that failed only because another job did. This card checks those calls against
labelled public CI failures, scores the plain "passed on retry" rule most vendors use beside them, and measures the
number nobody publishes: how often a failure called "known flaky" was really caused by the change under review.

## The sample (`sample.py`)

Public repos from the crawl's CI records with 20 or more pushes and re-runs on at least 5% of runs, eight per language
group (JavaScript and TypeScript, Python, Go, Rust, JVM, C and C++), seeded; each read the way `stackvitals ci report`
reads it (14 days of runs and jobs) and analysed by the same detector. From each repo, at most 5 events the detector
flagged, 3 retries only the plain rule flags, 3 failures on pull requests of jobs that had flaked, and 3 failures of
jobs that never flaked: **263 failed jobs from 51 repos**. Each kept its log (the lines leading to the first error and
the log's end), the failing step, the files the change touched and what happened when the job ran again on the same
code.

Labels follow [codebook.md](codebook.md): the cause (a test's own non-determinism, a race in the product,
infrastructure, network, a dependency, a timeout, the CI setup, the change itself, or unclear), whether the change
under review caused it, and whether the job failed for its own reason. Two model families labelled every item blind
(Claude, then Gemini 3.5 Flash-Lite), and their disagreements were adjudicated blind; see [Labels](#labels-two-model-families)
for how much the labeller moves each number. No person has audited the labels.

A first labelling round was thrown away: the log excerpts had lost the error line for 130 of 263 items (the cut kept
the start of the lines before the error). The excerpt was fixed, every log fetched again and every item relabelled.

## Results

| | Result | Bar |
|---|---|---|
| **Event precision:** flagged flakes that were neither caused by the change nor a side effect of another job | **97.2%** (92.2-99.1%), 108 events (of the 112 flagged jobs, 4 the labels couldn't decide) | at least 85% at the lower bound: met |
| The plain "passed on retry" rule (Trunk, Buildkite, CircleCI) on the same repos | 96.9% (94.0-98.3%) | doesn't beat the detector: met for the one rival scored, but it's a tie. Ours is 0.3 points higher (-4.0 to +4.0, not significant). The plain rule sees only retries: our retry events (95 of 95 right) plus the retries we leave out (54% right). The detector adds same-commit flips the plain rule can't see, which are right 77% of the time |
| The retries only the plain rule flags (outages, jobs failing because another did) | 54% right (29-77%), 13 | |
| Flakes that were real races in the product | 1 of 108 | |
| **Misses:** failures of jobs that never flaked that were intermittent and not caused by the change | 17% (11-26%), 98 | |

What the flagged flakes were: network 35, a test's own non-determinism 30, unclear 21, infrastructure 10, a
dependency 7, the CI setup 7, a product race 1, the change 1.

By language group (the sample was drawn four or more repos per group):

| Group | Flagged flakes that were real | Misses |
|---|---|---|
| C and C++ | 9 of 9 | 25% of 16 |
| Go | 16 of 16 | 36% of 14 |
| JavaScript and TypeScript | 16 of 16 | 0% of 10 |
| JVM | 20 of 20 | 25% of 8 |
| Python | 16 of 16 | 7% of 15 |
| Rust | **12 of 15 (80%, 55-93%)** | 21% of 19 |
| Other | 16 of 16 | 6% of 16 |

Rust is the one group where flagged flakes were not all real.

The detector joins two signals rivals use alone, and each was scored on its own (adjudicated labels; Gemini's in
brackets):

| Signal | Rivals that use it | Flagged flakes that were real |
|---|---|---|
| A later attempt of the same run passed | Trunk, Buildkite, CircleCI | 95 of 95, 100% (96-100%) [82%] |
| The same commit passed and failed in different runs | BuildPulse (same tree), Kubernetes (same commit) | 10 of 13, 77% (50-92%) [69%] |

The second signal is the weaker one. Its misses as sampled:
- a pull-request title check;
- two builds that asked for an LLVM release not yet published, which passed on the same commit a day later once it
  was. Outside state changed; it wasn't a flake.

All three were in workflows that also run when a pull request's text or labels change. A rule that left out
pull-request flips in such workflows looked perfect on these 13 (all kept flips real), but on the held-out read
(`heldout.py`, below) all 17 flips in such workflows were real flakes, as often as elsewhere (18 of 23). It threw away
real flakes, so it was dropped; only jobs whose workflow file visibly reads the pull request are left out, as before.

A limit on the time between the two runs, or a check for "not found / not published" errors, is the next
improvement to measure. TestGrid's flip rate with its three-failure cut-off needs longer history than a 14-day read
and is not scored.

## Masking: "known flaky" failures the change caused (`masking.py`)

Until 2026-10-23, a pull request whose job failed was told "known flaky: safe to re-run", and the StackVitals verdict
check passed, when that job had flaked before; the stricter rule below replaced it on 2026-10-28. Judged with the
history up to each failure only (no hindsight), 36 pull-request failures in 9 repos hit a job that had flaked before; each was labelled (15 from the sample above, 21 more drawn for this check).

| Rule | Called safe to re-run | Caused by the change |
|---|---|---|
| Before: any earlier flake | 34 | **15 (44%, 29-61%)** |
| Now: 3 or more flakes in the window, one of them in the step that failed this time | 7 (5 with a clear label) | **0 of 5** (0-43%) |

All 7 safe calls are one job in one repo, so they are one job's record rather than 7 independent cases, and the range
is kinder than the evidence.

What the caution costs: of the 19 failures the change didn't cause, the new rule calls 5 safe to re-run (26%, 12-49%);
the other 14 cost a look. On Gemini's labels the picture changes: the new rule's safe calls were caused by the change
in 5 of 7 (see [Labels](#labels-two-model-families)).

The first rule passed real breakages through the verdict check: a job that had flaked once in its build step was
called safe to re-run when a pull request broke its tests. The 15 came from 5 repos, so the rate is uncertain beyond
its range, but every one had only one or two earlier flakes, and 9 failed in a different step from those flakes.
StackVitals now calls a job failure known flaky only with three or more flakes in the window, one of them in the step
that failed now; anything less reads "flaked before: check whether this change caused it", and the verdict check waits
for a person. All 15 masked failures became "flaked before", along with 14 real flakes,
which now cost a look instead of a re-run.

**As a decision:** the verdict check passed 7 of these 36 failures and blocked 29. History alone (`natural.py`) can't
judge any of the 7 it passed, and of the 29 it blocked, it clears 2. Seven of the 29 blocked had the same error in the
same step on the default branch just before; StackVitals now says so ("already failing on main", below), but still
blocks.

**The bar (masking at most 5% at the upper bound) failed on held-out data.** The 0 of 5 above was one job's record. On
the wider read (`heldout.py`, below), the rule called 108 failures in 48 jobs and 15 repos safe to re-run (at most 3
per job sampled), and 13 of the 81 clearly labelled were the change's own failure (16%, 10-26%; Claude's labels 12 of
78, Gemini's 23 of 96). The caused ones were compile errors, a licence check and test assertions in jobs that do
flake in that step. Comparing the error with the job's past flakes didn't separate them (`safe_check.py`: the change's
own failure 4 of 22 times with the same error, 9 of 54 with a different one), and neither did more flakes (3 to 33).

So "known flaky" no longer passes the verdict check. It still says "likely a flake, re-run it", and the opt-in re-run
still re-runs it: a flake then passes, while the change's own failure (deterministic in every caused case here) fails
again and stays blocked. Test-level verdicts (from uploaded test reports) were not part of this check.

## A stricter "known flaky", pre-registered 2026-10-28 (`safe_rule.py`)

Written on 2026-10-28, before any failure of the fresh read below was pooled, labelled or scored.

**Where it comes from.** The held-out read above can't test a rule written after looking at it, so it now counts as
tuning data, with `masking.py`'s 36 failures. On those, the decision-time signals compared for the 108 held-out calls
(adjudicated labels: caused / not caused / unclear):

| Signal at decision time | Signal present | Signal absent |
|---|---|---|
| The failing step's log shows an outside service, the runner or a wait failing, and no test failed there | 0 / 31 / 3 (6 repos, 26 items from lxc/incus) | 13 / 37 / 24 |
| An error line names a file this pull request changed (PR files, one request) | 8 / 0 / 2 | 5 / 68 / 25 |
| Same error as the job's two newest flakes (`safe_check.py`) | 4 / 18 / 19 | 9 / 50 / 8 |
| The pull request changed CI files / dependency files | 3 / 1 / 1; 1 / 3 / 1 | 10 / 67 / 26; 12 / 65 / 26 |
| The failing step's name is a test step | 7 / 12 / 20 | 6 / 56 / 7 |
| The default branch failed in that step in the 3 days before | 7 / 41 / 15 | 6 / 27 / 12 |
| This branch's earlier runs failed in the same step | 5 / 18 / 7 | 8 / 50 / 20 |

The number of flakes (3 to 33), their recency and the job's flake rate didn't separate them either. On `masking.py`'s
36, the log signs matched 9 failures of jobs with any earlier flake (0 caused, 3 repos; none had 3+ flakes in the
step), and an error naming a changed file matched 7 (6 caused).

**The rule.** A pull request's job failure is "known flaky" only when all three hold:
1. history: 3 or more flakes in the 30-day window, one in the step that failed now (unchanged);
2. the log: the failing step's part, up to its first error, shows an outside service or the runner failing
   (`OUTSIDE`) or how flaky checks fail (`FLAKY_LOOK`: a wait or deadline running out, a live service in a test),
   and no test failed there (`TEST_FAILED`);
3. the change: no line in that part names a file the pull request changed (by file name, or a stem of 8+
   characters as a word; names with a stem under 5 characters never count).

Otherwise a job that flaked before reads "flaked before: look first", or "maybe yours" when that part names a
file the pull request changed. A test from an uploaded report needs the same: 3+ flakes, a sign in its message, and
no changed file named in its id or message.

**The check.** The fresh read: 36 public repos the crawl ranks next by re-run share, none read before by this card,
the masking check or the replay (`wide.py` excluding all three), up to 200 requests each. Every pull-request failure
that rule 1 calls known flaky (history before it only), at most 3 per job (seed 7), gets its log and the pull
request's files, and is labelled by the codebook, blind to the rule: Claude, then Gemini 3.5 Flash-Lite, disagreements
adjudicated blind. Measured on the adjudicated labels: the share of the rule's calls the change caused, with its 95%
Wilson range, and by repo; how many of rule 1's calls the rule keeps (coverage); and "maybe yours" calls the change
caused.

**The bar** (registry `flaky.known_flaky`, set 2026-10-21): caused by the change at most 5% at the upper bound. With
none caused, that needs 73 clearly labelled calls. If the fresh read can't show it, nothing reads "safe": the calls
the rule keeps say "looks like a flake (the evidence): check the error, then re-run", and the verdict check keeps
waiting for a green re-run.

**What the fresh read showed (scored 2026-10-28, `safe-rule-results.json`).** 36 repos read; the history rule called
197 pull-request failures known flaky, in 19 jobs and 9 repos; at most 3 per job gave 44 to label (Claude, Gemini,
blind adjudication; Claude's and Gemini's labels agreed on "caused by the change" 57% of the time, kappa 0.31, and the
adjudicator, a Claude model, sided with Claude's label on all 19 disputes).

| What the rule made of the 44 | Calls | Caused by the change (adjudicated) | Gemini's labels |
|---|---|---|---|
| History alone (the rule before) | 44 | 5 of 22 clear (23%, 10-43%) | 6 of 33 |
| **Known flaky (all three hold)** | **4** (9%; 3 jobs, 2 repos) | **0 of 4 (0-49%)** | 0 of 4 |
| Maybe yours (a changed file named) | 7 | 4 of 5 clear | 3 of 6 |
| Flaked before (no flake's sign) | 33 | 1 of 13 clear | 3 of 23 |

**The bar is not met.** The stricter rule called no change's failure a flake, here or on the data it was written
from (0 of 31 and 0 of 8), but 4 fresh calls can't show 5% or less: the upper bound is 49%, and 73 clear calls with
none caused would be needed. It also keeps few calls: 9% of the history rule's fresh calls, 31% on the first held-out
read. So nothing reads "safe to re-run":

- the calls the rule keeps read **"Likely flaky"** with their evidence ("flaked 4 times in 40 runs in this step, and
  the log shows a flake's sign ("ENOTFOUND"): looks like a flake, check the error, then re-run it; the error names
  none of the 6 files this pull request changed");
- the rest of what history called known flaky reads "flaked before: check whether this change caused it", or "maybe
  yours" when the failing step names a file the pull request changed;
- the verdict check never passes a red build, a likely flake's included: it waits for a green re-run. Quarantine and
  `rerun-flaky` stay opt-in; `rerun-flaky` re-runs an attempt only when every failure in it is a likely flake or an
  outside failure, so a failure the change caused fails again and stays blocked.

"Maybe yours" is the strong signal here: 14 of 15 clear cases on the tuning data and 4 of 5 fresh were the change's.
GitLab job logs aren't read, so there a job that flaked before is never called a likely flake. Logs are the bench's
excerpts (the lines up to the first error and the log's end) and the pull requests' files are as of the read, not as
of each failure.

## Already failing on main (`already.py`)

A pull request's job that fails in a step the default branch failed in during the 3 days before may not be the change.
On the labelled pull-request failures (gatekeeper jobs left out, since StackVitals never shows them):

| Rule | Failures it matches | Caused by the change (adjudicated) |
|---|---|---|
| Same step on the default branch just before | 20 in 10 repos | **4 of 20** (re-run 2026-10-23 on the grown history; was 23 in 12) |
| Same step and the same error | 12 in 5 repos | **0 of 12** (0-24%); Claude's and Gemini's labels agree |

- **The step alone isn't enough:** in the 4 caused cases the change brought its own error into a step that was
  already failing.
- **The same error** means most of this failure's error lines (without times, ids, paths and numbers) appear in the
  default branch's failing step too. The cut (2 of every 3 lines) was set on these same failures: the caused ones
  shared a third or less, the rest two thirds or more. Summary lines every failing run prints ("Tests: 1 failed",
  "npm ERR! Failed at the ... test script", make's "***") never count as shared: a whole-release review showed two
  different test failures matching on them alone. On these items that changed nothing.
- **What StackVitals says now:** "the same error as on the default branch 5 hours before this (run …), in this step:
  not caused by this change". With a different error it keeps its verdict and adds that the default branch failed in
  this step too. It reads the default branch's log once (one request).
- **It still blocks the verdict check.** Letting it pass needs the masking bar (at most 5% at the upper bound), and
  12 cases can't show that.
- **Tests from uploaded reports:** the same test failing with the same fingerprint on the default branch reads the same
  way. That isn't measured here, since the labels are per job.

## Held-out check (`wide.py`, `heldout.py`)

Every rule above was written or tuned on this card's sample, so a second read took 45 other public repos, the flakiest in
the crawl by re-run share, for up to 30 days each (complete days, newest first, 300 requests per repo). Of 1,961
pull-request failures in 30 of them, a seeded sample was labelled the same way (Claude, Gemini, blind adjudication; the
adjudicator sided with Claude in 53 of 56 disputes): 210 items in 19 repos.

| Rule | Held-out result (adjudicated) | On the sample it was tuned on |
|---|---|---|
| Known flaky (3+ flakes, one in the failing step) | 13 of 81 the change's (16%, 10-26%) | 0 of 5 (one repo) |
| Flips left out in pull-request-edit workflows | all 17 were real flakes | 3 misses removed |
| Already failing on main, same step | 5 of 51 the change's | 4 of 20 |
| Already failing on main, same error | 1 of 6 (only 11 of 60 matched) | 0 of 12 |
| Outside failures in the log | 0 of 38 the change's (0-9%) | 0 of 35 (15 repos) |
| Maybe flaky (2 of 150 never-flaked failures matched) | 1 of 2 | 0 of 4 never-flaked |

What changed because of it: known flakes no longer pass the verdict check, and the flip rule was dropped. The outside
signatures held. "Already failing" and "maybe flaky" keep their wording but never pass the check; their held-out
counts are too small to say more.

**Counted by repo:** items cluster by repo, and one repo dominates two rows. lxc/incus gave 43 of the 81
known-flaky calls and 35 of the 38 outside matches. Without it, known flaky was the change's 13 of 38 times (about 1 in
3, 21-50%), so the comment and the MCP answer say to check the error before re-running, and the track record names both
figures. The outside row rests on 3 repos here; with the tuning sample's 15 repos (0 of 35, at most 20% counting each
repo once), it still holds. Each repo counted once, known flaky is 4-45% (`heldout-results.json`, `by_repo`).

## Outside failures in the log

When a job fails for the first time, history can't call it a flake yet, and StackVitals used to say "no earlier flakes:
likely from this change". The agent head-to-head (`bench/accuracy/agents/`) showed what that costs: 8 of its 20 items
were flakes called that way. StackVitals now reads the failed jobs' logs (one request each, at most five a run) and
looks in the failing step's part, up to its first error, for an outside service or the runner failing: name lookups and
connection resets, a registry's 502 or 503, "too many requests", a cache's "ServerBusy", a full disk, a runner shutting
down. Warnings don't count, and a step where tests failed never does ("FAILED", "AssertionError", "3 failed"), so a test
the change broke can't be excused by what it logged. Such a failure reads "outside failure: likely not this change;
re-run it". It still blocks the verdict check, and the opt-in re-run may re-run it.

On the 284 labelled logs (this card's 263 and masking's 21, `outside.py`), the signatures matched 35, and **none of
the 35 was caused by the change** (90-100%); they found 35 of the 78 network and infrastructure failures, and 6 of the
17 intermittent failures the detector missed. A later fix added curl's connect and timeout errors and a few network
messages (3 more matches, none caused); out of memory was tried and left out, since its one match was the change's.
Held out, they matched 41 and none of the 38 clearly labelled was the change (0-9%). A first version searched more of the log and matched 36, also none
caused by the change, but the review showed how a broken test's own "Connection refused" could slip through; the
narrower search gives up 4 matches for that safety. The list was written from common runner and network errors and checked
on these labels; "failed to download and build", a dependency's build failing, was taken out after one such log was
caused by the change.

**Fresh check, no labeller** (`outside_fresh.py`, `outside-fresh-results.json`):
- **The sample:** 633 failed jobs from the same 51 repos' reads that were never labelled or used to write the
  signatures. That was every failure re-run on the same code, plus 149 drawn from those never re-run. Each log was
  read once; only the verdict is kept.
- **What matched:** the signatures matched 36.
- **Re-runs:** of the 30 matches re-run on the same code, 21 passed. 8 of the 9 that failed again also failed in the
  same step on the default branch at the time, so the outage lasted; it wasn't the change.
- **History check:** judged by the same rules as the section below, 5 of the 8 matches it decides were not caused
  by the change (63%, 31-86%). The 3 "caused" are one repo's Docker Hub rate limit (`toomanyrequests`), which lasted
  across re-runs while one earlier default-branch run had passed. The history check can't tell a lasting rate limit
  from a breaking change. (Before the corrections below it decided 13, 10 not caused.)
- **A guard that was tried and dropped:** withholding "outside failure" when the pull request edits CI files. On
  these matches it would have caught none of the change-caused cases and taken the excuse from 4 real outages.
- **What it misses:** the signatures catch few flakes. Of 255 failures a re-run proved flaky, they matched 21 (8%):
  most flakes are tests, not outside services.

## Maybe flaky: first failures that look like flakes (`maybe.py`)

A job or test that never flaked has no history to go on, so StackVitals used to say "likely from this change". The
agent head-to-head showed that misreading flaky tests whose logs look like real failures. Now, when the failing step's
part of the log (or a test's message) shows how flaky checks fail, the failure reads "maybe flaky: re-run it once to
tell; if it fails again, look at this change". The signs: a wait or deadline running out ("Timeout of 2000ms exceeded",
"deadline exceeded", "Expected condition failed: waiting for"), a benchmark gate, or a live service inside a test
("Retries 20 exhausted", "returned HTTP 500", "rate limit").

| On the labelled logs | Matched | Caused by the change |
|---|---|---|
| All 284 (outside failures left out) | 24 | **0** (22 not, 2 unclear; 0-15%) |
| Failures of jobs that had never flaked | 6 | **0** (4 not, 2 unclear) |

Among all 116 never-flaked failures, the change caused 58 of the 98 clearly labelled. The signs were written after
reading these logs and the agent card's misses, so this is how well they fit, not a held-out test. A change can make
a check slow or hang, so "maybe flaky" never passes the verdict check and is never re-run automatically: it only asks
for one re-run before anyone digs into the change. A plain wrong count or value, even from a timing-sensitive test,
still reads "new". Held out, the signs matched only 2 of 150 sampled never-flaked failures (one the change's), so they
help rarely.

## PR details: checks on the pull request itself (`pr_details.py`)

Some jobs check the pull request, not the code: a changelog label, a checkbox in the description, a title prefix. They
fail until someone edits the PR, then pass on the same code, so the history counted them as flakes: DataDog's
"Ensure labels / changelog" read "known flaky" (9 flakes in 21 runs), which advised a re-run that fails again. The
agent head-to-head (`../agents/`) found 9 of them among its 100 failures.

**Rule:** a pull-request failure in a workflow that also runs when the PR's title, description or labels change (read
from the workflow file, as `triggers.py` already did to keep those flips out of flake counts), whose error lines are about
the PR (the pull request, a checkbox, checklist or template, a label to add or missing), reads "PR details: fix the PR's
title, description or labels, not the code". It still blocks the verdict check, and is checked before history.

**Result:** on all 231 labelled pull-request failures in 47 repos (16 with such workflows), it matched 24 in 4 repos;
1 was labelled the change's code (1-20%, at the 20% bar's edge from a small sample): a PR-title check, which arguably
can't be. 21 of the 24 had read "known flaky". A first version that needed a step reading the PR missed 22 of the 24
(label checks gated by `if:`, and a description check in a script); a test assertion about "labels" matched the first
error-word list, so the words must be about the PR.

## Flake kinds (`kinds.py`)

A failure read as flaky also says what kind it looks like, from the failing step's log or a test's message:
infrastructure (the runner, a cache or artifact store, a service started on the runner itself), network (a registry, a
download, an outside API), concurrency (a data race, a deadlock) or timing (a wait or deadline running out).

| Kind | Flakes it names | Agrees with the label's cause |
|---|---|---|
| Infrastructure | 17 | 17 |
| Network | 26 | 25 (one labelled infrastructure) |
| Timing | 8 | 8 (the test's own waits) |
| Concurrency | 0 | none in the sample |

51 of the 181 flakes get a kind; the rest show no sign either way and get none. The first version agreed less often
(network 19 of 29, timing 8 of 14): artifact-store failures and services refusing connections on the runner itself
read as network, and Docker pulls running out of time read as timing. The signs were reworded on these same labels,
so the table shows the fit. Held out, infrastructure agreed 2 of 2 and timing 6 of 9 (the test's own waits), but
network only 7 of 40: 32 were one repo whose apt mirror answered 503 so a package couldn't be found, which the labels
call "dependency" and the codebook would call network (it names a failed download). A failure likely from the change
never gets a kind.

## Labels: two model families

Both labellers read the same codebook and the same evidence, blind to StackVitals' verdict and to each other.

| Field | Claude and Gemini agree | Kappa |
|---|---|---|
| Caused by the change | 69% | 0.43 |
| Cause | 56% | 0.47 |
| The job's own failure | 98% | 0.66 |
| Masking items: caused by the change | 71% | 0.51 |

- **Adjudication.** Every disagreement went to a third reading that saw the two labels as A and B, never whose they
  were (`adjudication-flaky.csv`, `adjudication-masking.csv`, with reasons). It sided with Claude's label in 78 of 81
  "caused by the change" disputes, 104 of 116 cause disputes and 6 of 6 masking disputes.
- **Who adjudicated.** That third reading was Claude's. Gemini, adjudicating a stratified sample of the same disputes,
  agreed with it on 15 of 40, and each adjudicator mostly sided with its own family. So adjudication doesn't settle
  who is right here.
- **What the adjudicators wrote:** Gemini tends to call a failure caused by the change when nothing was re-run, even
  when the failure sits in code the change didn't touch. Claude falls back to "unclear" when a log has no message.
- **Each number on each labeller's labels** (`../label-sensitivity.json`):

  | | Claude's labels | Gemini's labels | Adjudicated |
  |---|---|---|---|
  | Event precision | 97.2% | 80.2% | 97.2% |
  | The plain retry rule | 96.9% | 79.0% | 96.9% |
  | Misses | 16.8% | 25.4% | 17.3% |
  | Masking, old rule | 44% | 60% | 44% |
  | Masking, rule now | 0 of 5 | 5 of 7 | 0 of 5 |

  Under both labellers our rule and the plain retry rule are within a point of each other. How high both are, and whether
  the new masking rule is safe, depends on whose labels you trust. GitHub's own history settles most of it (next
  section).
- **A clearer codebook** (version 2, from the adjudicators' notes) was tested on a random 60 items relabelled by both.
  It made agreement worse:

  | On the same 60 items | Codebook 1 | Codebook 2 |
  |---|---|---|
  | Caused by the change | 73% (kappa 0.49) | 52% (kappa 0.22) |
  | Cause | 67% (0.60) | 58% (0.51) |

  Each model stayed close to its own first labels (78-83%), but the new rules moved the two apart. For this card,
  labels from two models can't settle the key field; the history check below can.

## History check: no labeller at all (`natural.py`)

GitHub already records the evidence a person would look for. A failure is judged from the history the sample
collected, with no requests and no model:

- **Not caused by the change** when a run on the identical code passed, and the same job flaked in the same step on
  other changes (other pull requests or branches).
- **Caused by the change** when it failed again on the identical code while the same job passed on the default
  branch every time in the three days before it. Only earlier runs count (once the change merges, the default branch
  holds it too), and never the failure's own run.
- Anything else stays undetermined.

| | Decided by history | Not caused | Caused |
|---|---|---|---|
| All 263 labelled failures | 48 | 44 | 4 |
| Flagged flakes | 42 of 112 | 42 | 0 |
| Masking check's failures | 2 of 36 | 2 | 0 |

**Two corrections:**
- The default branch is now the one GitHub reports. The guess (the branch most pushes went to) picked a busy feature
  branch in 5 of the 56 repos and tied in 2.
- "The same job failed in the same step on the default branch just before" no longer counts as not caused. It decided
  28 failures, and the adjudicated labels say 2 of them were the change: a different error in a step that was already
  failing. With it, history decided 82 failures (76 after the branch fix); without it, 48.

**Flagged flakes:** history confirms 42 of the 112 as not the change. It can't refute a flagged flake, because every
one passed on identical code, which is what flagged it. So this is a floor (42 of 112 confirmed), not a precision.

**Each labeller against history:**

| | Agrees | Said unclear | Wrong |
|---|---|---|---|
| Claude | 47 of 48 | 1 | 0 |
| Gemini | 39 of 48 | 0 | 9 |
| Adjudicated | 47 of 48 | 1 | 0 |

- **The base rate matters:** history mostly decides "not caused" cases, so a labeller that always said "not caused"
  would score 92%.
- **On their definite answers:** Claude's labels are right on all 47 (92-100%), Gemini's on 81% (68-90%, below the
  baseline).
- **The gap:** Gemini blames the change for failures that also flaked on other changes.
- So the adjudicated labels' lean toward Claude matches what GitHub recorded, not just which model adjudicated.

**What history can't settle:** the new masking rule's 7 "safe to re-run" calls. They were never re-run, and the
default branch was passing around them, so the masking bar stays unproven. Longer history or more repos are the next
step. Forked re-runs were considered and dropped, to keep everything on public repos' own records.

## What it can't show

- No person has audited the labels, and the two model families disagree enough to move the headline (above). The
  history check decides 82 of the 263 failures without any labeller, and sides with Claude's labels on those.
- The outside-failure signatures were written on the labelled logs. On fresh failures, 10 of the 13 matches history
  decides were not the change; the other 3 are one repo's lasting registry rate limit.
- Each repo was read for 14 days; jobs with rarer flakes look like "never flaked", which is part of the miss rate.
- A re-run that passed is the strongest evidence a labeller has; failures nobody re-ran lean on the log alone, and
  57 of 263 stayed unclear.
- Status precision (whether a job called flaky is flaky in general) needs repeated runs of pinned commits; it is not
  measured yet.

## Reproduce

```
# CI records: the crawl's daily ci-YYYY-MM-DD.ndjson.gz files (public at launch)
GH_TOKEN=... python bench/accuracy/flaky/sample.py --records <ci folder> --home <work folder> --per-group 8
GH_TOKEN=... python bench/accuracy/flaky/sample.py --records <ci folder> --home <work folder> --refresh-logs
python bench/accuracy/flaky/views.py --home <work folder> --parts 10     # blind views for labellers
python bench/accuracy/flaky/score.py --home <work folder> --log <sampler output> --second <second labels>
python bench/accuracy/flaky/masking.py pool --home <work folder>
GH_TOKEN=... python bench/accuracy/flaky/masking.py fetch --home <work folder>
python bench/accuracy/flaky/masking.py score --home <work folder>
python bench/accuracy/flaky/outside.py --home <work folder>
# The stricter known-flaky rule on a fresh read (wide.py excluding the earlier work folders, --repos 36 --budget 200)
python bench/accuracy/flaky/safe_rule.py pool --home <fresh work>
GH_TOKEN=... python bench/accuracy/flaky/safe_rule.py fetch --home <fresh work>
python bench/accuracy/labeller.py fresh --work <fresh work> --run    # then adjudicate.py fresh --packets / --apply
python bench/accuracy/flaky/safe_rule.py score --home <fresh work> --final <final/fresh.jsonl> --tune-home <held-out work> \
    --tune-final <final/heldout.jsonl> --masking-home <work folder>
# Second labeller, blind adjudication, final labels, and every number on each labeller's labels
python bench/accuracy/labeller.py flaky --work <work folder> --run      # Gemini; a dry run without --run
python bench/accuracy/labeller.py flaky --work <work folder> --compare
python bench/accuracy/adjudicate.py flaky --work <work folder> --packets  # then --apply
python bench/accuracy/finalise.py flaky --work <work folder's parent>
python bench/accuracy/sensitivity.py --work <work folder's parent>
python bench/accuracy/flaky/natural.py --home <work folder> --final <final work folder>   # the history check
GH_TOKEN=... python bench/accuracy/flaky/outside_fresh.py --home <work folder>          # signatures on fresh failures
python bench/accuracy/flaky/pr_details.py --flaky-home <work folder> --flaky-final <final labels folder> \
    --wide <held-out work> --wide-final <final/heldout.jsonl> --cache <workflow files cache>   # reads workflow files
```

Results: `card.json`, `masking-results.json`, `outside-results.json`, `safe-rule-results.json`; labels and links (no log text) in `items.csv`
(adjudicated) and `masking-labels.csv`; Gemini's labels in `labels-gemini-flaky.csv`, `labels-gemini-masking.csv` and `labels-gemini-fresh.csv`;
agreement in `agreement-gemini-*.json`; every ruling in `adjudication-*.csv`.
