# StackVitals compared with other tools

What each tool does better, what StackVitals does differently, and what was measured side by side. Checked 2026-11-01; each page names its sources.

| Tool | Kind | What it is |
|---|---|---|
| [Apache DevLake](devlake.md) | Open source (Apache 2.0), self-hosted | A data platform that collects DevOps data from about 50 tools into one model and shows it in Grafana, with DORA's five metrics. |
| [Middleware](middleware.md) | Open source (Apache 2.0), self-hosted | An open-source DORA app (middlewarehq/middleware) with its own web UI. |
| [CDviz](cdviz.md) | Open source (Apache 2.0), self-hosted or EUR 20/month hosted | Delivery observability built on CDEvents, the CD Foundation's event standard: a collector, Postgres with TimescaleDB, and Grafana. |
| [Pelorus](pelorus.md) | Open source (Apache 2.0), on OpenShift | A Red Hat community project measuring DORA's four metrics with Prometheus exporters and Grafana. |
| [Liatrio's DORA plugin for Backstage](liatrio-backstage.md) | Open source (Apache 2.0) | A Backstage plugin showing DORA metrics per service. |
| [Faros Community Edition](faros-community-edition.md) | Open source (Apache 2.0), withdrawn | An engineering-operations platform (Airbyte, Postgres, Hasura, Metabase, dbt, n8n). |
| [GrimoireLab](grimoirelab.md) | Open source (GPL-3.0), self-hosted | CHAOSS's software-analytics toolset: 30+ sources, identity merging and community-health dashboards. |
| [LinearB](linearb.md) | SaaS; gitStream automation is free up to 250 PRs a month | A commercial engineering-metrics product with DORA, and gitStream rules that automate pull requests. |
| [Swarmia](swarmia.md) | SaaS; free up to 9 developers | A commercial engineering-effectiveness product: DORA, developer surveys, AI-adoption tracking and software capitalization. |
| [Trunk Flaky Tests and BuildPulse](flaky-test-tools.md) | SaaS | Flaky-test services: they read JUnit reports from CI, detect flaky tests and quarantine them. |

## StackVitals in facts

- Runs as a GitHub Action in your own repo: no server of ours, no Docker, no account; history is kept on a `stackvitals-data` branch in the same repo. ([more](../architecture.md))
- Reads GitHub's API with the workflow's own token: Actions runs, jobs, logs and test reports, pull requests, reviews, releases and deployments. It doesn't use git hooks and doesn't point at lines of code. ([more](../connectors.md))
- On a pull request whose CI failed, one comment sorts each failure: likely flaky, already failing on main, new, and a few more; no verdict passes the check by itself. ([more](../modules.md))
- Deployments come from GitHub's Deployments API, deploy workflows and releases, found without setup, and from any other tool (Argo CD, Jenkins, a shell script) through `stackvitals record` or a `repository_dispatch` event. ([more](../connectors.md#deployments-and-incidents-from-elsewhere))
- It acts as well as reports: alerts to Slack, Teams, Discord or a webhook, opt-in re-runs of flaky jobs, issues, quarantine, suggested reviewers and size labels. ([more](../modules.md))
- Optional connectors: Jira, Linear, PagerDuty, incident.io, Slack and Discord channels, Discourse, GitLab, Bitbucket and Azure DevOps, SonarQube, test reports from Jenkins, CircleCI and Buildkite, AI spend. ([more](../connectors.md))
- SQL over the history in the browser and with `stackvitals sql`; an export with DevLake's table names for Postgres; Backstage catalog entities with the repo's level as an annotation (no card inside Backstage). ([more](../scaling.md))
- Speaks CDEvents: deployments, rollbacks and incidents come in as CDEvents or from Flux; alerts, newly flaky tests and pull request verdicts go out as CDEvents custom events, to a URL or as repository_dispatch. ([more](../connectors.md#findings-as-events))
- An MCP server gives AI agents the same history and verdicts. ([more](../architecture.md))
- Every verdict's rule is checked on public data and the misses are published. ([more](../accuracy.md))
