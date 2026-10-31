"""Effort and capitalisation for finance: one row per merged pull request (month, link, kind of work and how it was
decided, epic, written by an agent or a person) in a CSV an auditor can follow, and a monthly summary of author-weeks
by kind of work with the agent share."""
import csv
import io
from datetime import datetime, timezone

from stackvitals.core import capex

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


def pr(n, title, au="amy", at="User", mg="2026-10-05T10:00:00Z", labels=(), head="feature"):
    return {"n": n, "ti": title, "au": au, "at": at, "mg": mg, "lb": list(labels), "head": head, "base": "main", "add": 10, "del": 1}


def test_each_merged_pr_is_a_row_with_its_kind_how_it_was_decided_and_who_wrote_it():
    prs = [pr(1, "Add export button", labels=["feature"]), pr(2, "Fix crash on save", labels=["bug"]),
           pr(3, "Add retry", au="Copilot", at="Bot", head="copilot/x")]
    rows = capex.rows(prs, "o/r", NOW, private=True, base="main")
    by_n = {r["pr"]: r for r in rows}
    assert by_n[1]["kind"] == "feature" and by_n[2]["kind"] == "fix" and by_n[3]["author"] == "agent"
    assert by_n[1]["url"] == "https://github.com/o/r/pull/1" and by_n[1]["month"] == "2026-10" and by_n[1]["title"]
    text = capex.to_csv(rows)
    got = list(csv.DictReader(io.StringIO(text)))
    assert [r["pr"] for r in got] == ["1", "2", "3"] and set(got[0]) >= {"month", "pr", "url", "kind", "decided_by", "epic", "author"}


def test_a_public_repo_keeps_titles_off_the_file():
    rows = capex.rows([pr(1, "Secret plan")], "o/r", NOW, private=False, base="main")
    assert "title" not in rows[0]


def test_the_monthly_summary_counts_author_weeks_by_kind_and_the_agent_share():
    prs = [pr(1, "Add a", labels=["feature"], mg="2026-10-05T10:00:00Z"), pr(2, "Add b", labels=["feature"], mg="2026-10-06T10:00:00Z"),
           pr(3, "Add c", au="bob", labels=["feature"], mg="2026-10-14T10:00:00Z"),
           pr(4, "Fix d", au="Copilot", at="Bot", head="copilot/d", labels=["bug"], mg="2026-10-15T10:00:00Z")]
    got = capex.summary(capex.rows(prs, "o/r", NOW, private=True, base="main"))
    oct_ = got[-1]
    assert oct_["month"] == "2026-10" and oct_["prs"] == 4
    # amy's two feature PRs in one ISO week are one author-week; bob's is another.
    assert oct_["author_weeks"]["feature"] == 2 and oct_["agent_prs"] == 1 and oct_["feature_share"] == 0.75


def test_the_file_names_no_one():
    text = capex.to_csv(capex.rows([pr(1, "Add a", au="secret-person")], "o/r", NOW, private=True, base="main"))
    assert "secret-person" not in text and "_login" not in text
