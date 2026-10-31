"""What leaves a repo, where it goes and what switches it off: docs/privacy.md is built from this list, and the hosts
come from the code's own constants, so a test can check that every outside host in the code has its line here."""
from urllib.parse import urlparse

from stackvitals.ci import triage
from stackvitals.ci.bench import BENCH_REPO, PUBLIC_HOME
from stackvitals.ci.gitlab import API as GITLAB
from stackvitals.connectors import incident_io, linear, pagerduty
from stackvitals.deps import lookalike, release, runtimes, supply, vulns
from stackvitals.portal.inventory import SCORECARD_API
from stackvitals.connectors import sonar
from stackvitals.flow import code_hosts
from stackvitals.security.repo_checks import BADGE_API


def host(url: str) -> str:
    return urlparse(url).netloc


# feature, hosts, what is sent, when it runs, how to turn it off
FLOWS = [
    {"feature": "Every module (reading your repo, writing its results)", "hosts": ["api.github.com", "github.com"],
     "sends": "Requests with the workflow's own token: it reads runs, logs, pull requests, issues and files of this repo, "
              "and writes the stackvitals-data branch, Pages, and the comments, labels and issues your switches allow.",
     "when": "every run", "off": "Stays inside GitHub; remove a module from `modules` to stop it."},
    {"feature": "Delivery from Bitbucket or Azure DevOps (command line)", "hosts": [host(code_hosts.BITBUCKET), host(code_hosts.AZURE)],
     "sends": "Read-only requests for the repo you name, with BITBUCKET_TOKEN or AZURE_DEVOPS_TOKEN when set; nothing about a GitHub repo.",
     "when": "only when you run `stackvitals delivery --bitbucket` or `--azure`", "off": "Don't run it."},
    {"feature": "SonarQube or SonarCloud code quality", "hosts": ["sonarcloud.io"],
     "sends": "The Sonar project key in [connectors.sonar] (and the SONAR_TOKEN when set), to read its quality gate and measures.",
     "when": "once a day, when a project is set", "off": "Leave project under [connectors.sonar] empty."},
    {"feature": "Security checks: the OpenSSF Best Practices badge", "hosts": [host(BADGE_API)],
     "sends": "A public repo's address, to look up its badge level; a private repo's is never sent.",
     "when": "once a week", "off": "Remove `deps` from `modules`."},
    {"feature": "Benchmarks from public repos", "hosts": ["github.com"],
     "sends": f"A download of the crawl's benchmark files from {PUBLIC_HOME or BENCH_REPO}'s releases; nothing about your repo is sent.",
     "when": "every run, cached a day", "off": "Nothing to turn off: it is a download."},
    {"feature": "Shared benchmark figures (opt-in)", "hosts": ["github.com"],
     "sends": f"An issue on {BENCH_REPO}, filed by a person from a link in the run summary: this repo's rounded CI figures, "
              "its language and star tier, a random id kept in the data branch, and its name only with `name = true`. It is "
              "public once filed, and shows the account that filed it.",
     "when": "only when someone files the link", "off": "`[benchmarks] share = false` (the default); close the issue to withdraw it."},
    {"feature": "Dependency licences and Scorecards", "hosts": [host(supply.DEPS_DEV), host(supply.SCORECARD)],
     "sends": "The name and version of every package in the dependency graph (to deps.dev; that includes the names of "
              "private or internal packages the graph lists) and the public source repos behind them (to OpenSSF "
              "Scorecard); never this repo's name.",
     "when": "weekly, Dependencies module", "off": "`[deps] outside_lookups = false`."},
    {"feature": "Known vulnerabilities in every lockfile",
     "hosts": [host(vulns.RELEASES), "api.osv.dev", "api.deps.dev", "osv-vulnerabilities.storage.googleapis.com"],
     "sends": "A download of the pinned OSV-Scanner from its GitHub release (checked against its SHA-256); then the name "
              "and version of every package in the repo's lockfiles to OSV (and, for manifests without exact versions, to "
              "deps.dev to resolve them). With outside lookups off, OSV's public databases are downloaded instead and no "
              "package name is sent.",
     "when": "after CI runs and on the schedule, at most every 6 hours unless a lockfile changed; Dependencies module",
     "off": "`[deps] outside_lookups = false` (scans offline)."},
    {"feature": "Release checks on changed packages", "hosts": [host(release.NPM), host(release.PYPI), host(release.DEPS_DEV)],
     "sends": "The name and the old and new versions of each npm or PyPI package a pull request adds or upgrades (at most "
              "30), to read when it was released, its install scripts, dependencies and build provenance.",
     "when": "pull requests that change a lockfile", "off": "`[deps] outside_lookups = false`."},
    {"feature": "Runtime versions", "hosts": [host(runtimes.EOL_API)],
     "sends": "Only the runtime's name (nodejs, python, php, ruby or go), to read its release lines and support dates; "
              "never the repo or its versions.",
     "when": "weekly, Dependencies module", "off": "`[deps] outside_lookups = false`."},
    {"feature": "GuardDog code check (opt-in)", "hosts": ["pypi.org", "files.pythonhosted.org", "registry.npmjs.org"],
     "sends": "Downloads of GuardDog itself and of each npm or PyPI package version a pull request adds or upgrades (at "
              "most 10), whose code it reads on the runner; nothing about the repo is sent.",
     "when": "pull requests that change a lockfile, only with `[deps] guarddog = true`", "off": "Off by default."},
    {"feature": "History in a bucket (opt-in)", "hosts": ["the s3-endpoint you set"],
     "sends": "Every file of the data branch (history, pages, decisions), signed with your bucket key, to your own bucket.",
     "when": "every run, only with `storage: s3://...`", "off": "The default, `storage: git`."},
    {"feature": "Look-alike package check", "hosts": [host(lookalike.NPM_STATS), host(lookalike.PYPI_STATS)],
     "sends": "Only the name of a package a pull request adds whose name is one edit from a popular one, to read its "
              "weekly downloads.",
     "when": "pull requests that change a lockfile", "off": "`[deps] outside_lookups = false` (names are still checked)."},
    {"feature": "Model triage of unexplained CI failures",
     "hosts": sorted({host(p["url"]) for p in triage.PROVIDERS.values()}) + ["the `url` you set under [ci.triage]"],
     "sends": "The failing step's log excerpt (bounded) and the changed files' names, with your key, to the provider you "
              "choose or the endpoint you set; at most 3 calls a run.",
     "when": "off until `[ci.triage]` and a key are set; a private repo also needs `allow_private = true`",
     "off": "Off by default."},
    {"feature": "Issue trackers and incident tools",
     "hosts": ["*.atlassian.net", host(linear.URL), host(pagerduty.URL), host(incident_io.URL)],
     "sends": "Requests with your key that read issues, sprints and incidents; with write-back on, a comment linking the "
              "merged pull request (and a status move).",
     "when": "only with a key in the workflow; write-back only with `write_back = true`", "off": "Remove the key."},
    {"feature": "A Discourse forum", "hosts": ["your forum's host"],
     "sends": "Read requests for its public topics, with no key; only times and flags are kept, never usernames or text.",
     "when": "only with url under [connectors.discourse]", "off": "Remove the url."},
    {"feature": "Slack and Discord support channels", "hosts": ["slack.com", "discord.com"],
     "sends": "Read requests with your bot token for the channels you name; only times and flags are kept, never text or "
              "user ids.", "when": "only with a slack-token or discord-token", "off": "Remove the token."},
    {"feature": "Copilot usage reports", "hosts": ["api.github.com", "the report file host GitHub names"],
     "sends": "Requests with the reports token; the report file is fetched without it.",
     "when": "only with the Copilot token", "off": "Remove the token."},
    {"feature": "AI spend", "hosts": ["api.anthropic.com", "api.openai.com", "api.cursor.com"],
     "sends": "Read-only cost and usage report requests, each with that provider's own admin key; nothing about the repo.",
     "when": "only with an AI spend admin key", "off": "Remove the key."},
    {"feature": "Chat alerts and the weekly digest", "hosts": ["your webhook's host (Slack, Teams, Discord, other)"],
     "sends": "Alert and digest text: metric names and values, test names, this repo's name, links to its pages.",
     "when": "only with a webhook secret", "off": "Remove the webhook."},
    {"feature": "Test connection", "hosts": ["each connector's own host (above)", "your webhook's host", "the s3-endpoint you set",
                                            "your model provider", "your GitLab host (`CI_API_V4_URL`)"],
     "sends": "One cheap call per connector asked for, with its own key: it reads one item, never writes to a tracker. A "
              "chat webhook gets one labelled test message (\"StackVitals connection test\"), never retried; a bucket gets "
              "one small object (`.stackvitals-check`) written and deleted under the prefix; model triage calls the "
              "provider's model list; GitLab reads the project and the token's own scopes, at `CI_API_V4_URL` for a "
              "self-hosted GitLab. The results go in docs/connectors.json; on a public repo without account, channel, "
              "team or bucket names.",
     "when": "only when someone with write access presses Test connection, comments `/stackvitals check`, or runs "
             "`stackvitals connectors check`", "off": "Don't run it."},
    {"feature": "Exports (DevLake, CTRF, Postgres, OpenTelemetry)", "hosts": ["api.github.com"],
     "sends": "Reads with your token; the files are written on your machine and sent nowhere.",
     "when": "only when you run `stackvitals export`", "off": "Don't run it."},
    {"feature": "Portal Scorecard checks", "hosts": [host(SCORECARD_API)],
     "sends": "The names of the organisation's public repos; private repos are never sent.",
     "when": "weekly, Portal module", "off": "Leave the Portal module out."},
    {"feature": "GitLab CI", "hosts": [host(GITLAB)],
     "sends": "Requests with your GitLab token for one project's pipelines and jobs. The GitLab job also writes the "
              "project's stackvitals-data branch, its Pages and one merge request note, and downloads StackVitals from "
              "github.com and its packages from PyPI.",
     "when": "when you run `stackvitals ci gitlab`, or each pipeline once you include the GitLab job",
     "off": "Don't run or include it."},
    {"feature": "The app in a viewer's browser",
     "hosts": ["your Pages site", "api.github.com", "raw.githubusercontent.com", "avatars.githubusercontent.com",
               "api.linear.app", "your sign-in relay (optional)", "cdn.jsdelivr.net", "cdnjs.cloudflare.com"],
     "sends": "The viewer's browser loads the app from your Pages site (its code, font and docs are all there). With a "
              "GitHub token or sign-in, the app calls api.github.com with it to read repos and data branches, set up the "
              "workflow, save settings and decisions, and save secrets sealed in the browser; workflow files and data "
              "are also read from raw.githubusercontent.com, and the account picture from avatars.githubusercontent.com. "
              "Testing a Linear key from the page sends it only to api.linear.app. Sign in with GitHub, when the site was "
              "built with a relay, sends the one-time code (and later the refresh token) to that relay, which swaps it "
              "for a token and keeps nothing. Explore loads DuckDB from jsDelivr; printable pages load Chart.js from "
              "cdnjs. Nothing goes to a server of ours.",
     "when": "when someone opens the app", "off": "Keep Pages private, or don't publish them; don't connect GitHub in the app."},
]

# Hosts the code names only as links people open or as examples; nothing is sent to them by a run.
LINKS = {"docs.github.com", "linear.new", "linear.app", "app.incident.io", "support.pagerduty.com", "id.atlassian.com",
         "api.slack.com", "hooks.slack.com", "pkg.go.dev", "acme.atlassian.net", "your-site.atlassian.net",
         "your-endpoint.example.com", "chaoss.community", "discuss.example.org", "osv.dev", "json.schemastore.org",
         "aistudio.google.com", "docs.astral.sh", "owner.github.io"}


def hosts() -> set[str]:
    return {h for f in FLOWS for h in f["hosts"]}


def markdown() -> str:
    lines = ["# What leaves your repo", "",
             "StackVitals runs in your own workflow and keeps its history in your repo. There is no StackVitals server: "
             "nothing is sent to us. This page lists everything a run (or the app) sends anywhere, built from the code's "
             "own list, and a test fails if the code gains an outside host this page doesn't name.", "",
             "| Feature | Goes to | What is sent | When | To turn it off |", "|---|---|---|---|---|"]
    for f in FLOWS:
        lines.append(f"| {f['feature']} | {', '.join(f['hosts'])} | {f['sends']} | {f['when']} | {f['off']} |")
    lines += ["", "## Nothing leaves GitHub", "",
              "Leave model triage, connectors and webhooks unset (they are, by default), and "
              "set `[deps] outside_lookups = false`. Runs then talk to GitHub only: your repo, and the benchmark download "
              "from public releases. A private repo's Pages are private on plans that allow it; otherwise publish none and "
              "read the job summary and the data branch.", "",
              "## What each token can reach", "",
              "- **The workflow token** (`GITHUB_TOKEN`): this repo only, with the permissions the workflow file grants.",
              "- **An optional personal or App token** (`stackvitals-token`): whatever it was granted; the Portal's App is "
              "read-only.",
              "- **Tracker and incident keys:** only their own service's host; the Jira key goes only to an "
              "`*.atlassian.net` site.",
              "- **A model key:** its provider's host, or the `url` you set under `[ci.triage]`.", ""]
    return "\n".join(lines)
