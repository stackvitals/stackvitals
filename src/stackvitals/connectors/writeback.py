"""Opt-in write-back to Jira and Linear (`write_back = true` under the connector, with a key that may write): when a pull
request naming an issue merges, a comment on the issue links it, and the issue moves to the team's done status when one
is named. Each pull request and issue once, a few a run; a refusal is said, never fatal."""
import httpx

from stackvitals.connectors.base import ConnectorError
from stackvitals.connectors.tracker import pr_links

MAX_WRITES = 10
LINEAR = "https://api.linear.app/graphql"


def due(prs: list[dict], issues: list[dict], done: set[str], since: str = "") -> list[tuple[dict, dict]]:
    """(merged PR, issue) pairs merged since write-back was turned on and not written yet, oldest merge first."""
    merged = [p for p in prs if p.get("mg") and p["mg"] >= since and not (p.get("ti") or "").startswith("Revert ")
              and not (p.get("head") or "").startswith("revert-")]
    by_n, by_key = {p["n"]: p for p in merged}, {i["key"]: i for i in issues}
    pairs = [(by_n[n], by_key[key]) for n, key in pr_links(merged, issues) if f"{n}|{key}" not in done]
    return sorted(pairs, key=lambda x: x[0]["mg"])


def _ok(resp: httpx.Response, what: str) -> httpx.Response:
    if resp.status_code >= 300:
        raise ConnectorError(f"{what} was refused ({resp.status_code}); the key needs permission to write.")
    return resp


def jira_comment(client: httpx.Client, auth: str, key: str, text: str) -> None:
    headers = {"Authorization": auth, "Accept": "application/json"}
    doc = {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}
    _ok(client.post(f"/rest/api/3/issue/{key}/comment", json={"body": doc}, headers=headers), f"A comment on {key}")


def jira_move(client: httpx.Client, auth: str, key: str, transition: str) -> bool:
    """Moves the issue through the named transition when it offers one; False when it doesn't (already done)."""
    if not transition:
        return False
    headers = {"Authorization": auth, "Accept": "application/json"}
    found = _ok(client.get(f"/rest/api/3/issue/{key}/transitions", headers=headers), f"{key}'s transitions").json()
    pick = next((t for t in found.get("transitions") or [] if (t.get("name") or "").lower() == transition.lower()), None)
    if pick:
        _ok(client.post(f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": pick["id"]}}, headers=headers),
            f"Moving {key} to {transition}")
    return bool(pick)


def _gql(client: httpx.Client, key: str, query: str, variables: dict) -> dict:
    resp = _ok(client.post(LINEAR, json={"query": query, "variables": variables},
                           headers={"Authorization": key, "Content-Type": "application/json"}), "Linear")
    body = resp.json()
    if body.get("errors"):
        raise ConnectorError("Linear refused the write; the key needs permission to write.")
    return body.get("data") or {}


def linear_comment(client: httpx.Client, key: str, issue_id: str, text: str) -> None:
    _gql(client, key, "mutation($input: CommentCreateInput!) { ok: commentCreate(input: $input) { success } }",
         {"input": {"issueId": issue_id.split(":", 1)[1], "body": text}})


def linear_move(client: httpx.Client, key: str, issue_id: str, identifier: str, state: str) -> bool:
    """Moves the issue to the team's workflow state of that name; False when the team has none by that name."""
    if not state:
        return False
    found = _gql(client, key, "query($name: String!, $team: String!) { workflowStates(filter: "
                 "{name: {eqIgnoreCase: $name}, team: {key: {eq: $team}}}) { nodes { id } } }",
                 {"name": state, "team": identifier.split("-", 1)[0]})
    nodes = (found.get("workflowStates") or {}).get("nodes") or []
    if nodes:
        _gql(client, key, "mutation($id: String!, $state: String!) { ok: issueUpdate(id: $id, input: {stateId: $state}) "
             "{ success } }", {"id": issue_id.split(":", 1)[1], "state": nodes[0]["id"]})
    return bool(nodes)


def plan(store, prs: list[dict], now: str) -> list[tuple[dict, dict]]:
    """The pairs to write this run, recorded as written before the data branch is saved, so a retried or failed push
    never sends them twice (at most once, like the rest of the team automation). Merges from before write-back was last
    turned on are left alone, so switching it on never floods old issues."""
    issues = [r for r in store.load().get("issue") or [] if r.get("key")]
    state = store.state()
    since = state.get("write_since") or now
    done = set(state.get("written") or [])
    picked = due(prs, issues, done, since)[:MAX_WRITES]
    done |= {f"{p['n']}|{i['key']}" for p, i in picked}
    store.save_state({**store.state(), "write_since": since, "written": sorted(done)[-2000:]})
    return picked


def send(pairs: list[tuple[dict, dict]], repo: str, comment, move) -> dict:
    """After the commit: one comment per pair, then the move to done; a refused comment stops the run (the key can't
    write), a refused move is said and the next pair goes on."""
    wrote, moved, refused, unmoved = 0, 0, None, []
    for p, issue in pairs:
        text = f"Pull request {repo}#{p['n']} merged on {p['mg'][:10]}: https://github.com/{repo}/pull/{p['n']} (StackVitals)"
        try:
            comment(issue, text)
        except (ConnectorError, httpx.HTTPError) as exc:
            refused = str(exc)
            break
        wrote += 1
        try:
            moved += bool(move(issue))
        except (ConnectorError, httpx.HTTPError) as exc:
            unmoved.append(f"{issue['key']}: {exc}")
    return {"wrote": wrote, "moved": moved, "refused": refused, "unmoved": unmoved}
