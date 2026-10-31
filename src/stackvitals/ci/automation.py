import glob
import subprocess
from datetime import timedelta
from urllib.parse import urlencode

import httpx

from stackvitals.ci.api import ActionsAPI, APIError
from stackvitals.ci.feedback import SAFE_FLAKES
from stackvitals.ci.owners import owners_line
from stackvitals.ci.report import began_text
from stackvitals.ci.testreports import merge, parse_report

LABEL = "flaky-test"


def should_rerun(items: list[dict], run_attempt: int) -> bool:
    # Re-run once, and only when every failure is a known flake or an outside service failing.
    return run_attempt == 1 and bool(items) and all(i["verdict"] in ("known flaky", "outside failure") for i in items)


def rerun_failed_jobs(api: ActionsAPI, run_id: int) -> None:
    api.send("POST", f"/repos/{api.repo}/actions/runs/{run_id}/rerun-failed-jobs")


def expired(result: dict, settings: dict | None, now) -> list[str]:
    """Flaky tests quarantined on their own for longer than [ci.quarantine] max_days: they fail builds again until fixed."""
    days = ((((settings or {}).get("ci") or {}).get("quarantine") or {}).get("max_days")) or 0
    if not days or now is None:
        return []
    cut = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return sorted(t["id"] for t in result.get("tests", []) if t["state"] == "flaky" and (t.get("since") or "~") < cut)


def quarantine_list(result: dict, settings: dict | None = None, decisions: dict | None = None, now=None) -> list[str]:
    """Flaky tests, plus the repo's "always" list and tests someone quarantined, minus its "never" list, tests someone
    took out of quarantine (.github/stackvitals.toml and the decisions log) and flaky tests past max_days."""
    q = ((settings or {}).get("ci") or {}).get("quarantine") or {}
    # Only tests that flaked as often as a safe re-run needs are let through on their own; one flake isn't enough.
    flaky = {t["id"] for t in result.get("tests", []) if t["state"] == "flaky" and t.get("flake_events", 0) >= SAFE_FLAKES}
    flaky -= set(expired(result, settings, now))
    picked = lambda verb: {d["id"] for d in (decisions or {}).values() if d.get("kind") == "test" and d.get("verb") == verb}
    return sorted((flaky | set(q.get("always") or []) | picked("quarantine")) - set(q.get("never") or []) - picked("unquarantine"))


def job_key(j: dict) -> str:
    # How people name a job in decisions and issue titles: the workflow file, then the job.
    return f"{(j.get('workflow') or '?').rsplit('/', 1)[-1]} / {j['job']}"


def apply_decisions(result: dict, decisions: dict) -> None:
    """Each test and job carries the decision made about it; muted or acknowledged ones raise no alert and get no new
    issue (acknowledged has no end)."""
    for kind, items, key in (("test", result.get("tests") or [], lambda t: t["id"]), ("job", result.get("jobs") or [], job_key)):
        for item in items:
            d = decisions.get(f"{kind}:{key(item)}")
            if not d:
                continue
            item["decision"] = {k: d.get(k) for k in ("verb", "by", "at", "until", "reason")}
            if d.get("verb") in ("mute", "acknowledge"):
                item["muted_until"] = d.get("until") or "9999-12-31"


def quarantine_exit(code: int, failed: list[str], quarantined: set | None) -> int:
    # Pass only when the run failed solely on quarantined tests; an unreadable list quarantines nothing.
    if code == 0 or quarantined is None or not failed:
        return code
    return 0 if set(failed) <= quarantined else code


def run_quarantined(command: list[str], report_globs: list[str], quarantined: set | None) -> int:
    code = subprocess.run(command).returncode
    if code == 0:
        return 0
    parts = []
    for pattern in report_globs:
        for path in glob.glob(pattern, recursive=True):
            with open(path, "rb") as f:
                parsed = parse_report(path, f.read())
            if parsed:
                parts.append(parsed)
    return quarantine_exit(code, [f[0] for f in merge(parts)["failed"]], quarantined)


def _flaky_names(result: dict | None) -> dict[str, str]:
    out = {}
    for t in (result or {}).get("tests", []):
        # A muted test is still measured, but nobody is alerted or given an issue until the mute ends.
        if t["state"] == "flaky" and not t.get("muted_until"):
            out[f"test {t['id']}"] = f"Flaky test: {t['id']}"
    for j in (result or {}).get("jobs", []):
        if j["state"] == "flaky" and not j.get("muted_until"):
            out[f"job {job_key(j)}"] = f"Flaky job: {job_key(j)}"
    return out


def new_flakes(old: dict | None, new: dict) -> list[str]:
    # The first run has nothing to compare with, so it never alerts.
    if old is None:
        return []
    before = _flaky_names(old)
    return [k for k in _flaky_names(new) if k not in before]


def _owners_by_key(result: dict | None) -> dict[str, list[str]]:
    out = {f"test {t['id']}": t.get("owners") for t in (result or {}).get("tests", [])}
    out.update({f"job {(j.get('workflow') or '?').rsplit('/', 1)[-1]} / {j['job']}": j.get("owners")
                for j in (result or {}).get("jobs", [])})
    return out


def alert_message(names: list[str], repo: str, result: dict | None = None, links=()) -> dict:
    from stackvitals.core import chat
    owners = _owners_by_key(result)
    lines = [f"- `{chat.safe(n)}`" + (f" (owners {' '.join(owners[n])})" if owners.get(n) else "") for n in names]
    return chat.message(f"Newly flaky in {repo}", lines, links,
                        {"repo": repo, "alerts": [{"kind": "newly_flaky", "name": n} for n in names]})


def owners_of(names: list[str], result: dict | None) -> dict[str, list[str]]:
    owners = _owners_by_key(result)
    return {n: owners.get(n) or [] for n in names}


def send_alert(url: str, msg: dict, client: httpx.Client | None = None) -> str | None:
    """Every chat (Teams included) gets its own shape; returns what went wrong, if anything."""
    from stackvitals.core import chat
    return chat.post(url, msg, client, "the flaky-test webhook")


def _evidence(entry: dict) -> str:
    last = (entry.get("last_flake") or "")[:10]
    began = began_text(entry.get("began"))
    return (f"StackVitals saw this fail and then pass with no code change {entry.get('flake_events', 0)} times "
            f"in {entry.get('runs', 0)} runs over the last 30 days" + (f" (last on {last})" if last else "") + "."
            + (f" It {began}." if began else ""))


def _issue_body(entry: dict, mention: bool = False, linear: bool = False) -> str:
    owners = owners_line(entry, mention)
    name = entry.get("id") or f"{(entry.get('workflow') or '?').rsplit('/', 1)[-1]} / {entry.get('job')}"
    # A team that tracks work in Linear files it there in one click, prefilled; no token is needed.
    file_it = (f"\n\n[File it in Linear](https://linear.new?{urlencode({'title': f'Flaky: {name}', 'description': _evidence(entry)})})"
               if linear else "")
    return (_evidence(entry) + (f"\n\n{owners}" if owners else "") + file_it
            + "\n\nThis issue is kept up to date automatically and closed once it stays quiet for two weeks. "
              "Close it as *not planned* if the team accepts this flake: StackVitals keeps it closed.")


def _first_person(entry: dict) -> str | None:
    # CODEOWNERS entries are @user, @org/team or e-mail addresses; only a user can be assigned.
    for owner in entry.get("owners") or []:
        if owner.startswith("@") and "/" not in owner:
            return owner[1:]
    return None


def _all_issues(api: ActionsAPI) -> dict[str, dict]:
    """The newest issue for each title, open or closed, so a decision someone made on it is respected."""
    found = {}
    for page in range(1, 4):
        batch = api._get(f"/repos/{api.repo}/issues", {"labels": LABEL, "state": "all", "per_page": 100, "page": page}) or []
        for issue in batch:
            if "pull_request" not in issue and issue["number"] > found.get(issue["title"], {}).get("number", 0):
                found[issue["title"]] = issue
        if len(batch) < 100:
            break
    return found


def sync_issues(api: ActionsAPI, result: dict, mention_owners: bool = False, assign_owners: bool = False,
                linear: bool = False) -> dict:
    """One issue per flaky test or job for its whole life: updated while flaky, closed once fixed, reopened with fresh
    evidence when it flakes again after being closed as done. Closed as "not planned" (or a duplicate) is the team's
    decision to live with it: it stays closed and nothing new is opened. Owners are named in code format (no
    notification) unless mention_owners is on; assign_owners assigns the first owner who is a person."""
    issues = _all_issues(api)
    # Muted tests get no new issue; one already open stays as it is until the mute ends.
    entries = {f"Flaky test: {t['id']}": t for t in result.get("tests", []) if not t.get("muted_until")}
    entries.update({f"Flaky job: {job_key(j)}": j for j in result.get("jobs", []) if not j.get("muted_until")})
    counts = {"created": 0, "updated": 0, "closed": 0, "reopened": 0, "kept_closed": 0}
    for title, entry in entries.items():
        issue = issues.get(title)
        if entry["state"] == "flaky":
            if issue and issue.get("state") == "open":
                api.send("PATCH", f"/repos/{api.repo}/issues/{issue['number']}", {"body": _issue_body(entry, mention_owners, linear)})
                counts["updated"] += 1
            elif issue and issue.get("state_reason") not in (None, "completed", "reopened"):
                counts["kept_closed"] += 1
            elif issue and issue.get("closed_at") and (entry.get("last_flake") or "")[:19] <= issue["closed_at"][:19]:
                pass  # closed as done after its last flake: it stays closed unless it flakes again
            elif issue:
                api.send("PATCH", f"/repos/{api.repo}/issues/{issue['number']}",
                         {"state": "open", "body": _issue_body(entry, mention_owners, linear)})
                api.send("POST", f"/repos/{api.repo}/issues/{issue['number']}/comments",
                         {"body": "Flaky again. " + _evidence(entry)})
                counts["reopened"] += 1
            else:
                body = {"title": title, "body": _issue_body(entry, mention_owners, linear), "labels": [LABEL]}
                person = _first_person(entry) if assign_owners else None
                try:
                    api.send("POST", f"/repos/{api.repo}/issues", {**body, **({"assignees": [person]} if person else {})})
                except APIError:
                    if not person:
                        raise
                    # Someone without access to the repo can't be assigned; the issue still matters.
                    api.send("POST", f"/repos/{api.repo}/issues", body)
                counts["created"] += 1
        elif issue and issue.get("state") == "open" and entry["state"] == "fixed":
            api.send("PATCH", f"/repos/{api.repo}/issues/{issue['number']}", {"state": "closed", "state_reason": "completed"})
            counts["closed"] += 1
    return counts
