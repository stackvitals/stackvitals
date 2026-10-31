from datetime import datetime, timezone

from stackvitals.community.build import build
from stackvitals.community.report import _sections
from stackvitals.core.config import STATED_MAX, parse


def test_stated_texts_are_trimmed_and_wrong_types_noted():
    cfg, notes = parse('[community]\ncapacity = "two  volunteers"\nnorms = 3\n')
    assert cfg["community"] == {"capacity": "two volunteers", "norms": ""}
    assert any("community.norms" in n for n in notes)
    long, _ = parse(f'[community]\nnorms = "{"x" * 500}"\n')
    assert len(long["community"]["norms"]) == STATED_MAX


def test_defaults_have_no_statement():
    assert parse("")[0]["community"] == {"capacity": "", "norms": ""}


def test_statements_show_beside_who_carries_the_work():
    r = build({}, {}, {}, {}, {}, datetime(2026, 10, 24, tzinfo=timezone.utc),
              context={"stated": {"capacity": "two volunteers", "norms": "triage on Mondays"}})
    lines = dict(_sections(r))["Who carries the work"]
    assert "In the project's own words, who maintains it: two volunteers" in lines
    assert "In the project's own words, how it works: triage on Mondays" in lines
