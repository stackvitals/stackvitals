"""Agents propose, people submit: `stackvitals propose` and the MCP `propose_change` tool give the same prefilled request
issue the app opens, checked first with the same parsers, so a bad value or command never reaches GitHub."""
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from stackvitals.core import decisions as dec
from stackvitals.core.propose import ProposalError, proposal


def body_of(url):
    return parse_qs(urlparse(url).query)["body"][0]


def test_settings_and_a_command_become_one_request_the_action_reads():
    out = proposal("o/r", settings={"alerts.pickup_p75_hours": 6}, command="/stackvitals mute test:t::a for 7d because known",
                   today=date(2026, 10, 21))
    assert out["url"].startswith("https://github.com/o/r/issues/new?")
    req = dec.parse_request(body_of(out["url"]), date(2026, 10, 21))
    assert req.settings == {"alerts.pickup_p75_hours": 6}
    assert req.changes == [dec.Decision("mute", "test", "t::a", "2026-10-28", "known")]
    assert "someone with write access" in out["note"]


def test_bad_values_and_commands_are_refused_before_they_leave():
    with pytest.raises(ProposalError):
        proposal("o/r", settings={"alerts.pickup_p75_hours": -2}, today=date(2026, 10, 21))
    with pytest.raises(ProposalError):
        proposal("o/r", settings={"alerts.nope": 1}, today=date(2026, 10, 21))
    with pytest.raises(ProposalError):
        proposal("o/r", command="/stackvitals frobnicate test:x", today=date(2026, 10, 21))
    with pytest.raises(ProposalError):
        proposal("o/r", today=date(2026, 10, 21))


def test_the_cli_prints_the_link(capsys):
    from stackvitals.cli import main
    assert main(["propose", "o/r", "--set", "alerts.pickup_p75_hours=6", "--set", "automation.issues=true"]) == 0
    url = capsys.readouterr().out.strip().splitlines()[-1]
    assert dec.parse_request(body_of(url), date(2026, 10, 21)).settings == {"alerts.pickup_p75_hours": 6, "automation.issues": True}
