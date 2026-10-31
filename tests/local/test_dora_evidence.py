from datetime import datetime, timezone

from stackvitals.core import delivery

START = datetime(2026, 9, 1, tzinfo=timezone.utc)
END = datetime(2026, 10, 1, tzinfo=timezone.utc)


def dep(sha, day):
    return {"id": f"deployment:{sha}:{day}", "sha": sha, "finished": day}


def test_each_dora_number_names_the_items_it_was_computed_from():
    deps = [dep("a" * 40, "2026-09-05T10:00:00Z"), dep("b" * 40, "2026-09-12T10:00:00Z"), dep("c" * 40, "2026-08-01T10:00:00Z")]
    deployed = [{"deployment": deps[0]["id"], "cycle_min": 120, "pr": 11}, {"deployment": deps[1]["id"], "cycle_min": 600, "pr": 12},
                {"deployment": deps[1]["id"], "cycle_min": None, "pr": 13}, {"deployment": deps[2]["id"], "cycle_min": 5, "pr": 9}]
    incidents = [{"source": "revert", "number": 14, "deployment": deps[1]["id"], "created": "2026-09-12T11:00:00Z",
                  "resolved": "2026-09-12T12:30:00Z"}]
    out = delivery.dora(deps, deployed, incidents, START, END)
    ev = out["evidence"]
    # Lead time: the deployed PRs in the window with their minutes, longest first; PR 13 had no time, PR 9 shipped before.
    assert ev["lead_time"] == [[12, "bbbbbbbbbbbb", 600], [11, "aaaaaaaaaaaa", 120]] and out["lead_time_n"] == 2
    assert ev["deployments"] == [["aaaaaaaaaaaa", "2026-09-05T10:00:00Z"], ["bbbbbbbbbbbb", "2026-09-12T10:00:00Z"]]
    assert ev["failed"] == [["bbbbbbbbbbbb", "revert", 14]] and out["failed_deployments"] == 1
    assert ev["recovery"] == [["bbbbbbbbbbbb", "revert", 14, 150]] and out["recovery_n"] == 1


def test_long_evidence_lists_are_capped_and_say_how_many_there_were():
    deps = [dep(f"{i:040x}", f"2026-09-{1 + i % 28:02d}T10:00:00Z") for i in range(3)]
    deployed = [{"deployment": deps[i % 3]["id"], "cycle_min": i, "pr": i} for i in range(1, 900)]
    ev = delivery.dora(deps, deployed, [], START, END)["evidence"]
    assert len(ev["lead_time"]) == delivery.EVIDENCE_MAX and ev["lead_time_total"] == 899
    assert ev["lead_time"][0][2] == 899  # the longest come first, so the outliers are always shown


def test_a_phase_names_its_pull_requests_longest_first():
    values = [(n, float(n % 7)) for n in range(1, 40)]
    out = delivery._summary("pickup", [v for _n, v in values], [n for n, _v in values])
    assert out["n"] == 39 and out["evidence"][0] == [6, 6.0] and len(out["evidence"]) == 39
    assert "evidence" not in delivery._summary("pickup", [1.0, 2.0])
