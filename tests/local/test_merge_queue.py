"""Merge-queue health, which GitHub itself doesn't report: time from entering the queue to merge, removals by reason, and
removals that followed a merge-group run failing only on known flaky jobs."""
from datetime import datetime, timezone

from stackvitals.core.merge_queue import health
from stackvitals.flow.collect import QUERY, pr_record

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
CI = ".github/workflows/ci.yml"


def test_team_flow_reads_when_a_pr_entered_and_left_the_queue():
    assert "ADDED_TO_MERGE_QUEUE_EVENT" in QUERY and "REMOVED_FROM_MERGE_QUEUE_EVENT" in QUERY
    node = {"number": 7, "createdAt": "2026-10-10T08:00:00Z", "author": {"login": "amy", "__typename": "User"},
            "queue": {"nodes": [{"__typename": "AddedToMergeQueueEvent", "createdAt": "2026-10-10T10:00:00Z"},
                                {"__typename": "RemovedFromMergeQueueEvent", "createdAt": "2026-10-10T10:40:00Z", "reason": "CI_FAILURE"}]}}
    assert pr_record(node, NOW)["mq"] == [["add", "2026-10-10T10:00:00Z"], ["rm", "2026-10-10T10:40:00Z", "CI_FAILURE"]]


# Real-data finding (bevyengine/bevy): GraphQL gives lowercase reasons (merged, merge_conflict, failed_checks), and the
# "merged" removal can land minutes from the merge time.
PRS = [{"n": 1, "mg": "2026-10-10T12:00:00Z", "base": "main",
        "mq": [["add", "2026-10-10T10:00:00Z"], ["rm", "2026-10-10T12:09:00Z", "merged"]]},
       {"n": 2, "mg": "2026-10-11T15:00:00Z", "base": "main",
        "mq": [["add", "2026-10-11T10:00:00Z"], ["rm", "2026-10-11T10:40:00Z", "failed_checks"], ["add", "2026-10-11T13:00:00Z"]]},
       {"n": 3, "mg": None, "base": "main", "mq": [["add", "2026-10-12T10:00:00Z"], ["rm", "2026-10-12T11:00:00Z", "failed_checks"]]},
       {"n": 4, "mg": "2026-10-12T09:00:00Z", "base": "main"}]
DATA = {"runs": [{"id": 50, "att": 1, "ev": "merge_group", "br": "gh-readonly-queue/main/pr-2-abc", "c": "failure",
                  "cr": "2026-10-11T10:05:00Z", "path": CI},
                 {"id": 51, "att": 1, "ev": "merge_group", "br": "gh-readonly-queue/main/pr-3-def", "c": "failure",
                  "cr": "2026-10-12T10:05:00Z", "path": CI},
                 {"id": 52, "att": 1, "ev": "merge_group", "br": "gh-readonly-queue/main/pr-1-aaa", "c": "success",
                  "cr": "2026-10-10T10:05:00Z", "path": CI}],
        "jobs": [{"run": 50, "att": 1, "n": "e2e", "c": "failure"}, {"run": 51, "att": 1, "n": "unit", "c": "failure"}]}
STATES = {(CI, "e2e"): "flaky", (CI, "unit"): "ok"}


def test_time_in_queue_removals_and_the_ones_a_flake_caused():
    out = health(PRS, DATA, STATES, NOW, 30, min_n=1)
    assert (out["prs"], out["merged"], out["p50_h"], out["p90_h"]) == (3, 2, 2.0, 2.0)
    assert out["removals"] == {"failed_checks": 2}
    assert out["removed_by_flakes"] == [{"pr": 2, "at": "2026-10-11T10:40:00Z", "jobs": ["e2e"]}]
    assert (out["runs"], out["failed_runs"]) == (3, 2)


def test_no_queue_means_no_section():
    assert health([{"n": 4, "mg": "2026-10-12T09:00:00Z"}], {"runs": [], "jobs": []}, {}, NOW, 30) is None


def test_the_delivery_page_shows_queue_health_and_the_flaky_removals():
    from stackvitals.core import delivery_report
    from stackvitals.core.config import parse
    from stackvitals.core.delivery import build
    out = build({"closed": [], "open": []}, {"default_branch": "main"}, {"runs": [], "jobs": []}, [], NOW, 90, parse("")[0])
    out["merge_queue"] = health(PRS, DATA, STATES, NOW, 30, min_n=1)
    page = delivery_report.render_html(out, "o/r")
    assert "Merge queue" in page and "failed_checks" in page and "https://github.com/o/r/pull/2" in page
