---
name: stackvitals-flow
description: Use when asked what is blocking a repo's pull requests, who should review a PR, why a PR is waiting, or whether a planned change looks like the PRs that get merged there. Answers from the repo's PR history with StackVitals Team Flow.
---

# Pull requests: who acts next, and what gets merged here

Needs the StackVitals MCP server with every tool: `stackvitals serve --tools all` (the default 11 leave some of the tools below out).

Guessing from the PR list misses how this repo actually works. Team Flow keeps the repo's review history, so ask it.

## Steps

1. **What is waiting and on whom:** call `pr_queue` (CLI: `stackvitals flow report owner/repo`, `--json` for the raw
   numbers). Each open PR comes back with who acts next (reviewers asked, the author, or the maintainers), why, and since
   when. Lead with the overdue ones: they waited longer than this repo's own usual for that step. When the repo has no
   usual yet (shown as "-"), say that rather than calling anything slow.
2. **Who should review a PR nobody was asked to review:** call `who_should_review` with the PR number. It suggests people
   with its reason (they know the folders, own them in CODEOWNERS, and are not overloaded). It has no CLI form: without the
   MCP server, say suggestions need it, and never guess names.
3. **Before opening a PR:** call `preflight` with the paths you changed and the number of lines (CLI:
   `stackvitals flow preflight owner/repo --paths a.py b.py --lines 120`). Add what merged PRs there usually include
   (tests, a changelog entry, docs) and split the change if it is far bigger than usual.
4. **How review flows overall:** call `flow_health` (CLI: the same `stackvitals flow report`, which prints the review
   stages, insiders against outside contributors, and similar repos when they are known).

## Notes

- Quote the numbers with their sample sizes. Say "not enough data" when the answer does.
- Reviewers' answer times are private: use them to route work, never to rank people.
- Every command reads GitHub with `GH_TOKEN` or `GITHUB_TOKEN` (or the `gh` login).
