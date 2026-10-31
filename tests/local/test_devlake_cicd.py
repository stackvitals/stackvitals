import copy

from stackvitals.core import export
from stackvitals.core.config import DEFAULTS
from stackvitals.core.model import PipelineRun

RUN = {"id": 7, "att": 2, "wfn": "CI", "path": ".github/workflows/ci.yml", "ev": "push", "br": "main", "sha": "a" * 40,
       "c": "failure", "cr": "2026-10-01T10:00:00Z", "st": "2026-10-01T10:01:00Z", "up": "2026-10-01T10:11:00Z", "pr": []}
JOBS = [{"run": 7, "att": 2, "id": 70, "n": "test", "c": "failure", "cr": "2026-10-01T10:01:00Z", "st": "2026-10-01T10:02:00Z",
         "en": "2026-10-01T10:10:00Z", "lb": ["ubuntu-latest"], "steps": []},
        {"run": 7, "att": 1, "id": 60, "n": "test", "c": "success", "cr": "2026-10-01T09:00:00Z", "st": "2026-10-01T09:01:00Z",
         "en": "2026-10-01T09:05:00Z", "lb": [], "steps": []}]


def test_a_run_attempt_becomes_devlakes_pipeline_task_and_commit_rows():
    p = PipelineRun.from_ci(RUN, JOBS, "o/r")
    rows = p.to_devlake("scope-1")
    pipe = rows["cicd_pipelines"]
    assert pipe["id"] == p.id and pipe["name"] == "CI" and pipe["result"] == "FAILURE" and pipe["status"] == "DONE"
    assert pipe["original_result"] == "failure" and pipe["duration_sec"] == 600 and pipe["queued_duration_sec"] == 60
    assert pipe["cicd_scope_id"] == "scope-1" and pipe["url"] == "https://github.com/o/r/actions/runs/7/attempts/2"
    # Only this attempt's job, as DevLake keeps one task per job per attempt.
    assert [t["name"] for t in rows["cicd_tasks"]] == ["test"] and rows["cicd_tasks"][0]["pipeline_id"] == p.id
    assert rows["cicd_tasks"][0]["duration_sec"] == 480 and rows["cicd_tasks"][0]["result"] == "FAILURE"
    assert rows["cicd_pipeline_commits"] == [{"pipeline_id": p.id, "commit_sha": "a" * 40, "branch": "main",
                                              "repo_id": "scope-1", "repo_url": "https://github.com/o/r"}]


def test_the_devlake_export_carries_ci_runs_and_jobs():
    tables = export.devlake_tables("o/r", {"closed": [], "open": []}, {"default_branch": "main"}, {"runs": [RUN], "jobs": JOBS},
                                   [], copy.deepcopy(DEFAULTS))
    assert len(tables["cicd_pipelines"]) == 1 and len(tables["cicd_tasks"]) == 1 and len(tables["cicd_pipeline_commits"]) == 1
    assert set(tables["cicd_pipelines"][0]) == set(export.COLUMNS["cicd_pipelines"])
