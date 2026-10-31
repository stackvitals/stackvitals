# StackVitals and Middleware, run side by side

Run 2026-10-29 on the five repos and 90 days of the [DevLake side-by-side](../devlake/README.md), following
[preregistration.md](preregistration.md). Middleware (middlewarehq/middleware, the open-source DORA tool) ran from its
single Docker image on a GitHub Actions runner, configured only through its own API ([run.sh](run.sh)); each repo was
one team in its "every merge into the default branch is a deployment" mode, since it can't read GitHub's Deployments
API. Scores come from [score.py](score.py); every number below is in [results.json](results.json).

## What it took to run

| | Middleware | StackVitals |
|---|---|---|
| What runs | One container (web app, API, sync worker and its Postgres database inside), left running | One Python process, nothing left running |
| Image | 1.36 GB | none (a `pip install`) |
| Memory after the sync | 1.09 GB | one process |
| Start | 63 s until its API answered | 0 |
| Configure | A token, then one team per repo through its API | 0 (defaults) |
| Read 5 repos | 319 s, 690 GitHub requests | 584 s in the DevLake run on the same kind of runner; 78 requests for the merge-based pass here (data already kept) |
| Token | A personal access token (it calls `GET /user`); the built-in workflow token isn't enough | The workflow's own token |

## How far back each one read

Asked for 90 days (`DEFAULT_SYNC_DAYS=90`), Middleware returned pull requests from about the last 31 to 36 days on four
of the five repos (from 23 or 28 September) and 90 days only on nodejs/nodejs.org. Its deployment counts below are
smaller mostly for that reason; we didn't find why, and report what it returned.

## DORA, per repo

Deployments are counted the way Middleware counts them (every merge into the default branch) and, for StackVitals,
also from GitHub's Deployments API, which all five repos use and which StackVitals reads by default.

| Repo | Deployments, Middleware | StackVitals, every merge | StackVitals, Deployments API | Lead time, Middleware (mean) | StackVitals, every merge (median / mean) |
|---|---|---|---|---|---|
| getsentry/dotagents | 14 | 39 | 48 | 59.3 h | 1.6 h / 85.8 h |
| vercel-labs/run | 11 | 78 | 55 | 22.3 h | 0.22 h / 4.5 h |
| truffle-ai/dexto | 51 | 62 | 61 | 4.8 h | 0.47 h / 54.3 h |
| lissy93/bug-bounties | 19 | 68 | 40 | 1.9 h | 0.68 h / 5.2 h |
| nodejs/nodejs.org | 55 | 137 | 110 | 142.4 h | 62.1 h / 199.3 h |

Middleware reports a mean lead time and StackVitals a median (as DevLake and the DORA reports do), and a few PRs that sat
open for weeks pull a mean far from the typical PR; so the headline numbers aren't comparable, and the PR-by-PR check
below is the real test.

Change failure rate and time to restore: no repo had a revert or incident in the window. Middleware shows 0%;
StackVitals shows "N/A" when no incident was found at all, as DevLake does.

## Lead time, pull request by pull request

On the **96 pull requests both tools counted, 95 lead times agree within 10%** (or 5 minutes). The one that doesn't,
truffle-ai/dexto#926, was written on 22 July and rebased on 28 September: StackVitals starts the clock at the first
commit's author date (when the work began, 1,642 h), Middleware at its committer date (when it was rebased, 8.5 h).
The same choice gives Middleware a negative "first commit to open" time on 21 pull requests that were rebased after
being opened.

Pull requests only one tool counted:
- **Only Middleware:** bot pull requests (dependabot, github-actions, liss-bot, sentry-junior) and one human pull
  request on dexto. StackVitals leaves bots out of lead time by default, so people's work isn't diluted by them.
- **Only StackVitals:** the older pull requests from the part of the 90 days Middleware didn't return.

## Where this run departed from the protocol

- The pre-registration asked for StackVitals with `source = "merges"` on the runner. The workflow ran only the default
  pass, so the merge-based pass ran afterwards from a laptop (25 minutes later), over the same 90 days.
- That pass crashed at first: `source = "merges"` failed in the deploy dry run (a missing entry in a lookup). Fixed,
  with a test, before the numbers above were taken.

## Reading it

On the same pull requests the two tools agree on lead time almost exactly, except where a rebase hides when work began.
The differences are in reach and setup: Middleware needs a container, a personal token and per-team configuration,
returned a month of history where 90 days were asked for, and can't use GitHub's Deployments API; StackVitals runs in
the workflow with its own token and reads either source.
