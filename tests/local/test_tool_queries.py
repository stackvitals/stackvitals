import pytest

from mergescout.tool.queries import Snapshot, fts_query
from mergescout.tool.refs import parse_ref

from tool_data import ISSUE, REPO, make_snapshot

THIN = {**REPO, "repo_id": 2, "name": "tiny/thing", "merge_enough": 0, "merged": 3, "closed": 1, "merge_rate": 0.75,
        "merge_low": 0.3, "merge_high": 0.95, "review_enough": 0, "insiders": 1, "blocking_walls": 1,
        "walls_json": '[{"wall": "cla", "blocking": true, "evidence": "Sign the CLA"}]', "language": "Rust"}


@pytest.fixture
def snap(tmp_path):
    issues = [ISSUE, {**ISSUE, "number": 8, "title": "Fix login page typo", "body": "Typo on the login page.",
                      "labels": "[]", "opportunity": 0, "score": 0.4, "rank_score": 0.3},
              {**ISSUE, "number": 9, "title": "Taken one", "available": 0, "score": 0, "rank_score": 0,
               "blocked_by": "assigned"},
              {**ISSUE, "repo_id": 2, "number": 1, "title": "Database pool for the ETL job", "language": "Rust",
               "score": 0.5, "rank_score": 0.5}]
    return Snapshot(make_snapshot(tmp_path / "s.sqlite", repos=(REPO, THIN), issues=issues))


def test_thin_evidence_and_walls_are_said_plainly(snap):
    row = snap.find_issues(language="rust")["results"][0]
    assert row["outsider_merge"].startswith("not enough evidence yet (4 decided outsider PRs")
    assert row["walls"] == ["cla"]
    assert snap.find_issues(language="rust", allow_walls=False)["results"] == []


def test_topic_search_uses_words_and_stems(snap):
    assert [r["issue"] for r in snap.find_issues(topic="databases etl")["results"]] == ["octo/widgets#7",
                                                                                       "tiny/thing#1"]


def test_explain_repo_health_similar_and_help(snap):
    ev = snap.explain("octo/widgets", 7)
    assert ev["repo"]["outsider_merge"]["merged"] == 45 and ev["score"]["total"] == 0.7
    health = snap.repo_health("octo/widgets")
    assert health["insiders"] == 2 and "6.5 h" in health["review"]
    similar = snap.similar_issues("octo/widgets", 7)["results"]
    assert [r["issue"] for r in similar] == ["tiny/thing#1"]
    helped = snap.repos_needing_help()["results"]
    assert [r["repo"] for r in helped] == ["octo/widgets"]
    assert snap.stats()["issues"] == 4
