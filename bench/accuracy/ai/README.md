# AI-assisted pull requests, compared like with like

Vendors' AI-impact figures put "AI" pull requests against everything else, pooling coding agents' own PRs with people's
AI-assisted ones, and their makers call the comparisons non-causal. StackVitals keeps three kinds apart and compares
each with its own kind of control; this folder checks that design on the crawl.

## The design

- **Coding agents' PRs:** an agent's account, or a branch an agent opened (codex/, claude/, copilot/, cursor/, devin/,
  AIDev's public rule), whoever's account opened it. Compared with people's PRs of the same repo, month and size band
  (an agent has no "same author").
- **People's AI-marked PRs:** a person's PR with an AI co-author trailer or a coding tool's label. Compared with the same
  author's other PRs of the same size band (Watanabe et al.'s design).
- **Estimator:** Mantel-Haenszel risk difference with Sato's variance (it stays right when most matched groups hold one
  or two PRs), a 95% range, the share of PRs that found a match, and the gap the comparison could detect (80% power).
  Under five matched PRs a comparison says "too few to compare"; a range across zero says "no measurable difference" and
  how big a gap it could have seen.

## On the crawl (`replicate.py`)

1,455,049 closed and merged PRs from 21,804 public repos with 100+ stars (25 of the crawl's 101 first-week runs).

**Unadjusted merge rates**, against AIDev's (people 76.8%, Codex 65.3%, Claude Code 52.5%, Cursor 51.4%, Devin 48.9%,
Copilot 38.2%):

| | PRs | Merged | AIDev |
|---|---|---|---|
| People | 1,053,556 | 84.4% | 76.8% |
| Agents: Claude | 18,986 | 88.3% | 52.5% |
| Agents: Codex | 31,863 | 84.3% | 65.3% |
| Agents: Devin | 1,532 | 83.6% | 48.9% |
| Agents: Cursor | 3,683 | 72.7% | 51.4% |
| Agents: Copilot | 9,830 | 70.7% | 38.2% |

Copilot and Cursor come last, as in AIDev, but every agent's rate is far higher here and the people's rate too: the
crawl covers active repos with 100+ stars over the last year, where AIDev sampled 2025 agent PRs across 61,000 repos,
many of them personal. The levels don't transfer between populations; the ordering does.

**Self-merges:** 71.6% of merged agent PRs were merged by their own author, against 61.5% of people's (AIDev's
follow-up: 77.5% against 57.6%).

**Agents against people, like with like** (57% of agent PRs found a same-repo, same-month, same-size match):

| Gap in | Unadjusted | Same repo, month and size |
|---|---|---|
| Merged | -1.6 points | -3.6 (-4.1 to -3.1) |
| Merged by someone other than the author | **-9.0 points** | **+0.5 (-0.0 to +1.1)** |

Counted by whether anyone else accepted them, agents' PRs trail people's by 9 points overall, and the whole gap is where
and when agents are used: within the same repo, month and size it is gone. By tool, merged at all, matched: Claude +0.3 (-0.6 to +1.1),
Codex -1.8 (-2.5 to -1.2), Devin -3.9 (-7.4 to -0.3), Cursor -13.7 (-16.2 to -11.3), Copilot -14.6 (-16.1 to -13.1);
Copilot and Cursor stay clearly lower whatever they are compared with.

**People's AI-marked PRs against the same author's other PRs** (72% matched): unadjusted -2.7 points; same author,
repo and size +0.8 (-0.8 to +2.4); merged by someone else -1.7 (-2.9 to -0.4). Watanabe et al. found -7.2 points, or
-3.2 against a time-aligned set, for "Generated with Claude Code" PRs from February to April 2025; that gap does not
reproduce here, where the marker is a co-author trailer and the period a year later.

**Negative control:** the AI label shuffled among each author's matched PRs, 200 times: mean gap +0.1 points, 95% of
shuffles between -1.2 and +1.5. The estimator finds nothing when there is nothing to find.

## How often the AI marking is right (`detection.py`)

Every comparison above rests on telling agents' and AI-assisted PRs apart from the rest. The truth here is what a PR
states about itself (its author, branch, description, labels and commits), labelled blind with
[codebook-detection.md](codebook-detection.md); AI help nobody states can't be seen by anyone, so recall is recall of
stated AI involvement. 400 non-bot PRs created since March 2026, drawn from the crawl in four strata (an agent's branch
60, an agent's account 30, an AI trailer in the description 60, none of these 250, one per repo per stratum) and
weighted back to the crawl's 997,810 PRs in those strata; 395 decided, 5 unclear. Claude and Gemini agreed on 87%
(kappa 0.80); the 51 disagreements were settled blind (Claude's label kept 43 times, Gemini's 8).

| | Before | After (description and label spellings read) |
|---|---|---|
| Marked PRs that state AI involvement (precision) | 185 of 187 (96.2-99.7%) | 191 of 194 (95.5-99.5%; 188 repos, 95.5-99.5% each counted once) |
| Stated AI involvement that is marked (recall, weighted) | 75.0% | 78.8% |
| The same on the held-out half | 63.9% (93 of 108 found) | 66.3% (94 of 108), precision 94 of 95 |
| On Gemini's labels alone | 98.4% precision, 69.1% recall | 97.9% precision, 72.6% recall |
| Agent told apart from AI-assisted | 170 of 185 | 173 of 191 |

The "after" rule was set in two steps: the description's trailers and agent task links (Codex, Devin, Cursor) were
written down before any label was seen; Jules task links and label spellings ("AI Generated") came from the misses in
the tune half (odd ids) and were checked on the even half, where they found one more PR at no cost in precision.

What it shows: a quarter of the PRs the crawl calls unmarked (63 of 247) do state AI involvement, mostly in commit
trailers, which StackVitals reads (the crawl reads only descriptions). Of the 23 stated PRs the old rule missed, 5
named the tool in the description (now read), 6 had the trailer only in a commit older than the last five (not read:
each PR's commit list would cost requests), and the rest said it in a sentence ("OpenAI Codex generated the
implementation"), which no marker rule reads. So the AI-assisted share StackVitals shows is a floor, and the
comparisons above compare what is stated.

## When a repo starts taking agents' PRs (`adoption.py`, pre-registered)

Vendors report AI impact as before and after. This study asks the same question with a comparison group and wrote down
its design, outcomes and reading rules first ([preregistration.md](preregistration.md), SHA-256 9b0327c053f8… in the
results). Staggered difference-in-differences (Callaway and Sant'Anna) over the crawl's first full PR tables: 1,764
repos that started taking coding agents' PRs between February and August 2026 (at least 2 agent PRs in their first three
months, 3 covered months before), compared with 16,269 repos that hadn't started, within activity bands; 3,938 repos left
out (one-off trials, or too little history before). 95% ranges from 400 bootstrap draws of repos.

| Outcome | Four months after | Range | Pre-registered reading |
|---|---|---|---|
| People's merge rate | -0.9 points | -2.7 to +0.7 | no measurable change (checks pass) |
| Merged PRs (log) | +0.57 | +0.52 to +0.61 | not credible: adopters were already changing |
| People's merged PRs (log) | +0.34 | +0.30 to +0.39 | not credible: adopters were already changing |
| Wait for a first human review (log hours) | +0.05 | -0.25 to +0.39 | not credible: adopters were already changing |

Read plainly: in the four months before their first agent PR, adopters' merged PRs were already growing against the
comparison repos (-0.23, -0.20 and -0.17 log points at 4, 3 and 2 months before, every range excluding zero), and the
negative control (adoption moved 3 months earlier) found +0.11 (+0.07 to +0.14) where nothing should be. The adoption
month is also picked by an agent PR appearing, which a busy month makes likelier. So a before-and-after rise in
throughput after a team adopts agents, the figure vendors lead with, is mostly a repo that was growing anyway; the
public data can't separate the agents' share. What does hold: people's PRs were merged as often after adoption as
before (the range rules out a drop of more than 2.5 points). Not pre-registered, so description only: by activity band,
the merge-rate effect stays inside -12 to +8 points in every band.

What StackVitals does with it: the AI-assisted tab compares like with like within a repo (above) and never shows a
before-and-after throughput change as an AI effect.

## How far missed markers could move it

Agents' PRs are found by their account or branch; people's AI-assisted PRs by markers that find about 79% of stated AI
involvement (66% held out). Missed ones stay in the "people" group, which pulls that group toward the AI groups and
shrinks a gap by the share they make up (true gap = measured gap / (1 - share)).

- **What was stated but missed:** 1,932 people's PRs carry a marker; at 79% recall about 520 more were missed
  (982 at the held-out 66%), 0.05% to 0.09% of the 1,053,556 people's PRs. The agent gap of +0.5 points moves by
  under 0.01 points.
- **What was never stated:** unknown. Even if a fifth of "people's" PRs were AI-assisted without saying so, the matched
  gap would read +0.7 points (0.0 to +1.4): still a small gap that can't be told from none.
  The like-for-like conclusion holds; the share of AI work it rests on is a floor.

## What it can't show

- Markers miss most AI help: unmarked PRs can be AI-assisted, so "AI-marked" is a floor, and the page shows how much of
  the work carries a marker.
- Matching removes differences in repo, month, size and author, not in what the PR was for; a type band (fix, feature,
  docs) is the next refinement once the crawl keeps titles' types.
- Merge outcomes come from the crawl; CI failures, reverts and failed deployments are compared per repo, where the
  suite keeps them, and need more history than most repos have: those read "too few to compare" until it builds up.

## Reproduce

```
# Crawl PR tables: the prs/*.parquet files inside the crawl release tars (public at launch)
python bench/accuracy/ai/replicate.py <folder of prs parquet files> --placebos 200 --seed 13
python bench/accuracy/ai/adoption.py <folder of prs parquet files> --draws 400 --seed 23
python bench/accuracy/ai/detection.py sample --crawl <crawl folder> --home <work>   # then fetch, label, score
```

Results: `replicate-results.json`, `adoption-results.json`, `detection-results.json` (labels: `detection-labels.csv`, `labels-gemini-detection.csv`, `adjudication-detection.csv`).
