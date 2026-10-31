import json

import pytest

from mergescout.tool.tracking import Tracker


class Live:
    def __init__(self, status):
        self.status = status

    def issue_status(self, owner, name, number):
        return self.status


def test_tracked_issue_reports_what_changed(tmp_path):
    t = Tracker(tmp_path)
    t.track("o/r#1", {"state": "OPEN", "assignees": 0, "linked_open_prs": 0, "claims": [], "waits": []})
    changes = t.updates(Live({"state": "OPEN", "assignees": 1, "linked_open_prs": 0, "claims": [], "waits": []}))
    assert changes == [{"issue": "o/r#1", "changed": {"assignees": [0, 1]}}]
    assert t.updates(Live({"state": "OPEN", "assignees": 1, "linked_open_prs": 0, "claims": [], "waits": []})) == []


def test_outcomes_stay_local_and_are_checked(tmp_path):
    t = Tracker(tmp_path)
    t.report_outcome("o/r#1", "merged", "took 3 days")
    line = json.loads((tmp_path / "outcomes.jsonl").read_text().splitlines()[0])
    assert line["issue"] == "o/r#1" and line["outcome"] == "merged"
    with pytest.raises(ValueError, match="one of"):
        t.report_outcome("o/r#1", "great")
