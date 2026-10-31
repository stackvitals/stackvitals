# Questions people ask

## Is it really free? What's the catch?

It is licensed under Apache 2.0 and runs in your own GitHub Actions minutes, which are free for public repos and included in every
plan for private ones. There is no paid tier, no account and no StackVitals-hosted backend.
Optional integrations (a tracker, chat, a model for triage, storage outside git) use services and keys you choose, under
their own terms ([governance](../GOVERNANCE.md)).

## Does my code or data leave GitHub?

History is files on a branch of your repo, and your code is never sent anywhere. By default the dependency check
sends your dependencies' package names to deps.dev, OpenSSF Scorecard and the registries' download counts; set
`[deps] outside_lookups = false` to keep them in GitHub. Explore and the printable pages load their libraries from
public CDNs. Anything else (your Jira, your chat) needs a key you add. Each host and what it gets is listed on
[privacy](privacy.md).

## How many Actions minutes does it use?

A run takes about a minute on a small repo. It starts after your CI workflows and every 3 hours, so a busy repo runs
it often; on private repos, check that against your plan's minutes. For the busiest public repos (2,000 CI runs a
day), CI Health alone is estimated at under 40% of the built-in token's API limit ([scaling](scaling.md)).

## How is this different from asking an AI agent to look at my CI?

An agent with GitHub access sees what GitHub still has: 90 days of logs and whatever it can read in one chat.
StackVitals keeps the history after GitHub deletes it, has already counted how often each test flaked, and compares
your repo with similar public ones from a daily crawl. On a single fresh failure a good agent does as well alone; we
measured that and say so ([agents card](../bench/accuracy/agents/README.md)). The two work together: the MCP server
gives agents StackVitals' history.

## How is it different from LinearB, Swarmia, Trunk or DevLake?

They are good tools. StackVitals differs in three ways: it is free and has no hosted backend; the rules behind its verdicts
and headline numbers are checked on public data with the losses published ([accuracy](accuracy.md)); and it compares like with like (the same repo,
month and size) before saying something changed. Where we measured their default rules on the same data, the
results are on the cards, including where theirs tie ours.

## Can it rate developers?

No. People are named only to route work (an owner, who acts next on a pull request). The [DORA guide](dora-guide.md)
explains why team numbers must never be used for individual reviews.

## Why does it say "not enough data" so often?

Because a number from three pull requests misleads. Each figure shows its sample size, and below a floor it says so
instead of guessing. Small repos borrow strength from similar repos where that has been checked to help.

## A verdict was wrong. What do I do?

Say so with `/stackvitals dispute test:<id> because <why>` (or `confirm` when it was right). It is recorded with who
and why, and CI Health shows how often your team confirmed each kind of verdict. If the run is public, an issue with
its link helps the next accuracy check.

## Does it work with GitLab, Jenkins or Buildkite?

GitLab CI: a job you include in `.gitlab-ci.yml` keeps the pipeline history, publishes CI Health on GitLab Pages and
notes failed merge requests (preview; [connectors](connectors.md#gitlab)). Test reports from Jenkins, CircleCI and
Buildkite can be uploaded with `stackvitals ci upload`. Everything else reads GitHub ([connectors](connectors.md), [limitations](limitations.md)).

## Does it work on GitHub Enterprise Server?

The Action reads the API and GraphQL addresses GitHub Actions gives every job (`GITHUB_API_URL`,
`GITHUB_GRAPHQL_URL`), so on GitHub Enterprise Server it talks to your server, not github.com. Two limits: links in
the app point to github.com pages, and the daily crawl's peer comparisons cover public github.com repos only. The
command line takes the same two variables when you run it against your server.

## Is there a login, with roles for who sees what?

Yes, and it is GitHub's own. The app uses your GitHub token (or GitHub sign-in, where the site has a sign-in relay) and reads each repo's data branch with your access, so a
person sees exactly the repos GitHub already lets them read, and an org's roles (members, outside collaborators, teams)
apply unchanged; Portal's org view shows only the repos the viewer can open. Nothing is copied to a server of ours to
guard, so there is no second user list to keep in step. What you don't get is a separate admin screen for roles: you
manage them where you already do, in GitHub.

## Our repos are private. Can we still see the dashboard?

Yes, three ways. Run `stackvitals ui OWNER/REPO` to open it on your machine. Set `pages: artifact`: each run that
changed the app uploads it as a download kept 7 days; unzip it and run `python -m http.server 8000 --bind 127.0.0.1`
in the folder (opening `index.html` directly doesn't work). Or use Pages if your plan keeps Pages private
([enterprise](enterprise.md)).

## What happens if a run fails halfway?

Nothing is half-written: each run commits once, and the next run catches up. The tested failure modes are listed in
[limitations](limitations.md#failure-modes).
