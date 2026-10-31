<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/lockup-dark.png">
    <img alt="StackVitals" src="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/lockup-light.png" width="420">
  </picture>
</p>

<p align="center"><b>The vital signs of your GitHub repo.</b> Flaky tests, slow reviews, delivery and DORA, risky
dependencies and community health, measured in your own GitHub Actions.</p>

<p align="center">
  <a href="https://pypi.org/project/stackvitals/"><img alt="PyPI" src="https://img.shields.io/pypi/v/stackvitals?label=PyPI"></a>
  <a href="https://github.com/marketplace/actions/stackvitals"><img alt="GitHub Marketplace" src="https://img.shields.io/badge/Marketplace-StackVitals-green?logo=github"></a>
  <a href="https://github.com/stackvitals/stackvitals/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/stackvitals/stackvitals/actions/workflows/tests.yml/badge.svg"></a>
</p>

<p align="center">
  <picture>
    <source type="image/avif" srcset="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/stackvitals-video.avif">
    <img alt="A 27-second tour: three failing CI checks sorted by StackVitals, then the app's Overview, CI Health, Pull Requests and Delivery pages" src="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/stackvitals-video.gif" width="880">
  </picture>
  <br><sub>A tour on demo data. <a href="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/stackvitals-video.mp4">Watch it with sound</a>.</sub>
</p>

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

<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-dark.png"><img alt="" src="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-light.png" width="100%"></picture>

# What you see first

When CI fails on a pull request, one comment sorts each failure, from the repo's own CI history:

> **StackVitals: about this CI failure**
>
> 1 of 3 failure(s) look like flakes; the rest need a look.
>
> | Verdict | What failed | Why |
> |---|---|---|
> | Likely flaky | test `t::flaky_one` | flaked 6 times in 80 runs in the last 30 days, last 2026-10-20, and the message shows a flake's sign ("TimeoutError"): looks like a flake, check the error, then re-run it |
> | New | test `t::new_one` | no earlier flakes: likely from this change (fails with "assert result == 2") |
> | Already failing on main | test `t::broken_one` | also failing on the default branch, not caused by this change |

The verdict check still blocks until CI is green: a known flake is re-run, never waved through.

<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-dark.png"><img alt="" src="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-light.png" width="100%"></picture>

# Quick start

```sh
pip install stackvitals
gh auth login                        # once, so StackVitals can use your GitHub sign-in
stackvitals init your-name/your-repo
```

`init` adds one workflow file to your repo, runs it once and turns on your dashboard:

- **Public repo:** the dashboard goes live at `https://your-name.github.io/your-repo/`.
- **Private repo:** your data stays in your private repo, and the dashboard opens on your machine:

  ```sh
  stackvitals ui your-name/your-repo
  ```

Just looking? `stackvitals ci report owner/repo` reports CI health for any public repo in about 20 seconds, with
nothing added to it. Prefer clicking? The app's **Setup** page does the same as `init`. More:
[docs/quickstart.md](docs/quickstart.md).

<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-dark.png"><img alt="" src="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-light.png" width="100%"></picture>

# How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/architecture-overview-dark.png">
  <img alt="How StackVitals works: your repo and your tools feed a StackVitals run in GitHub Actions (collect, analyse with six modules, save), which commits to the stackvitals-data branch and feeds the web app, PR comments, alerts and the MCP server. No server, no account." src="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/architecture-overview-light.png">
</picture>

Every step, from what starts a run to what you see: [the architecture in detail](docs/architecture.md).

<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-dark.png"><img alt="" src="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-light.png" width="100%"></picture>

# Modules

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

<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-dark.png"><img alt="" src="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-light.png" width="100%"></picture>

# Connect your tools (optional)

Everything works with GitHub's built-in token. Integrations are optional; pass their keys as repository secrets:

```yaml
- uses: stackvitals/stackvitals@v0
  with:
    webhook: ${{ secrets.SLACK_WEBHOOK }}            # alerts to Slack, Teams or Discord
    pagerduty-token: ${{ secrets.PAGERDUTY_TOKEN }}  # incidents count in DORA
    jira-email: ${{ secrets.JIRA_EMAIL }}            # Jira, with its site URL under
    jira-token: ${{ secrets.JIRA_TOKEN }}            # [connectors.jira] in .github/stackvitals.toml
```

Every input: [docs/install.md](docs/install.md). Every setting: [docs/settings.md](docs/settings.md).

<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-dark.png"><img alt="" src="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-light.png" width="100%"></picture>

# AI agents (MCP)

Your coding agent can ask StackVitals before and while it changes code: *is this failure a known flake?*, *what is
blocking PR #123?*, *who should review this?*, *is this package safe to add?* It answers from your repo's history, with
the evidence.

Claude Code:

```sh
claude mcp add stackvitals -- uvx stackvitals serve
```

Claude Desktop, Cursor, VS Code and other MCP clients:

```json
{
  "mcpServers": {
    "stackvitals": { "command": "uvx", "args": ["stackvitals", "serve"] }
  }
}
```

It uses your `gh` login or `GITHUB_TOKEN`. The 11 core tools load by default (`ci_failure`, `is_known_flake`,
`pr_queue`, `who_should_review`, `check_package`, `insights` and more); `stackvitals serve --tools all` loads all 35.
Listed in the MCP registry as `io.github.stackvitals/stackvitals`.

<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-dark.png"><img alt="" src="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-light.png" width="100%"></picture>

# Three things it gets right that others get wrong

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

<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-dark.png"><img alt="" src="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-light.png" width="100%"></picture>

# Compared with other tools

What each one does better, what StackVitals does differently, and what was measured side by side ([docs/compare](docs/compare/README.md)):

| Compared with | Kind |
|---|---|
| [Apache DevLake](docs/compare/devlake.md) | Open source (Apache 2.0), self-hosted |
| [Middleware](docs/compare/middleware.md) | Open source (Apache 2.0), self-hosted |
| [CDviz](docs/compare/cdviz.md) | Open source (Apache 2.0), self-hosted or EUR 20/month hosted |
| [Pelorus](docs/compare/pelorus.md) | Open source (Apache 2.0), on OpenShift |
| [Liatrio's DORA plugin for Backstage](docs/compare/liatrio-backstage.md) | Open source (Apache 2.0) |
| [Faros Community Edition](docs/compare/faros-community-edition.md) | Open source (Apache 2.0), withdrawn |
| [GrimoireLab](docs/compare/grimoirelab.md) | Open source (GPL-3.0), self-hosted |
| [LinearB](docs/compare/linearb.md) | SaaS; gitStream automation is free up to 250 PRs a month |
| [Swarmia](docs/compare/swarmia.md) | SaaS; free up to 9 developers |
| [Trunk Flaky Tests and BuildPulse](docs/compare/flaky-test-tools.md) | SaaS |

<picture><source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-dark.png"><img alt="" src="https://raw.githubusercontent.com/stackvitals/stackvitals/main/docs/assets/divider-light.png" width="100%"></picture>

# Learn more

- **Five minutes:** [docs/quickstart.md](docs/quickstart.md). Try CI Health on any public repo first (needs
  [uv](https://docs.astral.sh/uv/) and `gh auth login` or a `GITHUB_TOKEN`):
  `uvx stackvitals ci report owner/repo --days 14 --html ./ci-report`.
- **By role:** [engineering managers](docs/guides/manager.md), [maintainers](docs/guides/maintainer.md),
  [platform teams](docs/guides/platform.md).
- **Before you rely on it:** [what each rule does](docs/rules.md), [known limitations](docs/limitations.md),
  [what leaves your repo](docs/privacy.md), [threat model](docs/threat-model.md), [enterprise controls](docs/enterprise.md).
- **More:** [FAQ](docs/faq.md), [how it works](docs/architecture.md), [roadmap](docs/roadmap.md),
  [contributing](CONTRIBUTING.md), [code of conduct](CODE_OF_CONDUCT.md), [governance](GOVERNANCE.md), [security](SECURITY.md).
