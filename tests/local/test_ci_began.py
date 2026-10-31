from datetime import timedelta

from test_ci_analyze import NOW, find, jb, run

from stackvitals.ci.analyze import analyze


def _history(clean_days: int, flaky_days: list[int]):
    """Two clean runs a day up to `clean_days`, then one flaky retry on each flaky day, all on main."""
    runs, jobs, rid = [], [], 0
    for day in range(clean_days):
        for half in (0, 0.5):
            rid += 1
            runs.append(run(rid, 1, day + half, "success", tree=f"c{rid}") | {"sha": f"sha{rid}"})
            jobs.append(jb(rid * 10, rid, 1, day + half, "e2e", "success"))
    for day in flaky_days:
        rid += 1
        runs += [run(rid, 1, day, "failure", tree=f"f{rid}") | {"sha": f"sha{rid}"},
                 run(rid, 2, day, "success", tree=f"f{rid}") | {"sha": f"sha{rid}"}]
        jobs += [jb(rid * 10, rid, 1, day, "e2e", "failure"), jb(rid * 10 + 1, rid, 2, day, "e2e", "success")]
    return {"runs": runs, "jobs": jobs}


def test_a_flake_that_began_after_a_long_clean_stretch_names_when_and_what_landed_before():
    began = find(analyze(_history(20, [21, 23, 25, 27]), NOW, window_days=40, default_branch="main"), "e2e")["began"]
    assert began["first"].startswith((NOW - timedelta(days=9)).date().isoformat())
    assert began["runs_before"] == 40 and began["flakes"] == 4 and began["clear"] is True and began["p"] < 0.05
    assert began["landed"] and all(s.startswith("sha") for s in began["landed"])


def test_with_few_runs_before_it_the_start_is_only_when_it_was_first_seen():
    began = find(analyze(_history(3, [4, 6]), NOW, window_days=40, default_branch="main"), "e2e")["began"]
    assert began["runs_before"] == 6 and began["clear"] is False


def test_a_job_that_never_flaked_has_no_start():
    assert find(analyze(_history(5, []), NOW, window_days=40, default_branch="main"), "e2e").get("began") is None


def test_the_start_reads_only_as_sure_as_the_runs_before_it_allow():
    from stackvitals.ci.report import began_text
    clear = {"first": "2026-10-03T10:00:00Z", "runs_before": 64, "runs_after": 30, "flakes": 6, "p": 0.0012, "clear": True,
             "landed": ["abc1234567", "def7654321"]}
    assert began_text(clear) == ("began around 2026-10-03: 64 runs before it never flaked (chance p = 0.0012); reached the "
                                 "default branch the day before: abc1234, def7654")
    assert "too few to say" in began_text({**clear, "runs_before": 6, "clear": False})
    assert "rare anyway" in began_text({**clear, "p": 0.4, "clear": False})
    assert began_text(None) == ""


def test_a_flaky_test_gets_a_start_too():
    data = _history(20, [21, 23, 25, 27])
    data["tests"] = []
    for r in data["runs"]:
        failed = [["t::sync", "fp", "Timeout"]] if r["c"] == "failure" else []
        data["tests"].append({"t": "tests", "run": r["id"], "att": r["att"], "art": r["id"] * 10 + r["att"], "name": "unit",
                              "total": 5, "skipped": 0, "failed": failed, "flaky": [], "slow": []})
    test = next(t for t in analyze(data, NOW, window_days=40, default_branch="main")["tests"] if t["id"] == "t::sync")
    assert test["began"]["runs_before"] == 40 and test["began"]["clear"] is True


def test_a_flaky_test_issue_offers_a_prefilled_linear_issue_when_the_repo_uses_linear():
    from urllib.parse import parse_qs, urlparse
    from stackvitals.ci.automation import _issue_body
    entry = {"id": "t::sync", "flake_events": 4, "runs": 40, "last_flake": "2026-10-20T00:00:00Z", "flake": "timing"}
    assert "linear.new" not in _issue_body(entry)
    body = _issue_body(entry, linear=True)
    link = next(w for w in body.split() if "linear.new" in w).strip("()<>")
    q = parse_qs(urlparse(link).query)
    assert "t::sync" in q["title"][0] and "4 times" in q["description"][0]
