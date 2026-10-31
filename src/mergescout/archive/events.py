import pyarrow as pa

from mergescout.timeutil import parse_time

KEPT_TYPES = frozenset({
    "IssuesEvent", "IssueCommentEvent", "PullRequestEvent", "PullRequestReviewEvent", "PushEvent",
})

SCHEMA = pa.schema([
    ("event_id", pa.string()),
    ("type", pa.string()),
    ("action", pa.string()),
    ("created_at", pa.timestamp("us", tz="UTC")),
    ("repo_id", pa.int64()),
    ("repo_name", pa.string()),
    ("actor_login", pa.string()),
    ("number", pa.int64()),
    ("is_pr", pa.bool_()),
    ("issue_state", pa.string()),
    ("assignee_count", pa.int32()),
    ("label_names", pa.list_(pa.string())),
    ("body_len", pa.int32()),
    ("ref", pa.string()),
])


def slim_event(event: dict) -> dict | None:
    etype = event.get("type")
    if etype not in KEPT_TYPES:
        return None
    payload = event.get("payload") or {}
    repo = event.get("repo") or {}
    actor = event.get("actor") or {}
    issue = payload.get("issue") or {}
    pr = payload.get("pull_request") or {}
    comment = payload.get("comment") or {}
    labels = issue.get("labels")
    assignees = issue.get("assignees")
    body = comment.get("body") if etype == "IssueCommentEvent" else issue.get("body")
    return {
        "event_id": str(event.get("id")),
        "type": etype,
        "action": payload.get("action"),
        "created_at": parse_time(event.get("created_at")),
        "repo_id": repo.get("id"),
        "repo_name": repo.get("name"),
        "actor_login": actor.get("login"),
        "number": issue.get("number") or pr.get("number") or payload.get("number"),
        "is_pr": etype in ("PullRequestEvent", "PullRequestReviewEvent") or "pull_request" in issue,
        "issue_state": issue.get("state"),
        "assignee_count": len(assignees) if assignees is not None else None,
        "label_names": [lb["name"] for lb in labels if lb.get("name")] if labels is not None else None,
        "body_len": len(body) if body is not None else None,
        "ref": payload.get("ref") if etype == "PushEvent" else None,
    }
