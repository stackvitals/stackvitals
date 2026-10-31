"""What changed before an incident: the deployments in the 72 hours before it began and the pull requests each shipped,
with config and dependency changes called out, ranked so the likeliest cause comes first (the last deployment before
it, a pull request a revert undid, then closeness in time)."""
from datetime import datetime, timedelta, timezone

from stackvitals.core import what_changed

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def at(hours_before):
    return iso(NOW - timedelta(hours=hours_before))


def pr(n, paths, merged_h, title="Change"):
    return {"n": n, "paths": paths, "mg": at(merged_h), "ti": title, "au": "amy", "add": 20, "del": 2}


def test_the_last_deployment_before_an_incident_and_its_prs_come_first():
    d1 = {"id": "d1", "sha": "aaa111", "finished": at(30), "name": "prod"}
    d2 = {"id": "d2", "sha": "bbb222", "finished": at(5), "name": "prod"}
    d3 = {"id": "d3", "sha": "ccc333", "finished": at(1), "name": "prod"}  # after the incident began: not a cause
    rows = [(pr(1, ["api/a.py"], 31), {}, d1), (pr(2, ["api/b.py", "poetry.lock"], 6), {}, d2),
            (pr(3, [".github/workflows/ci.yml"], 7), {}, d2), (pr(4, ["web/c.ts"], 2), {}, d3)]
    incident = {"source": "issue", "number": 77, "created": at(4), "resolved": at(2), "deployment": "d2"}
    got = what_changed.timeline(incident, rows, [d1, d2, d3])
    assert [c["ref"] for c in got["candidates"][:3]] == ["deployment bbb222", "#2", "#3"]
    kinds = {c["ref"]: c["kind"] for c in got["candidates"]}
    assert kinds["#2"] == "dependency" and kinds["#3"] == "config" and kinds["#1"] == "pr"
    assert "#4" not in kinds and "deployment ccc333" not in kinds
    assert got["window_hours"] == 72 and got["incident"]["number"] == 77


def test_a_pr_a_revert_undid_is_named_first_among_prs():
    d = {"id": "d1", "sha": "aaa111", "finished": at(5), "name": "prod"}
    rows = [(pr(1, ["api/a.py"], 6), {}, d), (pr(2, ["api/b.py"], 7), {}, d),
            (pr(3, ["api/b.py"], 1, title='Revert "Change b" (#2)'), {}, None)]
    rows[1][0]["ti"] = "Change b"
    incident = {"source": "revert", "number": 3, "created": at(3), "resolved": at(1), "deployment": "d1"}
    got = what_changed.timeline(incident, rows, [d])
    prs = [c for c in got["candidates"] if c["ref"].startswith("#")]
    assert prs[0]["ref"] == "#2" and "reverted" in prs[0]["why"]


def test_recent_incidents_each_get_a_timeline_and_old_ones_are_left_out():
    d = {"id": "d1", "sha": "aaa111", "finished": at(5), "name": "prod"}
    rows = [(pr(1, ["api/a.py"], 6), {}, d)]
    incidents = [{"source": "issue", "number": n, "created": at(h), "resolved": None, "deployment": None}
                 for n, h in ((1, 3), (2, 24 * 100))]
    got = what_changed.recent(incidents, rows, [d], NOW, days=90)
    assert [t["incident"]["number"] for t in got] == [1]
