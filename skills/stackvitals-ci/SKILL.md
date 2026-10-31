---
name: stackvitals-ci
description: Use when a CI run, GitHub Actions job or test has failed, before changing code to fix it. Checks the repo's CI history with the StackVitals MCP tools to tell known flaky failures (re-run) from failures caused by the change (fix).
---

# CI failed: check history before fixing

Needs the StackVitals MCP server with every tool (`pip install stackvitals`, then in Claude Code `claude mcp add stackvitals -- uvx stackvitals serve --tools all`): `stackvitals serve --tools all` (the default 11 leave some of the tools below out).

Agents waste hours "fixing" tests that only failed by chance. StackVitals keeps each repo's CI history, so check it first.

## Steps

1. **Get the failed run's URL.** Use the PR's checks, or `gh run list --limit 5` and then `gh run view <id> --json url`.
2. **Call `ci_failure` with that URL.** Each failure comes back with a verdict:
   - **known flaky:** it failed and then passed with no code change before. Re-run the failed jobs (`gh run rerun <id> --failed`) instead of changing code. Tell the user it is a known flake and give the numbers (for example "flaked 6 times in 80 runs").
   - **already failing:** it also fails on the default branch, so the change didn't cause it. Say so, and don't fix it as part of this change unless asked.
   - **new:** no flaky history. Treat it as caused by the change. Read the failing step or test and its message, then fix it.
3. **Before rewriting a test that looks flaky,** call `is_known_flake` with part of its name. Its failure history (how often, last seen, typical message) tells you whether the test or the code is at fault.
4. **When a failure belongs to a group** (`ci_failure` or `test_status` names one), call `failure_group` with its id: the same
   exception at the same place across tests and runs, with an `investigation_prompt` listing the runs to read and what to
   find out. Work through that list instead of starting from one log.
5. **When asked why CI is slow,** call `ci_slowest` (the slowest jobs and tests with daily medians, anything that got slower
   this week, new tests and skipped tests) and `ci_health` for the overall picture. To split a slow suite, suggest
   `stackvitals ci shards owner/repo --n N`.
6. **When asked about coverage,** read `coverage` in `ci_health`: the default branch's line coverage with its trend, and
   each pull request's patch coverage (added lines that ran, with the files that missed). Quote the line counts with the share.

## Notes

- Repos that run the StackVitals Action answer instantly from their `stackvitals-data` branch. Other repos are read live: the first call can take a minute, and later calls within the hour are instant.
- Quote the numbers you get back. Never call something flaky without them.
