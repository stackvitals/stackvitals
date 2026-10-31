"""Findings as events other tools can act on: a delivery alert, a newly flaky test, a pull request's verdict. Each is a
CDEvents custom event (dev.cdeventsx.stackvitals-*) sent as a CloudEvent to a URL the user names (a CDviz collector,
Argo Events, n8n), and/or as a repository_dispatch to a repo the user names, so its workflows can react. Off until one
of those is set; events carry names and counts, never log text."""
import hashlib
import os
import re

import httpx

SPEC = "0.5.1"
KINDS = ("alert", "newly_flaky", "pr_verdict")
# dev.cdeventsx.<tool>-<subject>.<predicate>.<version>, the CDEvents rule for tool-specific events (custom/README.md).
TYPES = {"alert": "dev.cdeventsx.stackvitals-alert.raised.0.1.0",
         "newly_flaky": "dev.cdeventsx.stackvitals-flakytest.detected.0.1.0",
         "pr_verdict": "dev.cdeventsx.stackvitals-verdict.posted.0.1.0"}
REPO = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")


def event(kind: str, repo: str, subject: str, content: dict, at: str) -> dict:
    """One CDEvent; its id is stable for the same finding, so a receiver can drop a repeat."""
    source = f"https://github.com/{repo}"
    eid = hashlib.sha256(f"{kind}|{repo}|{subject}|{at}".encode()).hexdigest()[:32]
    return {"context": {"specversion": SPEC, "id": eid, "source": source, "type": TYPES[kind], "timestamp": at},
            "subject": {"id": subject, "source": source, "content": content}}


def cloudevent(ev: dict) -> dict:
    """The CDEvent in CloudEvents structured mode, as CDEvents' CloudEvents binding asks."""
    c = ev["context"]
    return {"specversion": "1.0", "id": c["id"], "source": c["source"], "type": c["type"], "subject": ev["subject"]["id"],
            "time": c["timestamp"], "datacontenttype": "application/json", "data": ev}


def dispatch_body(ev: dict) -> dict:
    # GitHub allows 10 top-level keys in client_payload; a CDEvent has two (context, subject).
    return {"event_type": ev["context"]["type"], "client_payload": ev}


def wanted(settings: dict | None, kind: str, env=None) -> bool:
    env = os.environ if env is None else env
    cfg = (settings or {}).get("events") or {}
    target = env.get("STACKVITALS_EVENTS_URL") or (cfg.get("dispatch_repo") and env.get("STACKVITALS_EVENTS_TOKEN"))
    return bool(target) and kind in (cfg.get("send") or KINDS)


def send(evs: list[dict], settings: dict | None, env=None, client: httpx.Client | None = None) -> list[str]:
    """Send each event to the URL and/or the dispatch repo; trouble comes back as notes for the job summary."""
    env = os.environ if env is None else env
    cfg = (settings or {}).get("events") or {}
    evs = [e for e in evs if wanted(settings, next(k for k, t in TYPES.items() if t == e["context"]["type"]), env)]
    if not evs:
        return []
    client = client or httpx.Client(timeout=30)
    url, repo, token = (env.get("STACKVITALS_EVENTS_URL") or "").strip(), cfg.get("dispatch_repo") or "", env.get("STACKVITALS_EVENTS_TOKEN")
    notes, failed = [], {"url": 0, "dispatch": 0}
    for ev in evs:
        if url:
            try:
                r = client.post(url, json=cloudevent(ev), headers={"Content-Type": "application/cloudevents+json"})
                failed["url"] += r.status_code >= 300
            except (httpx.HTTPError, httpx.InvalidURL):
                failed["url"] += 1
        if repo and token:
            from stackvitals.ci.api import API
            try:
                r = client.post(f"{API}/repos/{repo}/dispatches", json=dispatch_body(ev),
                                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
                failed["dispatch"] += r.status_code != 204
            except httpx.HTTPError:
                failed["dispatch"] += 1
    if failed["url"]:
        notes.append(f"{failed['url']} of {len(evs)} events didn't reach the events URL.")
    if failed["dispatch"]:
        notes.append(f"{failed['dispatch']} of {len(evs)} events weren't accepted by {repo}: the events token needs "
                     "write access to that repo's contents (GitHub's rule for dispatch events).")
    return notes


def alerts(found: list[dict], repo: str, at: str) -> list[dict]:
    """Delivery and review alerts crossing (or back under) their limits."""
    return [event("alert", repo, f"{repo}/alerts/{e['metric']}", {"metric": e["metric"], "level": e["level"],
                  "value": e["value"], "limit": e["limit"], "n": e["n"]}, at) for e in found]


def newly_flaky(names: list[str], repo: str, at: str) -> list[dict]:
    from stackvitals.core.chat import safe
    return [event("newly_flaky", repo, f"{repo}/flaky/{safe(n, 160)}", {"name": safe(n)}, at) for n in names]


def pr_verdict(pr: int, sha: str, items: list[dict], repo: str, at: str) -> dict:
    """A pull request's failures by verdict; names are made inert, and no detail or log text goes out."""
    from collections import Counter

    from stackvitals.core.chat import safe
    counts = Counter(i.get("verdict") for i in items)
    return event("pr_verdict", repo, f"{repo}/pull/{pr}", {
        "pull_request": pr, "sha": sha, "verdicts": dict(sorted(counts.items())),
        "failures": [{"kind": i.get("kind"), "name": safe(i.get("name"), 160), "verdict": i.get("verdict")} for i in items[:20]],
        "blocking": sum(v != "known flaky" for v in counts.elements())}, at)
