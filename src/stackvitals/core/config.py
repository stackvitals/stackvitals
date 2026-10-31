"""The repo's own settings, from `.github/stackvitals.toml` on its default branch: monitor thresholds, mutes and quarantine
overrides. A missing file means the defaults; a bad value keeps its default and says so in the job summary."""
import copy
import re
import tomllib
from datetime import date, datetime

FILE = ".github/stackvitals.toml"
# Advisory severities, lowest first, as OSV and GitHub name them.
SEVERITIES = ("low", "moderate", "high", "critical")
# Trunk's documented monitor shape; the heal time keeps our own two quiet weeks (one line to change).
MONITORS = {
    "pass_on_retry": {"min_events": 2, "quiet_days": 14, "quiet_runs": 10},
    "failure_rate": {"enabled": True, "window_runs": 50, "min_runs": 20, "activate": 0.15, "resolve": 0.05},
    "broken": {"streak": 3, "window_runs": 5, "activate": 0.8, "resolve": 0.5},
    "slow": {"p50_ms": 5000},
    "timeout_inflation": {"ratio": 2.0, "min_failures": 3},
}
# Where code ships and what counts as an incident (DevLake's defaults, widened for common names).
DELIVERY = {"deploy_workflow": r"(?i)(deploy|release|publish|push-image)", "production": ["production", "prod", "live"],
            "incident_labels": ["incident", "outage", "sev1", "sev-1", "sev2", "sev-2", "p0"], "hotfix_labels": ["hotfix"],
            "source": "auto", "dora_report": "2023", "fix_patterns": [], "incident_sources": [], "ignore_reverts_of": [], "production_branches": []}
SOURCES = ("auto", "deployments", "workflows", "releases", "merges")
# Where incidents may come from; an empty list keeps the automatic choice (a pager tool's alone when there is one).
INCIDENT_SOURCES = ("issues", "reverts", "hotfixes", "fixes", "pager", "tracker", "recorded")
# Who is who when GitHub's account type gets it wrong, old logins, and teams (DevLake's team and user mapping).
IDENTITY = {"bots": [], "people": [], "aliases": {}, "teams": {}, "knowledge_names": False}
# Alert thresholds: P75 hours from LinearB's 2026 "good" band, the failure rate from DORA's 2023 medium tier; 0 turns one off.
ALERTS = {"pickup_p75_hours": 4.0, "review_p75_hours": 14.0, "cycle_p75_hours": 72.0, "change_failure_rate": 0.15,
          "channels": ["webhook"]}
CHANNELS = ("webhook", "issue")
# Switches that are also workflow inputs; unset means the input decides, so the app can change them without a workflow edit.
AUTOMATION = {k: None for k in ("pr_comments", "rerun_flaky", "quarantine", "issues", "mention_owners", "assign_owners",
                                "preflight_comments", "deps_comments", "label_stuck", "verdict_check", "verdict_strict")}
# Team automation writes to the repo, so each part is off until the team turns it on (user decision, 2026-10-24, after
# outside reviews; it was on by default before). Each says what it did in the summary.
AUTOMATION.update({"review_requests": False, "size_labels": False, "docs_label": False, "fix_requests": False,
                   "fix_by_copilot": False})
# The weekly digest: on the first scheduled run after this day and hour (UTC), to one pinned issue and/or the webhook.
DIGEST = {"enabled": True, "day": "monday", "hour": 6, "channels": ["issue"], "pulse": True}
# Findings sent out as events (core/events.py): which kinds, and a repo to send them to as repository_dispatch.
EVENTS = {"send": ["alert", "newly_flaky", "pr_verdict"], "dispatch_repo": ""}
EVENT_KINDS = ("alert", "newly_flaky", "pr_verdict")
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# Working agreements a team sets for itself (Swarmia's), all off until set; 0 or false is off.
AGREEMENTS = {"review_within_hours": 0, "merge_within_days": 0, "max_pr_lines": 0, "linked_issue": False,
              "review_before_merge": False}
# Outside trackers, each read with one key from the repo's secrets (a key never goes in this file).
CONNECTORS = {"jira": {"url": "", "email": "", "scope_jql": "", "incident_jql": "", "key_expires": "", "write_back": False,
                       "done_transition": "", "team_field": "", "severity_field": "",
                       "flaky_tickets": False, "ticket_project": ""},
              "linear": {"teams": [], "incident_labels": ["incident"], "key_expires": "", "write_back": False, "done_state": "",
                         "flaky_tickets": False, "ticket_team": ""},
              "pagerduty": {"services": [], "urgencies": ["high"], "key_expires": ""},
              "incident_io": {"incident_types": [], "key_expires": ""},
              "copilot": {"org": "", "key_expires": ""},
              # Anthropic, OpenAI and Cursor costs, each with an optional admin key; nothing to configure but the expiry.
              "ai_spend": {"key_expires": ""},
              "sonar": {"url": "https://sonarcloud.io", "project": "", "key_expires": ""},
              # A forum read from its public JSON: no key, so nothing to expire.
              "discourse": {"url": "", "team": [], "groups": []},
              # Chat support channels, read with a bot token the user installs; team members are user ids.
              "slack": {"channels": [], "team": [], "key_expires": ""},
              "discord": {"channels": [], "team": [], "key_expires": ""}}
URGENCIES = ("high", "low")
GITHUB_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
# Jira Cloud sites only, so a settings change can never send the key to another server.
JIRA_SITE = re.compile(r"https://[A-Za-z0-9][A-Za-z0-9-]*\.atlassian\.net/?")
CONNECTOR_HELP = {"jira": "url is your Jira Cloud site like https://acme.atlassian.net, email an address, scope_jql and "
                          "incident_jql JQL text, key_expires a date like 2027-10-21, write_back true or false, "
                          "done_transition a transition name, team_field and severity_field a field name or id",
                  "sonar": "url is https://sonarcloud.io or your SonarQube server, project the Sonar project key",
                  "linear": "teams and incident_labels are lists of names, key_expires a date like 2027-10-21, write_back true "
                            "or false, done_state a workflow state name",
                  "pagerduty": "services is a list of service ids, urgencies high and/or low, key_expires a date",
                  "incident_io": "incident_types is a list of incident type names, key_expires a date like 2027-10-21",
                  "copilot": "org is a GitHub organization name, key_expires a date like 2027-10-21",
                  "discourse": "url is the forum's https address like https://discuss.example.org, team and groups lists of "
                               "usernames and group names",
                  "slack": "channels and team are lists of channel ids (C0123) and user ids (U0123), key_expires a date",
                  "discord": "channels and team are lists of channel ids and user ids (numbers as text), key_expires a date"}
# Opt-in model triage of undecided failures (ci/triage.py): off or a provider name, an optional model and endpoint url,
# and whether a private repo's logs may be sent.
TRIAGE = {"provider": "off", "model": "", "url": "", "allow_private": False}
TRIAGE_PROVIDERS = ("off", "gemini", "openai", "anthropic", "mistral", "groq")
DEFAULTS = {"ci": {"monitors": MONITORS, "mute": {}, "quarantine": {"always": [], "never": [], "max_days": 0}, "coverage": {"min_patch": 0.0},
                   "triage": TRIAGE},
            "delivery": DELIVERY,
            "identity": IDENTITY, "alerts": ALERTS, "events": EVENTS, "automation": AUTOMATION, "digest": DIGEST, "agreements": AGREEMENTS,
            "connectors": CONNECTORS, "deps": {"licenses": {"deny": []}, "policy": {"min_scorecard": None, "max_severity": None},
                                                           "outside_lookups": True, "guarddog": False}, "investment": {"labels": {}},
            "community": {"capacity": "", "norms": ""}, "benchmarks": {"share": False, "name": False},
            # Services inside the repo (a monorepo): name -> CODEOWNERS-style paths and a deployment-name pattern.
            "services": {},
            # PR rules as code ([[rules]]): when a pull request matches, its label, reviewers or comment (flow/rules.py).
            "rules": [],
            # The team's working calendar: weekends and holidays left out of review phases (core/calendar.py).
            "calendar": {"weekends": [], "holidays": []}}
STATED_MAX = 300  # characters of each [community] statement shown beside the numbers
INVESTMENT = ("feature", "fix", "maintenance", "security", "docs")  # the kinds of work in the investment mix


def _day(value) -> str:
    # TOML gives dates, date-times (2027-10-21T10:00:00Z) or text; the key's expiry is kept as a plain date.
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat() if isinstance(value, date) else date.fromisoformat(value).isoformat() if value else ""


# A Discourse forum: any https site (no key goes there), without a path, query or credentials.
FORUM = re.compile(r"https://[a-z0-9.-]+\.[a-z]{2,}/?", re.I)


def _connector_ok(name: str, key: str, value) -> bool:
    if key in ("write_back", "flaky_tickets"):
        return isinstance(value, bool)
    if key in ("ticket_project", "ticket_team"):
        return isinstance(value, str) and bool(re.fullmatch(r"([A-Z][A-Z0-9_]{0,19})?", value))
    if key in ("done_transition", "done_state"):
        return isinstance(value, str) and len(value) <= 100
    if key == "key_expires":
        try:
            return value == "" or isinstance(value, date) or isinstance(value, str) and bool(date.fromisoformat(value))
        except ValueError:
            return False
    if name == "pagerduty" and key == "urgencies":
        return isinstance(value, list) and bool(value) and set(value) <= set(URGENCIES)
    if name == "copilot":
        return key == "org" and isinstance(value, str) and (value == "" or bool(GITHUB_NAME.fullmatch(value)))
    if name == "sonar":
        return isinstance(value, str) and ((key == "url" and bool(FORUM.fullmatch(value)))
                                           or (key == "project" and len(value) <= 400 and " " not in value))
    if name == "discourse" and key == "url":
        return isinstance(value, str) and (value == "" or bool(FORUM.fullmatch(value)))
    if name == "jira":
        return isinstance(value, str) and (
            (key == "url" and bool(JIRA_SITE.fullmatch(value))) or (key == "email" and "@" in value and " " not in value)
            or (key in ("scope_jql", "incident_jql") and len(value) <= 2000)
            or (key in ("team_field", "severity_field") and len(value) <= 100))
    return isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value)


def _valid(default, value) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def parse(text: str | None) -> tuple[dict, list[str]]:
    """(settings, notes): the defaults with the file's valid values on top, and a note for everything left out."""
    cfg, notes = copy.deepcopy(DEFAULTS), []
    if not (text or "").strip():
        return cfg, notes
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return cfg, [f"{FILE} couldn't be read ({exc}); the defaults were used."]
    for section in doc:
        if section not in DEFAULTS:
            notes.append(f"[{section}] in {FILE} is not a section StackVitals reads ({', '.join(DEFAULTS)}); it was ignored.")
    ci = doc.get("ci") if isinstance(doc.get("ci"), dict) else {}
    for key in ci:
        if key not in DEFAULTS["ci"]:
            notes.append(f"ci.{key} in {FILE} is not a setting StackVitals knows; it was ignored.")
    for name, values in (ci.get("monitors") or {}).items():
        if name not in MONITORS or not isinstance(values, dict):
            notes.append(f"[ci.monitors.{name}] in {FILE} is not a monitor StackVitals knows; it was ignored.")
            continue
        for key, value in values.items():
            default = MONITORS[name].get(key)
            if default is None or not _valid(default, value):
                notes.append(f"ci.monitors.{name}.{key} = {value!r} in {FILE} was ignored (the default {default!r} applies).")
                continue
            cfg["ci"]["monitors"][name][key] = value if isinstance(default, bool) else type(default)(value)
    for key, value in (ci.get("coverage") if isinstance(ci.get("coverage"), dict) else {}).items():
        if key == "min_patch" and isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
            cfg["ci"]["coverage"]["min_patch"] = float(value)
        else:
            notes.append(f"ci.coverage.{key} = {value!r} in {FILE} was ignored (min_patch is a share from 0 to 1; 0 is off).")
    for key, value in (ci.get("triage") if isinstance(ci.get("triage"), dict) else {}).items():
        ok = (key == "provider" and value in TRIAGE_PROVIDERS
              or key == "allow_private" and isinstance(value, bool)
              or key == "model" and isinstance(value, str) and len(value) <= 100
              or key == "url" and isinstance(value, str) and value.startswith("https://") and len(value) <= 300)
        if ok:
            cfg["ci"]["triage"][key] = value
        else:
            notes.append(f"ci.triage.{key} = {value!r} in {FILE} was ignored (provider is one of "
                         f"{', '.join(TRIAGE_PROVIDERS)}; url must be https; allow_private is true or false; GitHub Models "
                         f"was retired in July 2026).")
    for pattern, until in (ci.get("mute") or {}).items():
        text_date = until.isoformat() if isinstance(until, date) else str(until)
        try:
            date.fromisoformat(text_date)
        except ValueError:
            notes.append(f"ci.mute.{pattern!r} = {until!r} in {FILE} needs a date like 2026-12-31; it was ignored.")
            continue
        cfg["ci"]["mute"][str(pattern)] = text_date
    d = doc.get("delivery") if isinstance(doc.get("delivery"), dict) else {}
    for key, value in d.items():
        default = DELIVERY.get(key)
        ok = (isinstance(default, list) and isinstance(value, list) and all(isinstance(x, str) for x in value)) or \
             (isinstance(default, str) and isinstance(value, str))
        if key == "source" and value not in SOURCES or key == "dora_report" and value not in ("2021", "2023"):
            ok = False
        if key == "deploy_workflow" and ok:
            try:
                re.compile(value)
            except re.error:
                ok = False
        if key == "fix_patterns" and ok:
            # Each names the PR being fixed in its one group, like "^fix.*#([0-9]+)" or "^hotfix/([0-9]+)-".
            try:
                ok = len(value) <= 5 and all(re.compile(x).groups == 1 for x in value)
            except re.error:
                ok = False
        if key == "incident_sources" and ok and not set(value) <= set(INCIDENT_SOURCES):
            ok = False
        if default is None or not ok:
            notes.append(f"delivery.{key} = {value!r} in {FILE} was ignored (the default {default!r} applies).")
            continue
        cfg["delivery"][key] = value
    ident = doc.get("identity") if isinstance(doc.get("identity"), dict) else {}
    for key, value in ident.items():
        if key in ("bots", "people") and isinstance(value, list) and all(isinstance(x, str) for x in value):
            cfg["identity"][key] = list(value)
        elif key == "aliases" and isinstance(value, dict) and all(isinstance(v, str) for v in value.values()):
            cfg["identity"]["aliases"] = {str(k): v for k, v in value.items()}
        elif key == "teams" and isinstance(value, dict) and all(
                isinstance(v, list) and all(isinstance(x, str) for x in v) for v in value.values()):
            cfg["identity"]["teams"] = {str(k): list(v) for k, v in value.items()}
        elif key == "knowledge_names" and isinstance(value, bool):
            cfg["identity"]["knowledge_names"] = value
        else:
            notes.append(f"identity.{key} in {FILE} was ignored (bots and people are lists of logins, aliases maps an "
                         f"old login to the current one, teams maps a team to its logins).")
    from stackvitals.flow.rules import check_rule
    for i, rule in enumerate(doc.get("rules") if isinstance(doc.get("rules"), list) else []):
        problem = check_rule(rule)
        if problem:
            notes.append(f"rules[{i + 1}] in {FILE} was ignored ({problem}).")
        else:
            cfg["rules"].append({"name": rule["name"], "when": dict(rule.get("when") or {}), "then": dict(rule["then"]),
                                 "dry_run": bool(rule.get("dry_run", False))})
    cal = doc.get("calendar") if isinstance(doc.get("calendar"), dict) else {}
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    if "weekends" in cal:
        if isinstance(cal["weekends"], list) and all(isinstance(d, str) and d.lower() in days for d in cal["weekends"]):
            cfg["calendar"]["weekends"] = [d.lower() for d in cal["weekends"]]
        else:
            notes.append(f"calendar.weekends in {FILE} was ignored (a list of day names, like [\"saturday\", \"sunday\"]).")
    if "holidays" in cal:
        try:
            if not isinstance(cal["holidays"], list):
                raise ValueError("not a list")
            cfg["calendar"]["holidays"] = sorted({date.fromisoformat(str(h)).isoformat() for h in cal["holidays"]})
        except (ValueError, TypeError):
            notes.append(f"calendar.holidays in {FILE} was ignored (a list of dates, like [\"2026-12-25\"]).")
    for name, svc in (doc.get("services") if isinstance(doc.get("services"), dict) else {}).items():
        paths = svc.get("paths") if isinstance(svc, dict) else None
        if not (isinstance(paths, list) and paths and all(isinstance(x, str) and x.strip() for x in paths)):
            notes.append(f"services.{name} in {FILE} was ignored (paths is a list of CODEOWNERS-style patterns, like "
                         '["services/api/", "libs/shared/**"]).')
            continue
        deploy = svc.get("deploy") or ""
        try:
            re.compile(deploy) if isinstance(deploy, str) else None
        except re.error:
            deploy = None
        if not isinstance(deploy, str):
            notes.append(f"services.{name}.deploy in {FILE} was ignored (a pattern matched against each deployment's "
                         "environment or workflow name, like \"api-prod\").")
            deploy = ""
        cfg["services"][str(name)] = {"paths": list(paths), "deploy": deploy}
    for key, value in (doc.get("alerts") if isinstance(doc.get("alerts"), dict) else {}).items():
        if key == "channels" and isinstance(value, list) and set(value) <= set(CHANNELS):
            cfg["alerts"]["channels"] = list(value)
        elif key in ALERTS and key != "channels" and _valid(ALERTS[key], value):
            cfg["alerts"][key] = float(value)
        else:
            notes.append(f"alerts.{key} = {value!r} in {FILE} was ignored (thresholds are numbers, 0 turns one off; "
                         f"channels are {', '.join(CHANNELS)}).")
    for key, value in (doc.get("events") if isinstance(doc.get("events"), dict) else {}).items():
        if key == "send" and isinstance(value, list) and set(value) <= set(EVENT_KINDS):
            cfg["events"]["send"] = list(value)
        elif key == "dispatch_repo" and isinstance(value, str) and (not value or re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", value)):
            cfg["events"]["dispatch_repo"] = value
        else:
            notes.append(f"events.{key} = {value!r} in {FILE} was ignored (send is a list from {', '.join(EVENT_KINDS)}; "
                         "dispatch_repo is owner/name).")
    for key, value in (doc.get("automation") if isinstance(doc.get("automation"), dict) else {}).items():
        if key in AUTOMATION and isinstance(value, bool):
            cfg["automation"][key] = value
        else:
            notes.append(f"automation.{key} = {value!r} in {FILE} was ignored (switches are true or false: "
                         f"{', '.join(AUTOMATION)}).")
    for key, value in (doc.get("agreements") if isinstance(doc.get("agreements"), dict) else {}).items():
        if key in AGREEMENTS and _valid(AGREEMENTS[key], value):
            cfg["agreements"][key] = value
        else:
            notes.append(f"agreements.{key} = {value!r} in {FILE} was ignored (limits are numbers, 0 turns one off; "
                         "linked_issue and review_before_merge are true or false).")
    for key, value in (doc.get("digest") if isinstance(doc.get("digest"), dict) else {}).items():
        ok = ((key in ("enabled", "pulse") and isinstance(value, bool)) or (key == "day" and value in DAYS)
              or (key == "hour" and isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 23)
              or (key == "channels" and isinstance(value, list) and set(value) <= set(CHANNELS)))
        if ok:
            cfg["digest"][key] = list(value) if key == "channels" else value
        else:
            notes.append(f"digest.{key} = {value!r} in {FILE} was ignored (enabled is true or false, day a weekday name, "
                         f"hour 0 to 23 in UTC, channels from {', '.join(CHANNELS)}).")
    deps = doc.get("deps") if isinstance(doc.get("deps"), dict) else {}
    if "outside_lookups" in deps:
        if isinstance(deps["outside_lookups"], bool):
            cfg["deps"]["outside_lookups"] = deps["outside_lookups"]
        else:
            notes.append(f"deps.outside_lookups = {deps['outside_lookups']!r} in {FILE} was ignored (true or false).")
    if "guarddog" in deps:
        if isinstance(deps["guarddog"], bool):
            cfg["deps"]["guarddog"] = deps["guarddog"]
        else:
            notes.append(f"deps.guarddog = {deps['guarddog']!r} in {FILE} was ignored (true or false).")
    for key, value in (deps.get("licenses") if isinstance(deps.get("licenses"), dict) else {}).items():
        if key == "deny" and isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value):
            cfg["deps"]["licenses"]["deny"] = [x.strip() for x in value]
        else:
            notes.append(f"deps.licenses.{key} = {value!r} in {FILE} was ignored (deny is a list of SPDX licence ids, "
                         "* allowed, like [\"GPL-3.0*\", \"AGPL-*\"]).")
    for key, value in (deps.get("policy") if isinstance(deps.get("policy"), dict) else {}).items():
        if key == "min_scorecard" and isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 10:
            cfg["deps"]["policy"]["min_scorecard"] = float(value)
        elif key == "max_severity" and isinstance(value, str) and value.lower() in SEVERITIES:
            cfg["deps"]["policy"]["max_severity"] = value.lower()
        else:
            notes.append(f"deps.policy.{key} = {value!r} in {FILE} was ignored (min_scorecard is 0 to 10; max_severity is "
                         f"one of {', '.join(SEVERITIES)}).")
    for key, value in (doc.get("benchmarks") if isinstance(doc.get("benchmarks"), dict) else {}).items():
        if key in DEFAULTS["benchmarks"] and isinstance(value, bool):
            cfg["benchmarks"][key] = value
        else:
            notes.append(f"benchmarks.{key} = {value!r} in {FILE} was ignored (share and name are true or false).")
    # What the project says about itself (who maintains it and how much time they have, how it works), shown beside the numbers.
    for key, value in (doc.get("community") if isinstance(doc.get("community"), dict) else {}).items():
        if key in DEFAULTS["community"] and isinstance(value, str):
            cfg["community"][key] = " ".join(value.split())[:STATED_MAX]
        else:
            notes.append(f"community.{key} = {value!r} in {FILE} was ignored (capacity and norms are short texts).")
    investment = doc.get("investment") if isinstance(doc.get("investment"), dict) else {}
    for key in investment:
        if key != "labels":
            notes.append(f"investment.{key} in {FILE} is not a setting StackVitals knows (labels); it was ignored.")
    for name, value in (investment.get("labels") if isinstance(investment.get("labels"), dict) else {}).items():
        if name in INVESTMENT and isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value):
            cfg["investment"]["labels"][name] = [x.strip() for x in value]
        else:
            notes.append(f"investment.labels.{name} = {value!r} in {FILE} was ignored (a kind of work, one of "
                         f"{', '.join(INVESTMENT)}, with a list of label names).")
    for name, values in (doc.get("connectors") if isinstance(doc.get("connectors"), dict) else {}).items():
        if name not in CONNECTORS or not isinstance(values, dict):
            notes.append(f"[connectors.{name}] in {FILE} is not a connector StackVitals knows ({', '.join(CONNECTORS)}); "
                         "it was ignored.")
            continue
        for key, value in values.items():
            if key in CONNECTORS[name] and _connector_ok(name, key, value):
                cfg["connectors"][name][key] = (_day(value) if key == "key_expires" else list(value) if isinstance(value, list)
                                                else value.rstrip("/") if key == "url" else value)
            else:
                notes.append(f"connectors.{name}.{key} = {value!r} in {FILE} was ignored ({CONNECTOR_HELP[name]}).")
    quarantine = ci.get("quarantine") if isinstance(ci.get("quarantine"), dict) else {}
    for key in quarantine:
        if key not in ("always", "never", "max_days"):
            notes.append(f"ci.quarantine.{key} in {FILE} is not a setting StackVitals knows (always, never, max_days); it was ignored.")
    days = quarantine.get("max_days", 0)
    if isinstance(days, int) and not isinstance(days, bool) and 0 <= days <= 365:
        cfg["ci"]["quarantine"]["max_days"] = days
    else:
        notes.append(f"ci.quarantine.max_days in {FILE} must be a whole number of days (0 to 365); it was ignored.")
    for key in ("always", "never"):
        items = quarantine.get(key) or []
        if isinstance(items, list) and all(isinstance(x, str) for x in items):
            cfg["ci"]["quarantine"][key] = list(items)
        else:
            notes.append(f"ci.quarantine.{key} in {FILE} must be a list of test ids; it was ignored.")
    return cfg, notes
