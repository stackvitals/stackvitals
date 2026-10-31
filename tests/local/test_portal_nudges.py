"""Campaign nudges (Cortex and OpsLevel's reminders): the tracking issue is a checklist ticked again on every run, and a
reminder comment goes out once 7 days and once 1 day before the deadline, naming the repos still failing."""
from datetime import datetime, timezone

from stackvitals.portal.campaigns import issue_body, reminders_due


def progress(days_left, failing=("org/a", "org/b"), passing=1):
    return {"id": "codeowners", "title": "Every repo has owners", "rules": ["codeowners"], "until": "2026-11-01",
            "targets": len(failing) + passing, "passing": passing, "failing": list(failing), "passed": ["org/c"][:passing],
            "days_left": days_left, "burn_down": [["2026-10-20", 3], ["2026-10-21", 2]]}


def test_the_issue_is_a_checklist_ticked_on_every_run():
    body = issue_body(progress(10))
    assert "- [ ] org/a" in body and "- [ ] org/b" in body and "- [x] org/c" in body


def test_reminders_go_out_once_seven_days_and_one_day_before():
    now = datetime(2026, 10, 25, 9, tzinfo=timezone.utc)
    sent = {}
    due = reminders_due([progress(7)], sent, now)
    assert [(p["id"], days) for p, days in due] == [("codeowners", 7)]
    sent = {"codeowners": [7]}
    assert reminders_due([progress(7)], sent, now) == []
    assert [d for _p, d in reminders_due([progress(1)], sent, now)] == [1]
    assert reminders_due([progress(0, failing=())], {}, now) == []  # nothing left to nudge about
    assert reminders_due([progress(5)], {}, now) == []
