from datetime import timedelta

from ci_fake import T0, iso
from stackvitals.ci.analyze import analyze
from stackvitals.ci.feedback import classify_run, render_comment, verdict_payload

WF = ".github/workflows/pr.yml"
TITLE = ('2026-10-20T10:00:00Z ##[error]No release type found in pull request title "LAB-4702: reply to an issue". '
         "Add a prefix to indicate what kind of release this pull request corresponds to.")
CHECKBOX = '2026-10-20T10:00:00Z ##[error]AI assistance section incomplete: the checkbox "I read every line" is not checked'
LABEL = "2026-10-20T10:00:00Z ::error Add 'changelog/*' label"
ASSERT = "2026-10-20T10:00:00Z E   AssertionError: expected 3 labels in the chart, got 2\n##[error]Process completed with exit code 1."


def run(rid, ev="pull_request"):
    return {"t": "run", "id": rid, "att": 1, "path": WF, "wfn": "PR", "ev": ev, "br": "fix", "tree": "t1", "pr": [5],
            "c": "failure", "cr": iso(T0 + timedelta(days=29))}


def job(jid, rid, name="Validate PR title"):
    st = T0 + timedelta(days=29)
    return {"t": "job", "run": rid, "att": 1, "id": jid, "n": name, "c": "failure", "cr": iso(st), "st": iso(st),
            "en": iso(st + timedelta(minutes=1)), "lb": ["ubuntu-latest"], "steps": [[1, "Check", "failure"]]}


def items(log, name="Validate PR title", ev="pull_request", edits=(WF,), history=None):
    data = {"runs": [run(9, ev)], "jobs": [job(91, 9, name)]}
    result = {"default_branch": "main", "jobs": history or [], "tests": [], "pr_edit_workflows": list(edits)}
    return classify_run(data, result, 9, logs={91: log})


def test_a_job_that_checks_the_pr_title_and_fails_on_it_says_fix_the_pr_not_the_code():
    [item] = items(TITLE)
    assert item["verdict"] == "PR details"
    assert "title, description or labels" in item["detail"] and "re-run" in item["detail"]


def test_checkboxes_and_labels_count_and_a_matrix_name_still_matches():
    assert items(CHECKBOX, name="ai_assistance")[0]["verdict"] == "PR details"
    assert items(LABEL, name="Validate PR title (ubuntu)")[0]["verdict"] == "PR details"


def test_it_wins_over_a_flaky_history_that_was_really_label_edits():
    known = [{"workflow": WF, "job": "Validate PR title", "state": "flaky", "flake_events": 9, "runs": 21,
              "flake_steps": ["Check"], "last_flake": "2026-10-13T00:00:00Z"}]
    assert items(LABEL, history=known)[0]["verdict"] == "PR details"


def test_it_needs_both_the_workflow_and_an_error_about_the_pr():
    # A test failure that mentions labels, in a job that reads the PR, is still the change's.
    assert items(ASSERT)[0]["verdict"] == "new"
    # A workflow that never runs on PR edits, or a push run, never reads the PR.
    assert items(TITLE, edits=())[0]["verdict"] == "new"
    assert items(TITLE, ev="push")[0]["verdict"] == "new"
    assert items(None)[0]["verdict"] == "new"


def test_the_comment_and_check_say_to_fix_the_pr_and_the_check_still_blocks():
    found = items(TITLE)
    assert "Fix the pull request's details" in render_comment(found, "o/r")
    assert verdict_payload(found, green=False)["conclusion"] == "failure"


def test_analyze_publishes_the_workflows_run_by_pr_edits():
    data = {"runs": [run(9)], "jobs": [job(91, 9)]}
    now = T0 + timedelta(days=30)
    assert analyze(data, now, pr_metadata={WF: {"Validate PR title"}})["pr_edit_workflows"] == [WF]
    assert analyze(data, now, pr_edits={".github/workflows/x.yml"})["pr_edit_workflows"] == [".github/workflows/x.yml"]
    assert analyze(data, now)["pr_edit_workflows"] == []


def test_the_workflow_scan_remembers_which_workflows_run_on_edits(tmp_path):
    from stackvitals.ci.store import DataStore
    from stackvitals.ci.triggers import pr_edit_workflows, pr_metadata_workflows

    class Api:
        def file(self, path, ref):
            return {WF: b"on:\n  pull_request:\n    types: [opened, edited]\njobs:\n  ai:\n    runs-on: x\n    steps:\n"
                        b"      - run: node check.js\n",
                    ".github/workflows/ci.yml": b"on: [pull_request]\njobs:\n  t:\n    runs-on: x\n"}[path]
    store = DataStore(tmp_path)
    data = {"runs": [run(9), {**run(8), "path": ".github/workflows/ci.yml"}]}
    assert pr_metadata_workflows(Api(), store, data, "main", "2026-10-23") == {}
    assert pr_edit_workflows(store) == {WF}
