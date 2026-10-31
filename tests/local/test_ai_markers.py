from datetime import datetime, timezone

from stackvitals.core.ai_outcomes import assisted_by, mode
from stackvitals.flow.collect import body_tools, pr_record

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)


def test_a_description_names_the_agent_and_only_the_tool_name_is_kept():
    node = {"number": 3, "title": "Fix", "body": "Done in https://chatgpt.com/codex/tasks/task_e_1 and Generated with [Claude Code]",
            "createdAt": "2026-10-20T00:00:00Z", "author": {"login": "ann", "__typename": "User"}}
    rec = pr_record(node, NOW)
    assert rec["ai"] == ["claude", "codex"] and "body" not in rec and "chatgpt" not in str(rec)
    assert body_tools("Task: https://jules.google.com/task/954") == ["jules"] and body_tools(None) == []


def test_ai_labels_match_however_they_are_spelled():
    assert assisted_by({"lb": ["AI Generated"], "au": "ann", "at": "User"}) == ["ai"]
    assert mode({"lb": ["ai_generated"], "au": "ann", "at": "User"}) == "assisted"
