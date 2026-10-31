import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "accuracy" / "flaky"))

from natural import agreement, flakes, verdict  # noqa: E402

PATH = ".github/workflows/ci.yml"


def run(rid, att, tree, pr, day, br=None):
    return {"id": rid, "att": att, "path": PATH, "ev": "pull_request", "br": br or f"b{pr}", "tree": tree, "pr": [pr],
            "c": "failure", "cr": f"2026-10-{day:02d}T10:00:00Z"}


def job(jid, rid, att, c, day, step="Run tests"):
    return {"id": jid, "run": rid, "att": att, "n": "test", "c": c, "st": f"2026-10-{day:02d}T10:00:00Z",
            "en": f"2026-10-{day:02d}T10:05:00Z", "steps": [[3, step, c]]}


DATA = {"runs": [run(1, 1, "t1", 5, 6), run(1, 2, "t1", 5, 6), run(2, 1, "t2", 6, 4), run(2, 2, "t2", 6, 4),
                 run(3, 1, "t3", 7, 15), run(3, 2, "t3", 7, 15), {**run(4, 1, "t4", 8, 14, br="main"), "ev": "push", "pr": []},
                 {**run(5, 1, "t5", 9, 13, br="main"), "ev": "push", "pr": []}],
        "jobs": [job(11, 1, 1, "failure", 6), job(12, 1, 2, "success", 6),
                 job(21, 2, 1, "failure", 4), job(22, 2, 2, "success", 4),
                 job(31, 3, 1, "failure", 15), job(32, 3, 2, "failure", 15),
                 job(41, 4, 1, "success", 14), job(51, 5, 1, "success", 13)]}


def item(rid, jid):
    return {"run": rid, "att": 1, "job_id": jid, "job": "test", "workflow": PATH, "failing_step": "Run tests"}


def test_a_failure_whose_job_also_flaked_on_an_earlier_other_change_was_not_caused_by_this_change():
    ev = flakes(DATA)
    out = verdict(item(1, 11), DATA, ev)
    assert out["verdict"] == "not caused" and "before" in out["why"]


def test_a_failure_repeated_on_identical_code_while_other_changes_passed_was_caused_by_the_change():
    ev = flakes(DATA)
    out = verdict(item(3, 31), DATA, ev)
    assert out["verdict"] == "caused"


def test_a_flake_seen_only_on_this_change_stays_undetermined():
    data = {"runs": DATA["runs"][:2], "jobs": DATA["jobs"][:2]}
    assert verdict(item(1, 11), data, flakes(data))["verdict"] == "undetermined"


def test_other_pull_requests_failing_dont_stop_the_default_branch_from_deciding():
    data = {"runs": DATA["runs"] + [run(6, 1, "t6", 10, 15)], "jobs": DATA["jobs"] + [job(61, 6, 1, "failure", 15)]}
    assert verdict(item(3, 31), data, flakes(data))["verdict"] == "caused"
    broken = {"runs": data["runs"], "jobs": [j if j["id"] != 51 else {**j, "c": "failure"} for j in data["jobs"]]}
    assert verdict(item(3, 31), broken, flakes(broken))["verdict"] == "undetermined"


def test_the_default_branch_failing_in_the_same_step_just_before_no_longer_decides_it():
    # Phase 15: 2 of the 28 failures this rule decided were the change's own error in an already-failing step.
    data = {"runs": DATA["runs"] + [run(7, 1, "t7", 11, 20), {**run(8, 1, "t8", 0, 19, br="main"), "ev": "push", "pr": []}],
            "jobs": DATA["jobs"] + [job(71, 7, 1, "failure", 20), job(81, 8, 1, "failure", 19)]}
    assert verdict(item(7, 71), data, flakes(data))["verdict"] == "undetermined"


def test_the_default_branch_failing_after_the_change_could_have_merged_proves_nothing():
    data = {"runs": DATA["runs"] + [run(7, 1, "t7", 11, 20), {**run(8, 1, "t8", 0, 21, br="main"), "ev": "push", "pr": []}],
            "jobs": DATA["jobs"] + [job(71, 7, 1, "failure", 20), job(81, 8, 1, "failure", 21)]}
    assert verdict(item(7, 71), data, flakes(data))["verdict"] == "undetermined"


def test_labellers_are_scored_only_where_history_decides():
    verdicts = {1: {"verdict": "not caused"}, 2: {"verdict": "caused"}, 3: {"verdict": "undetermined"}}
    labels = {1: {"caused_by_change": "no"}, 2: {"caused_by_change": "no"}, 3: {"caused_by_change": "yes"}}
    out = agreement(verdicts, labels)
    assert (out["n"], out["agree"]) == (2, 1)


def test_a_default_branch_failure_is_not_its_own_evidence():
    data = {"runs": [{**run(9, 1, "t9", 0, 20, br="main"), "ev": "push", "pr": []}],
            "jobs": [job(91, 9, 1, "failure", 20)]}
    assert verdict(item(9, 91), data, flakes(data))["verdict"] == "undetermined"
