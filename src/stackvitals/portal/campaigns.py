"""Campaigns: a set of rules, the repos they target and a date. Progress and the burn-down come from the daily history, and
one tracking issue in the portal repo is kept up to date (issues in each repo would need write access everywhere)."""
import fnmatch
import json
import tomllib
from datetime import date, datetime
from pathlib import Path

from stackvitals.flow.report import _md

MARKER = "<!-- stackvitals:campaign"
DONE = ("pass", "exempt")


def load_campaigns(text: str | None) -> list[dict]:
    doc = tomllib.loads(text) if text else {}
    out = []
    for c in doc.get("campaign") or []:
        if isinstance(c, dict) and c.get("id") and c.get("rules"):
            out.append({"id": str(c["id"]), "title": str(c.get("title") or c["id"]), "rules": [str(r) for r in c["rules"]],
                        "repos": str(c.get("repos") or "*"), "language": c.get("language"), "until": str(c.get("until") or "")})
    return out


def _targeted(c: dict, name: str, language: str | None) -> bool:
    return fnmatch.fnmatch(name.lower(), c["repos"].lower()) and (not c["language"] or (language or "").lower() == c["language"].lower())


def progress(c: dict, repos: list[dict], history: Path, now: datetime) -> dict:
    """How many targeted repos pass every campaign rule today, who still fails, and the failing count on each kept day."""
    today = now.strftime("%Y-%m-%d")
    targets = [r for r in repos if not r.get("archived") and not r.get("fork") and _targeted(c, r["name"], r.get("language"))]

    def passes(r):
        results = {x["id"]: x["result"] for x in (r.get("score") or {}).get("results") or []}
        return all(results.get(rule) in DONE for rule in c["rules"])
    failing = sorted(r["name"] for r in targets if not passes(r))
    passed = sorted(r["name"] for r in targets if passes(r))
    burn = []
    for path in sorted(Path(history).glob("*.json")):
        if path.stem >= today:
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8")).get("repos") or []
        except (OSError, ValueError):
            continue
        burn.append([path.stem, sum(1 for row in rows if _targeted(c, row.get("name") or "", row.get("language"))
                                    and set(c["rules"]) & set(row.get("failed") or []))])
    burn.append([today, len(failing)])
    try:
        days_left = (date.fromisoformat(c["until"]) - now.date()).days if c["until"] else None
    except ValueError:
        days_left = None
    return {**c, "targets": len(targets), "passing": len(targets) - len(failing), "failing": failing, "passed": passed,
            "days_left": days_left, "burn_down": burn}


REMIND_AT = (7, 1)


def reminders_due(campaigns: list[dict], sent: dict, now: datetime) -> list[tuple[dict, int]]:
    """Campaigns at 7 or 1 days left that still have failing repos and haven't had that reminder (Cortex's rhythm)."""
    out = []
    for p in campaigns:
        days = p.get("days_left")
        if p.get("failing") and days in REMIND_AT and days not in (sent.get(p["id"]) or []):
            out.append((p, days))
    return out


def reminder_text(p: dict, days: int) -> str:
    names = ", ".join(_md(n) for n in p["failing"][:20]) + (f" and {len(p['failing']) - 20} more" if len(p["failing"]) > 20 else "")
    return (f"Reminder: {days} day{'' if days == 1 else 's'} left for this campaign (until {p['until']}). "
            f"{len(p['failing'])} repo{'' if len(p['failing']) == 1 else 's'} still fail: {names}.")


def issue_body(p: dict) -> str:
    lines = [f"{MARKER} {p['id']} -->", f"### Campaign: {_md(p['title'])}", "",
             f"{p['passing']} of {p['targets']} repos pass every rule ({', '.join(map(_md, p['rules']))})"
             + (f"; {p['days_left']} days left (until {p['until']})." if p.get("days_left") is not None else ".")]
    if p["failing"] or p.get("passed"):
        # A checklist ticked again on every run: done repos checked, the rest open.
        lines += ["", "**Repos:**", *[f"- [ ] {_md(n)}" for n in p["failing"][:100]],
                  *[f"- [x] {_md(n)}" for n in (p.get("passed") or [])[:50]]]
        if len(p["failing"]) > 100:
            lines.append(f"- ... and {len(p['failing']) - 100} more still failing")
    if len(p["burn_down"]) > 1:
        lines += ["", "**Failing repos over time:** " + " → ".join(f"{d} {n}" for d, n in p["burn_down"][-12:])]
    lines += ["", "<sub>Kept up to date by StackVitals Portal on each run; edits to this text are replaced.</sub>"]
    return "\n".join(lines)


def update_tracking_issue(api, repo: str, p: dict) -> int | None:
    """One issue per campaign in the portal repo, found by its marker and edited in place; closed once every repo passes."""
    marker = f"{MARKER} {p['id']} -->"
    open_issues = api._get(f"/repos/{repo}/issues", {"state": "open", "per_page": 100})
    found = next((i for i in open_issues if not i.get("pull_request") and marker in (i.get("body") or "")), None)
    body = issue_body(p)
    if found:
        api.send("PATCH", f"/repos/{repo}/issues/{found['number']}", {"body": body, **({} if p["failing"] else {"state": "closed"})})
        return found["number"]
    if p["failing"]:
        return api.send("POST", f"/repos/{repo}/issues", {"title": f"Campaign: {p['title']}", "body": body}).get("number")
    return None
