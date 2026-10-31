import pyarrow as pa

from mergescout.archive.events import SCHEMA, slim_event

REPO = {"id": 10, "name": "o/r"}

ISSUE_OPENED = {
    "id": "1", "type": "IssuesEvent", "created_at": "2026-10-01T15:00:01Z",
    "actor": {"login": "alice"}, "repo": REPO,
    "payload": {"action": "opened", "issue": {
        "number": 7, "state": "open", "body": "hello",
        "labels": [{"name": "good first issue"}], "assignees": []}},
}
PR_TRIMMED = {
    "id": "2", "type": "PullRequestEvent", "created_at": "2026-10-01T15:00:02Z",
    "actor": {"login": "bob"}, "repo": REPO,
    "payload": {"action": "opened", "number": 8,
                "pull_request": {"url": "u", "id": 99, "number": 8, "head": {}, "base": {}}},
}
PR_COMMENT = {
    "id": "3", "type": "IssueCommentEvent", "created_at": "2026-10-01T15:00:03Z",
    "actor": {"login": "carol"}, "repo": REPO,
    "payload": {"action": "created",
                "issue": {"number": 8, "state": "open", "pull_request": {"url": "x"}},
                "comment": {"body": "I will take this"}},
}
PUSH = {
    "id": "4", "type": "PushEvent", "created_at": "2026-10-01T15:00:04Z",
    "actor": {"login": "dan"}, "repo": REPO, "payload": {"ref": "refs/heads/main"},
}
WATCH = {"id": "5", "type": "WatchEvent", "created_at": "2026-10-01T15:00:05Z",
         "actor": {"login": "eve"}, "repo": REPO, "payload": {"action": "started"}}


def test_issue_opened():
    row = slim_event(ISSUE_OPENED)
    assert row["type"] == "IssuesEvent" and row["action"] == "opened"
    assert (row["repo_id"], row["repo_name"], row["actor_login"]) == (10, "o/r", "alice")
    assert (row["number"], row["is_pr"], row["issue_state"]) == (7, False, "open")
    assert (row["assignee_count"], row["label_names"], row["body_len"]) == (0, ["good first issue"], 5)


def test_trimmed_pr_event_still_gives_number():
    row = slim_event(PR_TRIMMED)
    assert (row["number"], row["is_pr"], row["issue_state"], row["label_names"]) == (8, True, None, None)


def test_comment_on_pr_is_marked_as_pr():
    row = slim_event(PR_COMMENT)
    assert (row["number"], row["is_pr"], row["body_len"]) == (8, True, len("I will take this"))


def test_push_keeps_ref_and_other_types_are_dropped():
    assert slim_event(PUSH)["ref"] == "refs/heads/main"
    assert slim_event(WATCH) is None


def test_missing_fields_do_not_crash():
    row = slim_event({"id": "6", "type": "IssuesEvent", "created_at": None,
                      "actor": None, "repo": {"id": 1, "name": "o/r"}, "payload": None})
    assert row["actor_login"] is None and row["number"] is None and row["created_at"] is None


def test_rows_match_schema():
    rows = [slim_event(e) for e in (ISSUE_OPENED, PR_TRIMMED, PR_COMMENT, PUSH)]
    table = pa.Table.from_pylist(rows, schema=SCHEMA)
    assert table.num_rows == 4 and len(SCHEMA) == 14
