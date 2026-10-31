"""A Jira or Linear ticket per flaky test (Trunk's auto-tickets): opened when a test turns flaky, commented and moved to
done once it is fixed, never opened twice (what was filed is kept on the data branch). Opt in with flaky_tickets = true
under [connectors.jira] (with ticket_project) or [connectors.linear] (with ticket_team); a refusal is said, never fatal."""
import json
from pathlib import Path

import httpx

from stackvitals.connectors.base import ConnectorError
from stackvitals.connectors.writeback import LINEAR, _gql, _ok, jira_comment, jira_move, linear_comment, linear_move

FILE = "ci/tickets.json"
MAX_NEW = 5


def _text(entry: dict) -> str:
    ev = entry.get("evidence") or []
    runs = ", ".join(str(e.get("run")) for e in ev[-3:] if e.get("run"))
    return (f"StackVitals saw this test fail and pass on the same code {entry.get('flake_events', 0)} times"
            f"{f' (runs {runs})' if runs else ''}. Its usual failure: {(entry.get('message') or 'not recorded')[:300]}")


def _jira_type(client, auth: str, project: str) -> str:
    """Bug when the project has it, else Task (team-managed projects often have no Bug type)."""
    resp = client.get(f"/rest/api/3/issue/createmeta/{project}/issuetypes", headers={"Authorization": auth, "Accept": "application/json"})
    names = [t.get("name") for t in ((resp.json() if resp.status_code < 300 else {}).get("issueTypes") or [])]
    return next((n for n in ("Bug", "Task") if n in names), names[0] if names else "Task")


def _jira_create(client, auth: str, project: str, title: str, text: str) -> dict:
    doc = {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}
    body = {"fields": {"project": {"key": project}, "summary": title[:250], "issuetype": {"name": _jira_type(client, auth, project)},
                       "description": doc}}
    resp = client.post("/rest/api/3/issue", json=body, headers={"Authorization": auth, "Accept": "application/json"})
    if resp.status_code == 400:
        # Jira says which field it refused; that beats guessing at permissions.
        errs = (resp.json() if resp.content else {}).get("errors") or {}
        raise ConnectorError(f"Jira refused the issue in {project}: {'; '.join(f'{k}: {v}' for k, v in errs.items())[:200] or 'bad request'}.")
    got = _ok(resp, f"A Jira issue in {project}").json()
    return {"key": got["key"], "id": got["id"]}


def _linear_create(client, key: str, team: str, title: str, text: str) -> dict:
    teams = _gql(client, key, "query($k: String!) { teams(filter: {key: {eq: $k}}) { nodes { id } } }", {"k": team})
    nodes = (teams.get("teams") or {}).get("nodes") or []
    if not nodes:
        raise ConnectorError(f"Linear has no team with the key {team}.")
    got = _gql(client, key, "mutation($input: IssueCreateInput!) { issueCreate(input: $input) { issue { id identifier } } }",
               {"input": {"teamId": nodes[0]["id"], "title": title[:250], "description": text}})
    issue = (got.get("issueCreate") or {}).get("issue") or {}
    return {"key": issue["identifier"], "id": f"linear:{issue['id']}"}


def sync(root: Path, result: dict, cfg: dict, env: dict, client: httpx.Client | None = None) -> dict:
    """Opens tickets for newly flaky tests and closes those of fixed ones; returns what it did."""
    conn = cfg.get("connectors") or {}
    which = next((n for n in ("jira", "linear") if (conn.get(n) or {}).get("flaky_tickets")), None)
    if which is None:
        return {"tickets": None}
    c = cfg["connectors"][which]
    path = Path(root) / FILE
    try:
        kept = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        kept = {}
    own = client is None
    if which == "jira":
        import base64
        token, email = (env.get("STACKVITALS_JIRA_TOKEN") or "").strip(), (env.get("STACKVITALS_JIRA_EMAIL") or c.get("email") or "").strip()
        target, ready = c.get("ticket_project"), bool(token and email and c.get("url") and c.get("ticket_project"))
        auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()
        client = client or httpx.Client(base_url=c.get("url") or "https://invalid", timeout=30)
    else:
        auth = (env.get("STACKVITALS_LINEAR_TOKEN") or "").strip()
        target, ready = c.get("ticket_team"), bool(auth and c.get("ticket_team"))
        client = client or httpx.Client(base_url=LINEAR, timeout=30)
    if not ready:
        return {"tickets": which, "problem": f"set the {which} key and its ticket_{'project' if which == 'jira' else 'team'}"}
    done = {"opened": [], "closed": [], "problem": None}
    try:
        for t in result.get("tests") or []:
            mine = kept.get(t["id"])
            if t["state"] == "flaky" and not mine and len(done["opened"]) < MAX_NEW:
                title = f"Flaky test: {t['id']}"
                made = (_jira_create(client, auth, target, title, _text(t)) if which == "jira"
                        else _linear_create(client, auth, target, title, _text(t)))
                kept[t["id"]] = {"tracker": which, **made, "open": True}
                done["opened"].append(made["key"])
            elif t["state"] == "fixed" and mine and mine.get("open"):
                note = "StackVitals: no flake for two weeks of runs; this test counts as fixed."
                if which == "jira":
                    jira_comment(client, auth, mine["key"], note)
                    jira_move(client, auth, mine["key"], c.get("done_transition") or "Done")
                else:
                    linear_comment(client, auth, mine["id"], note)
                    linear_move(client, auth, mine["id"], mine["key"], c.get("done_state") or "Done")
                mine["open"] = False
                done["closed"].append(mine["key"])
    except (ConnectorError, httpx.HTTPError, KeyError) as exc:
        done["problem"] = str(exc)[:200]
    finally:
        if own:
            client.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kept, indent=1, sort_keys=True), encoding="utf-8")
    return {"tickets": which, **done}
