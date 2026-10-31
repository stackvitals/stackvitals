# Using delivery numbers without fooling yourself

DORA's numbers describe a team's delivery system, not a person's work. They are useful for spotting where changes
wait and whether shipping got safer; they become useless the moment people work to move them. This page says what each
one can't tell you and how each is gamed, so a team can read them honestly.

## DORA's five metrics

DORA groups its [five software delivery metrics](https://dora.dev/guides/dora-metrics/) in two: throughput (deployment
frequency, change lead time, failed deployment recovery time) and instability (change fail rate, deployment rework
rate). StackVitals counts the first four with Apache DevLake's definitions (an incident blames the last production
deployment before it), and shows beside the change fail rate a second one where a revert blames the deployment that
shipped what it undid; rework rate is the share of deployments that shipped an unplanned fix. The tiers (elite,
high, medium, low) come from DevLake's 2023 table, which predates rework rate, so rework rate has no tier.
A pull request counts toward the production deployment that shipped it: the one whose commits (everything between it
and the deployment before it, read once and kept) hold its merge commit, as DevLake does; only when no range holds it
does the first deployment after the merge count. So a deploy of an older commit or a rollback doesn't take the pull
requests merged just before it.

## Never for individual reviews

Every number here is a property of how a team, its process and its tooling work together. A person's cycle time
depends on what they were given, who could review it and what broke that week. StackVitals never ranks people on its
pages, and its numbers shouldn't be used in performance reviews: once they are, people optimise the number instead of
the delivery, and the number stops meaning anything (Goodhart's law).

## Each number: what it can't tell, and how it gets gamed

| Number | What it can't tell you | How teams game it | What to look at beside it |
|---|---|---|---|
| Deployment frequency | Whether a deployment shipped anything users wanted; a repo that releases a library weekly isn't worse than one deploying a website hourly | Splitting one release into many, deploying empty or trivial changes, counting staging as production | Lead time and the deploy dry run (`stackvitals delivery owner/repo --deploys`): what counts as a deployment and why |
| Change lead time | Whether the change was the right one; time spent before the first commit (design, waiting for a decision) | Merging small cosmetic PRs to pull the median down, opening PRs late, skipping review | The four phases (coding, pickup, review, deploy; review split into approve and merge), the PR size mix, and merges without review |
| Change fail rate | Failures nobody linked to a deployment; failures caught before release; which deployment really caused it (in 15 regression reports that named the release that broke, the last release before the report was it 6 times) | Not labelling incidents, fixing forward without a revert or hotfix label, hiding incidents in a private tracker | Rework rate (deployments that shipped a revert or hotfix), and where incidents come from (labels, reverts, a pager tool) |
| Failed deployment recovery time | How bad the outage was or how many users it hit | Closing the incident issue before the fix ships, opening a new issue instead of reopening | The incident list with the deployment each is linked to, and whether a revert's fix chain agrees |
| Deployment rework rate | Planned refactoring (it counts only unplanned fixes) | Fixes without a revert or hotfix label | Change fail rate and the incident list |

## How StackVitals helps you read them

- **Ranges, not just numbers:** each figure comes with how sure it is (a range for the median, the number of PRs or
  deployments it rests on), and says "not enough data" below 10.
- **Where the numbers come from:** the deploy dry run shows which workflows, releases and environments count as
  deployments and why the rest don't; the incident list names each incident's source.
- **Tiers that could be either:** when the range crosses a DORA tier boundary, the page says which tiers the team could
  be in, not just one.
- **Measured against labels:** how often the deployment and incident rules are right is on the accuracy page
  (`docs/accuracy.md`), including where they fail.

## Further reading

- DORA's own guidance on the metrics and their misuse: <https://dora.dev/guides/dora-metrics-four-keys/>
- LinearB's definitions of the six cycle-time phases: <https://linearb.helpdocs.io/article/1s38stsugw-glossary-metrics>
