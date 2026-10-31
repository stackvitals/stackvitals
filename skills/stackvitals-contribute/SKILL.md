---
name: stackvitals-contribute
description: Use when someone wants an open-source issue to work on, asks whether an issue is free and likely to get merged, or is about to open a pull request in a repo they don't know. Answers with MergeScout's daily snapshot of public repos and StackVitals' repo brief.
---

# Contribute: issues you can get merged

Needs the StackVitals MCP server with every tool (`pip install stackvitals`, then in Claude Code `claude mcp add stackvitals -- uvx stackvitals serve --tools all`): `stackvitals serve --tools all` (the default 11 leave some of the tools below out).

## Steps

1. **Find issues:** call `find_issues` (filters: language, topic, beginner); CLI: `stackvitals contribute find --lang python
   --beginner`. Prefer the ones whose evidence shows outside contributors get merged there, and quote that evidence (merge
   rate with its sample size, review time). If the output says "Could not check for a new snapshot", the results may be
   days old: set `GH_TOKEN` (or `GITHUB_TOKEN`) and run it again before answering.
2. **Before starting one:** call `check_issue` with its URL (CLI: `stackvitals contribute check <url>`). If it says the
   issue is taken, closed, has a linked PR, or the repo rarely merges outside work, say so and pick another. "Linked PRs
   unknown without a token" means the check is incomplete: set the token and check again.
3. **Before writing the PR:** call `repo_brief` for the repo (CLI: `stackvitals contribute brief owner/repo`, a few minutes
   on a big repo), or `preflight` from Team Flow with the files you will change, and follow what merged PRs there usually
   include.
4. **After:** call `report_outcome` with what happened (CLI: `stackvitals contribute outcome`), so the evidence improves.

## Notes

- Say "not enough evidence" whenever a result does; never promise a merge.
