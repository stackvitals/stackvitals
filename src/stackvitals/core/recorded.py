"""Deployments and incidents pushed from any tool (Argo CD, Jenkins, a shell script, Opsgenie or Rootly webhooks): a
`repository_dispatch` event, sent by `stackvitals record` or one curl line, is kept on the data branch, and Delivery
counts it like GitHub's own. GitHub is the receiver, so no server of ours is involved."""
import json
import re
from pathlib import Path

PATH = "delivery/recorded.ndjson"
EVENTS = {"stackvitals-deployment": "deployment", "stackvitals-incident": "incident"}
STATES = {"success": "SUCCESS", "failure": "FAILURE", "error": "FAILURE"}
TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
SHA = re.compile(r"^[0-9a-f]{7,40}$")


def _utc(value) -> str | None:
    from datetime import datetime, timezone
    if not isinstance(value, str) or not TIME.match(value):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(kind: str, payload: dict) -> tuple[dict | None, str | None]:
    """One record from a dispatch payload, or why it was refused (what to fix, said plainly)."""
    p = payload if isinstance(payload, dict) else {}
    rid = str(p.get("id") or "").strip()[:100]
    if not rid:
        return None, "an id is needed (the same id sent again updates the record)"
    if kind == "deployment":
        finished = _utc(p.get("finished_at") or p.get("at"))
        sha = str(p.get("sha") or "").lower()
        if not finished:
            return None, "finished_at must be a time like 2026-10-29T10:00:00Z"
        if sha and not SHA.match(sha):
            return None, "sha must be a commit id (7 to 40 hex characters)"
        state = STATES.get(str(p.get("status") or "success").lower())
        if not state:
            return None, "status must be success or failure"
        return {"kind": "deployment", "id": rid, "env": str(p.get("environment") or "production")[:60], "sha": sha or None,
                "at": _utc(p.get("started_at")) or finished, "done": finished, "state": state,
                "tool": str(p.get("tool") or "")[:40] or None}, None
    created = _utc(p.get("created_at") or p.get("at"))
    if not created:
        return None, "created_at must be a time like 2026-10-29T10:00:00Z"
    resolved = _utc(p.get("resolved_at")) if p.get("resolved_at") else None
    return {"kind": "incident", "id": rid, "created": created, "resolved": resolved,
            "tool": str(p.get("tool") or "")[:40] or None}, None


def from_event(event_name: str | None, payload: dict | None) -> tuple[dict | None, str | None]:
    """The record a repository_dispatch event carries; (None, None) for any other event."""
    if event_name != "repository_dispatch" or not payload or payload.get("action") not in EVENTS:
        return None, None
    return parse(EVENTS[payload["action"]], payload.get("client_payload") or {})


def append(root: Path, rec: dict) -> None:
    path = Path(root) / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")


def load(root: Path) -> dict:
    """{"deployments": [...], "incidents": [...]}: the last record sent for each id (a later one updates it)."""
    last = {}
    try:
        lines = (Path(root) / PATH).read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        last[(rec.get("kind"), rec.get("id"))] = rec
    return {"deployments": [r for (k, _), r in last.items() if k == "deployment"],
            "incidents": [r for (k, _), r in last.items() if k == "incident"]}


def incidents(recorded: dict | None) -> list[dict]:
    """Recorded incidents in the shape Delivery's own incidents take."""
    return [{"source": "recorded", "number": r["id"], "created": r["created"], "resolved": r.get("resolved")}
            for r in (recorded or {}).get("incidents") or []]


def record_step(ws, env: dict, now) -> dict:
    """The Action's step for a repository_dispatch event: keep the record, or say in the summary why it was refused."""
    payload = None
    try:
        payload = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    except (KeyError, OSError, ValueError):
        pass
    rec, why = from_event(env.get("GITHUB_EVENT_NAME"), payload)
    if why:
        return {"recorded": None, "refused": why}
    if rec:
        append(ws.path, {**rec, "received": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return {"recorded": rec and rec["kind"], "id": rec and rec["id"]}


def dispatch_body(kind: str, fields: dict) -> dict:
    """What `stackvitals record` sends to POST /repos/{owner}/{repo}/dispatches."""
    return {"event_type": f"stackvitals-{kind}", "client_payload": {k: v for k, v in fields.items() if v is not None}}


def main(argv: list[str] | None = None, post=None) -> int:
    """`stackvitals record deployment|incident owner/repo ...`: checked here first, then sent as a repository_dispatch."""
    import argparse
    import os
    import sys
    from datetime import datetime, timezone
    ap = argparse.ArgumentParser(prog="stackvitals record", description="Send a deployment or incident from any tool. "
                                 "The token needs write access to the repo's contents (GitHub's rule for dispatch events).")
    ap.add_argument("kind", choices=["deployment", "incident"])
    ap.add_argument("repo", help="owner/name")
    ap.add_argument("--id", required=True, help="your tool's id; sending the same id again updates the record")
    ap.add_argument("--sha", help="the commit deployed")
    ap.add_argument("--environment", default="production")
    ap.add_argument("--status", default="success", choices=["success", "failure"])
    ap.add_argument("--at", help="when it finished (deployment) or began (incident); default now, UTC")
    ap.add_argument("--resolved-at", help="when the incident ended")
    ap.add_argument("--tool", help="what sent it, e.g. argo-cd, jenkins, opsgenie")
    a = ap.parse_args(argv)
    at = a.at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fields = ({"id": a.id, "sha": a.sha, "environment": a.environment, "status": a.status, "finished_at": at, "tool": a.tool}
              if a.kind == "deployment" else {"id": a.id, "created_at": at, "resolved_at": a.resolved_at, "tool": a.tool})
    _rec, why = parse(a.kind, {k: v for k, v in fields.items() if v is not None})
    if why:
        print(f"Not sent: {why}.", file=sys.stderr)
        return 2
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not tok:
        print("A GitHub token is needed in GITHUB_TOKEN.", file=sys.stderr)
        return 1
    if post is None:
        import httpx
        post = lambda url, body: httpx.post(url, json=body, timeout=30, headers={  # noqa: E731
            "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}).status_code
    from stackvitals.ci.api import API
    status = post(f"{API}/repos/{a.repo}/dispatches", dispatch_body(a.kind, fields))
    if status != 204:
        print(f"GitHub answered {status}: the token may lack write access to {a.repo}'s contents.", file=sys.stderr)
        return 1
    print(f"Sent: the {a.kind} is kept by the StackVitals workflow and counted from its next scheduled run.")
    return 0
