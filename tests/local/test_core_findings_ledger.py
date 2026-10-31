"""Findings remember: each has a stable key, a ledger counts the days it was active in the last 90 (open since, share,
"structural" past half, Swarmia's rule), and a finding someone acknowledged or snoozed leaves the top of the list with
who, why and until when, coming back when the snooze ends."""
from datetime import datetime, timedelta, timezone

from test_core_findings import BUMPS, NOW, REPO, delivery, flow, red_ci

from stackvitals.core import findings


def build():
    return findings.build(REPO, red_ci=red_ci(), delivery=delivery(), flow=flow(), bumps=BUMPS, now=NOW)


def test_every_finding_has_a_stable_key():
    keys = {f["kind"]: f["key"] for f in build()}
    assert keys["fix_job"] == "fix_job:CI / tests (3.12)" and keys["fix_test"] == "fix_test:tests/test_net.py::test_fetch"
    assert keys["incident"] == "incident:30" and keys["review_wait"] == "review_wait" and keys["red_ci"] == "red_ci"
    assert len({f["key"] for f in build()}) == len(build())


def test_the_ledger_counts_active_days_once_a_day_and_forgets_after_90():
    ledger = {}
    for day in range(60):
        ledger = findings.update_ledger(ledger, build(), NOW - timedelta(days=60 - day))
    same = findings.update_ledger(ledger, build(), NOW - timedelta(days=1))
    assert same == ledger  # the same day twice changes nothing, so a quiet run commits nothing
    entry = ledger["review_wait"]
    assert entry["first"] == (NOW - timedelta(days=60)).date().isoformat() and len(entry["days"]) == 60
    later = findings.update_ledger(ledger, [], NOW + timedelta(days=40))
    assert all(d >= (NOW - timedelta(days=50)).date().isoformat() for d in later["review_wait"]["days"])


def test_findings_show_open_since_their_share_and_whether_they_are_structural():
    ledger = {}
    for day in range(60):
        ledger = findings.update_ledger(ledger, build(), NOW - timedelta(days=59 - day))
    out = findings.annotate(build(), ledger, {}, NOW)
    wait = next(f for f in out if f["key"] == "review_wait")
    assert wait["open_since"] == (NOW - timedelta(days=59)).date().isoformat()
    assert wait["active_share_90d"] == round(60 / 90, 2) and wait["structural"] is True


def test_acknowledged_and_snoozed_findings_leave_the_top_and_come_back_on_expiry():
    state = {"finding:review_wait": {"verb": "snooze", "kind": "finding", "id": "review_wait", "until": "2026-10-25",
                                     "by": "alice", "reason": "release week"}}
    out = findings.annotate(build(), {}, state, NOW)
    assert next(f for f in out if f["key"] == "review_wait")["decision"]["by"] == "alice"
    text = findings.render_markdown(out, REPO)
    assert "waited 3 to 30 days" not in text and "acknowledged or snoozed" in text
    page = findings.render_html(out, REPO, NOW)
    assert "release week" in page and "until 2026-10-25" in page
    assert "decision" not in next(f for f in findings.annotate(build(), {}, {}, NOW) if f["key"] == "review_wait")


def test_the_ledger_keeps_each_findings_size_and_the_days_it_ranked_first():
    found = build()
    ledger = findings.update_ledger({}, found, NOW - timedelta(days=20))
    top = found[0]["key"]
    assert ledger[top]["top_days"] == [(NOW - timedelta(days=20)).date().isoformat()]
    assert ledger[top]["hours_first"] == ledger[top]["hours_last"] == found[0]["hours"]
    assert all("top_days" not in e or not e["top_days"] for k, e in ledger.items() if k != top)


def test_the_track_record_counts_top_findings_that_shrank_or_cleared():
    found = build()
    top = found[0]["key"]
    ledger = findings.update_ledger({}, found, NOW - timedelta(days=30))
    half = [{**f, "hours": f["hours"] / 4} if f["key"] == top else f for f in found]
    ledger = findings.update_ledger(ledger, half, NOW - timedelta(days=10))
    record = findings.track_record(ledger, NOW)
    assert record["top_findings"] >= 1 and record["shrank_by_half"] >= 1
    gone = findings.update_ledger(ledger, [f for f in found if f["key"] != top], NOW)
    later = findings.track_record(gone, NOW + timedelta(days=8))
    assert later["cleared"] >= 1 and later["since"] == (NOW - timedelta(days=30)).date().isoformat()


def test_a_snoozed_finding_is_never_the_top_one():
    found = build()
    ledger = findings.update_ledger({}, found, NOW, set_aside={found[0]["key"]})
    assert "top_days" not in ledger[found[0]["key"]] and ledger[found[1]["key"]]["top_days"]
