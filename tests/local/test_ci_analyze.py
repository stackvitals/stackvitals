from datetime import timedelta

from ci_fake import T0, iso
from stackvitals.ci.analyze import analyze

NOW = T0 + timedelta(days=30)


def run(rid, att, day, c, tree="t1", ev="push", br="main", pr=()):
    return {"t": "run", "id": rid, "att": att, "path": ".github/workflows/ci.yml", "wfn": "CI", "ev": ev, "br": br,
            "tree": tree, "pr": list(pr), "c": c, "cr": iso(T0 + timedelta(days=day))}


def jb(jid, rid, att, day, name, c, secs=60, step="Run tests", labels=("ubuntu-latest",), queue=5):
    st = T0 + timedelta(days=day, minutes=10 * (att - 1))
    steps = [[1, "Set up job", "success", iso(st), iso(st)],
             [2, step if c == "failure" else "Run tests", c, iso(st), iso(st + timedelta(seconds=secs))]]
    return {"t": "job", "run": rid, "att": att, "id": jid, "n": name, "c": c, "cr": iso(st - timedelta(seconds=queue)),
            "st": iso(st), "en": iso(st + timedelta(seconds=secs)), "lb": list(labels), "steps": steps}


def find(result, name):
    return next(j for j in result["jobs"] if j["job"] == name)


def test_different_results_on_the_same_code_are_a_flake_but_not_across_events():
    data = {"runs": [run(1, 1, 10, "failure", tree="a"), run(2, 1, 11, "success", tree="a"),
                     run(3, 1, 12, "failure", tree="b", ev="pull_request"), run(4, 1, 12, "success", tree="b")],
            "jobs": [jb(11, 1, 1, 10, "test", "failure"), jb(21, 2, 1, 11, "test", "success"),
                     jb(31, 3, 1, 12, "test", "failure"), jb(41, 4, 1, 12, "test", "success")]}
    assert find(analyze(data, NOW, default_branch="main"), "test")["flake_events"] == 1


def test_states_need_two_flakes_to_turn_on_and_two_quiet_weeks_to_turn_off():
    def flaky_run(rid, day):
        return ([run(rid, 1, day, "failure", tree=f"x{rid}"), run(rid, 2, day, "success", tree=f"x{rid}")],
                [jb(rid * 10 + 1, rid, 1, day, "e2e", "failure"), jb(rid * 10 + 2, rid, 2, day, "e2e", "success")])
    runs, jobs = [], []
    for rid, day in ((1, 25), (2, 27)):
        r, j = flaky_run(rid, day)
        runs += r
        jobs += j
    assert find(analyze({"runs": runs, "jobs": jobs}, NOW, default_branch="main"), "e2e")["state"] == "flaky"
    # The same two flakes long ago, then 12 clean runs over the last 20 days: fixed.
    runs, jobs = [], []
    for rid, day in ((1, -30), (2, -28)):
        r, j = flaky_run(rid, day)
        runs += r
        jobs += j
    for k in range(12):
        runs.append(run(50 + k, 1, 10 + k, "success", tree=f"y{k}"))
        jobs.append(jb(500 + k, 50 + k, 1, 10 + k, "e2e", "success"))
    assert find(analyze({"runs": runs, "jobs": jobs}, NOW, default_branch="main"), "e2e")["state"] == "fixed"


def test_durations_slowdowns_queue_and_minutes():
    runs, jobs = [], []
    for k in range(20):
        # 14 runs of 5 minutes, then 6 runs of 10 minutes in the last week.
        day, secs = (5 + k, 300) if k < 14 else (10 + k, 600)
        runs.append(run(k, 1, day, "success", tree=f"z{k}"))
        jobs.append(jb(k, k, 1, day, "build", "success", secs=secs, queue=30,
                       labels=("windows-latest",) if k == 0 else ("ubuntu-latest",)))
    result = analyze({"runs": runs, "jobs": jobs}, NOW, default_branch="main")
    j = find(result, "build")
    assert j["median_s"] == 300 and j["slower"]["after_s"] == 600 and j["slower"]["pct"] == 100
    assert result["queue"]["median_s"] == 30
    assert result["minutes"]["windows"] == 5 and result["minutes"]["linux"] == 13 * 5 + 6 * 10
