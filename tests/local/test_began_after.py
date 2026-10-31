from datetime import datetime, timezone

from stackvitals.core import findings

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def test_a_clear_start_names_the_merges_that_landed_just_before_it():
    ci_doc = {"jobs": [{"workflow": ".github/workflows/ci.yml", "job": "tests", "began": {
        "first": "2026-10-10T09:00:00Z", "clear": True, "landed": ["abc123", "def456"], "runs_before": 40, "p": 0.001}}],
        "tests": [{"id": "t::slow", "began": {"first": "2026-10-11T00:00:00Z", "clear": False, "landed": ["abc123"]}}]}
    prs = [{"n": 12, "mc": "abc123", "mg": "2026-10-09T20:00:00Z"}, {"n": 13, "mc": "zzz", "mg": "2026-10-01T00:00:00Z"}]
    began = findings.began_after(ci_doc, prs)
    assert began == {"job:tests": {"day": "2026-10-10", "prs": [12]}}  # an unclear start names nothing
    red = {"rerun_jobs": [{"workflow": "CI", "job": "tests", "hours": 30.0, "prs": 4, "runs": []}], "rerun_tests": []}
    [f] = [x for x in findings.build("o/r", red, None, None, None, NOW, began=began) if x["kind"] == "fix_job"]
    assert "right after #12 merged" in f["title"] and f["evidence"][0]["url"].endswith("/pull/12")


def test_flaky_findings_inside_red_ci_are_counted_once():
    red = {"prs": 30, "red_prs": 10, "red_hours_total": 50.0, "rerun_hours_total": 20.0, "measures": {}, "top": [],
           "rerun_jobs": [{"workflow": "CI", "job": "tests", "hours": 20.0, "prs": 4, "runs": []}], "rerun_tests": []}
    found = findings.build("o/r", red, None, None, None, NOW)
    fix = next(f for f in found if f["kind"] == "fix_job")
    assert fix["part_of"] == "red_ci"
    assert findings.opportunity(found) == {"hours": 50.0, "findings": 2, "inside_another": 1}


def test_opportunity_counts_shared_re_run_waits_once_with_or_without_an_open_red_ci_finding():
    from stackvitals.core import findings
    job = {"kind": "fix_job", "hours": 8.0}
    test = {"kind": "fix_test", "hours": 6.0}
    # No red-CI finding (too few merged PRs): jobs and tests split the same waits, so the larger counts.
    assert findings.opportunity([job, test])["hours"] == 8.0
    # A snoozed red-CI finding leaves the sum, and the re-run waits come back in it.
    red = {"kind": "red_ci", "hours": 20.0, "decision": {"verb": "snooze"}}
    assert findings.opportunity([red, {**job, "part_of": "red_ci"}, {**test, "part_of": "red_ci"}]) == {
        "hours": 8.0, "findings": 2, "inside_another": 0}
    assert findings.opportunity([{**red, "decision": None}, job, test])["hours"] == 20.0


def test_a_job_name_two_workflows_share_gets_no_began_note():
    from stackvitals.core import findings
    b = {"clear": True, "first": "2026-10-10T00:00:00Z", "landed": ["abc"]}
    doc = {"jobs": [{"workflow": "a.yml", "job": "build", "began": b}, {"workflow": "b.yml", "job": "build", "began": b}]}
    assert findings.began_after(doc, [{"n": 5, "mc": "abc", "mg": "2026-10-09"}]) == {}
