"""GitLab merge requests and deployments through the same Delivery build as GitHub's (shapes from GitLab's REST API)."""
from datetime import datetime, timezone

from stackvitals.core import delivery
from stackvitals.core.config import parse
from stackvitals.flow import gitlab_mr

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def mr(iid, created, merged, sha):
    return {"iid": iid, "title": f"feat: change {iid}", "state": "merged", "created_at": created, "updated_at": merged,
            "merged_at": merged, "author": {"username": "ana"}, "merged_by": {"username": "bo"}, "target_branch": "main",
            "source_branch": f"feature-{iid}", "merge_commit_sha": sha, "labels": []}


NOTES = {1: [{"system": False, "author": {"username": "bo"}, "created_at": "2026-10-10T11:00:00Z", "body": "looks good"},
             {"system": True, "author": {"username": "bo"}, "created_at": "2026-10-10T12:00:00Z", "body": "approved this merge request"}],
         2: []}


class Lab:
    def get(self, path, params=None):
        return {"default_branch": "main", "visibility": "public"}

    def pages(self, path, params, limit=50):
        if path == "/merge_requests":
            yield from [mr(1, "2026-10-10T10:00:00Z", "2026-10-10T13:00:00Z", "a" * 40),
                        mr(2, "2026-10-12T10:00:00Z", "2026-10-12T11:00:00Z", "b" * 40)]
        elif path.endswith("/notes"):
            yield from NOTES[int(path.split("/")[2])]
        elif path == "/deployments":
            yield from [{"status": "success", "sha": "a" * 40, "created_at": "2026-10-10T14:00:00Z", "finished_at": "2026-10-10T14:10:00Z",
                         "environment": {"name": "production"}},
                        {"status": "failed", "sha": "b" * 40, "created_at": "2026-10-12T12:00:00Z", "environment": {"name": "production"}},
                        {"status": "success", "sha": "b" * 40, "created_at": "2026-10-12T13:00:00Z", "finished_at": "2026-10-12T13:05:00Z",
                         "environment": {"name": "production"}}]


def test_merge_requests_and_deployments_give_dora_and_review_phases():
    flow, repo = gitlab_mr.collect(Lab(), NOW)
    first = flow["closed"][0]
    assert first["ev"][0][:4] == ["review", "2026-10-10T12:00:00Z", "bo", "APPROVED"] and first["cm"][0][1] == "bo"
    out = delivery.build(flow, repo, {"runs": []}, [], NOW, 90, parse("")[0])
    assert out["deploy_source"] == "deployments api" and out["dora"]["deployments"] == 2
    assert out["deploy_attempts"]["failed"] == 1
    assert out["phases"]["pickup"]["n"] == 2


def test_notes_refused_without_a_token_leave_the_phases_at_the_merge():
    from stackvitals.ci.api import APIError

    class Locked(Lab):
        def pages(self, path, params, limit=50):
            if path.endswith("/notes"):
                raise APIError("GET notes: HTTP 401")
            yield from super().pages(path, params, limit)
    flow, _repo = gitlab_mr.collect(Locked(), NOW)
    assert [p["cm"] for p in flow["closed"]] == [[], []] and len(flow["closed"]) == 2
