"""GitHub Copilot usage reports (the report API that replaced the old metrics API in April 2026), kept day by day: the
org's active users, suggestions accepted and Copilot pull requests, and this repo's Copilot pull requests. GitHub keeps
these reports for a limited time; the copy in the data branch keeps them as long as the branch does."""
import json
from datetime import date, datetime, timedelta

import httpx

from stackvitals.ci.api import API  # GitHub Enterprise Server's too, when Actions names it
from stackvitals.connectors.base import ConnectorError, json_of

NAME, TOKEN_ENV = "copilot", "STACKVITALS_COPILOT_TOKEN"
VERSION = "2026-03-10"
DAYS = 60       # the most days one run reads, and how far back a first run starts
LAG = 2         # a day is first asked for two days on; one GitHub hasn't finished yet is asked for again
SETTLED = 4     # a day still without a report this long after (and none after it) had no usage
FIRST = date(2025, 12, 12)  # the oldest organization report
ORG_FIELDS = ("daily_active_users", "weekly_active_users", "monthly_active_users", "monthly_active_chat_users",
              "monthly_active_agent_users", "code_generation_activity_count", "code_acceptance_activity_count",
              "loc_suggested_to_add_sum", "loc_added_sum", "loc_deleted_sum")
PR_FIELDS = ("total_created", "total_reviewed", "total_merged", "median_minutes_to_merge", "total_created_by_copilot",
             "total_reviewed_by_copilot", "total_merged_created_by_copilot", "total_merged_reviewed_by_copilot",
             "median_minutes_to_merge_copilot_authored")

__all__ = ["ConnectorError", "configured", "pull"]


def configured(env: dict, cfg: dict) -> bool:
    return bool((env.get(TOKEN_ENV) or "").strip())


def _report(client: httpx.Client, key: str, path: str, day: str) -> list[dict] | None:
    """The NDJSON rows of one day's report, or None when GitHub has none for that day."""
    try:
        resp = client.get(f"{API}{path}", params={"day": day}, headers={
            "Authorization": f"Bearer {key}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": VERSION})
    except httpx.HTTPError as exc:
        raise ConnectorError(f"GitHub could not be reached for Copilot reports ({type(exc).__name__}).") from None
    if resp.status_code in (401, 403):
        raise ConnectorError(f"GitHub refused the Copilot reports key ({resp.status_code}): it needs \"Organization Copilot "
                             "metrics: read\" (an org App or a fine-grained token) from an org owner.")
    if resp.status_code == 404:
        raise ConnectorError("GitHub has no Copilot usage reports for this organization (404): check org under "
                             "[connectors.copilot] and that Copilot usage metrics are turned on.")
    if resp.status_code == 204:
        return None
    if resp.status_code != 200:
        raise ConnectorError(f"GitHub answered {resp.status_code} for Copilot reports; the next run tries again.")
    rows = []
    for link in json_of(resp, "GitHub").get("download_links") or []:
        try:
            # A signed link: fetched without the key, so the key never reaches the file host.
            got = client.get(link)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"A Copilot report file could not be downloaded ({type(exc).__name__}).") from None
        if got.status_code != 200:
            raise ConnectorError(f"A Copilot report file answered {got.status_code}; the next run tries again.")
        try:
            rows += [json.loads(line) for line in got.text.split("\n") if line.strip()]
        except ValueError:
            raise ConnectorError("A Copilot report file was not JSON lines; the next run tries again.") from None
    return rows


def _prs(row: dict) -> dict:
    return {k: v for k, v in (row.get("pull_requests") or {}).items() if k in PR_FIELDS}


def pull(store, env: dict, cfg: dict, now: datetime, client: httpx.Client | None = None, days: int = DAYS) -> dict:
    owner, _, repo = (env.get("GITHUB_REPOSITORY") or "/").partition("/")
    org = cfg["connectors"]["copilot"]["org"] or owner
    key = env.get(TOKEN_ENV, "").strip()
    own = client is None
    client = client or httpx.Client(timeout=60)
    try:
        latest = now.date() - timedelta(days=LAG)
        through = store.state().get("through")
        start = date.fromisoformat(through) + timedelta(days=1) if through else max(FIRST, latest - timedelta(days=days - 1))
        read, day, last, newest = 0, start, through, None
        while day <= latest and (day - start).days < days:
            org_rows = _report(client, key, f"/orgs/{org}/copilot/metrics/reports/organization-1-day", day.isoformat())
            records = []
            for row in org_rows or []:
                gen, acc = row.get("code_generation_activity_count") or 0, row.get("code_acceptance_activity_count") or 0
                records.append({"t": "org_day", "id": f"copilot:org:{day}", "day": day.isoformat(), "org": org,
                                **{k: row.get(k) for k in ORG_FIELDS}, "acceptance": round(acc / gen, 4) if gen else None,
                                "pull_requests": _prs(row)})
            if org_rows:
                read, newest = read + 1, day
                repo_rows = _report(client, key, f"/orgs/{org}/copilot/metrics/reports/repos-1-day", day.isoformat()) or []
                records += [{"t": "repo_day", "id": f"copilot:repo:{day}", "day": day.isoformat(), "pull_requests": _prs(row)}
                            for row in repo_rows if row.get("repo_name") == repo and (row.get("repo_owner_name") or owner) == owner]
            store.add(records, now.date().isoformat())
            # Settled: it has a report, a later day does, or it ended long enough ago; else the next run asks again.
            if org_rows or day < now.date() - timedelta(days=SETTLED):
                last = day.isoformat()
            day += timedelta(days=1)
        if newest and newest.isoformat() > (last or ""):
            last = newest.isoformat()
        store.save_state({"through": last} if last else {})
        return {"read": read, "incidents": 0, "complete": day > latest}
    finally:
        if own:
            client.close()
