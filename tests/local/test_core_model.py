"""Typed entities with DevLake's names and enums, built from the records the modules already store."""
from stackvitals.core import model

PR = {"t": "pr", "n": 7, "ti": "Fix pool", "draft": True, "st": "MERGED", "cr": "2026-10-01T10:00:00Z", "up": "2026-10-03T00:00:00Z",
      "mg": "2026-10-02T12:00:00Z", "cl": "2026-10-02T12:00:00Z", "add": 12, "del": 3, "files": 2, "au": "amy", "at": "User",
      "as": "NONE", "base": "main", "head": "fix-pool", "ho": "amy", "lc": "2026-10-01T09:00:00Z", "la": "2026-09-30T09:00:00Z",
      "mgs": "MERGEABLE", "ci": "SUCCESS", "iss": True, "paths": ["src/pool.py"], "rq": [], "lb": ["bug"],
      "ev": [["ready", "2026-10-01T11:00:00Z"], ["req", "2026-10-01T11:05:00Z", "bob"],
             ["review", "2026-10-01T15:00:00Z", "bob", "APPROVED", "MEMBER", "User", False],
             ["merged", "2026-10-02T12:00:00Z", "bob"]],
      "cm": [["2026-10-01T12:00:00Z", "bob", "MEMBER", "User", True]], "f": "2026-10-03T00:00:00Z"}
RUN = {"t": "run", "id": 123, "att": 2, "wf": 9, "wfn": "CI", "path": ".github/workflows/ci.yml", "ev": "pull_request", "br": "fix-pool",
       "sha": "abc123", "tree": "t1", "pr": [7], "c": "failure", "cr": "2026-10-01T11:10:00Z", "st": "2026-10-01T11:11:00Z",
       "up": "2026-10-01T11:20:00Z", "ho": "amy"}
JOB = {"t": "job", "run": 123, "att": 2, "id": 555, "n": "tests (ubuntu)", "c": "failure", "cr": "2026-10-01T11:10:30Z",
       "st": "2026-10-01T11:11:00Z", "en": "2026-10-01T11:19:00Z", "lb": ["ubuntu-latest"],
       "steps": [[1, "Checkout", "success", "2026-10-01T11:11:00Z", "2026-10-01T11:11:10Z"],
                 [2, "Run tests", "failure", "2026-10-01T11:11:10Z", "2026-10-01T11:19:00Z"]]}
TESTS = {"t": "tests", "run": 123, "att": 2, "art": 77, "name": "junit", "total": 3, "skipped": 1,
         "failed": [["tests/test_pool.py::test_reuse", "fp1", "AssertionError: 3 != 4"]],
         "flaky": ["tests/test_pool.py::test_retry"], "slow": [["tests/test_pool.py::test_reuse", 2500]]}


def test_a_change_request_keeps_devlakes_names_and_a_typed_timeline():
    cr = model.ChangeRequest.from_flow(PR, "acme/web")
    assert cr.id == "github:PullRequest:acme/web:7" and cr.number == 7 and cr.state == "MERGED"
    assert cr.author == "amy" and cr.author_kind == "person" and cr.draft is True
    assert cr.created_at == "2026-10-01T10:00:00Z" and cr.ready_at == "2026-10-01T11:00:00Z" and cr.merged_at == "2026-10-02T12:00:00Z"
    kinds = [e.kind for e in cr.events]
    assert kinds == ["READY", "REVIEW_REQUEST", "COMMENT", "REVIEW", "MERGED"]
    review = next(e for e in cr.events if e.kind == "REVIEW")
    assert review.actor == "bob" and review.state == "APPROVED" and review.actor_kind == "person"
    row = cr.to_devlake()
    assert row["pull_request_key"] == 7 and row["status"] == "MERGED" and row["merged_date"] == cr.merged_at
    assert row["author_name"] == "amy" and row["additions"] == 12 and row["is_draft"] is True and row["head_ref"] == "fix-pool"


def test_a_pipeline_run_maps_github_conclusions_to_devlake_results_and_otel_names():
    run = model.PipelineRun.from_ci(RUN, [JOB], "acme/web")
    assert run.id == "github:CicdPipeline:acme/web:123:2" and run.result == "FAILURE" and run.attempt == 2
    assert run.sha == "abc123" and run.change_numbers == [7] and run.trigger == "pull_request"
    task = run.tasks[0]
    assert task.name == "tests (ubuntu)" and task.result == "FAILURE" and task.steps[1].name == "Run tests"
    assert task.steps[1].result == "FAILURE" and task.duration_s == 480
    assert model.cicd_result("success") == "SUCCESS" and model.cicd_result("cancelled") == "ABORT"
    assert model.cicd_result("timed_out") == "FAILURE" and model.cicd_result("skipped") == "OTHER"
    row = run.to_otel()
    assert row["cicd.pipeline.name"] == "CI" and row["cicd.pipeline.run.id"] == 123 and row["cicd.pipeline.result"] == "FAILURE"
    assert row["vcs.ref.head.revision"] == "abc123" and row["vcs.ref.head.name"] == "fix-pool"


def test_test_results_come_out_as_ctrf_shaped_records():
    results = model.TestResult.from_report(TESTS, "acme/web")
    by_id = {r.test_id: r for r in results}
    failed = by_id["tests/test_pool.py::test_reuse"]
    assert failed.status == "FAILED" and failed.fingerprint == "fp1" and failed.message == "AssertionError: 3 != 4"
    assert failed.duration_ms == 2500 and failed.run_id == 123 and failed.attempt == 2
    assert by_id["tests/test_pool.py::test_retry"].status == "FLAKY"
    ctrf = failed.to_ctrf()
    assert ctrf["name"] == failed.test_id and ctrf["status"] == "failed" and ctrf["duration"] == 2500 and ctrf["flaky"] is False
    assert by_id["tests/test_pool.py::test_retry"].to_ctrf()["flaky"] is True


def test_deployments_incidents_and_issues_have_devlake_enums_and_ids():
    d = model.Deployment.new("acme/web", "run:123", sha="abc123", finished_at="2026-10-02T13:00:00Z", source="workflow")
    assert d.id == "github:CicdDeployment:acme/web:run:123" and d.environment == "PRODUCTION" and d.result == "SUCCESS"
    i = model.Incident.new("acme/web", "issue:9", opened_at="2026-10-02T14:00:00Z", resolved_at=None, source="issue",
                           deployment_id=d.id)
    assert i.id == "github:Incident:acme/web:issue:9" and i.deployment_id == d.id and i.resolved_at is None
    issue = model.Issue.from_community({"t": "issue", "n": 9, "st": "CLOSED", "cr": "2026-10-02T14:00:00Z", "cl": "2026-10-03T00:00:00Z",
                                        "au": "amy", "at": "User", "as": "NONE", "cm": [], "lb": ["incident"]}, "acme/web")
    assert issue.id == "github:Issue:acme/web:9" and issue.type == "INCIDENT" and issue.status == "DONE"
    plain = model.Issue.from_community({"t": "issue", "n": 10, "st": "OPEN", "cr": "2026-10-02T14:00:00Z", "au": "amy", "cm": []}, "acme/web")
    assert plain.type == "REQUIREMENT" and plain.status == "TODO"
