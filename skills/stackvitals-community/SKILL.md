---
name: stackvitals-community
description: Use when asked how welcoming a repo is to new contributors, which newcomers are waiting for an answer, where contributors drop out, or how fast maintainers first answer issues and PRs. Answers with StackVitals Community.
---

# Community: newcomers waiting, and where they drop out

Needs the StackVitals MCP server with every tool: `stackvitals serve --tools all` (the default 11 leave some of the tools below out).

## Steps

1. **Who is waiting now:** call `newcomers_waiting` (CLI: `stackvitals community report owner/repo`, which prints them
   with links) and list the first-time contributors' issues and PRs still without an answer, oldest first.
2. **The picture:** call `community_health` (CLI: the same report; `--json` for the raw numbers) for the newcomer funnel
   (first contribution, second, regular), the time to a maintainer's first answer, and the score against similar repos.
   Give the numbers with their sample sizes; when there is no score, say which minimum the repo has not reached yet.
   `first_answers_by_tenure` says whether newcomers wait longer than regulars; `who_carries_the_work` gives the bus
   factor and the most active person's share with similar repos' typical values. Never name people.
3. **What to do:** suggest answering the oldest waiting newcomers first; a quick first answer is what the crawl ties most
   closely to newcomers coming back (an association, not proof of cause: say so). If nobody is waiting, say that and
   point to the answer times to keep.

## Notes

- Name no maintainer as slow; talk about the repo's answers, not people.
