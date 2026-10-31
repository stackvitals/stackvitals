from stackvitals.core.agreements import nudge_lines, nudges

AGREED = {"labels": {"review_within_hours": "First review within 24 h", "merge_within_days": "Merged within 5 days"},
          "exceptions": [{"pr": 12, "rule": "review_within_hours", "value": 30.2, "limit": 24, "open": True},
                         {"pr": 9, "rule": "merge_within_days", "value": 6.1, "limit": 5, "open": False},
                         {"pr": 15, "rule": "merge_within_days", "value": 7.0, "limit": 5, "open": True}]}


def test_each_open_break_is_nudged_once_and_forgotten_when_it_ends():
    fresh, keep = nudges(AGREED, [])
    assert [(e["pr"], e["rule"]) for e in fresh] == [(12, "review_within_hours"), (15, "merge_within_days")]
    assert nudges(AGREED, keep)[0] == []
    later = {**AGREED, "exceptions": [AGREED["exceptions"][2]]}
    _fresh, keep2 = nudges(later, keep)
    assert keep2 == ["15|merge_within_days"]
    assert nudges(None, ["x"]) == ([], [])


def test_nudge_lines_say_what_broke_against_the_agreement():
    lines = nudge_lines(nudges(AGREED, [])[0], AGREED["labels"], "o/r")
    assert "#12" in lines[0] and "30.2 h" in lines[0] and "First review within 24 h" in lines[0]
    assert "github.com/o/r/pull/15" in lines[1] and "7.0 days" in lines[1]
