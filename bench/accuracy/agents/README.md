# Against a general AI agent with live GitHub access

Any team can ask a capable agent with GitHub access about its CI. This card checks what StackVitals adds to that, on
questions with labelled answers, and publishes where it adds nothing.

## Setup (`prepare.py`, `score.py`)

Five public repos from the flaky card's sample (gno, revive, firewall-dotnet, munich-quantum-toolkit/core, GAM), chosen
for a mix of labelled flakes and failures their change caused. Three kinds of question:

1. **Twenty failed job attempts** (four a repo, half flakes, half caused by the change, labels from the flaky card):
   "did this attempt fail because of the change under review, or was it a flake?"
2. **One history question a repo:** "which jobs flaked (failed, then passed on the same code) in this 14-day window?",
   scored on the 16 jobs whose flakes are labelled.
3. **One cross-repo question a repo:** "what share of pushes passed CI on the first try, what is typical for public repos
   of the same language and size, and where does this repo rank?"

Two arms, same model and instructions: a general agent whose only network access is a GitHub wrapper that counts every
call (100 a repo for questions 1-2, 40 a repo for question 3), and the same agent given StackVitals' answers as well
(its verdict for each failure, computed from the history before it; the CI health page; the crawl's comparison).

## Results

| | General agent | Agent with StackVitals | StackVitals alone |
|---|---|---|---|
| Failure questions right | **20 of 20** | **20 of 20** | 13 of 20 (6 before this card's fixes, then 11) |
| Labelled flaky jobs found | 16 of 16 | 16 of 16 | |
| GitHub calls, questions 1-2 | 214 | 259 | 0 |
| Cross-repo: repos the comparison rests on | 14-23 | 56-311 | 56-311 |
| Cross-repo: GitHub calls | 198 | 0 | 0 |
| Cross-repo: typical share within 5 points of the 56-311-repo reading | 2 of 5 | 5 of 5 (read it) | |

**Where StackVitals adds nothing:** a single failure inside GitHub's retention window. An agent that reads the log
and the re-runs answered all 20 correctly; given StackVitals' verdicts it still checked everything live and spent more
calls, not fewer. On this question StackVitals is a cheaper first answer, not a better one.

**What this card changed:** StackVitals alone called 8 first-time flakes "likely from this change", because history
can't know about a flake before the re-run. It now reads the failed jobs' logs for outside failures (a registry, a
cache, the runner) and says so; that took it from 6 to 11 of 20 at no cost to the change-caused failures (see the flaky
card's "Outside failures" section). A second fix took it to 13: a first failure whose log shows how flaky
checks fail (a benchmark gate, a live API retrying until it gave up) now reads "maybe flaky: re-run it once to tell; if
it fails again, look at this change" instead of "likely from this change". It counts here as leaning to a flake, and
still blocks the verdict check (see the flaky card's "Maybe flaky" section). Of the 7 it doesn't get: 2 flaky tests of
a file watcher whose logs show only a wrong count, read as "new" (a rule for them would be fitted to one repo); 4
failures the change caused in jobs that had flaked before, left at "flaked before: check whether this change caused
it" (counted as no answer, which is the masking fix doing its job); and a dependency pin failing daily on the default
branch, which StackVitals calls "already failing" and the label puts on the change.

**Opt-in model triage (`triage_check.py`):** with `[ci.triage]` on, a model (Gemini 3.5 Flash-Lite, free tier) reads
the failing step's log and the changed files of each failure the rules leave undecided. On these 20 it was asked about
13 and was right on 11. Of the 6 failures StackVitals alone got wrong or left unclear, it got 5 right; of the 7
StackVitals alone got right, it disagreed on 1. Its view is shown beside the verdict and never changes it: on the
flaky card's 98 first-time failures, Gemini's labels were wrong 11 of the 34 times they said "not the change".

**Where it adds most:** the comparison with similar repos. The general agent spent its whole budget sampling 14 to 23
repos, judging each on about 15 runs, and its typical shares came out at 0.90 to 1.00 where the 56-311-repo reading is
0.88 to 0.96; StackVitals answered from its crawl with no calls. The agent's own-share readings also differ where the
crawl and the agent counted pushes differently (firewall-dotnet: 2 pushes by the agent's count, 24 in the crawl's
14 days), so only the peer side is scored as a gap.

## A bigger head-to-head: 100 failures, 44 repos, two models (`prepare2.py`, `score2.py`)

100 labelled pull-request failures from the flaky card and the held-out read (`../flaky/`), half the change's own and
half flakes or outside failures, at most 4 a repo, seeded. Each arm is one agent per group of repos, given only the
failure's URL and a counting GitHub wrapper (about 12 calls a failure); the "with StackVitals" arm also reads what the
MCP tool `ci_failure` answers for that failure, computed from the history before it (verdicts, error lines, how often each
verdict held, what was checked). Sonnet answered all 100; Haiku, half (5 of the 9 groups). The prompts are in
`prompts.md`.

| On 91 failures (9 checks on the PR itself apart) | Right | GitHub calls a failure |
|---|---|---|
| Sonnet, general agent | 86 | 2.1 |
| Sonnet with StackVitals | 88 | 2.2 |
| Haiku, general agent (48 of them) | 44 | 2.8 |
| Haiku with StackVitals | 43 | 2.2 |
| StackVitals alone (what the PR comment says, nobody asking) | 60 (15 left open) | 0 |
| StackVitals with opt-in model triage (Gemini Flash-Lite, free tier) | 79 | 0 |

**What it shows:** on a single failure inside GitHub's log retention, a capable agent reading the log is right about 9
times in 10 with or without StackVitals (Sonnet 86 against 88, McNemar p = 0.63; Haiku 44 against 43, p = 1.0). With
StackVitals, Haiku spent a fifth fewer calls. StackVitals on its own is the answer nobody had to ask for (the PR comment
and the verdict check); with model triage it gets 79 of 91, still below an agent reading the log.

**What it changed in the product:**
- **"PR details"**: 9 failures were checks on the PR itself (a changelog label, a PR-description checkbox, a title
  prefix) that StackVitals had called known flaky or new, because label edits look like flips. They now read "PR
  details: fix the PR's title, description or labels, not the code" (see the flaky card's "PR details" section). They are
  scored apart because the question fits them badly: the code is fine, yet the same PR fails again until it is edited;
  the labels say "not the change", and every arm mostly said "change" (Sonnet 8 of 9 with and without StackVitals).
- **"Known flaky" asks for a look first**: Haiku trusted it on 2 failures the change caused (16% of held-out known
  flaky calls are). It now says "likely a flake, but check the error isn't from this change, then re-run it"; on the
  re-run both were answered right.
- **The harness**: the call wrapper first printed the start of long logs and lost their failures; it now prints the
  end. The first run is kept apart and not scored.

**Caveats:** the labels come from Claude and Gemini with Claude adjudicating, and agents read the same logs, so agreement
is expected. Two agents opened files outside their own (other groups' StackVitals answers; their own saved logs) and said
they did not use them. Results: `results2.json`; the first answers, before "PR details": `.work/agents2/run1-before-pr-details`
(local only).

## What it can't show

- Twenty items and five repos: small. The failure labels are the flaky card's first (Claude) labels, with no person
  audit, made from the same logs the agents read; an agent reading logs is expected to agree with them.
- The cross-repo "truth" is StackVitals' own crawl reading, so the second arm's agreement with it is by construction;
  the measured gap is the general agent's cost and sample size.
- History questions beyond GitHub's 90-day log retention, where precomputed history matters most, are not asked yet:
  the sample's data covers 14 days.

## The default tool set (2026-10-24)

`stackvitals serve` now offers 11 tools by default (all 35 with `--tools all`). To see whether the shorter list changes
which tool an agent picks, two Claude Haiku agents, each given one list, chose the first tool for 11 everyday questions
(one per core tool: "should I fix or re-run this failure", "who should review #88", "is this upgrade safe"...). Both
picked the right tool for all 11. On questions this plain the list length made no difference; the default keeps an
agent's context smaller, not its choices better. Harder or ambiguous questions aren't tested, and this was an informal
check: its questions and answers weren't kept. The skill pack and the MCP registry entry start the server with
`--tools all`, since the skills use tools outside the 11.

## Reproduce

```
python bench/accuracy/agents/prepare.py --flaky-home <flaky work folder> --out <folder> --ci-records <crawl ci folder>
# run the two arms with the prompts in this card's setup, answers in <folder>/answers-*.json and peer-answers-*.json
python bench/accuracy/agents/score.py --out <folder>
```

Results: `results.json` (right or wrong per arm and calls; no answers' text).
