# How StackVitals works

StackVitals has no hosted backend. Everything happens in three places you already have: a GitHub Actions job in your repo, a
branch of your repo, and the reader's browser.

```
 your CI runs ──► StackVitals job (GitHub Actions, your token)
                    │  reads: Actions runs and logs, pull requests, issues, deployments, test reports
                    │  reads (optional, your keys): Jira, Linear, PagerDuty, incident.io, Copilot, Slack, Discord
                    ▼
                  stackvitals-data branch (one commit per job)
                    ├─ ci/  flow/  community/  deps/  portal/  connectors/   history, one file per day
                    ├─ summary/   tables the app and Explore read
                    ├─ decisions/log.ndjson   every decision and settings change, who and why
                    └─ docs/   the app (static files) ──► GitHub Pages, a 7-day artifact, or `stackvitals ui`
                    │
                    ├─► pull request comment and verdict check, issues, chat alerts (after the commit)
                    └─► MCP server for AI agents (reads the same branch, or GitHub live)

 cross-repo evidence (built once a day by the crawler, published as data, never your private data):
   peers for benchmarks, upgrade outcomes for packages, maintainers' merge habits for Contribute
```

## One job, one commit

Each run of the Action opens one shallow checkout of the `stackvitals-data` branch, runs every module named in
`modules:` against it, keeps house (retention, the size cap) and commits once
([core/workspace.py](../src/stackvitals/core/workspace.py)). If another run pushed first, the push is rejected and
every step runs again on the fresh data, so overlapping runs converge without losing either side. What talks to people
(comments, issues, chat) runs only after the commit, so a refused comment never loses data and a re-run never posts
twice.

A module that fails is reported in the job summary; the others still run and save. A run that runs out of API budget
saves what it read and says what it left; the next run carries on.

## Storage

History is plain files: one gzipped NDJSON file per day per stream, with retention per stream (CI days 180 days,
transitions and closed pull requests 400, Copilot 730) and a size cap (250 MB by default) that drops the oldest days
first ([scaling.md](scaling.md)). Busy public repos store about 1 KB per CI run. An opt-in squash rewrites the branch's
git history to one commit every 1,000 commits; the files stay byte for byte.

Nothing in the branch is a secret: tokens and keys live in Actions secrets, and on a public repo, tracker titles,
links and people's affiliations are never written ([privacy.md](privacy.md)).

## The app

The app is static: Preact and TypeScript bundled ahead of time (`web/`, built into the package) and copied into the
branch's `docs/` folder as `index.html` and `app/`, with a content security policy that allows only its own scripts. Explore and the printable module pages are separate pages
that load DuckDB and Chart.js from public CDNs at pinned versions. It reads the JSON tables the job wrote. Settings and
decisions made in the app are sent as GitHub issues or comments that the next job applies, or, with the person's own
GitHub token, committed or run straight from the browser; either way GitHub checks the sender's permissions and the
change is recorded in `decisions/log.ndjson`. Explore loads DuckDB in the browser
(from jsDelivr) to run SQL over the same tables.

## Rules and their evidence

The verdicts and headline numbers come from rules listed in [bench/accuracy/registry.json](../bench/accuracy/registry.json):
what it was tuned on, the held-out data it was checked on, the bar it had to meet and every change since
([rules.md](rules.md)). Each card in `bench/accuracy/` holds the method and the results;
[accuracy.md](accuracy.md) is generated from them, and a test fails when a page and its data disagree.

## Cross-repo evidence

What a single repo can't know (how similar repos compare, whether an upgrade broke other projects, how a maintainer
reviews outsiders) comes from a crawl of public repos (a list of about 125,000, about 90,000 of them sampled for CI benchmarks) run by
the project's own scheduled workflows
in `deploy/crawler/`. It publishes aggregates only. Your job reads them; it never sends your data back.

## Code map

| Folder | What it holds |
|---|---|
| `src/stackvitals/ci` | CI Health: collecting runs and test reports, flake detection, the PR verdict, automation |
| `src/stackvitals/flow` | Team Flow: who acts next, review stages, preflight |
| `src/stackvitals/core` | the shared job (workspace, store, settings, decisions), Delivery and DORA, Insights, Explore, the app's data |
| `src/stackvitals/deps` | Dependency Steward |
| `src/stackvitals/community` | Community health |
| `src/stackvitals/portal` | Portal: catalog, owners, scorecards, campaigns, golden paths, the org view |
| `src/stackvitals/connectors` | Jira, Linear, PagerDuty, incident.io, Copilot, Slack, Discord, Discourse |
| `src/stackvitals/web` | the app and the site |
| `src/stackvitals/mcp_server.py` | the MCP server |
| `src/mergescout` | Contribute (MergeScout) |
| `bench/accuracy` | accuracy cards, the rule registry and the generators for the accuracy pages |
| `worker/` | optional Cloudflare Worker for instant alerts |
| `deploy/crawler` | the crawler's workflows |
