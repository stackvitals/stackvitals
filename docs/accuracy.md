# How accurate StackVitals is

The rules behind StackVitals' verdicts and headline numbers were each checked against public data and, where a
judgement was needed, against labelled examples. Each card in `bench/accuracy/` holds the method, the
sample, the labels (links only), the competing rules scored beside ours, and what the check can't show. This
page is built from those cards' result files by `bench/accuracy/summary.py`; the exact statistical settings are in
[methods.md](methods.md).

**How the labels were made.**
- Two model families labelled each sample blind, from the same codebook and evidence: Claude, then Gemini 3.5
  Flash-Lite.
- Each disagreement was settled by a third reading that saw the two labels without knowing whose they were.
- That third reading was Claude's. Gemini, adjudicating a sample of the same disputes, agreed with it on 15 of 40.
- Each adjudicator mostly sided with its own family: Claude's 33 times, Gemini's 23 times.
- So each card shows its headline on each labeller's labels as well as the adjudicated ones.
- A second check: six models from three families (OpenAI gpt-5.4-mini and gpt-5-mini, Google gemini-3.8-flash and gemini-3.5-flash, Anthropic Claude Sonnet and Haiku) each answered the same plain-language questions alone, on 120 labelled items (the CI and reply items drawn first from those the first two labellers disagreed on). Where a majority formed, it matched the labels on CI causes 21 of the 24 it decided (40 asked), the release behind a bug 11 of the 12 it decided (15 asked), how releases reach users 9 of the 14 it decided (15 asked), but issue replies only 11 of the 24 it decided (30 asked): it called most replies the labels call drive-bys or project answers helpful answers from other users, so the Community card's reply labels are the least settled. On the replay's disputed items it reached no majority on 11 of 20.
- No person has audited the labels yet.

**How sure.** A rule is an *early observation* when its check rests on few cases; its numbers are a direction,
not a settled rate: `flaky.already_failing` (1 of 6 held-out matches with the same error); `flaky.maybe_flaky` (2 held-out matches in 150 failures); `flaky.only_this_pr` (not yet measured on labelled failures); `flaky.worse_on_pr` (not yet measured on seeded or labelled failures); `flaky.pr_details` (24 matches in 4 repos, one repo gave most); `dora.incident_link` (15 reports named the release that broke). A rule's *bar* is the accuracy it had to reach before it shipped; for the flaky-test rules it is that at most 5% of the failures it calls flaky were really caused by the change (*masking*: a real failure hidden as a flake). A rule whose bar *failed* is kept only where failing costs nothing it promised: `flaky.known_flaky` (too few calls to show 5%: the label says "likely", the advice says to check the error first, and the verdict check waits for a green re-run). The rest are validated: checked against their bar, on held-out data where the rule has one ([rules.md](rules.md) says which).

**Reproduce a number.** `python bench/accuracy/reproduce.py list` names the command behind every result file;
`reproduce.py check <card>` re-scores it and says whether the numbers match. Scoring reads the evidence each
card was labelled from (the `.work` folders: CI histories, crawl records, logs), which is too large and holds
too much third-party text for the repo; `reproduce.py pack` builds it into one archive (about 600 MB before
compression), shared on request. The final labels are committed beside each card, with links to the public items.

## Weekly changes and ranges

A change is flagged only when it is unlikely to be ordinary week-to-week variation. The digest checks many numbers at once, so it uses false-alarm control (Benjamini-Hochberg) rather than one cut-off per number: on this replay the two behave alike, but a fixed cut-off flags more often as numbers are added and this doesn't. The 26 repos are the independent units; shuffling their weeks tests the no-change case, it doesn't add repos.

| | Result | |
|---|---|---|
| Shuffled weeks that flag anything (nothing changed) | **7.5%** | every difference: 97.9%; each number at p < 0.1: 20.8%; at p < 0.05: 11.3% |
| 10x slowdowns caught in the same scans (first week) | **24.7%** | p < 0.1: 44.8%; p < 0.05: 32.4%; detection is the weak side |
| 10x slowdowns lasting two weeks, caught in the second | **34.8%** | the 14-day checks; 15.1% with weekly checks only |
| Small repos' first-try share pulled toward peers (3 pushes seen) | **29.3% less squared error** | a 95% range for later pushes held 94.6% of them |

Weak spot: A small repo's week can't tell even a large slowdown from noise; the page says so instead of guessing. Labels: none (replayed history). Card: [bench/accuracy/uncertainty](../bench/accuracy/uncertainty/README.md).

## AI-assisted pull requests, like with like

Agents' pull requests are compared with people's from the same repo, month and size.

| | Result | |
|---|---|---|
| Agents' PRs merged by someone else, against people's: unadjusted | **-9.0 points** |  |
| The same, same repo, month and size | **+0.5 points** | -0.0 to +1.1; can't be told from no difference |
| Shuffled AI labels (nothing to find) | **+0.1 points** | 200 shuffles |
| Marked PRs that state AI involvement (precision) | **98.5%** | 96-99%, 194 PRs; by repo: 188 repos, 95-99% counting each once; 1% from unredacted/freesocks-control-plane, without it 189 of 192 |
| Stated AI involvement that is marked (recall, a floor) | **78.8%** | held out 66.3%; weighted to the crawl |
| People's merge rate after a repo adopts agents (pre-registered) | **-0.9 points** | -2.7 to +0.7; throughput: not credible, adopters were already growing |

Weak spot: Markers find about 79% of stated AI involvement (66% held out) and none that goes unsaid, so "AI-marked" is a floor; matching can't see what a PR was for. Labels: crawl markers; the marking itself checked on 400 PRs labelled by Claude and Gemini. Card: [bench/accuracy/ai](../bench/accuracy/ai/README.md).

## Flaky CI

A job is flaky when the same code failed and passed; no failure is called safe to re-run: a likely flake needs history, a flake's sign in its log and no changed file named, and still waits for a green re-run.

| | Result | |
|---|---|---|
| Flagged flakes that were real flakes (event precision) | **97.2%** | 92-99%, 108 events; Claude's labels 97.2%, Gemini's 80.2%, adjudicated 97.2%; by repo: 40 repos, 87-99% counting each once; 4.6% from polyaxon/haupt, without it 100 of 103 |
| Flagged flakes GitHub's own history confirms weren't the change (no labeller) | **42 of 112** | a floor, not a precision: every flagged flake passed on identical code, so history can confirm one but never refute it; all 112 flagged jobs, where precision uses the 108 the labels could decide |
| The plain "passed on retry" rule on the same repos | **96.9%** | 94-98%; ours +0.3 points (-4.0 to +4.0, not significant); scored on the retries it can see; the retries only it flags were real 53.8% of the time |
| "Known flaky" failures the change caused, old rule | **44.1%** | 15 of 34, 29-61% |
| The same, 2026-10-22 rule (3+ flakes, one in the failing step), held out | **13 of 81** | 10-26%, 48 jobs in 15 repos; by repo: 11 repos, 4-45% counting each once; 53.1% from lxc/incus, without it 13 of 38; the 5% bar failed, so the rule was tightened (next row) (on the tuning sample: 0 of 5, all one job) |
| Stricter rule (history, a flake's sign in the log, no changed file named), pre-registered, fresh held out | **0 of 4** | 0-49%, 3 jobs in 2 repos; it kept 4 of 44 calls history made (9.1%); the 5% bar is unproven, so it reads "likely flaky", never safe; "maybe yours" (a changed file named): 4 of 5 the change's |
| End-to-end replay: "known flaky" calls a re-run turned green that the change had caused | **3 of 45 to 15 of 52** | the labellers disagree: 2-18% adjudicated by Claude (its 3 are a pull-request label check), 18-42% by Gemini; Claude's labels alone 0 of 41, Gemini's 17 of 50; people's labels pending. 2,874 failed pull-request jobs replayed as of each attempt in 35 repos; known flakes are re-run, never passed |
| Calls that blamed the change but went green on a re-run (random draw, 3 per run at most) | **4 of 66 to 22 of 80 were the change** | 2-15% to 19-38%: a green re-run doesn't prove the change clean either way, so the verdict check, by design, never passes red CI |
| Harmless failures the 2026-10-22 rule called known flaky (on its tuning sample) | **5 of 19** | 26.3%, 12-49%; the rest cost a look |
| "Already failing on main" (same step, same error) failures the change caused | **0 of 12** | 0-24%, 5 repos; the step alone: 4 of 20, so the error must match; the verdict check still blocks |
| "Maybe flaky" first failures (they look like flakes) the change caused | **0 of 4** | 0-49%; never-flaked failures overall: 58 of 98; signs written on these logs; asks for one re-run, still blocks |
| "PR details" failures (a check on the PR's title, description or labels) that were the change's code | **1 of 24** | 1-20%, 4 repos; 21 had been called known flaky, so a re-run that fails again was advised; still blocks; by repo: 4 repos, 0-53% counting each once; 75% from DataDog/datadog-api-client-go, without it 1 of 6: preliminary |
| Never-flaked failures that were intermittent (misses) | **17.3%** | 11-26%; Claude's labels 16.8%, Gemini's 25.4%, adjudicated 17.3% |
| Labellers on "caused by the change" | **69.2% agree (kappa 0.43)** | cause: 55.9% agree (kappa 0.47) |
| Labellers against GitHub's history, where it decides | **Claude 100%** | Gemini 81.2% of their definite answers on 48 failures; always answering "not caused" would score 91.7% |

Weak spot: 14-day reads miss rare flakes; status precision (re-running pinned commits) isn't measured yet; Rust jobs were real flakes 80% of the time. Labels: Claude and Gemini 3.5 Flash-Lite, disagreements adjudicated blind by Claude; no person audited. Card: [bench/accuracy/flaky](../bench/accuracy/flaky/README.md).

## Deployments and failures

Deployments come from the source that matches how a repo ships; a revert blames the deployment that shipped what it undid.

| | Result | |
|---|---|---|
| Repos whose deployment source is right: StackVitals | **53 of 60** | 78-94%; the first 25 led to one fix of the rule, the later 35 are held out: 85.7%; Claude's labels 92%, Gemini's 88%, adjudicated 92% on the first |
| The same with no setup: DevLake's default pattern / every merge | **15% / 8.3%** | paired on the same repos: 45 to 1 against DevLake's default |
| DevLake with a pattern a user would write (deploy, release, publish or push-image) | **36.7%** | 26-49%; paired: 33 to 2; it also counts docs-site builds |
| Lead time per pull request, on the same pull requests as Middleware | **95 of 96 within 10%** | 5 repos, 90 days, no labeller; the rest were rebased long after they were written (Middleware starts at the rebase); Middleware returned about a month where 90 days were asked on 4 of 5 repos |
| Reverts where time order blamed a release lacking the change | **71 of 89** | fix chain right on 87 of 89; 117 reverts in 23 repos, checked with the commit graph (no labeller); time order wrong by repo: 18 repos, 57-92% counting each once; 14.6% from Alfresco/alfresco-ng2-components, without it 60 of 76 |
| Regression reports naming the release that broke: the last release before the report was it | **6 of 15** | 20-64%; the version the report names: 10 of 15 (not significant, so DORA's rule stays); 15 of 60 reports said which release |
| Repos whose deployment tier changes with the definition | **61.9%** | 4,618 crawled repos |
| Labellers on whether a workflow ships | **95.3% agree (kappa 0.79)** | on each repo's full set of sources: 56% agree (kappa 0.50); held-out repos: 91.3% agree (kappa 0.74) and 48.6% agree (kappa 0.38) |

Weak spot: Shipping workflows with plain names (docker, pypi, CD) are missed: workflow recall 60% on the held-out repos; releases from maintenance branches with backports defeat both linkage rules. Labels: Claude and Gemini 3.5 Flash-Lite, disagreements adjudicated blind by Claude; no person audited. Card: [bench/accuracy/dora](../bench/accuracy/dora/README.md).

## First responses

A first response is the project's (a maintainer, a regular responder or someone who triages), and issues still waiting stay in the median.

| | Result | |
|---|---|---|
| Non-maintainer first comments that are drive-bys (issue-metrics counts them) | **45.8%** | 40-52%, held-out repos |
| Project answers the roles-only rule missed / regular responders and triagers catch | **18.9% / 56.5%** | drive-bys among what they add: 16.3%; regular responders alone, by labeller: Claude's labels 11.1%, Gemini's 21.5%, adjudicated 16.7% |
| Repos where an answered-only median hides that most issues wait | **61.1%** | 2,370 crawled repos |
| Labellers on the kind of comment (held-out set) | **67.8% agree (kappa 0.52)** | first set: 72% agree (kappa 0.57); drive-bys counted by issue-metrics: Claude's labels 46.9%, Gemini's 50.8%, adjudicated 45.8% |

Weak spot: About 43% of occasional contributors' project answers still go uncounted; the rule errs toward "waiting". Labels: Claude and Gemini 3.5 Flash-Lite, disagreements adjudicated blind by Claude; no person audited. Card: [bench/accuracy/community](../bench/accuracy/community/README.md).

## Against a general AI agent

The same questions, answered by an agent with live GitHub access, with and without StackVitals. On single failures the agent is as accurate either way; what StackVitals adds is answers with nobody asking (the PR comment and verdict) and comparisons with similar repos without GitHub calls.

| | Result | |
|---|---|---|
| Failure questions right: agent / agent with StackVitals / StackVitals alone | **20 / 20 / 13 of 20** | a live agent reading the log needs nothing from StackVitals here; agent against StackVitals alone: 7 to 0 (McNemar p = 0.016) |
| Labelled flaky jobs found (both agents) | **16 of 16** | GitHub calls: 214 without, 259 with StackVitals |
| Comparing with similar public repos: repos it rests on | **14-23 vs 56-311** | 198 calls for the live agent, 0 with StackVitals |
| 100 more failures in 44 repos, Sonnet: agent / with StackVitals | **86 / 88 of 91** | McNemar p = 0.625; GitHub calls per failure 2.1 without, 2.2 with; 9 checks on the PR itself scored apart |
| 100 more failures in 44 repos, Haiku (half of them): agent / with StackVitals | **44 / 43 of 48** | McNemar p = 1.000; GitHub calls per failure 2.8 without, 2.2 with; 3 checks on the PR itself scored apart |
| Same failures, no agent: StackVitals alone / with opt-in model triage | **60 / 79 of 91** | what the PR comment and verdict check say with nobody asking; an agent reading the log does better |

Weak spot: Questions beyond GitHub's 90-day log retention, where kept history matters most, are not asked yet. Labels: Claude (the flaky card's first labels). Card: [bench/accuracy/agents](../bench/accuracy/agents/README.md).

## Rule changes

Every rule a number rests on, with each revision and why, is in [registry.json](../bench/accuracy/registry.json).

- 2026-10-22, `flaky.event`: before, same-code flips in any workflow; all 3 flips that weren't real flakes, and 5 checks of the PR's own text, were pull-request runs of workflows that also run on PR edits or labels; after, 9 of 108 events left out (3 wrong, 5 PR-text checks, 1 real timing flake); 99 of 99 kept are real.
- 2026-10-23, `flaky.event`: before, pull-request flips left out in PR-edit workflows; held out, all 17 flips in such workflows were real flakes; after, reverted to the earlier rule.
- 2026-10-22, `flaky.known_flaky`: before, any earlier flake; 15 of 34 failures it called safe were caused by the change (44%); after, 7 called safe (5 clearly labelled, 0 caused), all one job; the other 29 now cost a look.
- 2026-10-23, `flaky.known_flaky`: before, a known flake passed the verdict check; 13 of 81 held-out safe calls were the change's own failure; matching past flakes' errors didn't separate them; after, known flaky still reads 'likely a flake, re-run it', but the verdict check passes only once CI is green.
- 2026-10-23, `flaky.known_flaky`: before, a known flake read 'likely a flake, re-run it'; in the agent head-to-head a smaller model trusted it on 2 failures the change caused; after, it asks to check the error isn't from the change before re-running; those 2 were then answered right.
- 2026-10-28, `flaky.known_flaky`: before, 3+ flakes in the window, one in the failing step (history alone); shown as "Known flaky"; held out, 13 of 81 such calls were the change's own failure; a flake's sign in the failing step's log and no changed file named separated them on the tuning data (0 of 31 caused when both held; 8 of 8 clear caused when a changed file was named); after, fresh read: 4 of 44 calls kept, 0 caused (0-49%), so the 5% bar is unproven; shown as "Likely flaky" with its evidence, never "safe"; the rest read flaked before, or maybe yours (4 of 5 clear fresh cases caused).
- 2026-10-22, `flaky.outside_failure`: before, failure-section match including 'failed to download and build'; a dependency's own build failing matched; after, taken out; 4 matches given up for safety.
- 2026-10-22, `flaky.outside_failure`: before, TEST_FAILED matching any 'FAILED:'; ninja's 'FAILED:' build lines hid an sccache outage; after, test-runner forms only.
- 2026-10-22, `flaky.already_failing`: before, the same step alone; 4 of 22 such failures were caused by the change, with a different error in that step; after, 12 matched, none caused.
- 2026-10-23, `flaky.maybe_flaky`: before, track record over all 24 signature matches; the product says maybe flaky only for never-flaked failures (a whole-release review); after, the track record counts never-flaked matches: 1 of 6 (0 of 4 tuning, 1 of 2 held out).
- 2026-10-23, `flaky.pr_details`: before, error lines mentioning a title, label or description anywhere; a test assertion about chart labels matched; after, the words must be about the PR.
- 2026-10-23, `flaky.pr_details`: before, only jobs whose steps read the PR (triggers.metadata_jobs); label checks gated by `if:` and checks reading the PR in a script were missed (2 matches of 24); after, any job of a workflow run by PR edits, with the error guard.
- 2026-10-23, `flaky.pr_details`: before, "checkbox", "template" or "PR" alone; any failing step; a whole-release review: a template rendering error in a CI workflow run on labels matched; after, those words need the PR's wording beside them, and a failing test rules it out; still 24 of 24 matched.
- 2026-10-21, `dora.deploy_source`: before, display name checked against the deny list; a file named deploy.yml titled 'Check and Publish' hit the deny word 'check'; after, a file named only deploy, release or publish ships whatever its display name; 22 to 23 of 25.
- 2026-10-22, `dora.fix_chain`: before, every revert counted as a failed deployment; 11 of 18 undid a change that never shipped; after, never-shipped reverts are no failed deployment.
- 2026-10-23, `community.regular_responders`: before, answers and first reviews only; triage acts mark people acting for the project; on the labelled comments the rule missed, they found 8 project answers among 11; after, held out: 4 more project answers (47% to 57% weighted); on Claude's labels 45% to 53%, on Gemini's 32% to 38%.
- 2026-10-22, `community.first_response_km`: before, closed-unanswered items treated as still waiting; they stopped being at risk when they closed; after, censored at closing.
- 2026-10-24, `uncertainty.digest`: before, weekly checks only; in a slowdown's second week the weekly check's baseline holds the first slow week, so 10x slowdowns were caught in 15% of scans; after, on the same replay, second-week catches of 10x slowdowns 15% to 35%, first-week 31% to 25%, false alarms 7.4% to 7.5%; CUSUM charts tried and dropped (no gain).
- 2026-10-23, `ai.detection`: before, AI trailers in the last 5 commits, labels matched exactly, agent account or branch; 5 of 23 missed PRs named the tool in their description; label spellings and Jules task links missed in the tune half; after, recall 75.0% to 78.8% weighted (63.9% to 66.3% held out); precision 185 of 187 to 191 of 194.
