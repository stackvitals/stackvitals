"""Every setting in `.github/stackvitals.toml` in one list: what it does, its type and limits, and where it shows. Defaults
come from core/config.py, so this list, the parser, docs/settings.md and the app's settings editor always agree."""
from dataclasses import dataclass

from stackvitals.core import config


@dataclass(frozen=True)
class Setting:
    key: str          # dotted path in the file, e.g. "alerts.pickup_p75_hours"
    kind: str         # int, number, share, hours, bool, switch, regex, text, date, choice, choices, list, map, teams, dates,
                      # services
    help: str
    module: str       # the app section it belongs to
    choices: tuple = ()
    unit: str = ""


_M = "ci.monitors"
SETTINGS = (
    Setting(f"{_M}.pass_on_retry.min_events", "int", "Fail-then-pass events with no code change before a test or job is flaky.", "ci"),
    Setting(f"{_M}.pass_on_retry.quiet_days", "int", "Days without a flake before the pass-on-retry monitor lets go.", "ci", unit="days"),
    Setting(f"{_M}.pass_on_retry.quiet_runs", "int", "Clean runs in a row before a flaky test counts as fixed.", "ci", unit="runs"),
    Setting(f"{_M}.failure_rate.enabled", "bool", "Watch each test's failure share on the default branch.", "ci"),
    Setting(f"{_M}.failure_rate.window_runs", "int", "Latest default-branch runs the failure rate looks at.", "ci", unit="runs"),
    Setting(f"{_M}.failure_rate.min_runs", "int", "Runs needed before the failure-rate monitor can fire.", "ci", unit="runs"),
    Setting(f"{_M}.failure_rate.activate", "share", "Failure share that turns the monitor on.", "ci"),
    Setting(f"{_M}.failure_rate.resolve", "share", "The monitor stays on while the failure share is above this.", "ci"),
    Setting(f"{_M}.broken.streak", "int", "Default-branch runs in a row that all failed: the test keeps failing (broken).", "ci", unit="runs"),
    Setting(f"{_M}.broken.window_runs", "int", "Latest runs the broken monitor looks at.", "ci", unit="runs"),
    Setting(f"{_M}.broken.activate", "share", "Failure share in that window that marks a test broken.", "ci"),
    Setting(f"{_M}.broken.resolve", "share", "A broken test stays broken while its failure share is at least this.", "ci"),
    Setting(f"{_M}.slow.p50_ms", "int", "Label a test slow when its median passing time is above this.", "ci", unit="ms"),
    Setting(f"{_M}.timeout_inflation.ratio", "number", "Label a test when its median failure time is at least this many times its P95 pass time.", "ci", unit="x"),
    Setting(f"{_M}.timeout_inflation.min_failures", "int", "Failures needed before that label shows.", "ci"),
    Setting("ci.mute", "dates", "Test ids or glob patterns muted until a date: still measured, but no alert and no new issue.", "ci"),
    Setting("ci.quarantine.always", "list", "Test ids always on the quarantine list, flaky or not.", "ci"),
    Setting("ci.quarantine.never", "list", "Test ids never quarantined, even when flaky.", "ci"),
    Setting("ci.quarantine.max_days", "int", "Days a flaky test may stay in quarantine on its own before it fails builds again and is listed as overdue for a fix; 0 never ends it. Tests someone quarantined by hand stay.", "ci"),
    Setting("ci.coverage.min_patch", "share", "The verdict check fails when fewer of a pull request's added lines ran than this (from the coverage report CI uploads); 0 is off.", "ci"),
    Setting("ci.triage.provider", "choice", "A model reads the log of up to 3 failures the history can't decide and says whether they look like the change, beside the verdict (never in it); needs the triage-key input (docs/triage.md says how). Setups for each provider: docs/triage.md (gemini has a free tier).", "ci", choices=("off", "gemini", "openai", "anthropic", "mistral", "groq")),
    Setting("ci.triage.model", "text", "The model to ask (empty: the provider's suggested small model).", "ci"),
    Setting("ci.triage.url", "text", "Another OpenAI-compatible endpoint (https) instead of the provider's own.", "ci"),
    Setting("ci.triage.allow_private", "bool", "Send a private repo's failing logs too (off: free tiers may keep what they're sent).", "ci"),
    Setting("delivery.deploy_workflow", "regex", "Workflow names that count as deployments when the repo has no production deployments.", "delivery"),
    Setting("delivery.production", "list", "GitHub deployment environments that count as production (matched on the first word).", "delivery"),
    Setting("delivery.incident_labels", "list", "Issue labels that mark an incident.", "delivery"),
    Setting("delivery.hotfix_labels", "list", "Pull request labels that mark a hotfix (counted as an incident).", "delivery"),
    Setting("delivery.source", "choice", "Where deployments come from; auto tries deployments, deploy workflows, then releases; merges counts every merged pull request as one (only when chosen: it is a poor guess for most repos).", "delivery",
            choices=config.SOURCES),
    Setting("delivery.fix_patterns", "list", "Regular expressions on a merged pull request's title or branch that mark it as a fix, with one group naming the pull request it fixes, like ^fix.*#([0-9]+) or ^hotfix/([0-9]+)-; the incident blames the deployment that shipped that pull request.", "delivery"),
    Setting("delivery.incident_sources", "list", "Where incidents come from: any of issues, reverts, hotfixes, fixes, pager, tracker, recorded; empty keeps the automatic choice (a pager tool's alone when connected, else all of GitHub's).", "delivery"),
    Setting("delivery.production_branches", "list", "Branches besides the default one that ship to production (globs, like production or release/*): deploy workflows on them count, and so do pull requests merged into them.", "delivery"),
    Setting("delivery.ignore_reverts_of", "list", "Reverts that are not incidents: of pull requests touching only these paths (globs, like docs/**) or by these authors (like dependabot[bot]).", "delivery"),
    Setting("delivery.dora_report", "choice", "The DORA report whose tiers DevLake's dashboard uses.", "delivery", choices=("2023", "2021")),
    Setting("investment.labels", "teams", "Your own labels for each kind of work (feature, fix, maintenance, security, docs), "
            "like maintenance = [\"area: platform\"] under [investment.labels]; checked before the common ones, for where "
            "the work went.", "delivery"),
    Setting("rules", "rules", "PR rules as code: each [[rules]] has a name, a when (author, paths, lines_over, risk, labels, "
            "first_time) and a then (label, reviewers, comment); dry_run = true only reports. Each action happens once per "
            "pull request; the Pull Requests page shows what each rule matched before and now.", "flow"),
    Setting("calendar.weekends", "list", "Days the team doesn't work, like saturday and sunday; left out of review phases and cycle "
            "time (DORA's DevLake-matching numbers stay in calendar time, with a working-time lead time beside them).", "delivery"),
    Setting("calendar.holidays", "list", "Dates the team doesn't work, like 2026-12-25; left out the same way.", "delivery"),
    Setting("services", "services", "Services inside this repo (a monorepo): under [services.<name>], paths is a list of "
            "CODEOWNERS-style patterns (like [\"services/api/\", \"libs/shared/**\"]) and deploy an optional pattern matched "
            "against each deployment's environment or workflow name. Delivery then shows review phases per service, and "
            "DORA per service for those with a deploy pattern; a pull request touching two services counts in both.", "delivery"),
    Setting("identity.bots", "list", "Logins that are bots even if GitHub says otherwise.", "people"),
    Setting("identity.people", "list", "Logins that are people even if they look like bots.", "people"),
    Setting("identity.aliases", "map", "Old login to current login, so one person's history stays together. A key can also "
            "be a tool's id (`jira:<account id>`, `linear:<user id>`, `slack:<member id>`, `discord:<user id>`) or an email, "
            "so one person counts once across tools.", "people"),
    Setting("identity.teams", "teams", "Team name to its members' logins, for numbers by team.", "people"),
    Setting("identity.knowledge_names", "bool", "On a public repo, name the person behind each area in the knowledge map (folders one person knows, authors gone quiet). Off by default: public pages show the areas only. Private repos always show names.", "people"),
    Setting("alerts.pickup_p75_hours", "hours", "Alert when 3 in 4 PRs wait longer than this for a first comment or review (last 28 days); 0 turns it off.", "alerts", unit="h"),
    Setting("alerts.review_p75_hours", "hours", "Alert when 3 in 4 reviews take longer than this; 0 turns it off.", "alerts", unit="h"),
    Setting("alerts.cycle_p75_hours", "hours", "Alert when 3 in 4 PRs take longer than this from first commit to merge; 0 turns it off.", "alerts", unit="h"),
    Setting("alerts.change_failure_rate", "share", "Alert when more than this share of deployments led to an incident; 0 turns it off.", "alerts"),
    Setting("alerts.channels", "choices", "Where alerts go: the webhook from the workflow, and/or one issue in this repo.", "alerts",
            choices=config.CHANNELS),
    Setting("events.send", "choices", "Which findings go out as events once the events-url input or dispatch_repo is set: delivery alerts, newly flaky tests, pull request verdicts (CDEvents custom events; names and counts, never log text).", "alerts",
            choices=config.EVENT_KINDS),
    Setting("events.dispatch_repo", "text", "A repo (owner/name) that gets each event as a repository_dispatch, so its workflows can react; needs the events-token input with write access to its contents.", "alerts"),
    Setting("automation.pr_comments", "switch", "One comment on failed PR runs saying which failures are known flakes.", "automation"),
    Setting("automation.rerun_flaky", "switch", "Re-run failed jobs once when every failure is a known flake (needs actions: write).", "automation"),
    Setting("automation.quarantine", "switch", "Keep the quarantine list for the stackvitals ci quarantine command.", "automation"),
    Setting("automation.issues", "switch", "One issue per flaky test or job, closed once fixed (needs issues: write).", "automation"),
    Setting("automation.mention_owners", "switch", "@-mention code owners in those issues (off: owners are named without a notification).", "automation"),
    Setting("automation.assign_owners", "switch", "Assign a new flaky-test issue to its first code owner who is a person.", "automation"),
    Setting("automation.preflight_comments", "switch", "One note on new outside PRs that miss what merged PRs here usually include.", "automation"),
    Setting("automation.deps_comments", "switch", "One comment on same-repo PRs listing changed packages and their verdicts.", "automation"),
    Setting("automation.review_requests", "switch", "Off until turned on: request the top suggested reviewer (who knows the folders, who reviewed the author's PRs, eased by load) on ready PRs nobody was asked to review; once per PR. Needs pull-requests: write.", "automation"),
    Setting("automation.fix_requests", "switch", "Off until turned on: one issue per failure that breaks the default branch every "
            "run, closed with proof once fixed. Needs issues: write.", "automation"),
    Setting("automation.fix_by_copilot", "switch", "With fix_requests: assign each new one to Copilot's coding agent.", "automation"),
    Setting("automation.size_labels", "switch", "Off until turned on: a size/XS to size/XL label on each open PR by lines changed (under 10, 100, 500, 1000).", "automation"),
    Setting("automation.docs_label", "switch", "Off until turned on: label PRs that only change docs (Markdown, docs/, README) as low risk: docs only; never approves.", "automation"),
    Setting("automation.label_stuck", "switch", "Label PRs whose asked-for review has not started after 3 days, and unlabel them later.", "automation"),
    Setting("automation.verdict_check", "switch", "A \"StackVitals verdict\" check on pull requests: one required check that waits for every workflow on the newest commit and passes once CI is green (and patch coverage holds); known flakes are re-run, never let through (with rerun_flaky, automatically). Needs checks: write. On a private repo also set the repository variable STACKVITALS_EVERY_CI_RUN to true, so passing CI runs start a job.", "automation"),
    Setting("automation.verdict_strict", "switch", "With the verdict check: when a failure the comment called likely from this change goes green on a re-run of the same code, the check stays red until someone with triage access comments /stackvitals accept rerun on the pull request. Off by default (a green re-run passes).", "automation"),
    Setting("agreements.review_within_hours", "hours", "Agreement: every PR gets a first comment or review within this many hours; 0 is off.", "agreements", unit="h"),
    Setting("agreements.merge_within_days", "number", "Agreement: PRs merge within this many days of being ready; 0 is off.", "agreements", unit="days"),
    Setting("agreements.max_pr_lines", "int", "Agreement: PRs stay under this many changed lines; 0 is off.", "agreements", unit="lines"),
    Setting("agreements.linked_issue", "bool", "Agreement: every PR links the issue it solves.", "agreements"),
    Setting("agreements.review_before_merge", "bool", "Agreement: nothing merges without a review.", "agreements"),
    Setting("digest.enabled", "bool", "Post a weekly digest: what changed, what to fix first, decisions ending soon.", "digest"),
    Setting("digest.pulse", "bool", "With the issue digest, three pulse questions (flow, friction, satisfaction) answered by reaction; next week's digest shows only the counts (GitHub shows reactions to anyone who can see the issue; on a public repo only the team's own people count).", "digest"),
    Setting("digest.day", "choice", "The day the digest goes out (the first scheduled run after the hour).", "digest", choices=config.DAYS),
    Setting("digest.hour", "int", "The hour, in UTC, from which the digest may go out on that day.", "digest", unit="UTC"),
    Setting("digest.channels", "choices", "Where the digest goes: one pinned issue in this repo, and/or the webhook.", "digest",
            choices=config.CHANNELS),
    Setting("deps.policy.min_scorecard", "number", "Projects behind the dependencies scoring under this OpenSSF Scorecard (0 to 10) are listed on the supply page, unless a decision accepted the package. Empty is off.", "deps"),
    Setting("deps.policy.max_severity", "text", "The pull request check flags a changed package with an open advisory rated above this (low, moderate, high or critical). Empty is off.", "deps"),
    Setting("deps.outside_lookups", "bool", "Look dependencies' public package names up at deps.dev, OpenSSF Scorecard, OSV, npm/PyPI release data, endoflife.date and the registries' download counts (docs/privacy.md); off scans with downloaded OSV databases, skips release checks, runtimes and GuardDog, and keeps every dependency name in the repo.", "deps"),
    Setting("deps.guarddog", "bool", "Off by default: the pull request check also runs DataDog's GuardDog on each npm or PyPI package version it adds or upgrades (at most 10), which downloads the package and looks for malicious code (install hooks, obfuscation, data sent out); a finding is a reason to look first. Needs outside_lookups on; Linux runners only.", "deps"),
    Setting("deps.licenses.deny", "list", "SPDX licence ids the repo's dependencies must not use (* allowed, like GPL-3.0*); a package offering an allowed choice is fine. Empty is off.", "deps"),
    Setting("benchmarks.share", "bool", "Off by default: each CI run's summary offers a link that files this repo's rounded CI figures (pushes, time to green, first-try share; no names, no code) as an issue on StackVitals' public repo, so private repos get peer groups once 10+ of a kind have shared. Nothing is sent unless a person opens the link and files it.", "ci"),
    Setting("benchmarks.name", "bool", "With benchmarks.share on: include this repo's name in the shared figures. Off shares them without it.", "ci"),
    Setting("community.capacity", "text", "Who maintains the project and how much time they have, in your words (like \"two volunteers, evenings and weekends\"); shown on the Community page so the numbers are read against it.", "community"),
    Setting("community.norms", "text", "How the project works with people, in your words (like \"issues are triaged on Mondays; ideas go to Discussions first\"); shown on the Community page.", "community"),
    Setting("connectors.jira.url", "text", "Your Jira Cloud site, like https://acme.atlassian.net. The API token goes in the JIRA_API_TOKEN secret, never here.", "integrations"),
    Setting("connectors.jira.email", "text", "The Jira account's email, when it is not in the JIRA_EMAIL secret.", "integrations"),
    Setting("connectors.jira.scope_jql", "text", "JQL for the issues to read, like project in (WEB, API); empty reads every issue the account can see.", "integrations"),
    Setting("connectors.jira.incident_jql", "text", "JQL for the issues that are incidents, like issuetype = Incident; they count in DORA's change failure rate and recovery.", "integrations"),
    Setting("connectors.jira.key_expires", "date", "When the Jira API token expires (a year at most); a warning shows 14 days before.", "integrations"),
    Setting("connectors.jira.write_back", "bool", "Comment on the Jira issue a merged pull request names (the account must be able to comment); off by default.", "integrations"),
    Setting("connectors.jira.done_transition", "text", "With write-back on, the transition to move that issue through, like Done; empty only comments.", "integrations"),
    Setting("connectors.jira.flaky_tickets", "bool", "Open a Jira issue for each test that turns flaky, in ticket_project, and comment and move it to done_transition (or Done) once fixed; the key must be able to write.", "integrations"),
    Setting("connectors.jira.ticket_project", "text", "The Jira project key flaky-test issues go in, like WEB.", "integrations"),
    Setting("connectors.jira.team_field", "text", "A Jira field that names each issue's team (its name, like Team, or its id, like customfield_10001): done issues are counted per team. Private repos only.", "integrations"),
    Setting("connectors.jira.severity_field", "text", "A Jira field that gives each incident's severity (name or id), shown with the incident.", "integrations"),
    Setting("connectors.linear.teams", "list", "Linear team keys to read, like ENG; empty reads every team the key can see.", "integrations"),
    Setting("connectors.linear.incident_labels", "list", "Linear labels that mark an incident.", "integrations"),
    Setting("connectors.linear.key_expires", "date", "When the Linear key expires, if it does; a warning shows 14 days before.", "integrations"),
    Setting("connectors.linear.write_back", "bool", "Comment on the Linear issue a merged pull request names (the key needs write access); off by default.", "integrations"),
    Setting("connectors.linear.done_state", "text", "With write-back on, the team's workflow state to move that issue to, like Done; empty only comments.", "integrations"),
    Setting("connectors.linear.flaky_tickets", "bool", "Open a Linear issue for each test that turns flaky, in ticket_team, and comment and move it to done_state (or Done) once fixed; the key must be able to write.", "integrations"),
    Setting("connectors.linear.ticket_team", "text", "The Linear team key flaky-test issues go in, like ENG.", "integrations"),
    Setting("connectors.discourse.url", "text", "The project's Discourse forum, like https://discuss.example.org; its public topics are read with no key (times and flags only, never text or usernames).", "integrations"),
    Setting("connectors.discourse.team", "list", "Forum usernames whose replies count as the project's (forum staff always do).", "integrations"),
    Setting("connectors.discourse.groups", "list", "Forum groups whose members' replies count as the project's.", "integrations"),
    Setting("connectors.slack.channels", "list", "Slack support channel ids to read (the bot from the slack-token input must be in each); only times and flags are kept.", "integrations"),
    Setting("connectors.slack.team", "list", "Slack user ids whose replies count as the project's.", "integrations"),
    Setting("connectors.slack.key_expires", "date", "When the Slack bot token expires, if it does; a warning shows 14 days before.", "integrations"),
    Setting("connectors.discord.channels", "list", "Discord channel ids to read (the bot from the discord-token input needs View Channel and Read Message History); only times and flags are kept.", "integrations"),
    Setting("connectors.discord.team", "list", "Discord user ids whose replies count as the project's.", "integrations"),
    Setting("connectors.discord.key_expires", "date", "When the Discord bot token expires, if it does; a warning shows 14 days before.", "integrations"),
    Setting("connectors.pagerduty.services", "list", "PagerDuty service ids whose incidents count; empty counts every service the key can see.", "integrations"),
    Setting("connectors.pagerduty.urgencies", "choices", "Which PagerDuty urgencies count as production incidents.", "integrations",
            choices=config.URGENCIES),
    Setting("connectors.pagerduty.key_expires", "date", "When the PagerDuty key expires, if it does; a warning shows 14 days before.", "integrations"),
    Setting("connectors.incident_io.incident_types", "list", "incident.io incident types that count, like Platform; empty counts every type (test and tutorial incidents never count).", "integrations"),
    Setting("connectors.incident_io.key_expires", "date", "When the incident.io key expires, if it does; a warning shows 14 days before.", "integrations"),
    Setting("connectors.copilot.org", "text", "The organization whose Copilot usage reports to keep; empty means this repo's owner.", "integrations"),
    Setting("connectors.copilot.key_expires", "date", "When the Copilot reports token expires, if it does; a warning shows 14 days before.", "integrations"),
    Setting("connectors.sonar.url", "text", "SonarCloud (https://sonarcloud.io) or your SonarQube server.", "integrations"),
    Setting("connectors.sonar.project", "text", "The Sonar project key, like myorg_myrepo; its quality gate and measures are read each day. A private project or SonarQube server needs the SONAR_TOKEN secret.", "integrations"),
    Setting("connectors.sonar.key_expires", "date", "When the Sonar token expires, if one is used; a warning shows 14 days before.", "integrations"),
    Setting("connectors.ai_spend.key_expires", "date", "When the soonest of the AI spend admin keys (Anthropic, OpenAI, "
            "Cursor) expires, if it does; a warning shows 14 days before.", "integrations"),
)
BY_KEY = {s.key: s for s in SETTINGS}


def default(key: str):
    node = config.DEFAULTS
    for part in key.split("."):
        node = node[part]
    return node


def to_json() -> list[dict]:
    """The list for the app's settings editor."""
    return [{"key": s.key, "kind": s.kind, "default": default(s.key), "help": s.help, "module": s.module,
             **({"choices": list(s.choices)} if s.choices else {}), **({"unit": s.unit} if s.unit else {})} for s in SETTINGS]


def _action_inputs() -> dict[str, str]:
    # The Action's input defaults, from action.yml beside the source (absent from an installed package).
    import re
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "action.yml"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    return dict(re.findall(r'^  ([a-z0-9-]+):\n(?:    .*\n)*?    default: "?([^"\n]*)"?', text, re.M))


def _shown(value, key: str = "", kind: str = "") -> str:
    if value is None:
        # Settings with no file default take the workflow input of the same name, else they are off.
        name = key.rsplit(".", 1)[-1].replace("_", "-")
        given = _action_inputs().get(name)
        if given is not None:
            return f"{'on' if given == 'true' else 'off'} (input {name})"
        return "off" if kind == "switch" else "none (off)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(f'"{v}"' for v in value) + "]" if value else "[] (none)"
    if isinstance(value, dict):
        return "{} (none)" if not value else str(value)
    return f'"{value}"' if isinstance(value, str) else str(value)


def markdown() -> str:
    """docs/settings.md: every setting with its default, grouped by section."""
    lines = ["# StackVitals settings", "",
             f"Put these in `{config.FILE}` on your default branch. A merged change applies on the next run (the workflow",
             "runs when the file is pushed). A missing file means the defaults; a value StackVitals can't use keeps its",
             "default and is named in the job summary. The app's Settings page edits the same file.", ""]
    section = None
    for s in SETTINGS:
        head = s.key.rsplit(".", 1)[0] if s.kind not in ("dates",) else s.key
        if head != section:
            section = head
            lines += ["", f"## [{section}]", "", "| Key | Default | What it does |", "|---|---|---|"]
        name = s.key.rsplit(".", 1)[-1] if s.kind != "dates" else '"test id or pattern"'
        unit = f" {s.unit}" if s.unit and s.kind not in ("share",) else ""
        lines.append(f"| `{name}` | `{_shown(default(s.key), s.key, s.kind)}`{unit} | {s.help} |")
    lines += ["", "Example:", "", "```toml", "[alerts]", "pickup_p75_hours = 6", "channels = [\"webhook\", \"issue\"]", "",
              "[ci.mute]", "\"tests/test_api.py::test_slow_network\" = 2026-12-31", "", "[automation]", "issues = true", "```", ""]
    return "\n".join(lines)
