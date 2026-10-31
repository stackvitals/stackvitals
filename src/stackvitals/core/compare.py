"""StackVitals beside the tools people compare it with: docs/compare/ (one page each and an index), the README's table
and llms.txt's facts are all built from this list, so they can't drift apart. Every claim about another tool names a
source; every number of ours links the card it comes from."""

CHECKED = "2026-11-01"
PAGES = "docs/compare"

# What StackVitals is, in facts an AI answer can quote; each with the page that shows it.
FACTS = [
    ("Runs as a GitHub Action in your own repo: no server of ours, no Docker, no account; history is kept on a "
     "`stackvitals-data` branch in the same repo.", "architecture.md"),
    ("Reads GitHub's API with the workflow's own token: Actions runs, jobs, logs and test reports, pull requests, "
     "reviews, releases and deployments. It doesn't use git hooks and doesn't point at lines of code.", "connectors.md"),
    ("On a pull request whose CI failed, one comment sorts each failure: likely flaky, already failing on main, new, and "
     "a few more; no verdict passes the check by itself.", "modules.md"),
    ("Deployments come from GitHub's Deployments API, deploy workflows and releases, found without setup, and from any "
     "other tool (Argo CD, Jenkins, a shell script) through `stackvitals record` or a `repository_dispatch` event.",
     "connectors.md#deployments-and-incidents-from-elsewhere"),
    ("It acts as well as reports: alerts to Slack, Teams, Discord or a webhook, opt-in re-runs of flaky jobs, issues, "
     "quarantine, suggested reviewers and size labels.", "modules.md"),
    ("Optional connectors: Jira, Linear, PagerDuty, incident.io, Slack and Discord channels, Discourse, GitLab, "
     "Bitbucket and Azure DevOps, SonarQube, test reports from Jenkins, CircleCI and Buildkite, AI spend.",
     "connectors.md"),
    ("SQL over the history in the browser and with `stackvitals sql`; an export with DevLake's table names for Postgres; "
     "Backstage catalog entities with the repo's level as an annotation (no card inside Backstage).", "scaling.md"),
    ("An MCP server gives AI agents the same history and verdicts.", "architecture.md"),
    ("Every verdict's rule is checked on public data and the misses are published.", "accuracy.md"),
]

DEVLAKE = "../../bench/accuracy/devlake/README.md"
MIDDLEWARE = "../../bench/accuracy/middleware/README.md"
DORA_CARD = "../../bench/accuracy/dora/README.md"

ALTERNATIVES = [
    {"slug": "devlake", "name": "Apache DevLake", "kind": "Open source (Apache 2.0), self-hosted",
     "what": "A data platform that collects DevOps data from about 50 tools into one model and shows it in Grafana, "
             "with DORA's five metrics. An Apache top-level project, very active in 2026.",
     "runs": "Four containers: MySQL or Postgres, the DevLake server, a config UI and Grafana (Docker Compose or Helm).",
     "better": ["Many more sources (Jenkins, Bamboo, Azure Pipelines, Opsgenie, Rootly and more) joined in one model.",
                "Real SQL on a real database, dozens of editable Grafana dashboards and team rollups.",
                "Raw API answers are kept, so metrics can be recomputed after a setting changes without fetching again.",
                "An ASF project, with the governance that brings."],
     "ours": ["Nothing to host: one Action, history on a branch of your repo.",
              "Finds the deployment source without setup; DevLake needs a job-name pattern or GitHub Deployments.",
              "Flaky-test triage on pull requests, which DevLake doesn't do."],
     "measured": [
         ("Same 5 repos and 90 days: DevLake pulled 9.2 GB of images and took 7,771 s (2 h 10 min) to collect at its "
          "900 requests an hour; StackVitals took 584 s with a `pip install`.", DEVLAKE),
         ("DORA tiers on those 5 repos: the same for deployment frequency and lead time on 5 of 5 (after a bug the "
          "side-by-side found in StackVitals was fixed). Five repos is too few to generalise from.", DEVLAKE),
         ("Deployment source with no setup, 60 public repos: StackVitals right on 53 (78-94%), DevLake's default pattern "
          "on 9, a pattern a user would write on 22. Labels by two model families, not people.", DORA_CARD)],
     "not_measured": "change failure rate and recovery time, since neither tool found an incident on the 5 repos.",
     "sources": [("DevLake docs: introduction", "https://devlake.apache.org/docs/Overview/Introduction"),
                 ("DevLake docs: architecture", "https://devlake.apache.org/docs/Overview/Architecture"),
                 ("DevLake docs: DORA", "https://devlake.apache.org/docs/DORA"),
                 ("DevLake docs: metrics", "https://devlake.apache.org/docs/Metrics"),
                 ("Repository", "https://github.com/apache/devlake")]},
    {"slug": "middleware", "name": "Middleware", "kind": "Open source (Apache 2.0), self-hosted",
     "what": "An open-source DORA app (middlewarehq/middleware) with its own web UI. Last release 0.3.1 in May 2025; "
             "a few fixes in 2026.",
     "runs": "One Docker image with Postgres and Redis inside, left running.",
     "better": ["A ready-made interactive app with team and repo filters, nothing to build.",
                "One place syncs many repos with one personal token.",
                "GitLab as well as GitHub."],
     "ours": ["Nothing left running, and the workflow's own token is enough.",
              "Reads GitHub's Deployments API as well as merges; Middleware counts workflow runs or merges.",
              "Flaky-test triage, PR comments and alerts, which Middleware doesn't do."],
     "measured": [
         ("Same 5 repos: Middleware's image is 1.36 GB and it used 1.09 GB of memory; it read the repos in 319 s, faster "
          "than StackVitals' 584 s.", MIDDLEWARE),
         ("Lead time on the 96 pull requests both counted: 95 agree within 10%; the one that doesn't was rebased weeks "
          "after the work began.", MIDDLEWARE),
         ("Asked for 90 days, Middleware returned about 31 to 36 days on 4 of the 5 repos.", MIDDLEWARE)],
     "not_measured": "change failure rate and recovery time, since no repo had a revert or incident in the window.",
     "sources": [("Repository and README", "https://github.com/middlewarehq/middleware"),
                 ("Docs", "https://docs.middlewarehq.com/")]},
    {"slug": "cdviz", "name": "CDviz", "kind": "Open source (Apache 2.0), self-hosted or EUR 20/month hosted",
     "what": "Delivery observability built on CDEvents, the CD Foundation's event standard: a collector, Postgres with "
             "TimescaleDB, and Grafana. Very active, small adoption.",
     "runs": "A collector, Postgres with TimescaleDB and Grafana; Docker, Helm or a hosted plan (GitHub and GitLab only).",
     "better": ["Speaks CDEvents in and out, so Argo CD, Kubernetes, Jenkins and Harbor feed it with no glue.",
                "Sends events out (webhooks, Kafka, NATS, SSE) to trigger other workflows: its standout feature.",
                "Records deployments from the cluster itself, and test reports from any CI (JUnit, TAP, SARIF)."],
     "ours": ["Nothing to host; deployments found without wiring events.",
              "Sorts each failure on a pull request (flaky, already failing, new); CDviz shows a pass/fail history line.",
              "Alerts, re-runs and issues act on findings, but not as CDEvents yet."],
     "measured": [],
     "not_measured": "no side-by-side run yet.",
     "sources": [("CDviz", "https://cdviz.dev/"), ("Pricing", "https://cdviz.dev/pricing"),
                 ("Docs", "https://cdviz.dev/docs/"), ("Repository", "https://github.com/cdviz-dev/cdviz")]},
    {"slug": "pelorus", "name": "Pelorus", "kind": "Open source (Apache 2.0), on OpenShift",
     "what": "A Red Hat community project measuring DORA's four metrics with Prometheus exporters and Grafana. Not "
             "archived, but its last release was in June 2024 and its main branch says the next version isn't active.",
     "runs": "OpenShift 4.7 or later, through its operator; Prometheus and Grafana.",
     "better": ["True production deploy times from labelled OpenShift objects, not from CI.",
                "Failures from ServiceNow, PagerDuty or Jira; any git host."],
     "ours": ["Runs anywhere GitHub Actions runs; no cluster.",
              "Pull request flow and flaky-test triage, which Pelorus doesn't do.",
              "Maintained, with releases in 2026."],
     "measured": [], "not_measured": "no side-by-side run yet.",
     "sources": [("Repository", "https://github.com/dora-metrics/pelorus"),
                 ("Docs", "https://pelorus.readthedocs.io/en/latest/")]},
    {"slug": "liatrio-backstage", "name": "Liatrio's DORA plugin for Backstage", "kind": "Open source (Apache 2.0)",
     "what": "A Backstage plugin showing DORA metrics per service. Last release May 2025; its chart library is archived.",
     "runs": "A Backstage app, Loki with Promtail, Liatrio's OpenTelemetry collector and its DORA API; a GitHub token "
             "with full repo access and an org webhook.",
     "better": ["Metrics inside Backstage, next to each service in the catalog.",
                "A standard OpenTelemetry pipeline; weekends and holidays can be left out."],
     "ours": ["Exports Backstage catalog entities with the repo's level as an annotation, but has no card inside Backstage.",
              "Finds deployments without GitHub Deployments; the plugin sees only those.",
              "Nothing to host."],
     "measured": [], "not_measured": "no side-by-side run yet.",
     "sources": [("Repository", "https://github.com/liatrio/backstage-dora-plugin"),
                 ("DORA API", "https://github.com/liatrio/liatrio-dora-api")]},
    {"slug": "faros-community-edition", "name": "Faros Community Edition", "kind": "Open source (Apache 2.0), withdrawn",
     "what": "An engineering-operations platform (Airbyte, Postgres, Hasura, Metabase, dbt, n8n). Its repository and "
             "docs site were gone on 2026-11-01; the last release was v0.6.0 in May 2023.",
     "runs": "A Docker Compose stack of seven services (4 CPUs and 4 GB of memory recommended).",
     "better": ["A deep shared schema across many tools, with GraphQL and editable dashboards (when it was live)."],
     "ours": ["Maintained; nothing to host."],
     "measured": [], "not_measured": "it can no longer be installed to compare.",
     "sources": [("Last archived copy of the repository",
                  "http://web.archive.org/web/20251122101324/https://github.com/faros-ai/faros-community-edition")]},
    {"slug": "grimoirelab", "name": "GrimoireLab", "kind": "Open source (GPL-3.0), self-hosted",
     "what": "CHAOSS's software-analytics toolset: 30+ sources, identity merging and community-health dashboards. "
             "Active (1.23.0 in October 2026). No DORA metrics.",
     "runs": "Docker Compose with MariaDB, Valkey and OpenSearch; 2 CPUs and 8 GB of memory.",
     "better": ["Far broader sources (mailing lists, chat, Gerrit, Bugzilla).",
                "Merges people's identities and affiliations; CHAOSS-standard metrics at Linux Foundation scale."],
     "ours": ["DORA, flaky-test triage and pull request flow, which GrimoireLab doesn't do.",
              "A Community module with first-response times, and a CHAOSS mapping (docs/chaoss.md)."],
     "measured": [], "not_measured": "no side-by-side run yet.",
     "sources": [("Repository", "https://github.com/chaoss/grimoirelab")]},
    {"slug": "linearb", "name": "LinearB", "kind": "SaaS; gitStream automation is free up to 250 PRs a month",
     "what": "A commercial engineering-metrics product with DORA, and gitStream rules that automate pull requests.",
     "runs": "Hosted; GitHub App. Essentials $29 a user a month with a 50-user minimum; 45-day trial without a card.",
     "better": ["Mature pull request automation (gitStream): reviewer routing, auto-merge of safe changes, labels.",
                "AI code review, several git hosts, Jira and Azure Boards, forecasting and cost reports, support."],
     "ours": ["Free at any size, and your data stays in your repo.",
              "Flaky-test triage (none found in LinearB's docs).",
              "Suggested reviewers and size labels, simpler than gitStream."],
     "measured": [], "not_measured": "no side-by-side run yet.",
     "sources": [("Pricing", "https://linearb.io/pricing"), ("Security", "https://linearb.io/security"),
                 ("gitStream limits", "https://docs.gitstream.cm/limits/")]},
    {"slug": "swarmia", "name": "Swarmia", "kind": "SaaS; free up to 9 developers",
     "what": "A commercial engineering-effectiveness product: DORA, developer surveys, AI-adoption tracking and "
             "software capitalization.",
     "runs": "Hosted on Google Cloud in Frankfurt by default; GitHub App. $45-55 a developer a month above 9.",
     "better": ["Developer experience surveys with benchmarks; working agreements with Slack nudges.",
                "Investment and capitalization reports; AI-tool adoption across vendors; polish and support."],
     "ours": ["Free at any size, and your data stays in your repo.",
              "Test-level flaky triage; Swarmia's CI view shows job failure rates, not flaky tests.",
              "No surveys: StackVitals reads history only."],
     "measured": [], "not_measured": "no side-by-side run yet.",
     "sources": [("Pricing", "https://swarmia.com/pricing/"), ("Security", "https://www.swarmia.com/security/"),
                 ("CI visibility", "https://help.swarmia.com/get-visibility-into-your-ci-pipeline")]},
    {"slug": "flaky-test-tools", "name": "Trunk Flaky Tests and BuildPulse", "kind": "SaaS",
     "what": "Flaky-test services: they read JUnit reports from CI, detect flaky tests and quarantine them. Trunk is "
             "free up to 5 committers on private repos (data in the US); BuildPulse starts at $99 a month.",
     "runs": "Hosted; an uploader in your CI sends test results to the service.",
     "better": ["Test-level detection across every CI, with quarantine that keeps CI green.",
                "Tickets in Jira, Linear or GitHub; Trunk adds a merge queue; support."],
     "ours": ["Free at any size; results stay in your repo.",
              "Sorts each failure on a pull request against main's history (already failing on main, new, flaky), "
              "and quarantine is opt-in too.",
              "Delivery, pull request flow and dependencies in the same Action."],
     "measured": [], "not_measured": "no side-by-side run yet.",
     "sources": [("Trunk pricing", "https://trunk.io/pricing"), ("Trunk docs", "https://docs.trunk.io/flaky-tests"),
                 ("BuildPulse pricing", "https://buildpulse.io/pricing")]},
]


def _page(a: dict) -> str:
    # What the tool is comes first: llms.txt and search snippets quote a page's first sentence.
    lines = [f"# StackVitals and {a['name']}", "", f"{a['name']}: {a['what']}", "",
             f"**Kind:** {a['kind']}. **How it runs:** {a['runs']}", "",
             f"Checked {CHECKED} from the sources below; tools change, so check them before you rely on this.", "",
             f"## Where {a['name']} is better", "", *[f"- {x}" for x in a["better"]], "",
             "## Where StackVitals differs", "", *[f"- {x}" for x in a["ours"]], "", "## Measured side by side", ""]
    lines += [f"- {text} ([evidence]({src}))" for text, src in a["measured"]]
    lines += [f"- Not measured: {a['not_measured']}", "", "## Sources", "",
              *[f"- [{label}]({url})" for label, url in a["sources"]], ""]
    return "\n".join(lines)


def index() -> str:
    rows = [f"| [{a['name']}]({a['slug']}.md) | {a['kind']} | {a['what'].split('. ')[0].rstrip('.')}. |" for a in ALTERNATIVES]
    facts = [f"- {text} ([more](../{page}))" for text, page in FACTS]
    return "\n".join(["# StackVitals compared with other tools", "",
                      f"What each tool does better, what StackVitals does differently, and what was measured side by "
                      f"side. Checked {CHECKED}; each page names its sources.", "",
                      "| Tool | Kind | What it is |", "|---|---|---|", *rows, "", "## StackVitals in facts", "", *facts, ""])


def pages() -> dict[str, str]:
    """Every compare page by path, the index included."""
    out = {f"{PAGES}/README.md": index()}
    out.update({f"{PAGES}/{a['slug']}.md": _page(a) for a in ALTERNATIVES})
    return out


def readme_table() -> str:
    """The README's short table, between its compare markers."""
    rows = [f"| [{a['name']}](docs/compare/{a['slug']}.md) | {a['kind']} |" for a in ALTERNATIVES]
    return "\n".join(["| Compared with | Kind |", "|---|---|", *rows])


def llms_facts() -> list[str]:
    return [f"- {text}" for text, _ in FACTS]
