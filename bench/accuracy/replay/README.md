# End-to-end replays: what the comment and the verdict check would have said

The other CI cards check one rule at a time. This one replays the whole pull-request path: for every failed attempt of
a pull-request run, the product's own `classify_run` (the code behind the PR comment) and `verdict_payload` (the
verdict check) were run on the history before that attempt only, and what each said was compared with what happened
next on the same code.

## The read

- **35 repos, 2,874 failed pull-request jobs in 1,351 failed attempts.** 25 repos come from the 30-day held-out CI read
  (`flaky/wide.py`, chosen for heavy re-running). 10 are busy public projects on GitHub Actions, monorepos among them:
  pytorch/pytorch, microsoft/vscode, home-assistant/core, grafana/grafana, vercel/next.js, angular/angular,
  apache/airflow, nrwl/nx, rust-lang/rust and python/cpython. Each was read with the Action's own collector, newest day
  first, at 300 requests per repo (400 for pytorch, vscode and home-assistant, read twice).
- **Busy repos give a short history.** 300 to 400 requests cover 1 to 9 days there, against the 30 the product keeps.
  An attempt is replayed only with at least 3 days before it, so busy repos contribute 598 failed jobs and few
  "known flaky" calls (a call needs 3 flakes in the failing step). Their results lean on the held-out repos.
- **Logs aren't read in the replay.** Verdicts are the history-only ones; the log-based refinements ("outside
  failure", "maybe flaky", same error as on main) aren't applied.

## What happened next

| The comment said | Re-run passed | Failed again | Not run again |
|---|---|---|---|
| Known flaky: re-run it | 127 | 80 | 343 |
| Likely from this change | 210 | 87 | 964 |
| Flaked before, check the change | 141 | 97 | 676 |
| Already failing on main | 18 | 23 | 108 |

A "re-run" here is a later attempt of the same run or another run of the workflow on the same code. Of the known-flaky
calls that ran again, 61% passed (55-68%; 40-79% counting each repo once). People re-ran a known-flaky failure that went
on to pass after a median of 3 minutes (127; 13 minutes over every failure that passed on a re-run).
`[automation] rerun_flaky` re-runs an attempt only when every failure in it is a known flake: 303 of the 1,351 failed
attempts here.

The verdict check fails every red attempt, a known flake's included, until a re-run is green; that is how it is built
(0 of 1,351 passed red), not something this replay found.

## The reviewers' question: did a re-run hide a real bug?

Two groups were labelled blind (the labellers saw the log, the failing step and the files the change touched, never the
verdict or what happened next; [codebook](../flaky/codebook.md)):

- every known-flaky call that ran again, at most 3 per job: 93 (90 from the held-out repos, 3 from the busy ones);
- a seeded random draw of 90 calls that blamed the change ("likely from this change" or "flaked before") and passed
  when run again, at most 3 per run (`blamed_sample`, seed 19), from 22 repos.

Claude labelled first and Gemini 3.5 Flash-Lite second; they agreed on "caused by the change" for 68% of the 254
labelled items (kappa 0.46). Every disagreement was adjudicated blind twice, once by Claude and once by Gemini, and each
rate is shown on all four label sets, because they differ a lot:

| Caused by the change | Claude's labels | Gemini's labels | Adjudicated by Claude | Adjudicated by Gemini |
|---|---|---|---|---|
| Known-flaky calls a re-run turned green | 0 of 41 | 17 of 50 | **3 of 45** (2-18%) | **15 of 52** (18-42%) |
| Known-flaky calls that failed again | 0 of 26 | 4 of 31 | 0 of 26 (0-13%) | 1 of 31 (1-16%) |
| Blamed on the change, then green on a re-run (random draw) | 4 of 64 | 22 of 80 | 4 of 66 (2-15%) | 22 of 80 (19-38%) |

Counting each repo once widens every range (known-flaky green: 1-29% on Claude's adjudication, 13-51% on Gemini's);
lxc/incus holds the most items (8 of the known-flaky green ones). Claude marks more items "unclear" (15 against 8).

**What it means.** Somewhere between about 1 in 15 and 1 in 3 known-flaky calls that a re-run turned green was the
change's own failure, depending on which model family reads the logs. On Claude's adjudication the 3 are the label check below, so no
change's code; on Gemini's, 12 more in 6 repos, mostly failing tests (7) and code changes (3) by Gemini's reading (in the items
read by hand, Gemini blamed the change where Claude read timing or a node that wasn't up). The held-out card
found 13 of 81 (16%) on known-flaky calls nobody re-ran, inside this range. So a known-flaky call is not proof the change
is clean, which is why the comment says "check the error isn't from this change, then re-run it", and why the verdict
check never passes on a known flake alone. Which end of the range is right needs people's labels. A five-agent model panel (Claude Sonnet,
each answering alone, the re-run result hidden) re-read the 50 items the two adjudications split on: its
majority sided with Claude's adjudication on 16, Gemini's on 7, neither on 8, and had no majority or couldn't
tell on 19. Being Claude's family, it doesn't settle the split (`audit-results.json`). Six models from three families (two each from OpenAI, Google and Anthropic) read 20 of
them too: no majority on 11, Claude's adjudication on 5, Gemini's on 4 (`../panel-results.json`).

Three of the known-flaky items (17-19) are one job that fails until the pull request has a `changelog/*` label. Both
labellers labelled the three alike, the first adjudication split them two to one, so one ruling was applied to all
three ("caused": the pull request's labels decided it, not its code; `decisions-07`). In the product, with the job's
log read, such a check is called "PR details", not known flaky; the replay reads no logs.

## What it can't show

- Most failures were never re-run (2,091 of 2,874), so their outcome is unknown.
- Busy repos contribute few calls (3 known-flaky calls that ran again): their 1 to 9 days of history rarely reach the 3
  flakes a known-flaky call needs. The rates rest on the 25 held-out repos.
- An earlier version of this card drew the blamed-then-green items from the start of a sorted list, so one jruby/jruby
  pull request (one missing artifact failing 30 jobs) made "half were the change". The random draw capped per run
  replaced it.
- No person audited these labels yet.

## Reproduce

```
GH_TOKEN=... python bench/accuracy/replay/replay.py read --home <work> --budget 300   # the busy repos
python bench/accuracy/replay/replay.py pool --home <work> --home <held-out wide work folder>
GH_TOKEN=... python bench/accuracy/replay/replay.py fetch --home <work>
python bench/accuracy/labeller.py replay --work <work> --run          # the second labeller; first labels in labels.jsonl
python bench/accuracy/adjudicate.py replay --work <work> --packets    # then --apply (Claude's decisions-NN.jsonl)
python bench/accuracy/replay/replay.py cross --home <work>            # Gemini adjudicates the same disagreements
python bench/accuracy/replay/replay.py score --home <work> --labels <final/replay.jsonl>
```

Results: `replay-results.json`. Labels: `replay-labels.csv` (ids, links, verdicts, what happened and the final labels;
no logs).
