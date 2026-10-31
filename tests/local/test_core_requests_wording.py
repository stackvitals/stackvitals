"""Settings changes read as people say them in the log and the reply: no "null"."""
from stackvitals.core.requests import _changes_line, _moves


def test_an_unset_value_and_a_reset_read_plainly():
    before = {"automation": {"verdict_check": None}, "alerts": {"pickup_p75_hours": 5.0}}
    moves = _moves(before, {"automation.verdict_check": True, "alerts.pickup_p75_hours": None})
    assert moves == {"automation.verdict_check": "(not set) to true", "alerts.pickup_p75_hours": "5.0 to the default"}
    line = _changes_line(before, {"automation": {"verdict_check": True}, "alerts": {"pickup_p75_hours": 8.0}},
                         ["automation.verdict_check"])
    assert "null" not in line and "(not set)" in line
