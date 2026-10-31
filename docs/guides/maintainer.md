# StackVitals for an open-source maintainer

You want red CI to stop eating contributors' time, newcomers answered, and fewer surprise dependency breaks. The Action
is free on public repos and needs only the built-in token.

## Set it up

[Quickstart](../quickstart.md): `stackvitals init owner/repo` adds the workflow file, runs it once and turns on GitHub Pages from the `stackvitals-data` branch. Your
dashboard is public like your repo. Your code stays in GitHub; the dependency check sends package names to deps.dev
and the registries unless you set `[deps] outside_lookups = false` ([privacy](../privacy.md)).

## CI that contributors can trust

- When CI fails on a pull request, one comment says which failures are known flakes, which already fail on the
  default branch and which are likely the change's own ([modules](../modules.md#ci-health)). The verdict check still
  blocks until CI is green, so a flake is re-run, never waved through.
- Upload test reports (JUnit XML, CTRF, Jest, Vitest, `go test -json`, TRX) to see single flaky tests, not just jobs.
- Opt in under `[automation]` to re-run known flakes once, open one issue per flaky test, or quarantine one.
- Contributors and agents can ask `stackvitals contribute brief owner/repo` for how changes get merged here: what
  merged pull requests usually include, who reviews each folder, and which tests are flaky.

## Newcomers

Community shows how fast issues get a first answer from the project (maintainers, regular responders and triagers;
drive-by comments don't count), where newcomers drop out, and who carries the work
([modules](../modules.md#community)). Issues still waiting stay in the median, so a slow week can't hide.

## Dependencies

On each pull request that changes a lockfile, the Dependency Steward checks what was added or upgraded: advisories on
the installed version, look-alike names, licence changes, and how the same upgrade went in other public repos
([modules](../modules.md#dependency-steward)).

## Commands

Anyone with triage access can decide from a comment: `/stackvitals acknowledge`, `mute`, `snooze`, `quarantine`, `accept` and more, with `for 14d` and
`because <reason>`. Every decision is recorded with who and why, and temporary ones end on their own ([all commands](../modules.md#decide-on-github-hear-back-every-week)).
