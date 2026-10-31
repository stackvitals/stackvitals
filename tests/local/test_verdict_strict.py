from datetime import date

from stackvitals.ci.feedback import blamed_sha, render_comment, verdict_payload
from stackvitals.core.config import parse
from stackvitals.core.decisions import parse_command

SHA = "a" * 40


def test_a_comment_that_blames_the_change_remembers_the_commit():
    body = render_comment([{"kind": "job", "name": "CI / tests", "verdict": "new", "detail": "no earlier flakes: likely from this change"}],
                          "o/r", SHA)
    assert blamed_sha(body) == SHA
    flaky = render_comment([{"kind": "job", "name": "CI / tests", "verdict": "known flaky", "detail": "flaked 4 times"}], "o/r", SHA)
    assert blamed_sha(flaky) is None


def test_a_held_verdict_fails_even_when_ci_is_green():
    assert verdict_payload([], True)["conclusion"] == "success"
    held = verdict_payload([], True, held=True)
    assert held["conclusion"] == "failure" and "accept rerun" in held["output"]["title"]


def test_accept_rerun_on_a_pull_request_targets_its_rerun():
    [d] = parse_command("/stackvitals accept rerun because the flaky DNS step", date(2026, 10, 24), default=("pr", "12"))
    assert (d.verb, d.kind, d.id) == ("accept", "rerun", "12") and "DNS" in d.reason


def test_strict_mode_is_off_by_default():
    assert not parse("")[0]["automation"]["verdict_strict"]
    assert parse("[automation]\nverdict_strict = true\n")[0]["automation"]["verdict_strict"] is True
