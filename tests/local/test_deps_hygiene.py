"""Dependency-update hygiene from the pull requests the repo already keeps: open update PRs by age, security updates
waiting more than 48 hours (unless the team accepted the risk until a date), how fast updates merge, and whether the
bot has gone quiet (Dependabot pauses itself after 90 days without interaction)."""
from datetime import datetime, timedelta, timezone

from stackvitals.deps.hygiene import hygiene

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def at(h):
    return (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def bump(n, h, title, merged=None, head=None, login="dependabot[bot]", lb=()):
    return {"n": n, "ti": title, "cr": at(h), "mg": at(merged) if merged is not None else None, "au": login, "at": "Bot",
            "head": head or f"dependabot/pip/{title.split()[1]}-1", "lb": list(lb)}


FLOW = {"open": [bump(10, 100, "Bump requests from 2.31.0 to 2.32.0", lb=["security"]),
                 bump(11, 20, "[Security] Bump urllib3 from 2.0.0 to 2.2.2"),
                 bump(12, 300, "Bump black from 24.1.0 to 24.4.0"),
                 {"n": 13, "ti": "Fix docs", "cr": at(5), "au": "amy", "at": "User", "head": "fix", "lb": []}],
        "closed": [bump(1, 200, "Bump idna from 3.6 to 3.7", merged=150), bump(2, 300, "Bump pytest from 8.0 to 8.1", merged=290)]}


def test_open_updates_by_age_and_security_ones_past_48_hours():
    out = hygiene(FLOW, {}, NOW)
    assert [u["pr"] for u in out["open"]] == [12, 10, 11]  # oldest first, people's PRs left out
    assert [u["pr"] for u in out["security_overdue"]] == [10]  # urllib3 waits 20 h, still inside 48 h
    assert out["open"][0]["package"] == "black" and out["merged_90d"] == 2 and out["merge_median_hours"] == 30.0
    assert out["bots"] == ["dependabot"] and out["quiet_days"] == 0


def test_an_accepted_risk_leaves_the_overdue_list_until_its_date():
    state = {"package:requests": {"verb": "accept", "kind": "package", "id": "requests", "until": "2026-11-01", "by": "alice",
                                  "reason": "not reachable from our code"}}
    out = hygiene(FLOW, state, NOW)
    assert out["security_overdue"] == [] and out["open"][1]["decision"]["reason"] == "not reachable from our code"


def test_a_bot_that_stopped_opening_pull_requests_is_noticed():
    old = {"open": [], "closed": [bump(1, 24 * 40, "Bump idna from 3.6 to 3.7", merged=24 * 39)]}
    assert hygiene(old, {}, NOW)["quiet_days"] == 40
    assert hygiene({"open": [], "closed": []}, {}, NOW) is None
