"""A working calendar: [calendar] weekends and holidays left out of every review phase (pickup, review, cycle time), so a
pull request opened on Friday evening isn't charged the weekend; DORA's DevLake-matching numbers stay in calendar time
for comparison, with a working-time lead time beside them."""
from stackvitals.core import calendar
from stackvitals.core.config import parse
from stackvitals.core.delivery import phases

WEEKEND = {"weekends": ["saturday", "sunday"], "holidays": ["2026-10-26"]}


def test_weekend_and_holiday_hours_are_left_out():
    # Friday 18:00 to Monday 10:00 is 64 hours on the clock; Saturday and Sunday are 48 of them.
    assert calendar.elapsed_hours("2026-10-23T18:00:00Z", "2026-10-26T10:00:00Z", {"weekends": ["saturday", "sunday"]}) == 16
    # With Monday a holiday too, only Friday's 6 hours count.
    assert calendar.elapsed_hours("2026-10-23T18:00:00Z", "2026-10-26T10:00:00Z", WEEKEND) == 6
    assert calendar.elapsed_hours("2026-10-27T09:00:00Z", "2026-10-27T11:30:00Z", WEEKEND) == 2.5
    assert calendar.elapsed_hours("2026-10-27T09:00:00Z", "2026-10-27T11:30:00Z", None) == 2.5


def test_the_calendar_is_read_from_settings_and_bad_values_are_named():
    cfg, notes = parse('[calendar]\nweekends = ["saturday", "sunday"]\nholidays = ["2026-12-25"]\n')
    assert cfg["calendar"] == {"weekends": ["saturday", "sunday"], "holidays": ["2026-12-25"]} and notes == []
    cfg, notes = parse('[calendar]\nweekends = ["funday"]\nholidays = ["soon"]\n')
    assert cfg["calendar"] == {"weekends": [], "holidays": []} and len(notes) == 2
    assert parse("")[0]["calendar"] == {"weekends": [], "holidays": []}


def test_phases_use_working_time_when_a_calendar_is_set():
    pr = {"n": 1, "au": "amy", "cr": "2026-10-23T18:00:00Z", "mg": "2026-10-27T12:00:00Z",
          "ev": [["review", "2026-10-27T10:00:00Z", "bob", "APPROVED", "", "User"]]}
    plain, working = phases(pr, None), phases(pr, None, WEEKEND)
    assert plain["pickup"] == 88 and working["pickup"] == 6 + 10
    assert working["review"] == 2 and working["devlake_cycle_min"] == plain["devlake_cycle_min"]  # DevLake's stays exact
