---
name: stackvitals-delivery
description: Use when asked about a repo's cycle time, DORA metrics (deployment frequency, lead time, change failure rate, recovery), stuck or slow pull requests, or what to fix first to ship faster. Answers with StackVitals Delivery and Insights.
---

# Delivery: where the time goes, and what to fix first

Needs the StackVitals MCP server with every tool: `stackvitals serve --tools all` (the default 11 leave some of the tools below out).

## Steps

1. **What to fix first:** call `insights` (CLI: `stackvitals insights owner/repo`). Its findings are ranked by the hours of
   waiting at stake, each with evidence links and the action. Start your answer with the top one or two and their numbers.
   If it says "nothing stands out yet", say so (findings need about 10 merged PRs) and lead with step 4 instead.
2. **Cycle time:** call `cycle_time` (CLI: `stackvitals delivery owner/repo`). Give the phase with the largest P75
   (coding, pickup, review, approve, merge or deploy), its LinearB band, and the number of PRs behind it.
3. **DORA:** call `delivery_health` (CLI: `stackvitals delivery owner/repo --json`; read `deploy_source`,
   `deploy_confidence`, `deploy_names` and `dora`). Say where deployments came from and how sure that is: "deployments api"
   is sure, "releases" fairly sure, workflow names a guess. When it is a guess, name the workflows counted and say one line
   in `.github/stackvitals.toml` fixes it. `dora.rework_rate` is DORA's fifth key (deployments that shipped a revert or
   hotfix); give it with `rework_deployments` of `deployments_n`. For AI-assisted work read `ai.outcomes.window`: AI-assisted
   and other PRs after merge, an association and never about a person. With a merge queue, `merge_queue` gives the time
   from entering it to merge (p50, p90), removals by reason and the removals a known flaky job caused. For "where does
   our time go", `investment` gives merged PRs by kind of work per month with `decided_by`; when `other` is large, suggest
   a label rule under `[investment.labels]`.
4. **Stuck pull requests:** call `stuck_prs` (CLI: the `Stuck` lines of `stackvitals delivery owner/repo`, or `stuck` in
   its `--json`) for reviews asked 3+ days ago and not started, PRs open over 30 days, long discussions, and failing checks
   nobody acted on; link them as https://github.com/owner/repo/pull/N.
5. **Numbers DevLake users know:** `stackvitals export owner/repo --format devlake --out <folder>` writes DevLake's tables
   and `dora.sql`, DevLake's own DORA SQL, to check against.

## Notes

- Every number has an n; under 10 PRs a phase says "not enough data": repeat that rather than inventing a figure.
- Findings never name reviewers; keep it that way in your answer.
