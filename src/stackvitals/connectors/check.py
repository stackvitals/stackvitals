"""Test connection: one cheap call per connector proves its key and the configured scope work, said as one plain sentence
with the next step when they don't. The app asks for it with a request ({"version": 1, "check": [...] or "all"}), a
comment asks with `/stackvitals check jira`, and `stackvitals connectors check` runs it locally. Results go under each
connector's entry in docs/connectors.json as "check"; a key is never sent anywhere but its own service, nor written."""
import argparse
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

from stackvitals.connectors import ai_spend, copilot, discord, discourse, incident_io, jira, linear, pagerduty, slack, sonar
from stackvitals.core.time import iso

TIMEOUT = 10
TRANSPORT = None  # tests swap in a fake transport
NAMES = {"jira": "Jira", "linear": "Linear", "pagerduty": "PagerDuty", "incident_io": "incident.io", "slack": "Slack",
         "discord": "Discord", "discourse": "Discourse", "copilot": "Copilot", "webhook": "Chat webhooks", "gitlab": "GitLab",
         "s3": "Bucket storage", "triage": "Model triage", "ai_spend": "AI spend", "sonar": "SonarQube"}
ALIASES = {"chat": "webhook", "webhooks": "webhook", "incident.io": "incident_io", "incidentio": "incident_io",
           "bucket": "s3", "storage": "s3", "model": "triage", "spend": "ai_spend", "ai": "ai_spend", "sonarqube": "sonar",
           "sonarcloud": "sonar"}
NAMED = {"discourse", "triage"}  # the only "as" a public repo shows: a forum or a model provider names nobody
# Where each key lives: the secret to add, the workflow input that passes it, and the variable the CLI reads.
KEYS = {"jira": ("the repository secret JIRA_API_TOKEN", "jira-token", jira.TOKEN_ENV),
        "linear": ("the repository secret LINEAR_API_KEY", "linear-token", linear.TOKEN_ENV),
        "pagerduty": ("the repository secret PAGERDUTY_API_KEY", "pagerduty-token", pagerduty.TOKEN_ENV),
        "incident_io": ("the repository secret INCIDENT_IO_API_KEY", "incident-io-token", incident_io.TOKEN_ENV),
        "slack": ("the repository secret SLACK_BOT_TOKEN", "slack-token", slack.TOKEN_ENV),
        "discord": ("the repository secret DISCORD_BOT_TOKEN", "discord-token", discord.TOKEN_ENV),
        "copilot": ("the token you pass as copilot-token (an org App's token)", "copilot-token", copilot.TOKEN_ENV),
        "webhook": ("the repository secret STACKVITALS_WEBHOOK", "webhook", "STACKVITALS_WEBHOOK"),
        "gitlab": ("a masked CI/CD variable GITLAB_TOKEN (a project access token with api and write_repository)", None,
                   "GITLAB_TOKEN"),
        "s3": ("the secrets you pass as s3-key-id and s3-secret", "s3-key-id and s3-secret",
               "STACKVITALS_S3_KEY_ID and STACKVITALS_S3_SECRET"),
        "triage": ("the secret you pass as triage-key (a free Gemini key works)", "triage-key", "STACKVITALS_TRIAGE_KEY"),
        "ai_spend": ("one of the repository secrets ANTHROPIC_ADMIN_KEY, OPENAI_ADMIN_KEY or CURSOR_ADMIN_KEY",
                     "anthropic-admin-key, openai-admin-key or cursor-admin-key", ai_spend.KEYS["anthropic"]),
        "sonar": ("the repository secret SONAR_TOKEN (only for a private project or your own SonarQube)", "sonar-token",
                  sonar.TOKEN_ENV)}
TEST_TITLE = "StackVitals connection test"


class Fail(Exception):
    def __init__(self, detail: str, fix: str):
        super().__init__(detail)
        self.detail, self.fix = detail, fix


def _missing(name: str) -> Fail:
    where, given, var = KEYS[name]
    passed = f" and pass it as {given} in the workflow" if given else ""
    return Fail(f"No {NAMES[name]} key is set.", f"Add {where}{passed} (locally: {var}).")


def _renew(name: str) -> str:
    where, _given, var = KEYS[name]
    return f"Create a new key, put it in {where} (locally: {var}), then test again."


def _key(env: dict, name: str) -> str:
    key = (env.get(KEYS[name][2]) or "").strip()
    if not key:
        raise _missing(name)
    return key


def _send(client, method: str, url: str, service: str, name: str, forbidden=None, missing=None, retry: bool = True,
          **kw) -> httpx.Response:
    """One request, retried once on a network error or a 5xx (unless retry=False); the usual refusals become plain sentences."""
    for attempt in ((1, 2) if retry else (2,)):
        try:
            resp = client.request(method, url, **kw)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            if attempt == 1 and not isinstance(exc, httpx.InvalidURL):
                continue
            raise Fail(f"{service} could not be reached ({type(exc).__name__}).",
                       "Check the address and your network, then try again in a few minutes.") from None
        if resp.status_code >= 500 and attempt == 1:
            continue
        break
    code = resp.status_code
    if code == 401:
        raise Fail(f"{service} refused the key (401): it is wrong or expired.", _renew(name))
    if code == 403:
        what, fix = forbidden or ("the key lacks a permission or scope this needs", _renew(name))
        raise Fail(f"{service} answered 403: {what}.", fix)
    if code == 404:
        what, fix = missing or ("the address wasn't found", f"Check the settings for {NAMES[name]}, then test again.")
        raise Fail(f"{service} answered 404: {what}.", fix)
    if code == 429:
        raise Fail(f"{service}'s rate limit was reached (429).", "Wait a few minutes, then try again.")
    if code >= 500:
        raise Fail(f"{service} is having trouble ({code}).", "The service is down or busy; try again later.")
    return resp


def _json(resp: httpx.Response, service: str, kinds=(dict,)):
    try:
        out = resp.json()
    except ValueError:
        out = None
    if not isinstance(out, kinds):
        raise Fail(f"{service} answered with a page that is not JSON ({resp.status_code}).",
                   "Check the address; if it is right, try again later.")
    return out


def _bad(resp: httpx.Response, service: str, fix: str = "Try again later; if it repeats, check the settings.") -> None:
    if resp.status_code >= 300:
        raise Fail(f"{service} answered {resp.status_code}.", fix)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _it(pub: bool, word: str, value) -> str:
    # On a public repo a channel id, team key or bucket name stays off the data branch.
    return f"one configured {word}" if pub else f"{word} {value}"


def _jira(cfg, env, client, now, pub=False):
    key = _key(env, "jira")
    c = cfg["connectors"]["jira"]
    if not c["url"]:
        raise Fail("Jira's site isn't set.", "Set url under [connectors.jira] in .github/stackvitals.toml to your Jira Cloud "
                                             "site (https://<name>.atlassian.net).")
    if not c["url"].strip().lower().startswith("https://"):
        # The key would travel in the clear; it is never sent to a plain http address.
        raise Fail("Jira's site address isn't https, so the key wasn't sent.", "Set url under [connectors.jira] to the "
                   "https address of your Jira Cloud site (https://<name>.atlassian.net).")
    email = (env.get(jira.EMAIL_ENV) or "").strip() or c["email"]
    if not email:
        raise Fail("Jira needs the account's email beside the token.", "Add the repository secret JIRA_EMAIL and pass it as "
                   "jira-email (locally: STACKVITALS_JIRA_EMAIL), or set email under [connectors.jira].")
    site = c["url"].rstrip("/")
    headers = {"Authorization": "Basic " + base64.b64encode(f"{email}:{key}".encode()).decode(), "Accept": "application/json"}
    wrong_site = ("there is no Jira Cloud API at that site", "Check url under [connectors.jira]: https://<name>.atlassian.net.")
    me = _json(_send(client, "GET", f"{site}/rest/api/3/myself", "Jira", "jira", missing=wrong_site, headers=headers), "Jira")
    scope = c["scope_jql"].strip()
    where = "updated >= -30d ORDER BY updated DESC"
    resp = _send(client, "GET", f"{site}/rest/api/3/search/jql", "Jira", "jira", headers=headers,
                 forbidden=("the account can't browse the projects in scope_jql", "Give the account Browse projects "
                            "permission on those projects, or change scope_jql under [connectors.jira]."),
                 params={"jql": f"({scope}) AND {where}" if scope else where, "maxResults": 1, "fields": "summary"})
    if resp.status_code == 400:
        try:
            said = "; ".join((resp.json() or {}).get("errorMessages") or [])[:200]
        except (ValueError, AttributeError):
            said = ""
        raise Fail(f"Jira couldn't run the scope query ({said or 'bad request'}).",
                   "Fix scope_jql under [connectors.jira] (JQL, like project = WEB).")
    _bad(resp, "Jira")
    issues = _json(resp, "Jira").get("issues") or []
    if not issues:
        return me.get("displayName"), ("Signed in, but the scope query found no issue updated in the last 30 days; check "
                                       "scope_jql if that is unexpected.")
    project = str(issues[0].get("key") or "").split("-")[0]
    return me.get("displayName"), f"Signed in and read an issue from {_it(pub, 'project', project)} updated in the last 30 days."


# The configured team keys are asked for by name, so a team past the first 100 is still found.
LINEAR_CHECK = ("query Check($keys: [String!]) { viewer { name } organization { name } "
                "teams(first: 100) { nodes { key } pageInfo { hasNextPage } } "
                "wanted: teams(first: 100, filter: {key: {in: $keys}}) { nodes { key } } }")


def _linear(cfg, env, client, now, pub=False):
    key = _key(env, "linear")
    want = list(cfg["connectors"]["linear"]["teams"])
    resp = _send(client, "POST", linear.URL, "Linear", "linear",
                 json={"query": LINEAR_CHECK, "variables": {"keys": [t.upper() for t in want]}},
                 headers={"Authorization": key, "Content-Type": "application/json"})
    body = _json(resp, "Linear")
    errors = body.get("errors") or []
    if any((e.get("extensions") or {}).get("code") == "AUTHENTICATION_ERROR" for e in errors):
        raise Fail("Linear refused the key: it is wrong or expired.", _renew("linear"))
    if errors or resp.status_code != 200:
        said = "; ".join(str(e.get("message") or "") for e in errors)[:200]
        raise Fail(f"Linear couldn't answer ({said or resp.status_code}).", "Try again later.")
    data = body.get("data") or {}
    who = (data.get("viewer") or {}).get("name")
    org = (data.get("organization") or {}).get("name")
    teams = data.get("teams") or {}
    keys = [str(n.get("key") or "") for n in teams.get("nodes") or []]
    found = {str(n.get("key") or "").upper() for n in (data.get("wanted") or {}).get("nodes") or []} | {k.upper() for k in keys}
    unseen = [t for t in want if t.upper() not in found]
    if unseen:
        if pub:
            raise Fail(f"The key can't see {_plural(len(unseen), 'configured team')}.", "Check teams under "
                       "[connectors.linear] (team keys like ENG), or use a key from someone in that team.")
        raise Fail(f"The key can't see team {', '.join(unseen)} (it sees {', '.join(keys[:6]) or 'no team'}).",
                   "Check teams under [connectors.linear] (team keys like ENG), or use a key from someone in that team.")
    many = "100+ teams" if (teams.get("pageInfo") or {}).get("hasNextPage") else _plural(len(keys), "team")
    shown = "" if pub else ", ".join((want or keys)[:3])
    return (f"{who} ({org})" if who and org else who or org), \
        f"Signed in and sees {many}" + (f", including {shown}." if shown else ".")


def _pagerduty(cfg, env, client, now, pub=False):
    key = _key(env, "pagerduty")
    c = cfg["connectors"]["pagerduty"]
    headers = {"Authorization": f"Token token={key}", "Accept": "application/vnd.pagerduty+json;version=2"}
    base = pagerduty.URL.rsplit("/", 1)[0]
    for sid in c["services"]:
        fix = "Check services under [connectors.pagerduty]: the ids from each service's page address, like PABC123."
        got = _send(client, "GET", f"{base}/services/{quote(sid, safe='')}", "PagerDuty", "pagerduty", headers=headers,
                    missing=(f"there is no {_it(pub, 'service', sid)} this key can see", fix))
        _bad(got, f"PagerDuty, for {_it(pub, 'service', sid)},", fix)
    params = [("limit", 1), *(("service_ids[]", s) for s in c["services"]), *(("urgencies[]", u) for u in c["urgencies"])]
    resp = _send(client, "GET", pagerduty.URL, "PagerDuty", "pagerduty", headers=headers, params=params)
    if resp.status_code == 400:
        raise Fail("PagerDuty couldn't list incidents with these settings (400).",
                   "Check services and urgencies under [connectors.pagerduty].")
    _bad(resp, "PagerDuty")
    _json(resp, "PagerDuty")
    n = len(c["services"])
    return None, (f"Listed incidents for the {_plural(n, 'configured service')}." if n else
                  "Listed incidents; no services are set, so every service in the account counts.")


def _incident_io(cfg, env, client, now, pub=False):
    key = _key(env, "incident_io")
    resp = _send(client, "GET", incident_io.URL, "incident.io", "incident_io", params={"page_size": 1},
                 headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                 forbidden=("the key lacks permission to view incidents", "Create a key with the \"View data\" permission and put it in "
                            "the repository secret INCIDENT_IO_API_KEY."))
    _bad(resp, "incident.io")
    _json(resp, "incident.io")
    return None, "Listed incidents: the key can view them."


SLACK_REVOKED = {"invalid_auth", "not_authed", "account_inactive", "token_revoked", "token_expired"}


def _slack_call(client, key: str, method: str, **params) -> dict:
    resp = _send(client, "GET", f"{slack.API}/{method}", "Slack", "slack", params=params,
                 headers={"Authorization": f"Bearer {key}"})
    body = _json(resp, "Slack")
    err = body.get("error")
    if not body.get("ok") and err in SLACK_REVOKED:
        raise Fail(f"Slack refused the token ({err}): it is wrong or expired.", _renew("slack"))
    if not body.get("ok") and err == "missing_scope":
        need = body.get("needed") or "channels:history"
        raise Fail(f"The Slack bot lacks the {need} scope.", f"Add the {need} scope to the Slack app, reinstall it, and "
                   "put the new token in the repository secret SLACK_BOT_TOKEN.")
    return body


def _slack(cfg, env, client, now, pub=False):
    key = _key(env, "slack")
    me = _slack_call(client, key, "auth.test")
    if not me.get("ok"):
        raise Fail(f"Slack refused the token ({me.get('error')}).", _renew("slack"))
    bot = me.get("user") or "the bot"
    who = f"{me.get('user')} in {me.get('team')}" if me.get("user") and me.get("team") else me.get("team")
    channels = cfg["connectors"]["slack"]["channels"]
    if not channels:
        raise Fail("The token works, but no channels are set.", "Add the support channels' ids (like C0123) under channels "
                   "in [connectors.slack].")
    for ch in channels:
        # The same call and scope the real pull uses (channels:history), so a pass means it will read.
        got = _slack_call(client, key, "conversations.history", channel=ch, limit=1)
        err = got.get("error")
        if got.get("ok"):
            continue
        name = _it(pub, "channel", ch)
        if err == "not_in_channel":
            raise Fail(f"The bot isn't in {name}.", f"Invite it: open the channel in Slack and type /invite @{bot}.")
        if err == "channel_not_found":
            raise Fail(f"Slack has no {name} the bot can see (channel_not_found).",
                       f"Check channels under [connectors.slack] (ids like C0123); for a private channel, /invite @{bot} there.")
        raise Fail(f"Slack refused reading {name} ({err}).", f"Check the bot's scopes (channels:history, "
                   f"groups:history for private channels) and /invite @{bot} to the channel.")
    return who, f"Signed in and can read {_plural(len(channels), 'channel')}."


def _discord(cfg, env, client, now, pub=False):
    key = _key(env, "discord")
    headers = {"Authorization": f"Bot {key}"}
    me = _json(_send(client, "GET", f"{discord.API}/users/@me", "Discord", "discord", headers=headers), "Discord")
    channels = cfg["connectors"]["discord"]["channels"]
    if not channels:
        raise Fail("The bot token works, but no channels are set.", "Add the support channels' ids under channels in "
                   "[connectors.discord].")
    where = ("Check channels under [connectors.discord] (turn on Developer Mode, right-click the channel, Copy Channel ID); "
             "a forum or voice channel isn't read.")
    for ch in channels:
        name = _it(pub, "channel", ch)
        resp = _send(client, "GET", f"{discord.API}/channels/{quote(ch, safe='')}/messages", "Discord", "discord",
                     headers=headers, params={"limit": 1},
                     forbidden=(f"the bot can't read {name}", "Give the bot View Channel and Read Message History in that "
                                "channel (its Permissions, or the bot's role)."),
                     missing=(f"there is no {name} the bot can see", where))
        if resp.status_code == 400:
            raise Fail(f"Discord answered 400 for {name}: not a text channel, or a bad channel id.", where)
        _bad(resp, "Discord", where)
    return me.get("username"), f"Signed in and can read {_plural(len(channels), 'channel')}."


def _discourse(cfg, env, client, now, pub=False):
    url = (cfg["connectors"]["discourse"]["url"] or "").rstrip("/")
    if not url:
        raise Fail("No forum is set.", "Set url under [connectors.discourse] to the forum's address (https://...).")
    resp = _send(client, "GET", f"{url}/latest.json", "The forum", "discourse", headers={"Accept": "application/json"},
                 missing=("there is no Discourse forum at that address", "Check url under [connectors.discourse]: the "
                          "forum's home address, like https://discuss.example.org."),
                 forbidden=("the forum doesn't let visitors read it", "StackVitals reads public forums only; a forum "
                            "that needs a login can't be read."))
    _bad(resp, "The forum", "Check url under [connectors.discourse].")
    topics = (_json(resp, "The forum").get("topic_list") or {}).get("topics") or []
    return None, f"Read the forum's latest topics ({len(topics)} on the first page); no key needed."


def _webhook(cfg, env, client, now, pub=False):
    from stackvitals.core import chat
    url = (env.get("STACKVITALS_WEBHOOK") or "").strip()
    teams = chat.team_hooks(env)
    if not url and not teams:
        raise _missing("webhook")
    msg = chat.message(TEST_TITLE, ["A test from the Test connection button in StackVitals. Nothing needs doing; "
                                    "you can delete this message."])
    targets = ([("The webhook", url)] if url else []) + [("One team webhook" if pub else f"The {team} webhook", u)
                                                         for team, u in teams.items()]
    fix = "Create a new incoming webhook and put it in the STACKVITALS_WEBHOOK secret (or the team's line in " \
          "STACKVITALS_TEAM_WEBHOOKS)."
    for label, hook in targets:
        if not hook.startswith("https://"):
            raise Fail(f"{label} isn't an https address.", fix)
        # Never retried: a slow chat that did post would get the test message twice.
        resp = _send(client, "POST", hook, label, "webhook", json=chat.payload(hook, msg), retry=False,
                     forbidden=("the chat refused the post", fix),
                     missing=("the webhook was deleted or its address is wrong", fix))
        _bad(resp, label, fix)
    shapes = {"slack": "Slack", "teams": "Teams", "discord": "Discord", "json": "JSON"}
    who = ", ".join(([f"{shapes[chat.kind(url)]} webhook"] if url else []) +
                    ([_plural(len(teams), "team webhook")] if teams else []))
    return who, (f"Posted a labelled test message (\"{TEST_TITLE}\") to {_plural(len(targets), 'webhook')}; look for "
                 "it in the chat.")


GITLAB_SCOPES = ("api", "write_repository")  # notes and pipelines through the API; pushes to the data branch


def _gitlab(cfg, env, client, now, pub=False):
    from stackvitals.ci import gitlab
    key = _key(env, "gitlab")
    project = (env.get("CI_PROJECT_PATH") or env.get("STACKVITALS_GITLAB_PROJECT") or "").strip()
    if not project:
        raise Fail("No GitLab project is named.", "Set STACKVITALS_GITLAB_PROJECT to group/project (inside GitLab CI it "
                   "comes from CI_PROJECT_PATH).")
    base = (env.get("CI_API_V4_URL") or gitlab.API).rstrip("/")
    scopes_fix = "Give the token the api and write_repository scopes (a new project access token), then update GITLAB_TOKEN."
    headers = {"PRIVATE-TOKEN": key}
    resp = _send(client, "GET", f"{base}/projects/{quote(project, safe='')}", "GitLab", "gitlab", headers=headers,
                 forbidden=("the token lacks a scope this needs", scopes_fix),
                 missing=(f"there is no {_it(pub, 'project', project)} this token can see", "Check the project path, and "
                          "that the token belongs to that project."))
    _bad(resp, "GitLab")
    body = _json(resp, "GitLab")
    name = body.get("path_with_namespace") or project
    shown = "the project" if pub else f"project {name}"
    read = f"Read {shown} (default branch {body.get('default_branch') or 'unknown'})"
    # Reading proves little: the job also writes notes and pushes, so the token's scopes are read too.
    try:
        me = _json(_send(client, "GET", f"{base}/personal_access_tokens/self", "GitLab", "gitlab", headers=headers), "GitLab")
    except Fail:
        me = None
    scopes = me.get("scopes") if isinstance(me, dict) else None
    if not isinstance(scopes, list):
        # Some tokens (older GitLab, job tokens) can't read their own scopes; say what to confirm instead.
        return (None if pub else name), (f"{read}; GitLab didn't show the token's scopes, so make sure it has api and "
                                          "write_repository.")
    lacking = [s for s in GITLAB_SCOPES if s not in scopes]
    if lacking:
        raise Fail(f"The token can read, but lacks the {' and '.join(lacking)} scope"
                   f"{'s' if len(lacking) > 1 else ''} it needs to write.", scopes_fix)
    if me.get("active") is False:
        raise Fail("GitLab says the token is no longer active.", _renew("gitlab"))
    return (None if pub else name), f"{read}; the token has the api and write_repository scopes."


def _s3(cfg, env, client, now, pub=False):
    from stackvitals.core.bucket import EMPTY, BucketError, BucketStore, _sha, sign
    storage = (env.get("STACKVITALS_STORAGE") or "").strip()
    if not storage.startswith("s3://"):
        raise Fail("No bucket is set.", "Set the storage input to s3://bucket/prefix (locally: STACKVITALS_STORAGE).")
    endpoint = (env.get("STACKVITALS_S3_ENDPOINT") or "").strip()
    if not endpoint:
        raise Fail("The bucket's endpoint isn't set.", "Set the s3-endpoint input to your bucket service's S3 endpoint "
                   "(locally: STACKVITALS_S3_ENDPOINT).")
    kid, secret = (env.get("STACKVITALS_S3_KEY_ID") or "").strip(), (env.get("STACKVITALS_S3_SECRET") or "").strip()
    if not kid or not secret:
        raise _missing("s3")
    try:
        store = BucketStore(storage, Path("."), endpoint, kid, secret, env.get("STACKVITALS_S3_REGION") or "auto")
    except BucketError as exc:
        raise Fail(f"The storage address isn't right ({exc}).", "Set storage to s3://bucket/prefix.") from None
    where = f"s3://{store.bucket}/{store.prefix}".rstrip("/")
    spot = "the configured bucket and prefix" if pub else where
    give = (f"the key lacks permission on {spot}", f"Give the key read, write, delete and list on {spot}, then test again.")

    def call(method, url, body=b""):
        # Signed at send time, not with the job's clock: S3 refuses a signature more than 15 minutes old.
        headers = sign(method, url, {}, _sha(body) if body else EMPTY, kid, secret, store.region, datetime.now(timezone.utc))
        return _send(client, method, url, "The bucket", "s3", content=body or None, headers=headers, forbidden=give,
                     missing=(f"there is no {_it(pub, 'bucket', store.bucket)} at that endpoint", "Check the bucket in "
                              "storage, s3-endpoint, and s3-region for AWS."))
    listing = f"{store.endpoint}/{store.bucket}?list-type=2&max-keys=1" + (f"&prefix={store.prefix}/" if store.prefix else "")
    _bad(call("GET", listing), "The bucket")
    # Only after listing works: one tiny object under the prefix, removed right away.
    probe = store._url(store._key(".stackvitals-check"))
    _bad(call("PUT", probe, b"stackvitals connection check"), "The bucket")
    left = (f"The test object .stackvitals-check was written but not deleted; it was left at {spot} and can be deleted "
            "by hand")
    try:
        gone = call("DELETE", probe)
    except Fail as f:
        raise Fail(f"{left} ({f.detail.rstrip('.')}).", f"Give the key delete on {spot}, then delete .stackvitals-check "
                   "there.") from None
    if gone.status_code >= 300:
        raise Fail(f"{left} ({gone.status_code}).", f"Give the key delete on {spot}, then delete .stackvitals-check there.")
    return (None if pub else where), "Listed the prefix, then wrote and deleted a small test object (.stackvitals-check)."


def _triage(cfg, env, client, now, pub=False):
    from stackvitals.ci.triage import PROVIDERS
    key = _key(env, "triage")
    t = (cfg.get("ci") or {}).get("triage") or {}
    provider = t.get("provider") or "off"
    if provider not in PROVIDERS:
        raise Fail("Model triage is off, so the key isn't used.", "Set provider under [ci.triage] (gemini for Google AI "
                   "Studio's free tier).")
    url = (t.get("url") or PROVIDERS[provider]["url"]).rstrip("/")
    model = t.get("model") or PROVIDERS[provider]["model"]
    headers = {"Authorization": f"Bearer {key}"}
    if provider == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    resp = _send(client, "GET", f"{url}/models", provider.capitalize(), "triage", headers=headers,
                 missing=("the endpoint has no models list", "Check url under [ci.triage]."))
    if resp.status_code == 400:
        raise Fail(f"{provider.capitalize()} refused the key (400): it is wrong or expired.", _renew("triage"))
    _bad(resp, provider.capitalize())
    ids = [str(m.get("id") or "") for m in _json(resp, provider.capitalize()).get("data") or [] if isinstance(m, dict)]
    if any(i == model or i.endswith("/" + model) for i in ids):
        return provider, f"The key works and {model} is available."
    return provider, f"The key works, but {model} isn't in the provider's model list; check model under [ci.triage]."


def _copilot(cfg, env, client, now, pub=False):
    key = _key(env, "copilot")
    org = cfg["connectors"]["copilot"]["org"] or (env.get("GITHUB_REPOSITORY") or "").partition("/")[0]
    if not org:
        raise Fail("No organization is named.", "Set org under [connectors.copilot].")
    day = (now.date() - timedelta(days=copilot.LAG)).isoformat()
    resp = _send(client, "GET", f"{copilot.API}/orgs/{quote(org, safe='')}/copilot/metrics/reports/organization-1-day",
                 "GitHub", "copilot", params={"day": day},
                 headers={"Authorization": f"Bearer {key}", "Accept": "application/vnd.github+json",
                          "X-GitHub-Api-Version": copilot.VERSION},
                 forbidden=("the token lacks the \"Organization Copilot metrics: read\" permission", "Make the token from an org App "
                            "(or a fine-grained token) with Organization Copilot metrics: read, set up by an org owner."),
                 missing=(f"there are no Copilot usage reports for {org}", "Check org under [connectors.copilot], and that "
                          "Copilot usage metrics are turned on for the organization."))
    _bad(resp, "GitHub")
    if resp.status_code == 204:
        return org, f"The token can read {org}'s Copilot usage reports; GitHub has none for {day} yet."
    return org, f"The token can read {org}'s Copilot usage reports (the one for {day} is ready)."


def _ai_spend(cfg, env, client, now, pub=False):
    """One day of each provider's cost report (one page of Cursor's spend) with each admin key set."""
    keys = {name: (env.get(var) or "").strip() for name, var in ai_spend.KEYS.items()}
    if not any(keys.values()):
        raise _missing("ai_spend")
    day = (now - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    read = []
    if keys["anthropic"]:
        _bad(_send(client, "GET", ai_spend.ANTHROPIC, "Anthropic", "ai_spend", params={"starting_at": day, "limit": 1},
                   headers={"x-api-key": keys["anthropic"], "anthropic-version": "2023-06-01"},
                   forbidden=("the key isn't an Admin API key", "Create an Admin API key (sk-ant-admin...) in the Claude "
                              "Console's organization settings; workspace keys can't read costs.")), "Anthropic")
        read.append("Anthropic's cost report")
    if keys["openai"]:
        _bad(_send(client, "GET", ai_spend.OPENAI, "OpenAI", "ai_spend",
                   params={"start_time": int((now - timedelta(days=1)).timestamp()), "limit": 1},
                   headers={"Authorization": f"Bearer {keys['openai']}"},
                   forbidden=("the key isn't an admin key", "Create an admin key in OpenAI's organization settings.")), "OpenAI")
        read.append("OpenAI's costs")
    if keys["cursor"]:
        _bad(_send(client, "POST", f"{ai_spend.CURSOR}/teams/spend", "Cursor", "ai_spend", json={"pageSize": 1},
                   auth=(keys["cursor"], ""),
                   forbidden=("the key isn't a Cursor admin API key", "Create one in Cursor's team settings (admins only).")),
             "Cursor")
        read.append("Cursor's team spend")
    return None, "Read " + ", ".join(read) + "."


def _sonar(cfg, env, client, now, pub=False):
    """The project's quality gate, read once (public SonarCloud projects need no key)."""
    c = cfg["connectors"]["sonar"]
    if not c.get("project"):
        raise Fail("No Sonar project is set.", "Set project under [connectors.sonar], like myorg_myrepo.")
    token = (env.get(sonar.TOKEN_ENV) or "").strip()
    resp = _send(client, "GET", f"{(c.get('url') or 'https://sonarcloud.io').rstrip('/')}/api/qualitygates/project_status",
                 "Sonar", "sonar", params={"projectKey": c["project"]}, headers={"Authorization": f"Bearer {token}"} if token else {},
                 forbidden=("Sonar refused the request", "A private project needs the SONAR_TOKEN secret."))
    _bad(resp, "Sonar", "Check project under [connectors.sonar]; the key is shown in the project's Information page.")
    gate = (resp.json().get("projectStatus") or {}).get("status")
    return None, f"Read {c['project']}'s quality gate ({gate or 'none set'})."


CHECKS = {"jira": _jira, "linear": _linear, "pagerduty": _pagerduty, "incident_io": _incident_io, "slack": _slack,
          "discord": _discord, "discourse": _discourse, "copilot": _copilot, "webhook": _webhook, "gitlab": _gitlab,
          "s3": _s3, "triage": _triage, "ai_spend": _ai_spend, "sonar": _sonar}


def _scrub(out: dict, env: dict) -> dict:
    # A last guard: no key or webhook address from the environment survives in what is said.
    secrets = [v.strip() for k, v in env.items() if v and len(v.strip()) >= 8 and any(
        w in k for w in ("TOKEN", "KEY", "SECRET", "WEBHOOK", "EMAIL"))]
    for field in ("as", "detail", "fix"):
        if isinstance(out.get(field), str):
            for s in secrets:
                out[field] = out[field].replace(s, "***")
    return out


def check(name: str, cfg: dict, env: dict, client: httpx.Client | None = None, now: datetime | None = None,
          public: bool = False) -> dict:
    """{"ok", "as", "detail", "checked_at", "fix"} for one connector; a failure of any kind is a failed check, never an error."""
    now = now or datetime.now(timezone.utc)
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, transport=TRANSPORT, follow_redirects=False)
    try:
        who, detail = CHECKS[name](cfg, env, client, now, public)
        out = {"ok": True, "as": who or None, "detail": detail, "fix": None}
    except Fail as f:
        out = {"ok": False, "as": None, "detail": f.detail, "fix": f.fix}
    except Exception as exc:  # noqa: BLE001 - a bug in one check must never stop the run or the other checks
        out = {"ok": False, "as": None, "detail": f"The check stopped on an unexpected {type(exc).__name__}.",
               "fix": "Try again; if it repeats, open an issue on StackVitals with this message."}
    finally:
        if own:
            client.close()
    out = _scrub(out, env)
    return {"ok": out["ok"], "as": out["as"], "detail": out["detail"], "checked_at": iso(now), "fix": out["fix"]}


def configured(name: str, env: dict, cfg: dict) -> bool:
    """Whether a connector has anything set up, so "all" tests it."""
    if name == "discourse":
        return discourse.configured(env, cfg)
    if name == "webhook":
        return bool((env.get("STACKVITALS_WEBHOOK") or "").strip() or (env.get("STACKVITALS_TEAM_WEBHOOKS") or "").strip())
    if name == "s3":
        return (env.get("STACKVITALS_STORAGE") or "").strip().startswith("s3://")
    if name == "ai_spend":
        return ai_spend.configured(env, cfg)
    if name == "sonar":
        return sonar.configured(env, cfg)
    if name == "triage":
        return bool((env.get("STACKVITALS_TRIAGE_KEY") or "").strip()) or \
            (((cfg.get("ci") or {}).get("triage") or {}).get("provider") or "off") != "off"
    return bool((env.get(KEYS[name][2]) or "").strip())


def resolve(asked, cfg: dict, env: dict) -> list[str]:
    """The connectors to test: "all" means every one set up; names may use the app's ids (chat) or aliases."""
    if asked == "all":
        return [n for n in CHECKS if configured(n, env, cfg)]
    out = []
    for raw in asked:
        name = ALIASES.get(str(raw).strip().lower(), str(raw).strip().lower())
        if name not in CHECKS:
            raise ValueError(f"Unknown connector {raw!r}; known: {', '.join(CHECKS)} (or all).")
        if name not in out:
            out.append(name)
    return out


def run(names: list[str], cfg: dict, env: dict, now: datetime | None = None, client: httpx.Client | None = None,
        public: bool = False) -> dict:
    return {n: check(n, cfg, env, client, now, public) for n in names}


def shown(results: dict, public: bool) -> dict:
    """What may be published: on a public repo "as" (an account, bot, project or bucket) is left out, but for the forum and model."""
    return {n: {**r, "as": None} if public and n not in NAMED else r for n, r in results.items()}


def save(root: Path, results: dict, public: bool) -> None:
    """Each result under its connector's entry in docs/connectors.json as "check", every other field kept."""
    from stackvitals.core.store import published, write_if_changed
    path = Path(root) / "docs" / "connectors.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    conn = dict(doc.get("connectors") or {})
    for name, r in shown(results, public).items():
        conn[name] = {**(conn.get(name) or {"name": NAMES[name]}), "check": r}
    path.parent.mkdir(parents=True, exist_ok=True)
    write_if_changed(path, published({**{k: v for k, v in doc.items() if k not in ("schema", "connectors")}, "connectors": conn}))


def line(name: str, r: dict) -> str:
    if r["ok"]:
        return f"{NAMES[name]}: working" + (f", as {r['as']}" if r.get("as") else "") + f". {r['detail']}"
    return f"{NAMES[name]}: not working. {r['detail']} Fix: {r['fix']}"


def _env_file(path: Path) -> dict:
    """KEY=VALUE lines of a .env file (comments, `export` and quotes allowed)."""
    out = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.removeprefix("export ").partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        elif " #" in v:
            # An unquoted " # note" after the value is a comment, as in other .env readers.
            v = v.split(" #", 1)[0].rstrip()
        out[k.strip()] = v
    return out


# The repository secret each key is stored as; a local .env written with those names is read the same way.
SECRET_NAMES = {jira.TOKEN_ENV: "JIRA_API_TOKEN", jira.EMAIL_ENV: "JIRA_EMAIL",linear.TOKEN_ENV: "LINEAR_API_KEY", pagerduty.TOKEN_ENV: "PAGERDUTY_API_KEY",
                incident_io.TOKEN_ENV: "INCIDENT_IO_API_KEY", slack.TOKEN_ENV: "SLACK_BOT_TOKEN",
                discord.TOKEN_ENV: "DISCORD_BOT_TOKEN", sonar.TOKEN_ENV: "SONAR_TOKEN",
                **{env: env.removeprefix("STACKVITALS_") for env in ai_spend.KEYS.values()}}


def load_env(path: Path, environ) -> dict:
    """The .env file under the environment, with keys saved under their repository secret names filled in."""
    env = {**_env_file(path), **environ}
    for name, secret in SECRET_NAMES.items():
        if not (env.get(name) or "").strip() and (env.get(secret) or "").strip():
            env[name] = env[secret]
    return env


def main(argv: list[str] | None = None) -> int:
    from stackvitals.core.config import FILE, parse
    parser = argparse.ArgumentParser(prog="stackvitals connectors", description="Connectors to outside services.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="Test each connector's key with one cheap call (a chat webhook gets one test message)")
    p.add_argument("names", nargs="*", help=f"connectors to test: {', '.join(CHECKS)} (default: every one set up)")
    p.add_argument("--all", action="store_true", help="test every connector that has a key or settings")
    p.add_argument("--json", action="store_true", help="print the results as JSON")
    p.add_argument("--config", default=FILE, help=f"the settings file (default {FILE})")
    p.add_argument("--env-file", default=".env", help="a KEY=VALUE file read for keys not in the environment (default .env)")
    args = parser.parse_args(argv)
    env = load_env(Path(args.env_file), os.environ)
    try:
        cfg = parse(Path(args.config).read_text(encoding="utf-8"))[0]
    except OSError:
        cfg = parse("")[0]
    try:
        names = resolve("all" if args.all or not args.names else args.names, cfg, env)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not names:
        print("Nothing is set up to test: no connector key in the environment and none in the settings file.")
        return 0
    results = run(names, cfg, env)
    if args.json:
        print(json.dumps(results, indent=1))
    else:
        for name, r in results.items():
            print(line(name, r))
    return 0 if all(r["ok"] for r in results.values()) else 1
