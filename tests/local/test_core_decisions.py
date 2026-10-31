"""Decisions on items, made on GitHub: `/stackvitals` commands and request blocks parse into a few verbs with an expiry
and a reason, the data branch keeps an append-only log, and the current state drops what has expired."""
from datetime import date, datetime, timezone

import pytest

from stackvitals.core import decisions as dec

NOW = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)
TODAY = date(2026, 10, 21)


def test_a_command_on_an_items_issue_targets_that_item_with_an_expiry_and_reason():
    got = dec.parse_command("/stackvitals quarantine for 14d because the upstream fix lands next week",
                            TODAY, default=("test", "tests/test_api.py::test_retry"))
    assert got == [dec.Decision("quarantine", "test", "tests/test_api.py::test_retry", "2026-11-04",
                                "the upstream fix lands next week")]


def test_explicit_targets_dates_and_quoted_names():
    assert dec.parse_command('/stackvitals mute job:"CI / test (3.11)" until 2026-12-01', TODAY) == [
        dec.Decision("mute", "job", "CI / test (3.11)", "2026-12-01", "")]
    assert dec.parse_command("/stackvitals exclude #42 because release PR", TODAY) == [
        dec.Decision("exclude", "pr", "42", None, "release PR")]
    assert dec.parse_command("/stackvitals snooze finding:review_wait for 2w", TODAY)[0].until == "2026-11-04"


def test_defaults_give_every_temporary_decision_a_review_date():
    quarantine = dec.parse_command("/stackvitals quarantine test:t::a", TODAY)[0]
    snooze = dec.parse_command("/stackvitals snooze finding:red_ci", TODAY)[0]
    ack = dec.parse_command("/stackvitals acknowledge test:t::a", TODAY)[0]
    assert (quarantine.until, snooze.until, ack.until) == ("2026-11-20", "2026-11-04", None)


def test_only_lines_that_start_with_the_command_count_and_unknown_verbs_say_what_exists():
    assert dec.parse_command("thanks! /stackvitals quarantine in the middle does nothing", TODAY) == []
    with pytest.raises(dec.CommandError) as err:
        dec.parse_command("/stackvitals frobnicate test:t::a", TODAY)
    assert "quarantine" in str(err.value)
    with pytest.raises(dec.CommandError):
        dec.parse_command("/stackvitals quarantine", TODAY)  # no item and no default target
    with pytest.raises(dec.CommandError):
        dec.parse_command("/stackvitals exclude test:t::a", TODAY)  # exclude is for pull requests


def test_a_request_block_from_the_app_carries_changes_and_settings():
    body = ("Requested from the StackVitals app.\n\n```stackvitals\n"
            '{"version": 1, "changes": [{"verb": "mute", "kind": "test", "id": "t::a", "until": "2026-11-30", '
            '"reason": "known"}], "settings": {"alerts.pickup_p75_hours": 6}}\n```\n')
    req = dec.parse_request(body, TODAY)
    assert req.changes == [dec.Decision("mute", "test", "t::a", "2026-11-30", "known")]
    assert req.settings == {"alerts.pickup_p75_hours": 6}
    assert dec.parse_request("no block here", TODAY) is None
    with pytest.raises(dec.CommandError):
        dec.parse_request("```stackvitals\n{not json\n```", TODAY)


def test_the_store_logs_every_decision_and_expired_ones_drop_out(tmp_path):
    store = dec.Store(tmp_path)
    store.record([dec.Decision("quarantine", "test", "t::a", "2026-10-25", "flaky upstream"),
                  dec.Decision("mute", "job", "CI / lint", None, "")], by="alice", source="issue #7", now=NOW)
    store.record([dec.Decision("unquarantine", "test", "t::a", None, "fixed")], by="bob", source="comment", now=NOW)
    assert len(store.log()) == 3
    state = store.state(TODAY)
    assert state["test:t::a"]["verb"] == "unquarantine" and state["job:CI / lint"]["by"] == "alice"
    later = dec.Store(tmp_path)
    later.record([dec.Decision("snooze", "finding", "red_ci", "2026-10-22", "")], by="alice", source="request", now=NOW)
    assert "finding:red_ci" in later.state(TODAY) and "finding:red_ci" not in later.state(date(2026, 10, 23))
    assert later.ids("quarantine", "test", TODAY) == set() and later.ids("mute", "job", TODAY) == {"CI / lint"}
