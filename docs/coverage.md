# Coverage and peer groups

When StackVitals compares your repo with "similar public repos", the peers come from the MergeScout crawler, which reads public GitHub repos daily on GitHub Actions. This page says what it reads, what it misses, and how each peer group is formed.

## What the crawl reads

- **Repos:** public repos with 100+ stars pushed in the last 90 days, without forks or archived repos; about 125,000. The list is rebuilt from scratch each month.
- **Order:** source repos of tracked packages first, then repos with the most beginner-labelled issues per API cost.
- **Per repo:** settings and contributing rules; up to 300 pull requests opened in the last 365 days, newest first, with their first 5 reviews; up to 200 open issues active in the last 90 days, with their last 5 comments.
- **Refreshes:** the crawl runs hourly until that hour's API points run out. Repos with beginner-labelled issues are due again after 1 day, others after 7. A refresh fetches only changes; a full crawl comes back every 30 days.
- **CI, stars and shipping samples:** a separate daily job reads a 28th of the repos with 100+ stars pushed in the last 30 days (about 90,000), so each is read about once every 4 weeks: the newest 50 push runs, the weekly star history, and 90 days of deployments and releases.

The first full crawl (fetched 2026-10-16 to 18) held 1,653,419 pull requests from 23,100 repos.

## What it misses

- Private and enterprise repos; repos under 100 stars, forks, archived repos, and repos with no recent push.
- GitLab, Bitbucket and other hosts; CI other than GitHub Actions; CI runs on pull requests.
- Older history of busy repos: only the newest 300 pull requests of the year are read, so their window is shorter. In the first full crawl, 2,430 of 23,100 repos reached 300.
- A pull request's CI result, read only for dependency-bot pull requests: empty for 98% of pull requests in the first full crawl. Only the upgrade ledger uses it.
- Draft history (pickup counts from opening), who closed an issue, reviews after the fifth, and deployments made outside GitHub.
- Repos the queue has not reached yet. Until it has, the crawled set leans toward repos with beginner-labelled issues.

## Peer groups, benchmark by benchmark

Most groups use the repo's main language (the 25 most common; the rest are "Other") and its stars band (100-1k, 1k-10k, 10k+). If that group is missing or too small, StackVitals tries the language at any size, then any language at that size, then all repos. If none qualifies, no comparison is shown. People's numbers leave out bots and AI agents.

| Benchmark | Used on | How peers are grouped | Minimum group size | Refresh | Notes |
|---|---|---|---|---|---|
| CI push time and first-try green (`ci-benchmarks.json`) | CI Health; Portal silver rule | Language, stars band | 20 repos | Daily sample, each repo every 4 weeks | Under 30 pushes, your share is also pulled toward the group. |
| Review flow: first review, opened to merged, outside PRs merged, PR size (`flow-benchmarks.json`) | Team Flow; contributor brief; Portal first-review rules | Language, stars band; repos with 10+ people's PRs in 90 days | 50 repos per metric | Daily | Portal silver: better than half; gold: better than three quarters. |
| Delivery P75: pickup, review, opened to merged (`delivery-benchmarks.json`) | Delivery page | As flow; 5+ values per metric | 50 repos per metric | Daily | Shares inside LinearB's 2026 bands. |
| Coding agents' PRs next to people's (`flow-benchmarks.json`) | Delivery page; contributor brief | As flow; the gap matches repo, month and size | 20 repos | Daily, 180 days | Merge shares need 5+ decided agent and outside PRs per repo. |
| Community: first answer, newcomers, top person's share, bus factor (`community-benchmarks.json`) | Community page and score | Language, stars band; 10+ outside PRs, 10+ newcomers or 20+ merged PRs | 50 repos per fact | Daily | Score needs two facts. Newcomer table pools all repos. |
| Star growth, 12 weeks (`stars-benchmarks.json`) | Community page | Language, stars band | 20 repos | Daily sample, each repo every 4 weeks | Only repos with 100+ stars are compared. |
| Upgrade outcomes (`deps-ledger.json`) | Dependency Steward, `deps check`, MCP `supply_chain` | Ecosystem, package, step (major, minor, patch) | 3 PRs to publish; rates from 30 PRs in 10 repos | Daily, 180 days | Dependabot and Renovate PRs. |
| Package map, advisories, owners, trends (`deps-map`, `deps-osv`, `deps-owners`, `deps-trends`) | As above | Per package, no peer group | None | Daily; map reused a week, advisories until changed | 1,000 most-used npm and PyPI packages, plus upgraded ones. |
| Shipping frequency (`deploys-benchmarks.json`) | Not shown yet | Language, stars band | 20 repos with a source | Daily sample | Built, not read by StackVitals. |

Sizes in the files built 2026-10-20 to 22: CI 6,623 repos, review flow and delivery 35,925, community 22,957, stars 5,916, coding agents 611. The smallest published groups held 20 repos (CI, stars) and 53 (flow, delivery, community). The upgrade ledger built 2026-10-21 held 125,992 merged upgrades in 6,420 cells.

## How fresh the numbers are

- Flow, delivery, community and dependency files are rebuilt daily from the crawl. A file that fails to build keeps yesterday's version.
- CI, stars and shipping files are rebuilt daily from 35 days of samples, so a repo's sample can be 5 weeks old.
- A repo's crawled data is 1 to 7 days old when the hourly crawl keeps up, older when it falls behind.
- StackVitals keeps a downloaded file for a day. Every comparison shows when its file was built.
- Windows: CI 30 days; review flow, delivery and first answers 90 days; who carries the work, coding agents and upgrades 180 days.

## How to read a comparison

- Read the group name and repo count first. "Python repos with 1k-10k stars" is closer than "public repos we track"; a wide group means the narrow one was too small.
- Places are rough: read from the group's 10th to 90th percentiles, kept between 10% and 90%, rounded down to 5.
- Your repo is measured the crawl's way: same window, people only. Flow and delivery need 10+ people's PRs from your repo in 90 days.
- Delivery ranges are 95% ranges for the typical value; Community's low and high are the group's 25th and 75th percentiles.
- Peers are public repos with 100+ stars. A private team can differ for good reasons.
- To use your own file, set `STACKVITALS_BENCH_URL` or the matching variable for that benchmark.
