from datetime import datetime, timezone

import httpx

from stackvitals.ci.analyze import analyze
from stackvitals.ci.gitlab import GitLab, collect, records
from stackvitals.ci.store import DataStore

NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)


def job(jid, name, status, at, stage="test", **kw):
    return {"id": jid, "name": name, "status": status, "stage": stage, "created_at": at, "started_at": at,
            "finished_at": at.replace("00:00Z", "05:00Z"), "tag_list": [], **kw}


def pipeline(pid, at, status="failed", source="merge_request_event", sha="abc", ref="feature", mr=12):
    return {"id": pid, "status": status, "source": source, "sha": sha, "ref": ref, "created_at": at, "updated_at": at,
            "merge_request_iid": mr}


def test_a_retried_job_becomes_a_second_attempt_and_a_flake():
    jobs = [job(1, "unit", "failed", "2026-10-20T10:00:00Z"), job(2, "lint", "success", "2026-10-20T10:00:00Z"),
            job(3, "unit", "success", "2026-10-20T10:10:00Z")]
    recs = records(pipeline(100, "2026-10-20T09:59:00Z"), jobs)
    runs = [r for r in recs if r["t"] == "run"]
    assert [(r["att"], r["c"], r["ev"], r["pr"]) for r in runs] == [(1, "failure", "pull_request", [12]), (2, "success", "pull_request", [12])]
    second = [(r["n"], r["c"]) for r in recs if r["t"] == "job" and r["att"] == 2]
    assert sorted(second) == [("lint", "success"), ("unit", "success")]
    unit = next(j for j in analyze({"runs": runs, "jobs": [r for r in recs if r["t"] == "job"]}, NOW, default_branch="main")["jobs"]
                if j["job"] == "unit")
    assert unit["flake_events"] == 1


def test_a_job_allowed_to_fail_never_fails_the_pipeline():
    recs = records(pipeline(101, "2026-10-20T09:59:00Z", status="success", source="push", mr=None),
                   [job(4, "experimental", "failed", "2026-10-20T10:00:00Z", allow_failure=True)])
    assert next(r for r in recs if r["t"] == "run")["c"] == "success"
    assert next(r for r in recs if r["t"] == "job")["c"] == "neutral"


def test_collect_reads_finished_pipelines_once_with_their_retries(tmp_path):
    asked = []

    def handler(request):
        asked.append(request.url.path)
        assert "/projects/group%2Fproj" in request.url.raw_path.decode()
        if request.url.path.endswith("/projects/group%2Fproj") or request.url.path.endswith("/projects/group/proj"):
            return httpx.Response(200, json={"default_branch": "main"})
        if request.url.path.endswith("/pipelines"):
            return httpx.Response(200, json=[pipeline(100, "2026-10-20T09:59:00Z"),
                                             {**pipeline(102, "2026-10-21T09:00:00Z"), "status": "running"}])
        if request.url.path.endswith("/pipelines/100/jobs"):
            assert request.url.params["include_retried"] == "true"
            return httpx.Response(200, json=[job(1, "unit", "failed", "2026-10-20T10:00:00Z"),
                                             job(3, "unit", "success", "2026-10-20T10:10:00Z")])
        return httpx.Response(404)
    store = DataStore(tmp_path)
    lab = GitLab("group/proj", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert collect(lab, store, NOW) == {"pipelines": 1, "stopped": None}
    assert store.state()["default_branch"] == "main" and len(store.load()["runs"]) == 2
    before = len(asked)
    collect(lab, store, NOW)
    assert not any(p.endswith("/pipelines/100/jobs") for p in asked[before:])  # read once
