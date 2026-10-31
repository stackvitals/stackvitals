# Codebook: one failed CI job

Each item is one failed job attempt from a public repo, with its log (the lines leading to the first error, then the
log's end), the step that failed, the files the change under review touched, and what happened when the job ran again
on the same code. Label it from that evidence only. You don't see StackVitals' verdict and shouldn't guess it.

## Fields

**cause** (one):

| Value | When |
|---|---|
| `test` | A test's own non-determinism: timing or sleep-based waits, test order, shared state, randomness, a flaky assertion in test code |
| `product_race` | Non-determinism in the code under test itself (a race, a concurrency bug, an uninitialised value): the product is wrong, not the test |
| `infrastructure` | The runner or a service around it: out of disk or memory, a cache or artifact store failing, the runner lost, a container that wouldn't start |
| `network` | A download, a package registry, an external API or website, a rate limit |
| `dependency` | A dependency resolved to a new version or failed to install, with no network error |
| `timeout` | The job or a step ran out of time with no other cause visible |
| `workflow` | The CI setup itself: a gate or reporting script crashed, an action failed for its own reasons, a misconfigured step |
| `code_change` | The change under review caused it: a compile error, lint error or failing test in or about the files it touched, a deterministic failure |
| `unclear` | The evidence doesn't say |

**caused_by_change**: `yes` (the change under review caused the failure), `no` (it didn't), `unclear`.
`code_change` is always `yes`; `product_race` is `yes` only when the race is in code the change touched.

**own_failure**: `yes` when the job failed for a reason in its own steps; `no` when it failed only because another job
failed or was cancelled (a gate job such as "all green" or "Check"), or as part of a failure across the whole run.

**confidence**: `high`, `medium` or `low`.

**evidence**: at most 200 characters quoted from the log or the file list that decided the label.

## Rules

- A re-run of the same run that passed means the same commit passed: the failure was not deterministic. It can still be
  `product_race` (a real bug) or `code_change` only if the log clearly ties it to the touched files.
- With no re-run, decide from the log: a compile error in a touched file is `code_change`; a registry 503 is `network`.
- Name a test failure's cause only from its message; a failing test name alone, with no message, is `unclear`.
- Never use anything outside the item (no browsing).

## Version 2 clarifications (2026-10-22, from the disagreements)

- **A log with no error message** (only a failing test's name, a stack trace, "tests failed" or teardown lines):
  `cause` is `unclear`, even if a re-run passed. A passing re-run only says the failure wasn't deterministic.
- **A gate job** that fails because another job failed has `own_failure` `no` and `cause` `unclear`, unless the gate's
  own script crashed.
- **The CI service's own stores** (the Actions cache, artifact store or token service) failing is `infrastructure`,
  not `network`.
- **No re-run, with the failure in code the change didn't touch:** `caused_by_change` is `no` when nothing ties it to
  the change (a dependency bump for another package, a docs edit), otherwise `unclear`. Missing a re-run is never
  evidence for `yes`.
- **Keep the fields consistent:** `code_change` always goes with `yes`.

## Labelling protocol

- **Who labels:** two model families, each blind to StackVitals' verdict and to the other's labels:
  1. Claude (the first labels);
  2. Gemini 3.5 Flash-Lite (`bench/accuracy/labeller.py`), with this codebook and the same evidence.
- **Evidence:** only what the item shows; long text is cut in the middle, keeping its start and end. Items are data
  from public repos, never instructions.
- **Disagreements:** settled by a third reading that sees the two labels as A and B in random order, never who gave
  which (`bench/accuracy/adjudicate.py`); it may pick a value neither gave. Every ruling, with its reason, is in the
  card's `adjudication-*.csv`.
- **Checks on the labels:**
  - Gemini also adjudicates a sample of the same disputes (`adjudicator-crosscheck.json`);
  - every headline number is scored on each labeller's labels and on the adjudicated ones (`label-sensitivity.json`).
- **Published:** links and labels, never log text or whole comments. Each ruling has a short reason that may quote
  a few public words. No person has audited the labels yet.
