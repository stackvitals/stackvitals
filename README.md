# StackVitals

[![PyPI](https://img.shields.io/pypi/v/stackvitals)](https://pypi.org/project/stackvitals/)
[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-StackVitals-green?logo=github)](https://github.com/marketplace/actions/stackvitals)
[![Tests](https://github.com/stackvitals/stackvitals/actions/workflows/tests.yml/badge.svg)](https://github.com/stackvitals/stackvitals/actions/workflows/tests.yml)

A free, open-source developer suite for GitHub: CI health and flaky tests, pull request flow, delivery and DORA,
dependencies, community health and an org portal. It runs in your own GitHub Actions and keeps its history in your own
repo: no StackVitals-hosted backend, account or subscription, and optional integrations use services and keys you
choose. GitHub's built-in token covers every module in a repo; an org's private repos in the Portal need a read-only
App, and org-wide Copilot usage an org token. Actions minutes on private repos are billed by GitHub as usual
([docs/scaling.md](docs/scaling.md#actions-minutes-private-repos)). The rules behind its verdicts are checked on public
data, with the losses published.

Every run publishes an app on your repo's GitHub Pages (or `stackvitals ui owner/repo` on your machine): one page per
module, decisions and settings saved straight from the browser, setup for more repos in a few clicks once GitHub is
connected (connecting takes one token, made from a prefilled GitHub page; Pages are turned on for public repos), and a demo at
`?demo=1`. [docs/app.md](docs/app.md) walks through it.

Install it as the GitHub Action `stackvitals/stackvitals@v0` (also on the
[GitHub Marketplace](https://github.com/marketplace/actions/stackvitals)), or the CLI and MCP server from PyPI:
`pip install stackvitals` (or run it without installing: `uvx stackvitals`).

<!-- mcp-name: io.github.stackvitals/stackvitals -->

## Three things it gets right that others get wrong

Measured on public repos beside the rules other tools use ([docs/accuracy.md](docs/accuracy.md)):

- **Where you deploy from.** With no setup, StackVitals named the right deployment source for 53 of 60 repos (30 of
  35 held out). On the same 60, DevLake's default pattern got 9 and a pattern a user would typically write got 22. A
  wrong source makes every DORA number wrong.
- **Who answered an issue.** Of the first comments by non-maintainers that the github/issue-metrics action counts as
  the answer, 46% are drive-bys (40-52%, held-out repos). StackVitals counts the project's answers: maintainers,
  regular responders and triagers.
- **Whether AI help changed anything.** Agents' pull requests look 9 points less likely than people's to be merged by someone else.
  Compared within the same repo, month and size, the gap is +0.5 points (0.0 to +1.1): most of the raw gap comes
  from which repos agents work in and the size of their changes.

It publishes what failed too. Of the failures an old rule called safe to re-run, 44% (15 of 34) were caused by the
change. The tightened rule still got 13 of 81 held-out calls wrong (16%). A stricter one (a flake's sign in the log,
no changed file named) got none of 4 fresh calls wrong, too few to show 5%, so nothing is called safe: likely flakes
are re-run, never passed by the check. Each sample was labelled by two
model families (Claude and Gemini); no person has audited the labels.

## What you see first

When CI fails on a pull request, one comment sorts each failure, from the repo's own CI history:

> **StackVitals: about this CI failure**
> 1 of 3 failure(s) look like flakes; the rest need a look.
>
> | Verdict | What failed | Why |
> |---|---|---|
> | Likely flaky | test `t::flaky_one` | flaked 6 times in 80 runs in the last 30 days, last 2026-10-20, and the message shows a flake's sign ("TimeoutError"): looks like a flake, check the error, then re-run it |
> | New | test `t::new_one` | no earlier flakes: likely from this change (fails with "assert result == 2") |
> | Already failing on main | test `t::broken_one` | also failing on the default branch, not caused by this change |

The verdict check still blocks until CI is green: a known flake is re-run, never waved through.

## Modules

| Module | What it answers | Status |
|---|---|---|
| **[CI Health](docs/modules.md#ci-health)** | Which jobs and tests are flaky or slowing down, who owns them, coverage and patch coverage | stable |
| **[Team Flow](docs/modules.md#team-flow)** | Who has to act next on each pull request, and how long reviews take | stable |
| **[Delivery](docs/modules.md#delivery-cycle-time-and-dora)** | Cycle time split into coding, pickup, review and deploy (LinearB's phases), DORA's five metrics, AI-assisted work compared like with like | stable |
| **[Insights](docs/modules.md#insights-what-to-fix-first)** | What to fix first across modules, ranked by hours lost, with alerts and a weekly digest | stable |
| **[Dependency Steward](docs/modules.md#dependency-steward)** | Known vulnerabilities and malware in the lockfiles OSV-Scanner reads (npm, PyPI, Go, Rust, Maven, Ruby, .NET, PHP and more; 65 of 100 sampled repos had one); whether to add, keep or upgrade a package, with upgrade evidence from public repos | preview |
| **[Community](docs/modules.md#community)** | Where newcomers drop out, how fast they get an answer, who carries the work | stable |
| **[Portal](docs/modules.md#portal)** | A lightweight catalog on GitHub alone: what an org owns, who owns it (checked), scorecards, golden paths and an org-wide view | preview |
| **Explore** | SQL over your repo's data in the browser, with links to share a query | preview |
| **[Contribute](docs/modules.md#contribute-mergescout)** | Open-source issues an outsider can realistically get merged | stable |

Stable: measured, reviewed and used on the sandbox for every release. Preview: built and tested, but newer or measured on
less; its behaviour may still change.

**Works with** Jira Cloud, Linear, PagerDuty, incident.io, Copilot usage reports, Slack, Teams, Discord, Discourse,
test reports from other CI systems, Backstage, and DevLake's tables ([docs/connectors.md](docs/connectors.md)). AI
agents get every module through one MCP server (11 core tools by default, all 35 with `--tools all`).

## Start

- **Five minutes:** [docs/quickstart.md](docs/quickstart.md). Try CI Health on any public repo first (needs
  [uv](https://docs.astral.sh/uv/) and `gh auth login` or a `GITHUB_TOKEN`):
  `uvx stackvitals ci report owner/repo --days 14 --html ./ci-report`.
- **By role:** [engineering managers](docs/guides/manager.md), [maintainers](docs/guides/maintainer.md),
  [platform teams](docs/guides/platform.md).
- **Before you rely on it:** [what each rule does](docs/rules.md), [known limitations](docs/limitations.md),
  [what leaves your repo](docs/privacy.md), [threat model](docs/threat-model.md), [enterprise controls](docs/enterprise.md).
- **More:** [FAQ](docs/faq.md), [how it works](docs/architecture.md), [roadmap](docs/roadmap.md),
  [contributing](CONTRIBUTING.md), [governance](GOVERNANCE.md), [security](SECURITY.md).
