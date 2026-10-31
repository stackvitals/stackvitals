"""Bitbucket Cloud and Azure DevOps pull requests through the same Delivery build as GitHub's (shapes from their REST APIs)."""
from datetime import datetime, timezone

from stackvitals.core import delivery
from stackvitals.core.config import parse
from stackvitals.flow import code_hosts

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


class Fake:
    def __init__(self, pages):
        self.pages, self.requests = pages, 0

    def get(self, url, params=None):
        for key, val in self.pages.items():
            if url.endswith(key):
                return val
        return {"values": [], "value": []}


def test_bitbucket_prs_activity_and_pipeline_deployments():
    pr = lambda n, who: {"id": n, "title": f"feat {n}", "created_on": "2026-10-10T10:00:00+00:00", "updated_on": "2026-10-10T13:00:00+00:00",  # noqa: E731
                         "author": {"nickname": who}, "destination": {"branch": {"name": "main"}}, "source": {"branch": {"name": f"f{n}"}},
                         "merge_commit": {"hash": f"{n:012x}"}, "closed_by": {"nickname": "bo"}}
    fake = Fake({"/repositories/w/r": {"mainbranch": {"name": "main"}, "is_private": False},
                 "/repositories/w/r/pullrequests": {"values": [pr(1, "ana"), pr(2, "Renovate Bot")]},
                 "/pullrequests/1/activity": {"values": [{"approval": {"date": "2026-10-10T12:00:00+00:00", "user": {"nickname": "bo"}}},
                                                         {"comment": {"created_on": "2026-10-10T11:00:00+00:00", "user": {"nickname": "bo"}}},
                                                         {"update": {"state": "MERGED", "date": "2026-10-10T12:30:00+00:00"}}]},
                 "/environments": {"values": [{"uuid": "{e1}", "name": "Production"}]},
                 "/deployments": {"values": [{"environment": {"uuid": "{e1}"}, "release": {"commit": {"hash": f"{1:012x}"}},
                                              "state": {"status": {"name": "SUCCESSFUL"}, "started_on": "2026-10-10T14:00:00+00:00",
                                                        "completed_on": "2026-10-10T14:05:00+00:00"}}]}})
    flow, facts = code_hosts.bitbucket("w/r", NOW, client=fake)
    first = flow["closed"][0]
    assert first["mg"] == "2026-10-10T12:30:00Z" and first["ev"][0][3] == "APPROVED" and first["cm"][0][1] == "bo"
    out = delivery.build(flow, facts, {"runs": []}, [], NOW, 90, parse("")[0])
    assert out["prs"] == 1 and out["dora"]["deployments"] == 1 and out["deploy_source"] == "deployments api"


def test_azure_devops_completed_prs_and_vote_threads():
    fake = Fake({"/repositories/r": {"defaultBranch": "refs/heads/main", "project": {"visibility": "public"}},
                 "/repositories/r/pullrequests": {"value": [{"pullRequestId": 7, "title": "x", "creationDate": "2026-10-01T10:00:00Z",
                                                             "closedDate": "2026-10-01T15:00:00Z", "createdBy": {"displayName": "Ana"},
                                                             "targetRefName": "refs/heads/main", "sourceRefName": "refs/heads/x",
                                                             "lastMergeCommit": {"commitId": "c" * 40}}]},
                 "/pullRequests/7/threads": {"value": [
                     {"properties": {"CodeReviewThreadType": {"$value": "VoteUpdate"}},
                      "comments": [{"author": {"displayName": "Bo"}, "publishedDate": "2026-10-01T12:00:00Z", "content": "Bo voted 10 (approved)"}]},
                     {"comments": [{"author": {"displayName": "Bo"}, "publishedDate": "2026-10-01T11:00:00Z", "commentType": "text"}]}]}})
    flow, facts = code_hosts.azure("o/p/r", NOW, client=fake)
    p = flow["closed"][0]
    assert facts["default_branch"] == "main" and p["au"] == "Ana" and p["base"] == "main" and p["mc"] == "c" * 40
    assert [e[0] for e in p["ev"]] == ["review", "merged"] and p["cm"][0][1] == "Bo"
